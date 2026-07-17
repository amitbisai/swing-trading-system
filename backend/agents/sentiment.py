"""
Sentiment agent — Finnhub news headlines + Claude batch scoring.

Design rationale
----------------
Alpha Vantage (25 calls/day free tier) could only score the top-25 stocks
by TA+Pattern, leaving 122/147 T1 stocks stuck at a default score of 50.
A constant value provides *no* discriminating power in the confidence formula.

Finnhub (60 calls/min free tier) covers ALL 147 T1 stocks in ~3 minutes.
One Claude call then scores every stock simultaneously — the full pipeline
model (settings.llm_model) is used to guarantee the call succeeds.
Stocks with no news still receive 50 (neutral), but that now reflects a
genuine absence of news rather than an API budget limitation.

Pipeline (called once per nightly run)
---------------------------------------
  1. get_all_headlines(symbols)  — Finnhub REST, batched, rate-limited
  2. Build one structured prompt with all {symbol: [headlines]} pairs
  3. llm.ainvoke(prompt)         — Claude returns JSON {symbol: score}
  4. Map results back to SentimentOutput for every bundle

Fallback behaviour
------------------
  • No FINNHUB_API_KEY           → all stocks receive 50 (neutral)
  • Finnhub returns no headlines → all stocks receive 50
  • Claude call fails            → all stocks receive 50; error logged
  • Score missing for a symbol   → 50
"""

from __future__ import annotations

import asyncio
import json
import logging

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

from agents.models import AgentInputBundle, SentimentOutput
from config import settings
from data.finnhub import get_all_headlines

logger = logging.getLogger(__name__)

# Chunked scoring: one mega-call with ~500 stocks proved fragile in production
# (run died at this step nightly from 2026-07-10 to 2026-07-16, and 500 scores
# also exceed a 4096-token response). Bounded chunks keep each request small,
# fully parseable, and individually fallback-safe.
_CHUNK_SIZE = 100
_CHUNK_TIMEOUT = 120.0   # seconds per Claude call
_CHUNK_MAX_TOKENS = 2048  # 100 scores ≈ 1000 tokens — generous headroom


async def run_sentiment_batch(bundles: list[AgentInputBundle]) -> list[SentimentOutput]:
    """
    Score news sentiment for ALL bundles in a single pass.

    Returns one SentimentOutput per bundle, in the same order as *bundles*.
    """
    if not bundles:
        return []

    symbols = [b.symbol for b in bundles]

    # ── Guard: no API key ──────────────────────────────────────────────────────
    if not settings.finnhub_api_key:
        logger.info("Sentiment: FINNHUB_API_KEY not set — all %d stocks default to 50", len(symbols))
        return [SentimentOutput(symbol=s, score=50) for s in symbols]

    # ── 1. Fetch Finnhub headlines ─────────────────────────────────────────────
    headlines_map = await get_all_headlines(symbols)
    stocks_with_news = {sym: hl for sym, hl in headlines_map.items() if hl}

    if not stocks_with_news:
        logger.info("Sentiment: no headlines returned by Finnhub — all stocks default to 50")
        return [SentimentOutput(symbol=s, score=50) for s in symbols]

    logger.info(
        "Sentiment: %d/%d stocks have Finnhub headlines — sending to Claude (%s)",
        len(stocks_with_news), len(symbols), settings.llm_model,
    )

    # ── 2 + 3. Score in bounded chunks ─────────────────────────────────────────
    llm = ChatAnthropic(
        model=settings.llm_model,
        api_key=settings.anthropic_api_key,
        max_tokens=_CHUNK_MAX_TOKENS,
    )

    items = list(stocks_with_news.items())
    chunks = [
        dict(items[i : i + _CHUNK_SIZE]) for i in range(0, len(items), _CHUNK_SIZE)
    ]

    raw_scores: dict[str, int] = {}
    for idx, chunk in enumerate(chunks, 1):
        try:
            chunk_scores = await asyncio.wait_for(
                _score_chunk(llm, chunk), timeout=_CHUNK_TIMEOUT
            )
            raw_scores.update(chunk_scores)
            logger.info(
                "Sentiment: chunk %d/%d scored %d/%d symbols",
                idx, len(chunks), len(chunk_scores), len(chunk),
            )
        except asyncio.TimeoutError:
            logger.error(
                "Sentiment: chunk %d/%d timed out (>%ds) — its %d symbols default to 50",
                idx, len(chunks), int(_CHUNK_TIMEOUT), len(chunk),
            )
        except Exception as exc:
            logger.error(
                "Sentiment: chunk %d/%d failed — its %d symbols default to 50: %s",
                idx, len(chunks), len(chunk), exc,
            )

    logger.info(
        "Sentiment: Claude scored %d/%d stocks that had news (%d chunk(s))",
        len(raw_scores), len(stocks_with_news), len(chunks),
    )

    # ── 4. Assemble SentimentOutput for every bundle ───────────────────────────
    outputs: list[SentimentOutput] = []
    for bundle in bundles:
        sym       = bundle.symbol
        headlines = headlines_map.get(sym, [])

        if sym in raw_scores:
            score = max(0, min(100, int(raw_scores[sym])))
        else:
            score = 50  # no news or Claude parse failure → neutral

        outputs.append(
            SentimentOutput(
                symbol=sym,
                score=score,
                news_count_24h=len(headlines),
            )
        )

    with_real_score = sum(1 for o in outputs if o.symbol in raw_scores)
    logger.info(
        "Sentiment batch complete: %d/%d stocks received a real Claude score "
        "(%d had no Finnhub headlines)",
        with_real_score, len(bundles), len(bundles) - len(stocks_with_news),
    )
    return outputs


