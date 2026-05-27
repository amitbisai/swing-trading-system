"""
Finnhub news fetcher — async, rate-limited to stay within the free tier (60 calls/min).

Fetches company news headlines for a list of symbols and returns a mapping of
symbol → list[headline_string].

Rate limiting strategy
----------------------
  Batch size  : 10 symbols fetched concurrently
  Inter-batch delay : 12 s  →  10 calls / 12 s ≈ 50 calls/min  (headroom below the 60/min cap)
  Total time for 147 T1 stocks: ~15 batches × 12 s ≈ 180 s (3 min) — fits comfortably
  inside the orchestrator's nightly window.

Usage
-----
    from data.finnhub import get_all_headlines
    headlines = await get_all_headlines(symbols)   # dict[str, list[str]]
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta

import httpx

from config import settings

logger = logging.getLogger(__name__)

_BATCH_SIZE    = 10    # symbols fetched in parallel per batch
_BATCH_DELAY   = 12.0  # seconds to wait between batches (50 calls/min ≈ safe under 60/min cap)
_DAYS_BACK     = 7     # calendar days of news history to request
_MAX_HEADLINES = 5     # max headlines per symbol passed to the Claude scorer


async def _fetch_one(
    client: httpx.AsyncClient,
    symbol: str,
    from_date: str,
    to_date: str,
) -> tuple[str, list[str]]:
    """
    Fetch up to _MAX_HEADLINES titles for a single symbol from the Finnhub
    company-news endpoint.  On any error (network, 4xx, 5xx, parse) returns
    an empty list — the caller handles neutralisation.
    """
    try:
        resp = await client.get(
            "https://finnhub.io/api/v1/company-news",
            params={
                "symbol": symbol,
                "from":   from_date,
                "to":     to_date,
                "token":  settings.finnhub_api_key,
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        articles = resp.json()
        headlines = [
            a["headline"]
            for a in articles
            if isinstance(a, dict) and a.get("headline")
        ][:_MAX_HEADLINES]
        return symbol, headlines
    except Exception as exc:
        logger.warning("Finnhub: failed to fetch news for %s: %s", symbol, exc)
        return symbol, []


async def get_all_headlines(
    symbols: list[str],
    days_back: int = _DAYS_BACK,
) -> dict[str, list[str]]:
    """
    Fetch recent news headlines for all symbols, respecting the free-tier rate limit.

    Parameters
    ----------
    symbols  : list of ticker strings
    days_back: how many calendar days of news history to request (default 7)

    Returns
    -------
    dict mapping symbol → list[headline_str].
    Symbols with no news (or API errors) map to an empty list.
    """
    if not settings.finnhub_api_key:
        logger.info("Finnhub: no API key configured — returning empty headlines for all symbols")
        return {sym: [] for sym in symbols}

    today     = date.today()
    to_date   = today.strftime("%Y-%m-%d")
    from_date = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")

    results: dict[str, list[str]] = {}
    total_batches = (len(symbols) + _BATCH_SIZE - 1) // _BATCH_SIZE

    async with httpx.AsyncClient() as client:
        for batch_idx, i in enumerate(range(0, len(symbols), _BATCH_SIZE)):
            batch  = symbols[i : i + _BATCH_SIZE]
            tasks  = [_fetch_one(client, sym, from_date, to_date) for sym in batch]
            pairs  = await asyncio.gather(*tasks)

            for sym, headlines in pairs:
                results[sym] = headlines

            # Wait between batches — skip the delay after the final batch
            if batch_idx < total_batches - 1:
                logger.debug(
                    "Finnhub: batch %d/%d complete — waiting %.0fs before next batch",
                    batch_idx + 1, total_batches, _BATCH_DELAY,
                )
                await asyncio.sleep(_BATCH_DELAY)

    found = sum(1 for v in results.values() if v)
    logger.info(
        "Finnhub: headlines fetched — %d/%d symbols had recent news (last %d days)",
        found, len(symbols), days_back,
    )
    return results
