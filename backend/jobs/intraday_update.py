"""
Hourly intraday update job — standalone, Railway-deployable.

Runs every hour during US market hours (cron: `30 13-20 * * 1-5` UTC) and does
three things, using near-realtime prices for ONLY the symbols that matter
(open positions + today's active suggestions — never the full universe):

  1. AUTO-ENTRY  — opens paper trades for today's active suggestions that
                   aren't already held, at the current live price.  Stop and
                   target are shifted from the suggestion's ATR-derived
                   distances so the risk geometry is preserved.
  2. AUTO-EXIT   — closes any open trade whose live price has breached its
                   stop or target, or whose holding period has exceeded
                   settings.max_holding_days (TIME_EXIT).
  3. MARK-TO-MARKET — upserts today's DailyPnL rows and the portfolio
                   snapshot so the Portfolio page shows near-live numbers.

The nightly analysis pipeline is untouched — signals are still generated once
per day.  This job only *executes* against those signals at a finer time grain.

Usage
-----
    python backend/jobs/intraday_update.py            # normal (guarded) run
    python backend/jobs/intraday_update.py --force    # skip market-hours guard
"""

from __future__ import annotations

import asyncio
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time as dtime, timezone
from decimal import Decimal
from pathlib import Path

# ── Ensure backend/ is on sys.path before any internal imports ────────────────
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

for _candidate in [
    Path(__file__).parent,
    Path(__file__).parent.parent,
    Path(__file__).parent.parent.parent,
]:
    if (_candidate / ".env").exists():
        load_dotenv(_candidate / ".env")
        break

from sqlalchemy import select  # noqa: E402

from config import settings  # noqa: E402
from db.models import PaperTrade, Suggestion  # noqa: E402
from db.session import async_session_factory  # noqa: E402
from paper_trading.engine import (  # noqa: E402
    get_portfolio_snapshot,
    open_trade,
    per_trade_cash_cap,
    plan_entries,
)
from paper_trading.mark_to_market import check_exit, compute_realized_pnl  # noqa: E402
from risk.entry_guards import is_gap_chase  # noqa: E402
from risk.position_sizing import compute_position_size  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("intraday")

_PRICE_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="px")


# ── Market-hours guard ─────────────────────────────────────────────────────────

def _market_is_open(now_utc: datetime) -> bool:
    """
    True during regular NYSE hours (9:30–16:00 America/New_York, Mon–Fri).
    Falls back to a fixed 13:30–21:00 UTC window if tz data is unavailable.
    """
    if now_utc.weekday() >= 5:
        return False
    try:
        from zoneinfo import ZoneInfo
        ny = now_utc.astimezone(ZoneInfo("America/New_York"))
        return dtime(9, 30) <= ny.time() <= dtime(16, 0)
    except Exception:
        return dtime(13, 30) <= now_utc.time() <= dtime(21, 0)


# ── Live prices ────────────────────────────────────────────────────────────────

def _fetch_live_price_sync(symbol: str) -> float | None:
    """Blocking: latest traded price via yfinance (fast_info, history fallback)."""
    import yfinance as yf

    try:
        t = yf.Ticker(symbol)
        price = None
        try:
            price = t.fast_info.get("last_price")  # type: ignore[union-attr]
        except Exception:
            price = None
        if not price or price <= 0:
            hist = t.history(period="1d", interval="5m")
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
        return float(price) if price and price > 0 else None
    except Exception as exc:
        log.debug("Live price fetch failed for %s: %s", symbol, exc)
        return None


async def _fetch_live_prices(symbols: list[str]) -> dict[str, Decimal]:
    loop = asyncio.get_event_loop()

    async def _one(sym: str) -> tuple[str, float | None]:
        return sym, await loop.run_in_executor(_PRICE_EXECUTOR, _fetch_live_price_sync, sym)

    results = await asyncio.gather(*[_one(s) for s in symbols])
    return {
        sym: Decimal(str(round(price, 4)))
        for sym, price in results
        if price is not None
    }


# ── Auto-entry ─────────────────────────────────────────────────────────────────

