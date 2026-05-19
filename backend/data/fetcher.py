"""
yfinance OHLCV fetcher.

Public API
----------
fetch_ohlcv(tickers, start, end)   → dict[symbol, DataFrame]
fetch_ohlcv_sync(...)              → same, synchronous

T2 screening is handled by agents/t2_screener.py — not this module.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import TYPE_CHECKING

import pandas as pd
import yfinance as yf

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Batch size for yfinance bulk downloads — keeps requests manageable
_DOWNLOAD_BATCH_SIZE = 100

# Thread pool for running sync yfinance calls from async context
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="yfinance")


# ── Public async API ──────────────────────────────────────────────────────────

async def fetch_ohlcv(
    tickers: list[str],
    start: date,
    end: date,
) -> dict[str, pd.DataFrame]:
    """
    Async wrapper around fetch_ohlcv_sync. Runs in a thread pool so it doesn't
    block the event loop.

    Returns {symbol: DataFrame} where each DataFrame has columns:
        Open, High, Low, Close, AdjClose, Volume, avg_volume_20d
    and a DatetimeIndex. Tickers with no data or errors are omitted.
    """
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, fetch_ohlcv_sync, tickers, start, end)


# ── Synchronous core ──────────────────────────────────────────────────────────

def fetch_ohlcv_sync(
    tickers: list[str],
    start: date,
    end: date,
) -> dict[str, pd.DataFrame]:
    """
    Download OHLCV for *tickers* between *start* and *end* (both inclusive).

    Strategy
    --------
    - Uses yf.download() in batches of _DOWNLOAD_BATCH_SIZE for efficiency.
    - Fetches auto_adjust=False to preserve raw Close alongside Adj Close.
    - Computes a 20-day rolling average volume on each per-ticker DataFrame.
    - Silently drops tickers that are delisted, return empty data, or error.

    Returns
    -------
    dict[symbol, pd.DataFrame]  — index is date, columns are
        Open | High | Low | Close | AdjClose | Volume | avg_volume_20d
    """
    if not tickers:
        return {}

    # yfinance end date is exclusive — add one day to include `end`
    yf_start = start.isoformat()
    yf_end = (end + timedelta(days=1)).isoformat()

    results: dict[str, pd.DataFrame] = {}

    for batch_start in range(0, len(tickers), _DOWNLOAD_BATCH_SIZE):
        batch = tickers[batch_start : batch_start + _DOWNLOAD_BATCH_SIZE]
        batch_results = _download_batch(batch, yf_start, yf_end)
        results.update(batch_results)

    logger.info(
        "fetch_ohlcv: %d/%d tickers returned data (%s → %s)",
        len(results), len(tickers), start, end,
    )
    return results


# ── Internal helpers ──────────────────────────────────────────────────────────

def _download_batch(
    tickers: list[str],
    yf_start: str,
    yf_end: str,
) -> dict[str, pd.DataFrame]:
    """Download one batch and return normalized per-ticker DataFrames."""
    try:
        raw: pd.DataFrame = yf.download(
            tickers,
            start=yf_start,
            end=yf_end,
            auto_adjust=False,
            progress=False,
            threads=True,
        )
    except Exception as exc:
        logger.error("yfinance batch download failed: %s", exc)
        return {}

    if raw.empty:
        return {}

    return _normalize_and_enrich(raw, tickers)


def _normalize_and_enrich(
    raw: pd.DataFrame,
    tickers: list[str],
) -> dict[str, pd.DataFrame]:
    """
    Split a raw yf.download() result into per-ticker DataFrames, then add
    the 20-day rolling average volume column.

    yfinance column layout:
    - Multiple tickers → MultiIndex columns: (field, ticker)
    - Single ticker    → Flat columns: Open, High, Low, Close, Adj Close, Volume
    """
    results: dict[str, pd.DataFrame] = {}
    is_multi = isinstance(raw.columns, pd.MultiIndex)

    if is_multi:
        available = raw.columns.get_level_values(1).unique().tolist()
    else:
        # Single ticker returned flat columns
        available = tickers[:1]

    for symbol in available:
        try:
            if is_multi:
                df = raw.xs(symbol, axis=1, level=1).copy()
            else:
                df = raw.copy()

            # Drop rows where Close is NaN (happens for non-trading days or
            # delisted stocks that yfinance partially returns)
            df = df.dropna(subset=["Close"])
            if df.empty:
                logger.debug("%s: empty after dropna — skipping", symbol)
                continue

            # Ensure Volume is numeric (yfinance can return object dtype on errors)
            df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce").fillna(0).astype("int64")

            # Rename "Adj Close" → "AdjClose" for consistency
            df = df.rename(columns={"Adj Close": "AdjClose"})

            # Fall back: if AdjClose column is missing (some ETFs / old data),
            # use Close as AdjClose so downstream code never sees NaN
            if "AdjClose" not in df.columns:
                df["AdjClose"] = df["Close"]

            # 20-day rolling average volume; min_periods=1 so the first rows
            # still get a value rather than NaN
            df["avg_volume_20d"] = (
                df["Volume"].rolling(window=20, min_periods=1).mean().round(0)
            )

            # Keep only the columns we care about, in a stable order
            df = df[["Open", "High", "Low", "Close", "AdjClose", "Volume", "avg_volume_20d"]]

            results[symbol] = df

        except Exception as exc:
            logger.warning("%s: extraction failed — %s", symbol, exc)
            continue

    return results
