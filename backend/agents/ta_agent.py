"""
Technical Analysis agent.

Fetches 90 days of OHLCV (enough for SMA-50 and meaningful ATR) and computes
a set of momentum / mean-reversion indicators via pandas-ta, then derives
a single composite 0-100 score.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd

from agents.models import AgentInputBundle, TAOutput
from data.fetcher import fetch_ohlcv

logger = logging.getLogger(__name__)

_HISTORY_DAYS = 90


async def run_ta(bundle: AgentInputBundle) -> TAOutput:
    today = date.today()
    start = today - timedelta(days=_HISTORY_DAYS)

    data = await fetch_ohlcv([bundle.symbol], start, today)
    df = data.get(bundle.symbol)

    if df is None or df.empty or len(df) < 20:
        logger.debug("TA: insufficient data for %s", bundle.symbol)
        return TAOutput(symbol=bundle.symbol, score=50)

    return _compute_ta(bundle.symbol, df)


def _compute_ta(symbol: str, df: pd.DataFrame) -> TAOutput:
    try:
        import pandas_ta as ta  # type: ignore
    except ImportError:
        logger.error("pandas-ta not installed")
        return TAOutput(symbol=symbol, score=50)

    close = df["Close"]
    high = df["High"]
    low = df["Low"]

    def _last(series: pd.Series | None) -> float | None:
        if series is None or series.empty:
            return None
        val = series.iloc[-1]
        return float(val) if pd.notna(val) else None

    def _col(frame: pd.DataFrame | None, prefix: str) -> float | None:
        if frame is None or frame.empty:
            return None
        matches = [c for c in frame.columns if c.startswith(prefix)]
        if not matches:
            return None
        val = frame[matches[0]].iloc[-1]
        return float(val) if pd.notna(val) else None

    rsi = ta.rsi(close, length=14)
    macd = ta.macd(close)
    atr = ta.atr(high, low, close, length=14)
    bb = ta.bbands(close, length=20)
    sma20 = ta.sma(close, length=20)
    sma50 = ta.sma(close, length=50)

    rsi_val = _last(rsi)
    macd_hist_val = _col(macd, "MACDh_")
    sma20_val = _last(sma20)
    sma50_val = _last(sma50)
    close_val = float(close.iloc[-1])

    score = _composite_score(
        rsi=rsi_val,
        macd_hist=macd_hist_val,
        close=close_val,
        sma20=sma20_val,
        sma50=sma50_val,
    )

    return TAOutput(
        symbol=symbol,
        rsi_14=rsi_val,
        macd_signal=_col(macd, "MACDs_"),
        macd_hist=macd_hist_val,
        atr_14=_last(atr),
        sma_20=sma20_val,
        sma_50=sma50_val,
        bb_upper=_col(bb, "BBU_"),
        bb_lower=_col(bb, "BBL_"),
        score=score,
    )


def _composite_score(
    rsi: float | None,
    macd_hist: float | None,
    close: float,
    sma20: float | None,
    sma50: float | None,
) -> int:
    """
    Combine indicator signals into a single 0-100 bullish score.

    Weights:
      RSI momentum       30 pts
      MACD histogram     30 pts
      Price vs SMAs      40 pts
    """
    score = 0

    # ── RSI (30 pts) ──────────────────────────────────────────────────────────
    if rsi is not None:
        if rsi < 30:
            score += 30        # oversold — strong long setup
        elif rsi < 40:
            score += 25
        elif rsi <= 60:
            score += 20        # neutral
        elif rsi <= 70:
            score += 10
        else:
            score += 0         # overbought

    # ── MACD histogram (30 pts) ───────────────────────────────────────────────
    if macd_hist is not None:
        if macd_hist > 0:
            score += 30        # bullish momentum
        else:
            score += 10        # bearish momentum

    # ── Price vs SMAs (40 pts) ────────────────────────────────────────────────
    above_sma20 = close > sma20 if sma20 else None
    above_sma50 = close > sma50 if sma50 else None
    sma_trend_up = (sma20 > sma50) if (sma20 and sma50) else None

    if above_sma20:
        score += 15
    if above_sma50:
        score += 15
    if sma_trend_up:
        score += 10

    return min(100, max(0, score))
