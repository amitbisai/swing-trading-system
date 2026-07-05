"""
Market Pulse — a 0-100 health score for the US market that scales how many
new positions the system opens each day (IBD-style market exposure model).

Two ingredients:

  1. SPY trend (60 pts) — close vs 200DMA (+20), close vs 50DMA (+15),
     50DMA vs 200DMA golden cross (+10), MACD histogram sign (+15).
  2. Breadth (40 pts) — % of tracked stocks trading above their own 50-day
     SMA, straight from our daily_prices table. Breadth confirms whether a
     rally is broad-based or carried by a handful of mega-caps.

Exposure ladder (fraction of the user's top-N daily entry cap):

    score >= 75   →  100%   strong uptrend, full participation
    60 – 74       →   60%
    45 – 59       →   40%
    30 – 44       →   20%   (at least 1 entry)
    <  30         →    0%   sideways/weak tape — sit out

The regime filter (SPY < 200DMA → suggestions inactive) still sits underneath
this as the hard off-switch; the pulse handles the shades of grey above it.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import text

from config import settings
from data.fetcher import fetch_ohlcv
from db.session import async_session_factory

logger = logging.getLogger(__name__)

_FETCH_CALENDAR_DAYS = 320

_BREADTH_SQL = text("""
    WITH ranked AS (
        SELECT symbol, close,
               ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY price_date DESC) AS rn
        FROM daily_prices
    ),
    latest AS (SELECT symbol, close FROM ranked WHERE rn = 1),
    -- Up to 50 trading days per symbol; accept >= 20 so breadth still works
    -- while daily_prices history is young (ingest keeps a rolling window that
    -- grows toward 50+). With less than 50 rows this is effectively a 20-30
    -- day MA — the standard short-term breadth variant.
    sma AS (
        SELECT symbol, AVG(close) AS sma50
        FROM ranked WHERE rn <= 50
        GROUP BY symbol HAVING COUNT(*) >= 20
    )
    SELECT COUNT(*) FILTER (WHERE l.close > s.sma50)::float / NULLIF(COUNT(*), 0)
    FROM latest l JOIN sma s USING (symbol)
""")


@dataclass
class MarketPulse:
    score: int                      # 0–100
    label: str                      # STRONG | UPTREND | NEUTRAL | WEAK | AVOID
    spy_close: float | None = None
    spy_sma50: float | None = None
    spy_sma200: float | None = None
    macd_hist: float | None = None
    breadth_pct: float | None = None   # 0.0–1.0, None if unavailable


def _label(score: int) -> str:
    if score >= 75:
        return "STRONG"
    if score >= 60:
        return "UPTREND"
    if score >= 45:
        return "NEUTRAL"
    if score >= 30:
        return "WEAK"
    return "AVOID"


def exposure_fraction(score: int) -> float:
    if score >= 75:
        return 1.0
    if score >= 60:
        return 0.6
    if score >= 45:
        return 0.4
    if score >= 30:
        return 0.2
    return 0.0


def entries_allowed(max_daily: int, score: int) -> int:
    """
    Scale the user's top-N cap by market health.
    max_daily <= 0 means "no cap" — then the pulse only gates on/off.
    """
    frac = exposure_fraction(score)
    if frac == 0.0:
        return 0
    if max_daily <= 0:
        return 10_000
    return max(1, math.ceil(max_daily * frac))


async def get_market_pulse() -> MarketPulse:
    """
    Compute today's market pulse. Fail-open to a NEUTRAL 50 if data is
    unavailable, so an API outage throttles rather than halts the system.
    """
    spy_close = spy_sma50 = spy_sma200 = macd_hist = None
    breadth: float | None = None

    # ── SPY trend ─────────────────────────────────────────────────────────────
    try:
        symbol = settings.regime_symbol
        today = date.today()
        data = await fetch_ohlcv([symbol], today - timedelta(days=_FETCH_CALENDAR_DAYS), today)
        df = data.get(symbol)
        if df is not None and len(df) >= 60:
            close = df["Close"]
            spy_close = float(close.iloc[-1])
            spy_sma50 = float(close.rolling(50).mean().iloc[-1])
            if len(df) >= 200:
                spy_sma200 = float(close.rolling(200).mean().iloc[-1])
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            macd_line = ema12 - ema26
            signal = macd_line.ewm(span=9, adjust=False).mean()
            macd_hist = float((macd_line - signal).iloc[-1])
    except Exception as exc:
        logger.warning("Market pulse: SPY fetch failed (%s)", exc)

    # ── Breadth from our own price DB ─────────────────────────────────────────
    try:
        async with async_session_factory() as session:
            row = (await session.execute(_BREADTH_SQL)).scalar_one_or_none()
            if row is not None:
                breadth = float(row)
    except Exception as exc:
        logger.warning("Market pulse: breadth query failed (%s)", exc)

    # ── Score ─────────────────────────────────────────────────────────────────
    if spy_close is None:
        logger.warning("Market pulse: no SPY data — failing open at NEUTRAL 50")
        return MarketPulse(score=50, label=_label(50), breadth_pct=breadth)

    trend = 0.0
    if spy_sma200 is not None and spy_close > spy_sma200:
        trend += 20
    if spy_sma50 is not None and spy_close > spy_sma50:
        trend += 15
    if spy_sma50 is not None and spy_sma200 is not None and spy_sma50 > spy_sma200:
        trend += 10
    if macd_hist is not None and macd_hist > 0:
        trend += 15

    if breadth is not None:
        score = trend + 40.0 * breadth
    else:
        score = trend * (100.0 / 60.0)   # rescale trend-only to 0–100

    score_int = int(round(min(max(score, 0.0), 100.0)))
    pulse = MarketPulse(
        score=score_int,
        label=_label(score_int),
        spy_close=spy_close,
        spy_sma50=spy_sma50,
        spy_sma200=spy_sma200,
        macd_hist=macd_hist,
        breadth_pct=breadth,
    )
    logger.info(
        "Market pulse: %d/100 (%s)  SPY=%.2f  50DMA=%s  200DMA=%s  breadth=%s",
        pulse.score, pulse.label, spy_close,
        f"{spy_sma50:.2f}" if spy_sma50 else "n/a",
        f"{spy_sma200:.2f}" if spy_sma200 else "n/a",
        f"{breadth*100:.0f}%" if breadth is not None else "n/a",
    )
    return pulse