# ── Chunk scoring helper ──────────────────────────────────────────────────────

async def _score_chunk(llm: ChatAnthropic, chunk: dict[str, list[str]]) -> dict[str, int]:
    """Score one chunk of {symbol: headlines}. Raises on failure (caller handles)."""
    news_block = "\n\n".join(
        f"[{sym}]\n" + "\n".join(f"- {h}" for h in hl) for sym, hl in chunk.items()
    )
    prompt = (
        "You are a financial news sentiment analyst specialising in short-term swing trading.\n"
        "For each stock ticker listed below, read the provided headlines and assign an integer "
        "sentiment score from 0 to 100:\n"
        "  0-30  = bearish   (negative earnings, guidance cut, regulatory risk, downgrade)\n"
        "  31-49 = mildly bearish / uncertain\n"
        "  50    = neutral / no clear signal\n"
        "  51-69 = mildly bullish / positive\n"
        "  70-100 = bullish  (beat + raise, major upgrade, strong guidance, catalyst)\n\n"
        "Scoring factors (swing-trade relevant, 1-2 week horizon):\n"
        "  - Earnings surprise (beat/miss vs estimate)\n"
        "  - Forward guidance revision (raised/lowered)\n"
        "  - Analyst rating changes (upgrade/downgrade, price target)\n"
        "  - Regulatory/legal actions\n"
        "  - Macro exposure (sector tailwinds/headwinds)\n"
        "  - Management changes, M&A rumours\n\n"
        "Return ONLY a valid JSON object mapping each ticker to its integer score. "
        "No explanation, no markdown fences, no extra text.\n"
        'Example: {"AAPL": 72, "TSLA": 38, "NVDA": 65}\n\n'
        f"{news_block}"
    )

    response = await llm.ainvoke([HumanMessage(content=prompt)])
    raw_text = str(response.content).strip()

    # Strip markdown code fences if the model wraps the JSON
    if "```" in raw_text:
        for part in raw_text.split("```"):
            candidate = part.strip()
            if candidate.startswith("json"):
                candidate = candidate[4:].strip()
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
    return json.loads(raw_text)


# ── Legacy single-stock shim (kept for backward compatibility) ─────────────────

async def run_sentiment(bundle: AgentInputBundle) -> SentimentOutput:
    """
    Deprecated single-stock entry point.  Wraps run_sentiment_batch() for any
    callers that still use the old per-stock signature.
    """
    results = await run_sentiment_batch([bundle])
    return results[0] if results else SentimentOutput(symbol=bundle.symbol, score=50)
