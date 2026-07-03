"""
Market regime filter.

Swing entries (both mean-reversion T1 and momentum T2) historically lose their
edge when the broad market is in a downtrend. The standard practitioner gate
is: only take new long entries while SPY trades above its 200-day SMA.

When the regime is bearish, suggestions are still generated and stored so the
signals remain visible in the UI — but they are marked inactive so the
auto-trading engine skips them.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from config import settings
from data.fetcher import fetch_ohlcv

logger = logging.getLogger(__name__)

_SMA_DAYS = 200
_FETCH_CALENDAR_DAYS = 320   # ~200 trading days + buffer


async def is_market_bullish() -> bool:
    """
    True when the regime index (default SPY) closes above its 200-day SMA,
    or when the filter is disabled / data is unavailable (fail-open so a
    Yahoo outage never silently halts the whole system).
    """
    if not settings.regime_filter_enabled:
        return True

    symbol = settings.regime_symbol
    today = date.today()
    start = today - timedelta(days=_FETCH_CALENDAR_DAYS)

    try:
        data = await fetch_ohlcv([symbol], start, today)
        df = data.get(symbol)
        if df is None or len(df) < _SMA_DAYS:
            logger.warning(
                "Regime filter: insufficient %s history (%d rows) — failing open (bullish)",
                symbol, 0 if df is None else len(df),
            )
            return True

        close = float(df["Close"].iloc[-1])
        sma200 = float(df["Close"].rolling(_SMA_DAYS).mean().iloc[-1])
        bullish = close > sma200
        logger.info(
            "Regime filter: %s close=%.2f  200DMA=%.2f  →  %s",
            symbol, close, sma200, "BULLISH" if bullish else "BEARISH",
        )
        return bullish
    except Exception as exc:
        logger.warning("Regime filter: %s fetch failed (%s) — failing open (bullish)", symbol, exc)
        return True
