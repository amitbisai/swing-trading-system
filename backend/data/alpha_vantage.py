"""Alpha Vantage client. Free tier: 25 requests/day — use sparingly."""
import httpx

from config import settings

_BASE = "https://www.alphavantage.co/query"
_daily_call_count = 0
DAILY_LIMIT = 25


async def get_news_sentiment(symbol: str) -> dict:
    global _daily_call_count
    if _daily_call_count >= DAILY_LIMIT:
        return {}

    params = {
        "function": "NEWS_SENTIMENT",
        "tickers": symbol,
        "limit": "10",
        "apikey": settings.alpha_vantage_api_key,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(_BASE, params=params)
        _daily_call_count += 1
        if resp.status_code == 200:
            return resp.json()
    return {}


async def get_technical_indicator(symbol: str, function: str, interval: str = "daily") -> dict:
    global _daily_call_count
    if _daily_call_count >= DAILY_LIMIT:
        return {}

    params = {
        "function": function,
        "symbol": symbol,
        "interval": interval,
        "apikey": settings.alpha_vantage_api_key,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(_BASE, params=params)
        _daily_call_count += 1
        if resp.status_code == 200:
            return resp.json()
    return {}
