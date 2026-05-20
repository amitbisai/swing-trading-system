"""
Sentiment agent — wraps the Alpha Vantage NEWS_SENTIMENT endpoint.

Budget: 25 API calls/day (free tier).  When the key is missing or the
budget is exhausted we return a neutral score of 50 so the pipeline
continues without crashing.

The module-level counter ensures we never exceed 25 calls per process run.
Since the agents service runs as a fresh process each night, the counter
resets automatically.
"""

from __future__ import annotations

import asyncio
import logging

from agents.models import AgentInputBundle, SentimentOutput
from config import settings
from data.alpha_vantage import get_news_sentiment

logger = logging.getLogger(__name__)

# ── Daily budget guard ────────────────────────────────────────────────────────
_AV_DAILY_LIMIT = 25          # Alpha Vantage free tier: 25 calls/day
_av_calls_used  = 0           # resets each process run (= each nightly cron)
_av_lock        = asyncio.Lock()


async def run_sentiment(bundle: AgentInputBundle) -> SentimentOutput:
    global _av_calls_used

    # Skip the API call entirely if no key is configured (local dev / CI)
    if not settings.alpha_vantage_api_key:
        return SentimentOutput(symbol=bundle.symbol, score=50)

    # Enforce daily budget — return neutral immediately once exhausted
    async with _av_lock:
        if _av_calls_used >= _AV_DAILY_LIMIT:
            return SentimentOutput(symbol=bundle.symbol, score=50)
        _av_calls_used += 1
        call_number = _av_calls_used

    logger.debug("Sentiment: AV call %d/%d for %s", call_number, _AV_DAILY_LIMIT, bundle.symbol)

    try:
        raw = await get_news_sentiment(bundle.symbol)
    except Exception as exc:
        logger.warning("Sentiment API error for %s: %s", bundle.symbol, exc)
        return SentimentOutput(symbol=bundle.symbol, score=50)

    if not raw or "feed" not in raw or not raw["feed"]:
        return SentimentOutput(symbol=bundle.symbol, score=50)

    feed = raw["feed"]

    sentiments: list[float] = []
    for item in feed:
        try:
            sentiments.append(float(item["overall_sentiment_score"]))
        except (KeyError, TypeError, ValueError):
            continue

    if not sentiments:
        return SentimentOutput(symbol=bundle.symbol, score=50)

    avg = sum(sentiments) / len(sentiments)
    # Map [-1.0, 1.0] → [0, 100]; clamp to valid range
    score = max(0, min(100, int(50 + avg * 50)))

    return SentimentOutput(
        symbol=bundle.symbol,
        headline_sentiment=round(avg, 4),
        news_count_24h=len(feed),
        score=score,
    )
