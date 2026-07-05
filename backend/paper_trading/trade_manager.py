"""
Nightly dynamic exit manager — "let winners run, protect the gains".

Runs once per night on every OPEN position (between mark-to-market and the
portfolio snapshot). Initial stop/target set at entry are never widened on the
risk side; this module only ratchets in the trade's favour:

  1. BREAKEVEN     — once the position is up >= breakeven_after_r × initial
                     risk, the stop moves to at least the entry price
                     (a winner is never allowed to become a loser).
  2. CHANDELIER    — trailing stop at highest close since entry − 3 × ATR(14)
                     (LeBeau's chandelier exit). Only ever tightens.
  3. TARGET EXTEND — if the trend is still intact AND price has covered
                     >= 60% of the way to the current target, the target is
                     raised to close + 2 × ATR so a strong trend isn't capped
                     at the original level.

"Trend intact" (LONG): close > SMA20 > SMA50 and MACD histogram > 0.
For SHORT positions every rule is mirrored.

Each adjustment stamps levels_updated_at + a human-readable adjustment_note,
which the Portfolio UI surfaces as a badge so managed positions stand out.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
from sqlalchemy import select

from agents.ta_agent import _atr, _macd, _sma
from config import settings
from data.fetcher import fetch_ohlcv
from db.models import PaperTrade
from db.session import async_session_factory

logger = logging.getLogger(__name__)

_HISTORY_DAYS = 90


@dataclass
class ManageResult:
    as_of: date
    trades_checked: int = 0
    stops_raised: int = 0
    targets_extended: int = 0
    breakevens_set: int = 0
    notes: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"ManageResult({self.as_of}): checked={self.trades_checked} "
            f"stops_raised={self.stops_raised} targets_extended={self.targets_extended} "
            f"breakevens={self.breakevens_set}"
        )


async def manage_open_trades(as_of: date) -> ManageResult:
    """Reassess stop/target for every open trade. Ratchets only — never loosens."""
    result = ManageResult(as_of=as_of)
    if not settings.dynamic_exits_enabled:
        logger.info("Dynamic exits disabled — skipping trade management")
        return result

    async with async_session_factory() as session:
        open_trades: list[PaperTrade] = list(
            (await session.execute(
                select(PaperTrade).where(PaperTrade.is_open == True)
            )).scalars().all()
        )
        if not open_trades:
            logger.info("manage_open_trades(%s): no open trades", as_of)
            return result

        result.trades_checked = len(open_trades)
        symbols = sorted({t.symbol for t in open_trades})
        start = as_of - timedelta(days=_HISTORY_DAYS)
        ohlcv = await fetch_ohlcv(symbols, start, as_of)

        for trade in open_trades:
            df = ohlcv.get(trade.symbol)
            if df is None or len(df) < 30:
                logger.debug("manage: insufficient data for %s — skipped", trade.symbol)
                continue
            try:
                _manage_one(trade, df, as_of, result)
            except Exception as exc:
                logger.warning("manage: %s failed — %s", trade.symbol, exc)

        await session.commit()

    logger.info(str(result))
    return result


def _manage_one(trade: PaperTrade, df: pd.DataFrame, as_of: date, result: ManageResult) -> None:
    is_long = trade.direction == "LONG"
    close_s = df["Close"]
    close = float(close_s.iloc[-1])

    atr = float(_atr(df["High"], df["Low"], close_s, 14).iloc[-1])
    sma20 = float(_sma(close_s, 20).iloc[-1])
    sma50 = float(_sma(close_s, 50).iloc[-1]) if len(df) >= 50 else sma20
    _, _, hist = _macd(close_s)
    macd_hist = float(hist.iloc[-1])

    if atr <= 0 or pd.isna(atr):
        return

    entry = float(trade.entry_price)
    stop = float(trade.stop_loss)
    target = float(trade.target_price)
    initial_risk = abs(entry - float(trade.original_stop or trade.stop_loss))
    if initial_risk <= 0:
        return

    profit = (close - entry) if is_long else (entry - close)
    r_multiple = profit / initial_risk

    # Highest (lowest for shorts) close since entry — for the chandelier trail
    entry_ts = pd.Timestamp(trade.entry_date)
    idx = pd.to_datetime(close_s.index)
    since_entry = close_s[idx >= entry_ts]
    if since_entry.empty:
        since_entry = close_s.iloc[-1:]
    extreme = float(since_entry.max() if is_long else since_entry.min())

    trend_intact = (
        (close > sma20 > sma50 and macd_hist > 0)
        if is_long
        else (close < sma20 < sma50 and macd_hist < 0)
    )

    notes: list[str] = []
    new_stop = stop
    new_target = target

    # ── 1. Breakeven protection ───────────────────────────────────────────────
    if r_multiple >= settings.breakeven_after_r:
        be = entry
        if (is_long and be > new_stop) or (not is_long and be < new_stop):
            new_stop = be
            notes.append(f"stop → breakeven ${be:,.2f} (up {r_multiple:.1f}R)")
            result.breakevens_set += 1

    # ── 2. Chandelier trailing stop (only when in profit) ────────────────────
    if profit > 0:
        chandelier = (
            extreme - atr * settings.trail_stop_atr_mult
            if is_long
            else extreme + atr * settings.trail_stop_atr_mult
        )
        if (is_long and chandelier > new_stop) or (not is_long and chandelier < new_stop):
            new_stop = round(chandelier, 4)
            notes.append(f"trail stop → ${new_stop:,.2f} (chandelier)")
            result.stops_raised += 1

    # ── 3. Target extension (trend intact + 60% of the move captured) ────────
    progress = (
        (close - entry) / (target - entry)
        if is_long and target > entry
        else (entry - close) / (entry - target)
        if not is_long and entry > target
        else 0.0
    )
    if trend_intact and progress >= 0.60:
        extended = (
            close + atr * settings.target_extend_atr_mult
            if is_long
            else close - atr * settings.target_extend_atr_mult
        )
        if (is_long and extended > new_target) or (not is_long and extended < new_target):
            new_target = round(extended, 4)
            notes.append(f"target → ${new_target:,.2f} (trend intact)")
            result.targets_extended += 1

    if not notes:
        return

    # First adjustment: preserve the entry-time levels for the UI comparison
    if trade.original_stop is None:
        trade.original_stop = trade.stop_loss
    if trade.original_target is None:
        trade.original_target = trade.target_price

    trade.stop_loss = Decimal(str(new_stop))
    trade.target_price = Decimal(str(new_target))
    trade.levels_updated_at = as_of
    trade.adjustment_note = "; ".join(notes)

    logger.info("manage: %s — %s", trade.symbol, trade.adjustment_note)
    result.notes.append(f"{trade.symbol}: {trade.adjustment_note}")
