"""
Live market universe from Yahoo Finance's public screener API.

Replaces the static 250-stock seed list as the primary T2 input.
No API key required — uses Yahoo Finance's public predefined screener endpoint.

Sources combined:
  most_actives  — top 100 stocks by today's dollar volume
  day_gainers   — top 75 stocks up >2% with above-average volume

Why this beats a static list
-----------------------------
A static list can only catch stocks already on it.  "Most Active" reflects
where institutional money is actually flowing TODAY — earnings reactions,
sector rotations, macro events.  Day Gainers ensures we don't miss breakouts
that have only just started accumulating volume.

Key data returned per stock (from the screener, before any OHLCV fetch):
  symbol, name, price, market_cap, volume, avg_volume_10d,
  rvol (volume / avg_volume_10d),
  today_change_pct (positive = up, negative = down — critical for falling-knife filter)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}
_TIMEOUT = 20.0


async def _fetch_screener(scr_id: str, count: int = 100) -> list[dict[str, Any]]:
    """
    Fetch a Yahoo Finance predefined screener result.
    Returns a list of raw quote dicts, or [] on any failure.

    Available scr_id values (subset):
      most_actives, day_gainers, day_losers,
      undervalued_growth_stocks, growth_technology_stocks,
      aggressive_small_caps, small_cap_gainers
    """
    params = {
        "formatted": "false",
        "scrIds": scr_id,
        "count": count,
        "start": 0,
        "region": "US",
        "lang": "en-US",
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(_BASE_URL, params=params, headers=_HEADERS)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("finance", {}).get("result", [])
            if results:
                quotes = results[0].get("quotes", [])
                logger.info("yahoo_screener: %s returned %d quotes", scr_id, len(quotes))
                return quotes
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "yahoo_screener: %s HTTP %s — falling back to static universe",
            scr_id, exc.response.status_code,
        )
    except Exception as exc:
        logger.warning("yahoo_screener: %s failed (%s) — falling back to static universe", scr_id, exc)
    return []


async def get_live_t2_universe(
    min_price: float = 5.0,
    min_market_cap: float = 200_000_000,    # $200M — slightly lower than T2 config gate
    max_market_cap: float = 100_000_000_000,
    min_avg_volume: int = 300_000,
    exclude_symbols: set[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch Yahoo Finance Most Active + Day Gainers, merge, filter, and return
    a list of candidate dicts ready for the T2 screener's Stage 1.

    Each dict contains:
        symbol            str
        name              str
        price             float
        market_cap        float
        volume            int     today's volume
        avg_volume_10d    int     10-day average daily volume
        rvol              float   today_volume / avg_volume_10d
        today_change_pct  float   today's % price change (raw, e.g. +3.2 = +3.2%)
        prev_close        float

    Falls back gracefully to an empty list (caller uses static universe as backup).
    """
    most_active_raw, day_gainers_raw = await asyncio.gather(
        _fetch_screener("most_actives", count=100),
        _fetch_screener("day_gainers",  count=75),
    )

    # Merge — most_active takes priority on duplicates (better volume data)
    combined: dict[str, dict[str, Any]] = {}
    for q in day_gainers_raw + most_active_raw:    # most_active last → wins on conflict
        sym = q.get("symbol")
        if sym:
            combined[sym] = q

    exclude = exclude_symbols or set()
    results: list[dict[str, Any]] = []

    for sym, q in combined.items():
        if sym in exclude:
            continue

        # Only US equities (skip ETFs, mutual funds, warrants etc.)
        quote_type = (q.get("quoteType") or "").upper()
        if quote_type and quote_type not in ("EQUITY", ""):
            continue

        price     = float(q.get("regularMarketPrice") or 0)
        mktcap    = float(q.get("marketCap") or 0)
        volume    = int(q.get("regularMarketVolume") or 0)
        avg_vol   = int(
            q.get("averageDailyVolume10Day")
            or q.get("averageDailyVolume3Month")
            or 1
        )
        change_pct = float(q.get("regularMarketChangePercent") or 0)
        rvol = volume / avg_vol if avg_vol > 0 else 0.0

        # Basic gates (cheap — no network call)
        if price < min_price:
            continue
        if mktcap > 0 and (mktcap < min_market_cap or mktcap > max_market_cap):
            continue
        if avg_vol < min_avg_volume:
            continue

        results.append({
            "symbol":           sym,
            "name":             q.get("shortName") or q.get("longName") or sym,
            "price":            round(price, 4),
            "market_cap":       mktcap,
            "volume":           volume,
            "avg_volume_10d":   avg_vol,
            "rvol":             round(rvol, 2),
            "today_change_pct": round(change_pct, 2),
            "prev_close":       float(q.get("regularMarketPreviousClose") or price),
        })

    logger.info(
        "yahoo_screener: %d candidates after basic filters "
        "(from %d most_active + %d day_gainers, excl %d T1)",
        len(results), len(most_active_raw), len(day_gainers_raw), len(exclude),
    )
    return results
