"""
Paper trading engine.

Nightly flow (called from scheduler/tasks.py after ingest + agents):
  1. accept_suggestions(date)      → opens new paper trades from today's suggestions
  2. update_open_trades(date)      → prices all open trades, closes hits, writes daily_pnl
  3. get_portfolio_snapshot(date)  → computes NAV and writes portfolio_snapshots

All money values use Decimal to match numeric(12,4) DB columns.
Prices are read from daily_prices (already ingested) before falling back to yfinance.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from config import settings
from db.models import DailyPrice, DailyPnL, PaperTrade, PortfolioSnapshot, Suggestion
from db.session import async_session_factory
from paper_trading.mark_to_market import (
    check_exit,
    compute_realized_pnl,
    compute_unrealized_pnl,
)
from risk.position_sizing import compute_position_size

logger = logging.getLogger(__name__)


# ── Result / value types ──────────────────────────────────────────────────────

@dataclass
class UpdateResult:
    as_of: date
    trades_checked: int = 0
    trades_closed: int = 0
    stop_hits: int = 0
    target_hits: int = 0
    time_exits: int = 0
    pnl_rows_written: int = 0
    total_unrealized: Decimal = field(default_factory=lambda: Decimal("0"))
    symbols_missing_price: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"UpdateResult({self.as_of}): "
            f"checked={self.trades_checked} "
            f"closed={self.trades_closed} "
            f"(stops={self.stop_hits}, targets={self.target_hits}, time={self.time_exits}) "
            f"pnl_rows={self.pnl_rows_written} "
            f"unrealized=${self.total_unrealized:,.2f}"
        )


# ── Core public functions ─────────────────────────────────────────────────────

async def open_trade(
    suggestion_id: int,
    shares: int,
    entry_price: Decimal | None = None,
    stop_loss: Decimal | None = None,
    target_price: Decimal | None = None,
) -> PaperTrade | None:
    """
    Create a single paper trade from a suggestion.

    If entry_price / stop_loss / target_price are provided they override the
    suggestion's stored values — used when the caller has looked up a fresher
    market price from daily_prices.

    Returns the created PaperTrade, or None if suggestion_id is invalid or shares <= 0.
    """
    if shares <= 0:
        logger.warning("open_trade: shares must be > 0 (got %d)", shares)
        return None

    async with async_session_factory() as session:
        suggestion = await session.get(Suggestion, suggestion_id)
        if suggestion is None:
            logger.warning("open_trade: suggestion %d not found", suggestion_id)
            return None

        effective_entry  = entry_price  if entry_price  is not None else suggestion.entry_price
        effective_stop   = stop_loss    if stop_loss    is not None else suggestion.stop_loss
        effective_target = target_price if target_price is not None else suggestion.target_price
        capital_at_risk  = effective_entry * Decimal(str(shares))

        trade = PaperTrade(
            suggestion_id=suggestion_id,
            symbol=suggestion.symbol,
            direction=suggestion.direction,
            entry_date=date.today(),
            entry_price=effective_entry,
            shares=shares,
            capital_at_risk=capital_at_risk,
            stop_loss=effective_stop,
            target_price=effective_target,
            # entry-time levels preserved for the dynamic-exit UI comparison
            original_stop=effective_stop,
            original_target=effective_target,
            is_open=True,
        )
        session.add(trade)
        await session.commit()
        await session.refresh(trade)

    logger.info(
        "Opened trade #%d — %s x%d @ $%s (cap_at_risk=$%s)",
        trade.id, trade.symbol, shares, trade.entry_price, capital_at_risk,
    )
    return trade


async def update_open_trades(as_of: date) -> UpdateResult:
    """
    Run nightly EOD processing for all currently open paper trades.

    For each open trade:
    - Looks up the EOD close price (DB first, yfinance fallback).
    - If stop-loss breached  → closes trade with exit_reason=STOP_HIT.
    - If target reached      → closes trade with exit_reason=TARGET_HIT.
    - Otherwise              → writes a DailyPnL row (close_price + unrealized_pnl).

    Returns an UpdateResult summary.
    """
    result = UpdateResult(as_of=as_of)

    async with async_session_factory() as session:
        open_trades: list[PaperTrade] = list(
            (await session.execute(
                select(PaperTrade).where(PaperTrade.is_open == True)
            )).scalars().all()
        )

        if not open_trades:
            logger.info("update_open_trades(%s): no open trades", as_of)
            return result

        result.trades_checked = len(open_trades)
        symbols = list({t.symbol for t in open_trades})

        # ── 1. Fetch EOD prices ───────────────────────────────────────────────
        prices = await _get_eod_prices(session, symbols, as_of)

        # yfinance fallback for any symbol still missing
        missing = [s for s in symbols if s not in prices]
        if missing:
            fetched = await _fetch_prices_yfinance(missing, as_of)
            prices.update(fetched)

        # ── 2. Process each trade ─────────────────────────────────────────────
        for trade in open_trades:
            close_price = prices.get(trade.symbol)

            if close_price is None:
                logger.warning(
                    "update_open_trades: no price for %s on %s — skipping",
                    trade.symbol, as_of,
                )
                result.symbols_missing_price.append(trade.symbol)
                continue

            exit_reason = check_exit(
                close_price=close_price,
                stop_loss=trade.stop_loss,
                target_price=trade.target_price,
                direction=trade.direction,
            )

            # Time-based exit: the swing thesis is 3–14 days. A trade that has
            # neither stopped out nor hit target in max_holding_days is dead
            # money occupying a slot — close it at the current price.
            if (
                exit_reason is None
                and settings.max_holding_days > 0
                and (as_of - trade.entry_date).days >= settings.max_holding_days
            ):
                exit_reason = "TIME_EXIT"

            if exit_reason is not None:
                # ── Close the trade ───────────────────────────────────────────
                trade.exit_date = as_of
                trade.exit_price = close_price
                trade.exit_reason = exit_reason
                trade.realized_pnl = compute_realized_pnl(
                    entry_price=trade.entry_price,
                    exit_price=close_price,
                    shares=trade.shares,
                    direction=trade.direction,
                )
                trade.is_open = False

                result.trades_closed += 1
                if exit_reason == "STOP_HIT":
                    result.stop_hits += 1
                elif exit_reason == "TIME_EXIT":
                    result.time_exits += 1
                else:
                    result.target_hits += 1

                logger.info(
                    "Closed %s (%s) @ $%s  PnL=$%s",
                    trade.symbol, exit_reason, close_price, trade.realized_pnl,
                )
            else:
                # ── Mark-to-market ────────────────────────────────────────────
                unrealized = compute_unrealized_pnl(
                    entry_price=trade.entry_price,
                    current_price=close_price,
                    shares=trade.shares,
                    direction=trade.direction,
                )
                result.total_unrealized += unrealized

                # Upsert (not insert): the hourly intraday job and the nightly
                # EOD job may both write today's row for the same trade.
                await session.execute(
                    pg_insert(DailyPnL)
                    .values(
                        trade_id=trade.id,
                        pnl_date=as_of,
                        close_price=close_price,
                        unrealized_pnl=unrealized,
                    )
                    .on_conflict_do_update(
                        index_elements=["trade_id", "pnl_date"],
                        set_={"close_price": close_price, "unrealized_pnl": unrealized},
                    )
                )
                result.pnl_rows_written += 1

        await session.commit()

    logger.info(str(result))
    return result


async def compute_nav(
    session,
    as_of: date,
    live_prices: dict[str, Decimal] | None = None,
) -> dict:
    """
    Compute NAV components without persisting anything.

    NAV components:
    - cash_balance          = initial_capital + Σ realized_pnl(all time) − Σ capital_at_risk(open)
    - invested_capital      = Σ capital_at_risk(open trades)
    - unrealized_pnl        = from *live_prices* when given, else today's DailyPnL rows
    - realized_pnl_today    = Σ realized_pnl where exit_date == as_of
    - cumulative_realized   = Σ realized_pnl(all closed trades)
    - total_capital         = cash_balance + invested_capital + unrealized_pnl
                            = initial_capital + cumulative_realized + unrealized_pnl

    When *live_prices* (symbol → price) is supplied, unrealized P&L is computed
    directly from open positions at those prices — this is what makes the
    on-demand /portfolio/snapshot endpoint reflect a buy or sell immediately.
    """
    open_trades: list[PaperTrade] = list(
        (await session.execute(
            select(PaperTrade).where(PaperTrade.is_open == True)
        )).scalars().all()
    )

    invested_capital = sum(
        (t.capital_at_risk for t in open_trades), Decimal("0")
    )

    if live_prices is not None:
        unrealized_pnl = Decimal("0")
        for t in open_trades:
            price = live_prices.get(t.symbol)
            if price is not None:
                unrealized_pnl += compute_unrealized_pnl(
                    entry_price=t.entry_price,
                    current_price=price,
                    shares=t.shares,
                    direction=t.direction,
                )
    else:
        unrealized_row = (await session.execute(
            select(func.coalesce(func.sum(DailyPnL.unrealized_pnl), Decimal("0")))
            .where(DailyPnL.pnl_date == as_of)
        )).scalar_one()
        unrealized_pnl = Decimal(str(unrealized_row))

    realized_today_row = (await session.execute(
        select(func.coalesce(func.sum(PaperTrade.realized_pnl), Decimal("0")))
        .where(PaperTrade.exit_date == as_of, PaperTrade.is_open == False)
    )).scalar_one()
    realized_pnl_today = Decimal(str(realized_today_row))

    cumulative_row = (await session.execute(
        select(func.coalesce(func.sum(PaperTrade.realized_pnl), Decimal("0")))
        .where(PaperTrade.is_open == False)
    )).scalar_one()
    cumulative_realized_pnl = Decimal(str(cumulative_row))

    cash_balance = (
        settings.initial_capital
        + cumulative_realized_pnl
        - invested_capital
    )
    total_capital = cash_balance + invested_capital + unrealized_pnl

    return {
        "snapshot_date": as_of,
        "total_capital": total_capital,
        "cash_balance": cash_balance,
        "invested_capital": invested_capital,
        "unrealized_pnl": unrealized_pnl,
        "realized_pnl_today": realized_pnl_today,
        "cumulative_realized_pnl": cumulative_realized_pnl,
        "open_positions": len(open_trades),
    }


async def get_portfolio_snapshot(as_of: date) -> PortfolioSnapshot:
    """
    Compute and persist (upsert) a PortfolioSnapshot for *as_of*.

    Upsert, not insert: the hourly intraday job and the nightly EOD job may
    both write the same day's snapshot row.
    """
    async with async_session_factory() as session:
        values = await compute_nav(session, as_of)

        await session.execute(
            pg_insert(PortfolioSnapshot)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["snapshot_date"],
                set_={k: v for k, v in values.items() if k != "snapshot_date"},
            )
        )
        await session.commit()

        snapshot = (await session.execute(
            select(PortfolioSnapshot).where(PortfolioSnapshot.snapshot_date == as_of)
        )).scalar_one()

    logger.info(
        "Snapshot(%s): total=$%s  cash=$%s  invested=$%s  "
        "unrealized=$%s  realized_today=$%s  open=%d",
        as_of, values["total_capital"], values["cash_balance"], values["invested_capital"],
        values["unrealized_pnl"], values["realized_pnl_today"], values["open_positions"],
    )
    return snapshot


# ── Entry planning (market pulse + capital pacing) ────────────────────────────

@dataclass
class EntryPlan:
    """Everything the entry loops need to pace new positions for one day."""
    as_of: date
    capital: Decimal
    cash: Decimal
    entered_today: int               # T1-tier trades entered today (count slots)
    deployed_today: Decimal          # Σ capital_at_risk of trades entered today
    allowed_today: int               # pulse-scaled top-N for today
    pulse_score: int
    pulse_label: str
    t2_entered_today: int = 0        # T2-tier trades entered today (hard cap)


async def plan_entries(session, as_of: date) -> EntryPlan:
    """
    Build today's entry plan:
      - live NAV (capital + cash)
      - how many trades were already entered today and what they cost
      - today's allowed entry count = user's top-N cap scaled by market pulse
    """
    from db.app_settings import get_int_setting
    from risk.market_pulse import entries_allowed, get_market_pulse

    nav = await compute_nav(session, as_of)

    # Only T1 entries consume top-N count slots — T2 signals are rare,
    # heavily pre-screened, and enter count-exempt (see per_trade_cash_cap).
    entered_today = (await session.execute(
        select(func.count()).select_from(PaperTrade)
        .join(Suggestion, PaperTrade.suggestion_id == Suggestion.id)
        .where(PaperTrade.entry_date == as_of, Suggestion.tier != "T2")
    )).scalar_one()

    t2_entered_today = (await session.execute(
        select(func.count()).select_from(PaperTrade)
        .join(Suggestion, PaperTrade.suggestion_id == Suggestion.id)
        .where(PaperTrade.entry_date == as_of, Suggestion.tier == "T2")
    )).scalar_one()

    deployed_row = (await session.execute(
        select(func.coalesce(func.sum(PaperTrade.capital_at_risk), Decimal("0")))
        .where(PaperTrade.entry_date == as_of)
    )).scalar_one()

    max_daily = await get_int_setting("max_entries_per_day", settings.max_entries_per_day)
    pulse = await get_market_pulse()
    allowed = entries_allowed(max_daily, pulse.score)

    # Persist today's pulse so trade outcomes can be analyzed against the
    # market context that existed at entry (outcome analytics feedback loop).
    from paper_trading.outcomes import log_market_pulse
    await log_market_pulse(as_of, pulse)

    logger.info(
        "Entry plan(%s): pulse=%d/100 (%s) → %d of %d entries allowed  "
        "(entered=%d, deployed=$%s)",
        as_of, pulse.score, pulse.label, allowed, max_daily,
        entered_today, deployed_row,
    )
    return EntryPlan(
        as_of=as_of,
        capital=nav["total_capital"],
        cash=nav["cash_balance"],
        entered_today=int(entered_today),
        deployed_today=Decimal(str(deployed_row)),
        allowed_today=allowed,
        pulse_score=pulse.score,
        pulse_label=pulse.label,
        t2_entered_today=int(t2_entered_today),
    )


def per_trade_cash_cap(
    plan: EntryPlan, opened: int, spent: Decimal, count_exempt: bool = False
) -> Decimal:
    """
    Cash available for the NEXT entry, respecting all pacing rules:
      - daily deployment budget (max_daily_deployment_pct of capital),
        split evenly across today's remaining allowed entries
      - cash reserve floor (min_cash_reserve_pct of capital never invested)
    Returns <= 0 when no further entry should be made today.

    count_exempt=True (T2 signals): the entry does not consume a top-N count
    slot — T2 setups are rare and heavily pre-screened, so whenever one
    appears it should be taken. It still shares the daily budget and cash
    reserve, and is still blocked when the pulse says sit out entirely.
    """
    entries_remaining = plan.allowed_today - plan.entered_today - opened
    if count_exempt:
        if plan.allowed_today <= 0:       # pulse < 30 — hard sit-out for everyone
            return Decimal("0")
        entries_remaining = max(entries_remaining, 0) + 1   # its own budget share
    elif entries_remaining <= 0:
        return Decimal("0")

    daily_budget = (
        plan.capital * Decimal(str(settings.max_daily_deployment_pct))
        - plan.deployed_today - spent
    )
    reserve = plan.capital * Decimal(str(settings.min_cash_reserve_pct))
    cash_available = plan.cash - spent - reserve

    per_entry_budget = daily_budget / Decimal(entries_remaining)
    return min(per_entry_budget, cash_available)


# ── Higher-level orchestration helper ─────────────────────────────────────────

async def accept_suggestions(as_of: date) -> int:
    """
    Open paper trades for today's suggestions, top-N by confidence.
    Skips symbols already held. Returns number of new trades opened.

    Entry discipline: at most `max_entries_per_day` new trades per day
    (runtime-overridable from the Analytics page via app_settings), counting
    trades already entered today so re-runs stay idempotent.
    """
    async with async_session_factory() as session:
        open_trades: list[PaperTrade] = list(
            (await session.execute(
                select(PaperTrade).where(PaperTrade.is_open == True)
            )).scalars().all()
        )
        open_symbols = {t.symbol for t in open_trades}
        open_count = len(open_trades)

        suggestions: list[Suggestion] = list(
            (await session.execute(
                select(Suggestion)
                .where(Suggestion.as_of_date == as_of, Suggestion.is_active == True)
                .order_by(Suggestion.confidence_score.desc())
            )).scalars().all()
        )

        plan = await plan_entries(session, as_of)

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
        # max_open_positions <= 0 means unlimited
        if 0 < settings.max_open_positions <= open_count:
            break
        if s.symbol in open_symbols:
            continue
        # Hard daily ceiling on count-exempt T2 entries (safety net)
        if is_t2 and 0 < settings.max_t2_entries_per_day <= plan.t2_entered_today + opened_t2:
            logger.info(
                "accept_suggestions: T2 daily hard cap reached (%d) — skipping %s",
                settings.max_t2_entries_per_day, s.symbol,
            )
            continue

        cash_cap = per_trade_cash_cap(plan, opened_t1, spent, count_exempt=is_t2)
        if cash_cap <= 0:
            if is_t2:
                continue   # budget/pulse blocked this T2; T1 slots may differ
            logger.info(
                "accept_suggestions: entry budget exhausted (pulse %d/100 → %d allowed) — done",
                plan.pulse_score, plan.allowed_today,
            )
            break

        shares = compute_position_size(
            plan.capital, s.entry_price, s.stop_loss, available_cash=cash_cap
        )
        if shares == 0:
            logger.debug("accept_suggestions: zero shares computed for %s — skipping", s.symbol)
            continue

        trade = await open_trade(s.id, shares)
        if trade is not None:
            open_symbols.add(s.symbol)
            open_count += 1
            opened_total += 1
            if is_t2:
                opened_t2 += 1
            else:
                opened_t1 += 1
            spent += trade.capital_at_risk

    logger.info(
        "accept_suggestions(%s): opened %d trade(s) (%d T1 counted, %d T2 exempt), deployed $%s",
        as_of, opened_total, opened_t1, opened_total - opened_t1, spent,
    )
    return opened_total


async def process_eod(as_of: date) -> None:
    """
    Nightly EOD sequence: exits → dynamic exit management → snapshot.

    update_open_trades applies stop/target/time exits at EOD prices; the
    trade manager then reassesses the survivors (trail stops, extend targets
    on strong trends); finally the portfolio snapshot is written.
    """
    from paper_trading.outcomes import sync_trade_outcomes, update_post_exit_returns
    from paper_trading.trade_manager import manage_open_trades

    await update_open_trades(as_of)
    await manage_open_trades(as_of)
    await get_portfolio_snapshot(as_of)
    try:
        await sync_trade_outcomes()
        await update_post_exit_returns()
    except Exception as exc:
        logger.warning("outcome analytics update failed (non-fatal): %s", exc)


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _get_eod_prices(session, symbols: list[str], as_of: date) -> dict[str, Decimal]:
    """Read EOD close prices from daily_prices table."""
    rows = await session.execute(
        select(DailyPrice.symbol, DailyPrice.close)
        .where(DailyPrice.symbol.in_(symbols), DailyPrice.price_date == as_of)
    )
    return {row[0]: Decimal(str(row[1])) for row in rows}


async def _fetch_prices_yfinance(symbols: list[str], as_of: date) -> dict[str, Decimal]:
    """Fallback: fetch today's close from yfinance for symbols not yet in DB."""
    from data.fetcher import fetch_ohlcv

    data = await fetch_ohlcv(symbols, as_of - timedelta(days=5), as_of)
    prices: dict[str, Decimal] = {}
    for symbol, df in data.items():
        try:
            import pandas as pd
            df.index = pd.to_datetime(df.index).normalize().map(lambda ts: ts.date())
            if as_of in df.index:
                prices[symbol] = Decimal(str(round(float(df.loc[as_of, "Close"]), 4)))
        except Exception:
            continue
    return prices


async def _current_capital(session) -> Decimal:
    """Return total capital from the latest snapshot, or initial_capital if none exists."""
    snap = (await session.execute(
        select(PortfolioSnapshot).order_by(PortfolioSnapshot.snapshot_date.desc()).limit(1)
    )).scalar_one_or_none()
    return snap.total_capital if snap else settings.initial_capital
