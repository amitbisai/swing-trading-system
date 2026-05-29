"""
Pattern agent — detects chart patterns and computes support/resistance levels.

Uses the last 90 days of OHLCV.  Scoring favours setups where price is
pulling back toward support (better risk/reward for a long entry).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd

from agents.models import AgentInputBundle, PatternOutput
from data.fetcher import fetch_ohlcv

logger = logging.getLogger(__name__)

_HISTORY_DAYS = 90


async def run_pattern(
    bundle: AgentInputBundle,
    df: pd.DataFrame | None = None,
) -> PatternOutput:
    """
    Detect chart patterns for *bundle*.

    If *df* is supplied (pre-fetched by the orchestrator) no network call is
    made.  Without *df* a per-stock yfinance download is performed as a
    fallback (used when calling the agent standalone for testing).
    """
    if df is None:
        today = date.today()
        start = today - timedelta(days=_HISTORY_DAYS)
        data = await fetch_ohlcv([bundle.symbol], start, today)
        df = data.get(bundle.symbol)

    if df is None or df.empty or len(df) < 20:
        logger.debug("Pattern: insufficient data for %s", bundle.symbol)
        return PatternOutput(symbol=bundle.symbol, score=50)

    return _detect_patterns(bundle.symbol, df)


def _detect_patterns(symbol: str, df: pd.DataFrame) -> PatternOutput:
    patterns: list[str] = []

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]

    close_val = float(close.iloc[-1])
    open_val = float(df["Open"].iloc[-1])
    prev_close = float(close.iloc[-2]) if len(close) >= 2 else close_val

    # ── Support / resistance ──────────────────────────────────────────────────
    high_20 = float(high.rolling(20).max().iloc[-1])
    low_20 = float(low.rolling(20).min().iloc[-1])
    high_50 = float(high.rolling(min(50, len(high))).max().iloc[-1])
    low_50 = float(low.rolling(min(50, len(low))).min().iloc[-1])

    support = round(low_20, 4)
    resistance = round(high_20, 4)
    price_range = high_20 - low_20

    # ── Candlestick patterns (last bar) ───────────────────────────────────────
    body = abs(close_val - open_val)
    upper_wick = high.iloc[-1] - max(close_val, open_val)
    lower_wick = min(close_val, open_val) - low.iloc[-1]
    total_range = float(high.iloc[-1] - low.iloc[-1])

    if total_range > 0:
        # Hammer: small body, long lower wick, at or near support
        if lower_wick >= 2 * body and upper_wick < body:
            patterns.append("HAMMER")

        # Shooting star: small body, long upper wick, near resistance
        if upper_wick >= 2 * body and lower_wick < body:
            patterns.append("SHOOTING_STAR")

        # Doji: very small body relative to total range
        if body <= 0.1 * total_range:
            patterns.append("DOJI")

    # Bullish engulfing: today's green bar fully wraps yesterday's red bar
    if (
        close_val > open_val          # today green
        and prev_close < float(df["Open"].iloc[-2]) if len(df) >= 2 else False  # yesterday red
        and close_val > float(df["Open"].iloc[-2]) if len(df) >= 2 else False
        and open_val < prev_close
    ):
        patterns.append("BULLISH_ENGULFING")

    # ── Trend context ─────────────────────────────────────────────────────────
    sma20_now = float(close.rolling(20).mean().iloc[-1])
    sma50_now = float(close.rolling(min(50, len(close))).mean().iloc[-1])

    if close_val > sma20_now > sma50_now:
        patterns.append("UPTREND")
    elif close_val < sma20_now < sma50_now:
        patterns.append("DOWNTREND")

    # ── Volume confirmation ───────────────────────────────────────────────────
    avg_vol_20 = float(volume.rolling(20).mean().iloc[-1])
    today_vol = float(volume.iloc[-1])
    if today_vol > 1.5 * avg_vol_20 and close_val > prev_close:
        patterns.append("VOLUME_BREAKOUT")

    # ── Score ─────────────────────────────────────────────────────────────────
    score = _pattern_score(
        close=close_val,
        support=low_20,
        resistance=high_20,
        price_range=price_range,
        patterns=patterns,
    )

    return PatternOutput(
        symbol=symbol,
        patterns_detected=patterns,
        support_level=support,
        resistance_level=resistance,
        score=score,
    )


def _pattern_score(
    close: float,
    support: float,
    resistance: float,
    price_range: float,
    patterns: list[str],
) -> int:
    """
    Base score = proximity to support (best risk/reward for a long entry).
    Bonus points for bullish patterns; penalty for bearish ones.
    """
    if price_range <= 0:
        base = 50
    else:
        # 100 = at support, 0 = at resistance
        dist_from_support = (close - support) / price_range
        base = max(0, min(100, int(100 - dist_from_support * 100)))

    bonus = 0
    bonus += 15 if "HAMMER" in patterns else 0
    bonus += 20 if "BULLISH_ENGULFING" in patterns else 0
    bonus += 10 if "VOLUME_BREAKOUT" in patterns else 0
    bonus += 5 if "UPTREND" in patterns else 0
    bonus -= 15 if "SHOOTING_STAR" in patterns else 0
    bonus -= 10 if "DOWNTREND" in patterns else 0

    return max(0, min(100, base + bonus))
