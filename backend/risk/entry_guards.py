"""
Entry guards — checks that block an entry the moment it stops being the
trade that was scored.

1. Earnings proximity (T1): a stock reporting earnings within N days can gap
   through any stop overnight; TA signals are irrelevant against that. The T2
   screener has excluded these since v2 — this module lets the synthesizer
   apply the same gate to T1 signals.

2. Gap-chase guard: if the live price has already run more than
   max_entry_gap_pct beyond the signal's entry, the setup that was scored
   (entry/stop/target geometry, R:R) no longer exists — buying the gap means
   chasing with a stale stop. Skip; if the price pulls back within range on a
   later hourly run, the entry happens normally.
"""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal

import pandas as pd

logger = logging.getLogger(__name__)

_CAL_EXECUTOR = ThreadPoolExecutor(max_workers=6, thread_name_prefix="earnings_cal")


# ── Gap-chase guard ───────────────────────────────────────────────────────────

def is_gap_chase(
    direction: str,
    signal_entry: Decimal,
    live_price: Decimal,
    max_gap_pct: float,
) -> bool:
    """
    True when the live price has moved more than max_gap_pct IN THE TRADE'S
    FAVOUR past the signal entry — i.e. the move already happened without us.
    Adverse gaps are not blocked here (stop/target geometry still holds and
    the falling-knife/stop rules handle them).
    """
    if max_gap_pct <= 0 or signal_entry <= 0:
        return False
    limit = Decimal(str(max_gap_pct))
    if direction == "SHORT":
        return live_price < signal_entry * (1 - limit)
    return live_price > signal_entry * (1 + limit)


# ── Earnings proximity ────────────────────────────────────────────────────────

def _days_to_earnings_sync(symbol: str) -> int | None:
    """Blocking: parse the next earnings date from yfinance's calendar."""
    import yfinance as yf

    try:
        cal = yf.Ticker(symbol).calendar
        time.sleep(0.1)   # light rate limiting

        earnings_date = None
        if isinstance(cal, dict):
            vals = cal.get("Earnings Date")
            if vals:
                first = vals[0] if isinstance(vals, (list, tuple)) else vals
                if first is not None and pd.notna(first):
                    earnings_date = pd.Timestamp(first).date()
        elif isinstance(cal, pd.DataFrame) and not cal.empty:
            if "Earnings Date" in cal.index:
                val = cal.loc["Earnings Date"].iloc[0]
                if pd.notna(val):
                    earnings_date = pd.Timestamp(val).date()
            elif "Earnings Date" in cal.columns:
                val = cal["Earnings Date"].iloc[0]
                if pd.notna(val):
                    earnings_date = pd.Timestamp(val).date()

        if earnings_date is None:
            return None
        return (earnings_date - date.today()).days
    except Exception as exc:
        logger.debug("earnings calendar fetch failed for %s: %s", symbol, exc)
        return None


async def get_days_to_earnings(symbols: list[str]) -> dict[str, int | None]:
    """Concurrently fetch days-until-earnings for *symbols* (None = unknown)."""
    if not symbols:
        return {}
    loop = asyncio.get_event_loop()

    async def _one(sym: str) -> tuple[str, int | None]:
        return sym, await loop.run_in_executor(_CAL_EXECUTOR, _days_to_earnings_sync, sym)

    results = await asyncio.gather(*[_one(s) for s in symbols])
    return dict(results)
