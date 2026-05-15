"""
Sentiment agent — wraps the Alpha Vantage NEWS_SENTIMENT endpoint.

Budget: 25 API calls/day (free tier).  When the key is missing or the
budget is exhausted we return a neutral score of 50 so the pipeline
continues without crashing.
"""

from __future__ import annotations

import logging

from agents.models import AgentInputBundle, SentimentOutput
from config import settings
from data.alpha_vantage import get_news_sentiment

logger = logging.getLogger(__name__)


async def run_sentiment(bundle: AgentInputBundle) -> SentimentOutput:
    # Skip the API call entirely if no key is configured (local dev / CI)
    if not settings.alpha_vantage_api_key:
        return SentimentOutput(symbol=bundle.symbol, score=50)

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