async def _auto_enter(today: date, prices: dict[str, Decimal]) -> int:
    """
    Open trades for today's active suggestions not already held.

    Entry count and sizing are governed by the shared entry plan:
    market-pulse-scaled top-N, daily deployment budget split across the
    remaining allowed entries, and a hard cash-reserve floor. Successive
    hourly runs re-read the plan, so the daily caps are never exceeded.
    """
    async with async_session_factory() as session:
        open_rows = (await session.execute(
            select(PaperTrade.symbol).where(PaperTrade.is_open == True)
        )).all()
        open_symbols = {r[0] for r in open_rows}
        open_count = len(open_rows)

        suggestions: list[Suggestion] = list(
            (await session.execute(
                select(Suggestion)
                .where(Suggestion.as_of_date == today, Suggestion.is_active == True)
                .order_by(Suggestion.confidence_score.desc())
            )).scalars().all()
        )

        plan = await plan_entries(session, today)

    # T2 first: rare, heavily pre-screened signals always get taken
    # (count-exempt); T1 signals then fill the pulse-scaled top-N slots.
    ordered = [s for s in suggestions if s.tier == "T2"] + [
        s for s in suggestions if s.tier != "T2"
    ]

    opened_t1 = 0
    opened_t2 = 0
    opened_total = 0
    spent = Decimal("0")
    for s in ordered:
        is_t2 = s.tier == "T2"
        if 0 < settings.max_open_positions <= open_count:
            break
        if s.symbol in open_symbols:
            continue
        # Hard daily ceiling on count-exempt T2 entries (safety net)
        if is_t2 and 0 < settings.max_t2_entries_per_day <= plan.t2_entered_today + opened_t2:
            log.info(
                "Auto-entry: T2 daily hard cap reached (%d) — skipping %s",
                settings.max_t2_entries_per_day, s.symbol,
            )
            continue

        cash_cap = per_trade_cash_cap(plan, opened_t1, spent, count_exempt=is_t2)
        if cash_cap <= 0:
            if is_t2:
                continue   # budget/pulse blocked this T2; T1 slots may differ
            log.info(
                "Auto-entry: entry budget exhausted (pulse %d/100 → %d allowed today) — done",
                plan.pulse_score, plan.allowed_today,
            )
            break

        live = prices.get(s.symbol)
        if live is None:
            log.warning("Auto-entry: no live price for %s — skipping this hour", s.symbol)
            continue

        # Gap-chase guard: if price already ran past the signal entry by more
        # than max_entry_gap_pct, the scored setup is gone — don't chase.
        # Re-checked each hourly run, so a pullback later today can still fill.
        if is_gap_chase(s.direction, s.entry_price, live, settings.max_entry_gap_pct):
            gap_pct = (live - s.entry_price) / s.entry_price * 100
            log.info(
                "Auto-entry: gap-chase guard skipped %s (%s) — live $%s is %+.2f%% vs "
                "signal entry $%s (limit %.1f%%)",
                s.symbol, s.direction, live, gap_pct, s.entry_price,
                settings.max_entry_gap_pct * 100,
            )
            continue

        # Preserve the suggestion's ATR-derived stop/target distances,
        # re-anchored to the live entry price.
        stop_dist   = s.entry_price - s.stop_loss        # signed: works for SHORT too
        target_dist = s.target_price - s.entry_price
        stop   = live - stop_dist
        target = live + target_dist

        shares = compute_position_size(plan.capital, live, stop, available_cash=cash_cap)
        if shares == 0:
            log.debug("Auto-entry: zero shares for %s — skipping", s.symbol)
            continue

        trade = await open_trade(
            s.id, shares, entry_price=live, stop_loss=stop, target_price=target
        )
        if trade is not None:
            open_symbols.add(s.symbol)
            open_count += 1
            opened_total += 1
            if is_t2:
                opened_t2 += 1
            else:
                opened_t1 += 1
            spent += trade.capital_at_risk
            log.info(
                "Auto-entry: %s %s (%s) x%d @ $%s (stop=%s target=%s)%s",
                s.symbol, s.direction, s.tier, shares, live, stop, target,
                "  [T2 — count-exempt]" if is_t2 else "",
            )
    return opened_total


# ── Auto-exit at live prices ───────────────────────────────────────────────────

