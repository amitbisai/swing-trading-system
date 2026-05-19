"""
T2 News Validation Agent.

For each T2 candidate:
  1. Fetch the 5 most recent news headlines from yfinance (free, no API limit).
  2. Send all candidates' headlines to Claude in ONE batch call.
  3. Claude returns a per-stock: news_summary (1-2 sentences) + verdict
     (SUPPORTS | NEUTRAL | CONTRADICTS the momentum/accumulation signal).

The result is stored in the t2_scans table and shown in the frontend.

Existing sentiment.py (Alpha Vantage) continues to score T1+T2 stocks
inside the main orchestrator pipeline — this module is separate and feeds
the T2 scan history, not the final trading suggestions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import yfinance as yf

from agents.t2_screener import T2Candidate

logger = logging.getLogger(__name__)

_NEWS_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="t2_news")
_MAX_HEADLINES_PER_STOCK = 5


# ── Public API ────────────────────────────────────────────────────────────────

async def get_news_summaries(
    candidates: list[T2Candidate],
) -> dict[str, dict[str, str]]:
    """
    Returns {symbol: {"summary": "...", "verdict": "SUPPORTS|NEUTRAL|CONTRADICTS"}}
    for every candidate.  Falls back to neutral on any error.
    """
    if not candidates:
        return {}

    # Step 1: fetch headlines for all candidates concurrently
    headlines_map = await _fetch_all_headlines(candidates)

    # Step 2: one Claude call to validate all at once
    try:
        results = await _claude_batch_validate(candidates, headlines_map)
    except Exception as exc:
        logger.warning("T2 news: Claude batch call failed: %s", exc)
        results = {}

    # Fill in neutral fallback for any missing
    for c in candidates:
        if c.symbol not in results:
            results[c.symbol] = {
                "summary": "No recent news available for validation.",
                "verdict": "NEUTRAL",
            }

    return results


# ── Step 1: yfinance headline fetch ──────────────────────────────────────────

async def _fetch_all_headlines(candidates: list[T2Candidate]) -> dict[str, list[str]]:
    loop = asyncio.get_event_loop()

    async def _one(sym: str) -> tuple[str, list[str]]:
        try:
            headlines = await loop.run_in_executor(
                _NEWS_EXECUTOR, _fetch_headlines_sync, sym
            )
            return sym, headlines
        except Exception as exc:
            logger.debug("T2 news: headlines failed for %s: %s", sym, exc)
            return sym, []

    results = await asyncio.gather(*[_one(c.symbol) for c in candidates])
    return dict(results)


def _fetch_headlines_sync(symbol: str) -> list[str]:
    """Blocking yfinance news fetch — runs in thread pool."""
    try:
        ticker = yf.Ticker(symbol)
        news = ticker.news or []
        time.sleep(0.1)
        headlines: list[str] = []
        for item in news[:_MAX_HEADLINES_PER_STOCK]:
            title = ""
            # yfinance news item format varies by version
            if isinstance(item, dict):
                # Try new format first
                content = item.get("content", {})
                if isinstance(content, dict):
                    title = content.get("title", "")
                if not title:
                    title = item.get("title", "")
            if title:
                headlines.append(title)
        return headlines
    except Exception as exc:
        logger.debug("_fetch_headlines_sync(%s) failed: %s", symbol, exc)
        return []


# ── Step 2: Claude batch validation ──────────────────────────────────────────

async def _claude_batch_validate(
    candidates: list[T2Candidate],
    headlines_map: dict[str, list[str]],
) -> dict[str, dict[str, str]]:
    """
    One Claude call for all candidates.
    Returns {symbol: {summary, verdict}}.
    """
    try:
        import anthropic  # noqa: PLC0415
    except ImportError:
        logger.warning("T2 news: anthropic package not installed — skipping Claude validation")
        return {}

    import os  # noqa: PLC0415
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key or api_key.startswith("sk-test"):
        logger.info("T2 news: no valid ANTHROPIC_API_KEY — skipping Claude validation")
        return {}

    # Build the prompt
    stock_blocks: list[str] = []
    for c in candidates:
        headlines = headlines_map.get(c.symbol, [])
        headline_text = (
            "\n".join(f"  - {h}" for h in headlines)
            if headlines
            else "  (no recent headlines found)"
        )
        stock_blocks.append(
            f"SYMBOL: {c.symbol}\n"
            f"Company: {c.name or c.symbol} | Sector: {c.sector or 'N/A'}\n"
            f"Signal: Tier {c.signal_tier.value} | Score {c.t2_score:.0f}/100 | "
            f"RVOL {c.rvol:.1f}x | {c.signal_summary}\n"
            f"Recent headlines:\n{headline_text}"
        )

    prompt = (
        "You are a financial analyst reviewing momentum stock signals against recent news.\n\n"
        "For each stock below, return a JSON object with:\n"
        '  "summary": 1-2 sentences on whether recent news supports the momentum signal\n'
        '  "verdict": one of SUPPORTS, NEUTRAL, or CONTRADICTS\n\n'
        "SUPPORTS = news confirms the bullish momentum (earnings beat, contract win, "
        "analyst upgrade, sector tailwind)\n"
        "CONTRADICTS = news undermines the momentum (earnings miss, scandal, sector headwind, "
        "insider selling)\n"
        "NEUTRAL = news is unrelated, mixed, or insufficient\n\n"
        "Return ONLY a JSON object keyed by ticker symbol. Example:\n"
        '{"AAPL": {"summary": "...", "verdict": "SUPPORTS"}, '
        '"MSFT": {"summary": "...", "verdict": "NEUTRAL"}}\n\n'
        "Stocks to analyse:\n\n" + "\n\n".join(stock_blocks)
    )

    client = anthropic.AsyncAnthropic(api_key=api_key)
    loop = asyncio.get_event_loop()

    def _call_claude():
        import anthropic as _anthropic  # noqa: PLC0415
        sync_client = _anthropic.Anthropic(api_key=api_key)
        msg = sync_client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text

    raw = await loop.run_in_executor(None, _call_claude)

    # Parse JSON response — Claude sometimes wraps in ```json ... ```
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    parsed: dict = json.loads(raw)

    results: dict[str, dict[str, str]] = {}
    for sym, val in parsed.items():
        if isinstance(val, dict):
            results[sym] = {
                "summary": str(val.get("summary", "")),
                "verdict": str(val.get("verdict", "NEUTRAL")).upper(),
            }
    return results
