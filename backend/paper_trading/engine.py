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
    pnl_rows_written: int = 0
    total_unrealized: Decimal = field(default_factory=lambda: Decimal("0"))
    symbols_missing_price: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"UpdateResult({self.as_of}): "
            f"checked={self.trades_checked} "
            f"closed={self.trades_closed} (stops={self.stop_hits}, targets={self.target_hits}) "
            f"pnl_rows={self.pnl_rows_written} "
            f"unrealized=${self.total_unrealized:,.2f}"
        )


# ── Core public functions ─────────────────────────────────────────────────────

async def open_trade(suggestion_id: int, shares: int) -> PaperTrade | None:
    """
    Create a single paper trade from a suggestion.

    Entry is simulated at the suggestion's entry_price (next-day open approximation).
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

        capital_at_risk = suggestion.entry_price * Decimal(str(shares))

        trade = PaperTrade(
            suggestion_id=suggestion_id,
            symbol=suggestion.symbol,
            direction=suggestion.direction,
            entry_date=suggestion.as_of_date,
            entry_price=suggestion.entry_price,
            shares=shares,
            capital_at_risk=capital_at_risk,
            stop_loss=suggestion.stop_loss,
            target_price=suggestion.target_price,
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

                session.add(DailyPnL(
                    trade_id=trade.id,
                    pnl_date=as_of,
                    close_price=close_price,
                    unrealized_pnl=unrealized,
                ))
                result.pnl_rows_written += 1

        await session.commit()

    logger.info(str(result))
    return result


async def get_portfolio_snapshot(as_of: date) -> PortfolioSnapshot:
    """
    Compute and persist a PortfolioSnapshot for *as_of*.

    NAV components:
    - cash_balance          = initial_capital + Σ realized_pnl(all time) − Σ capital_at_risk(open)
    - invested_capital      = Σ capital_at_risk(open trades)
    - unrealized_pnl        = Σ unrealized from today's DailyPnL rows
    - realized_pnl_today    = Σ realized_pnl where exit_date == as_of
    - cumulative_realized   = Σ realized_pnl(all closed trades)
    - total_capital         = cash_balance + invested_capital + unrealized_pnl
                            = initial_capital + cumulative_realized + unrealized_pnl
    """
    async with async_session_factory() as session:
        # Open trades as of today (after update_open_trades has run)
        open_trades: list[PaperTrade] = list(
            (await session.execute(
                select(PaperTrade).where(PaperTrade.is_open == True)
            )).scalars().all()
        )

        invested_capital = sum(
            (t.capital_at_risk for t in open_trades), Decimal("0")
        )

        # Unrealized PnL from today's DailyPnL rows
        unrealized_row = (await session.execute(
            select(func.coalesce(func.sum(DailyPnL.unrealized_pnl), Decimal("0")))
            .where(DailyPnL.pnl_date == as_of)
        )).scalar_one()
        unrealized_pnl = Decimal(str(unrealized_row))

        # Realized PnL: today and cumulative
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

        # Cash = starting capital + all realised gains/losses − money currently in trades
        cash_balance = (
            settings.initial_capital
            + cumulative_realized_pnl
            - invested_capital
        )
        total_capital = cash_balance + invested_capital + unrealized_pnl

        snapshot = PortfolioSnapshot(
            snapshot_date=as_of,
            total_capital=total_capital,
            cash_balance=cash_balance,
            invested_capital=invested_capital,
            unrealized_pnl=unrealized_pnl,
            realized_pnl_today=realized_pnl_today,
            cumulative_realized_pnl=cumulative_realized_pnl,
            open_positions=len(open_trades),
        )
        session.add(snapshot)
        await session.commit()
        await session.refresh(snapshot)

    logger.info(
        "Snapshot(%s): total=$%s  cash=$%s  invested=$%s  "
        "unrealized=$%s  realized_today=$%s  open=%d",
        as_of, total_capital, cash_balance, invested_capital,
        unrealized_pnl, realized_pnl_today, len(open_trades),
    )
    return snapshot


# ── Higher-level orchestration helper ─────────────────────────────────────────

async def accept_suggestions(as_of: date) -> int:
    """
    Open paper trades for today's suggestions, respecting position limits.
    Skips symbols already held and fills up to max_open_positions.
    Returns number of new trades opened.
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

        capital = await _current_capital(session)

    opened = 0
    for s in suggestions:
        if open_count >= settings.max_open_positions:
            break
        if s.symbol in open_symbols:
            continue

        shares = compute_position_size(capital, s.entry_price, s.stop_loss)
        if shares == 0:
            logger.debug("accept_suggestions: zero shares computed for %s — skipping", s.symbol)
            continue

        trade = await open_trade(s.id, shares)
        if trade is not None:
            open_symbols.add(s.symbol)
            open_count += 1
            opened += 1

    logger.info("accept_suggestions(%s): opened %d trade(s)", as_of, opened)
    return opened


async def process_eod(as_of: date) -> None:
    """
    Convenience wrapper: update_open_trades → get_portfolio_snapshot.
    Called by the Celery nightly task after accept_suggestions.
    """
    await update_open_trades(as_of)
    await get_portfolio_snapshot(as_of)


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
