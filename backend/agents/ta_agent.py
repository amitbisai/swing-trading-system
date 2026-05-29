"""
Technical Analysis agent.

Fetches 90 days of OHLCV (enough for SMA-50 and meaningful ATR) and computes
a set of momentum / mean-reversion indicators using pure pandas (no pandas-ta),
then derives a single composite 0-100 score.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd

from agents.models import AgentInputBundle, TAOutput
from data.fetcher import fetch_ohlcv

logger = logging.getLogger(__name__)

_HISTORY_DAYS = 90


# ── Pure-pandas indicator implementations ─────────────────────────────────────

def _rsi(close: pd.Series, length: int = 14) -> pd.Series:
    """Wilder's RSI using EMA smoothing (matches pandas-ta output)."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    # Avoid division by zero: when avg_loss is 0, RS → inf → RSI = 100
    rs = avg_gain / avg_loss.replace(0.0, float("nan"))
    return 100 - (100 / (1 + rs))


def _macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (macd_line, signal_line, histogram)."""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    length: int = 14,
) -> pd.Series:
    """Average True Range using Wilder's EMA smoothing."""
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()


def _bbands(
    close: pd.Series,
    length: int = 20,
    std_mult: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (upper_band, mid_band, lower_band)."""
    mid = close.rolling(window=length).mean()
    std = close.rolling(window=length).std(ddof=0)
    return mid + std_mult * std, mid, mid - std_mult * std


def _sma(close: pd.Series, length: int) -> pd.Series:
    return close.rolling(window=length).mean()


# ── Agent entry point ─────────────────────────────────────────────────────────

async def run_ta(
    bundle: AgentInputBundle,
    df: pd.DataFrame | None = None,
) -> TAOutput:
    """
    Compute TA indicators for *bundle*.

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
        logger.debug("TA: insufficient data for %s", bundle.symbol)
        return TAOutput(symbol=bundle.symbol, score=50)

    return _compute_ta(bundle.symbol, df)


def _compute_ta(symbol: str, df: pd.DataFrame) -> TAOutput:
    close = df["Close"]
    high  = df["High"]
    low   = df["Low"]

    def _last(series: pd.Series) -> float | None:
        if series is None or series.empty:
            return None
        val = series.iloc[-1]
        return float(val) if pd.notna(val) else None

    # Compute indicators
    rsi_series              = _rsi(close, length=14)
    macd_line, sig_line, hist = _macd(close)
    atr_series              = _atr(high, low, close, length=14)
    bb_upper, _bb_mid, bb_lower = _bbands(close, length=20)
    sma20_series            = _sma(close, length=20)
    sma50_series            = _sma(close, length=50)

    rsi_val       = _last(rsi_series)
    macd_hist_val = _last(hist)
    macd_sig_val  = _last(sig_line)
    atr_val       = _last(atr_series)
    bb_upper_val  = _last(bb_upper)
    bb_lower_val  = _last(bb_lower)
    sma20_val     = _last(sma20_series)
    sma50_val     = _last(sma50_series)
    close_val     = float(close.iloc[-1])

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
        macd_signal=macd_sig_val,
        macd_hist=macd_hist_val,
        atr_14=atr_val,
        sma_20=sma20_val,
        sma_50=sma50_val,
        bb_upper=bb_upper_val,
        bb_lower=bb_lower_val,
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