async def _auto_exit(today: date, prices: dict[str, Decimal]) -> int:
    """Close open trades whose live price breaches stop/target, or that timed out."""
    closed = 0
    async with async_session_factory() as session:
        open_trades: list[PaperTrade] = list(
            (await session.execute(
                select(PaperTrade).where(PaperTrade.is_open == True)
            )).scalars().all()
        )

        for trade in open_trades:
            live = prices.get(trade.symbol)
            if live is None:
                continue

            exit_reason = check_exit(
                close_price=live,
                stop_loss=trade.stop_loss,
                target_price=trade.target_price,
                direction=trade.direction,
            )
            if (
                exit_reason is None
                and settings.max_holding_days > 0
                and (today - trade.entry_date).days >= settings.max_holding_days
            ):
                exit_reason = "TIME_EXIT"

            if exit_reason is None:
                continue

            trade.exit_date = today
            trade.exit_price = live
            trade.exit_reason = exit_reason
            trade.realized_pnl = compute_realized_pnl(
                entry_price=trade.entry_price,
                exit_price=live,
                shares=trade.shares,
                direction=trade.direction,
            )
            trade.is_open = False
            closed += 1
            log.info(
                "Auto-exit: %s (%s) @ $%s  PnL=$%s",
                trade.symbol, exit_reason, live, trade.realized_pnl,
            )

        await session.commit()
    return closed


# ── Mark-to-market at live prices ─────────────────────────────────────────────

async def _mark_to_market_live(today: date, prices: dict[str, Decimal]) -> int:
    """Upsert today's DailyPnL rows for open trades at live prices."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from db.models import DailyPnL
    from paper_trading.mark_to_market import compute_unrealized_pnl

    written = 0
    async with async_session_factory() as session:
        open_trades: list[PaperTrade] = list(
            (await session.execute(
                select(PaperTrade).where(PaperTrade.is_open == True)
            )).scalars().all()
        )
        for trade in open_trades:
            live = prices.get(trade.symbol)
            if live is None:
                continue
            unrealized = compute_unrealized_pnl(
                entry_price=trade.entry_price,
                current_price=live,
                shares=trade.shares,
                direction=trade.direction,
            )
            await session.execute(
                pg_insert(DailyPnL)
                .values(
                    trade_id=trade.id,
                    pnl_date=today,
                    close_price=live,
                    unrealized_pnl=unrealized,
                )
                .on_conflict_do_update(
                    index_elements=["trade_id", "pnl_date"],
                    set_={"close_price": live, "unrealized_pnl": unrealized},
                )
            )
            written += 1
        await session.commit()
    return written


# ── Main ──────────────────────────────────────────────────────────────────────

async def main(force: bool = False) -> None:
    now = datetime.now(timezone.utc)
    if not force and not _market_is_open(now):
        log.info("Market is closed (%s UTC) — nothing to do.", now.strftime("%H:%M"))
        return

    today = date.today()
    log.info("=" * 60)
    log.info("Intraday update — %s", now.strftime("%Y-%m-%d %H:%M UTC"))
    log.info("=" * 60)

    # ── Collect symbols that matter ───────────────────────────────────────────
    async with async_session_factory() as session:
        open_syms = {
            r[0] for r in (await session.execute(
                select(PaperTrade.symbol).where(PaperTrade.is_open == True)
            )).all()
        }
        sugg_syms = {
            r[0] for r in (await session.execute(
                select(Suggestion.symbol).where(
                    Suggestion.as_of_date == today, Suggestion.is_active == True
                )
            )).all()
        }

    symbols = sorted(open_syms | sugg_syms)
    if not symbols:
        log.info("No open positions and no active suggestions — nothing to do.")
        return

    log.info(
        "Fetching live prices for %d symbol(s): %d open, %d suggested",
        len(symbols), len(open_syms), len(sugg_syms),
    )
    prices = await _fetch_live_prices(symbols)
    log.info("Live prices returned for %d / %d symbols", len(prices), len(symbols))

    # ── 1. Auto-entry (skipped entirely in nightly mode) ──────────────────────
    opened = 0
    if settings.auto_entry_mode == "intraday":
        opened = await _auto_enter(today, prices)

    # ── 2. Auto-exit ──────────────────────────────────────────────────────────
    closed = await _auto_exit(today, prices)
    if closed:
        try:
            from paper_trading.outcomes import sync_trade_outcomes
            await sync_trade_outcomes()
        except Exception as exc:
            log.warning("sync_trade_outcomes failed (non-fatal): %s", exc)

    # ── 3. Mark-to-market at live prices + snapshot ───────────────────────────
    try:
        await _mark_to_market_live(today, prices)
    except Exception as exc:
        log.warning("Mark-to-market failed (non-fatal): %s", exc)
    try:
        await get_portfolio_snapshot(today)
    except Exception as exc:
        log.warning("Snapshot failed (non-fatal): %s", exc)

    log.info(
        "Intraday update complete — %d opened, %d closed, %d live prices",
        opened, closed, len(prices),
    )


if __name__ == "__main__":
    asyncio.run(main(force="--force" in sys.argv))
