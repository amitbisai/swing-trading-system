"""
Sentiment agent — Finnhub news headlines + Claude batch scoring.

Design rationale
----------------
Alpha Vantage (25 calls/day free tier) could only score the top-25 stocks
by TA+Pattern, leaving 122/147 T1 stocks stuck at a default score of 50.
A constant value provides *no* discriminating power in the confidence formula.

Finnhub (60 calls/min free tier) covers ALL 147 T1 stocks in ~3 minutes.
One Claude Haiku call then scores every stock simultaneously — cheap (~$0.002)
and fast (~5 s).  Stocks with no news still receive 50 (neutral), but that now
reflects a genuine absence of news rather than an API budget limitation.

Pipeline (called once per nightly run)
---------------------------------------
  1. get_all_headlines(symbols)  — Finnhub REST, batched, rate-limited
  2. Build one structured prompt with all {symbol: [headlines]} pairs
  3. llm.ainvoke(prompt)         — Claude Haiku returns JSON {symbol: score}
  4. Map results back to SentimentOutput for every bundle

Fallback behaviour
------------------
  • No FINNHUB_API_KEY           → all stocks receive 50 (neutral)
  • Finnhub returns no headlines → all stocks receive 50
  • Claude call fails            → stocks with headlines receive 50; others 50
  • Score missing for a symbol   → 50
"""

from __future__ import annotations

import json
import logging

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

from agents.models import AgentInputBundle, SentimentOutput
from config import settings
from data.finnhub import get_all_headlines

logger = logging.getLogger(__name__)

# Use Haiku for batch sentiment — adequate quality, minimal cost/latency
_HAIKU_MODEL = "claude-haiku-4-5"


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

    # ── 2. Build Claude batch prompt ───────────────────────────────────────────
    news_block = "\n\n".join(
        f"[{sym}]\n" + "\n".join(f"- {h}" for h in hl)
        for sym, hl in stocks_with_news.items()
    )

    prompt = (
        "You are a financial news sentiment analyst specialising in short-term swing trading.\n"
        "For each stock ticker listed below, read the provided headlines and assign an integer "
        "sentiment score from 0 to 100:\n"
        "  0–30  = bearish   (negative earnings, guidance cut, regulatory risk, downgrade)\n"
        "  31–49 = mildly bearish / uncertain\n"
        "  50    = neutral / no clear signal\n"
        "  51–69 = mildly bullish / positive\n"
        "  70–100 = bullish  (beat + raise, major upgrade, strong guidance, catalyst)\n\n"
        "Scoring factors (swing-trade relevant, 1-2 week horizon):\n"
        "  • Earnings surprise (beat/miss vs estimate)\n"
        "  • Forward guidance revision (raised/lowered)\n"
        "  • Analyst rating changes (upgrade/downgrade, price target)\n"
        "  • Regulatory/legal actions\n"
        "  • Macro exposure (sector tailwinds/headwinds)\n"
        "  • Management changes, M&A rumours\n\n"
        "Return ONLY a valid JSON object mapping each ticker to its integer score. "
        "No explanation, no markdown fences, no extra text.\n"
        'Example: {"AAPL": 72, "TSLA": 38, "NVDA": 65}\n\n'
        f"{news_block}"
    )

    # ── 3. Claude Haiku batch call ─────────────────────────────────────────────
    raw_scores: dict[str, int] = {}
    llm = ChatAnthropic(
        model=_HAIKU_MODEL,
        api_key=settings.anthropic_api_key,
        max_tokens=1024,
    )

    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        text = str(response.content).strip()

        # Strip markdown code fences if the model wraps the JSON
        if "```" in text:
            parts = text.split("```")
            # Take the first fenced block's content
            for part in parts:
                candidate = part.strip()
                if candidate.startswith("json"):
                    candidate = candidate[4:].strip()
                try:
                    raw_scores = json.loads(candidate)
                    break
                except json.JSONDecodeError:
                    continue
        else:
            raw_scores = json.loads(text)

        logger.info(
            "Sentiment: Claude Haiku scored %d/%d stocks that had news",
            len(raw_scores), len(stocks_with_news),
        )
    except json.JSONDecodeError as exc:
        logger.error("Sentiment: failed to parse Claude JSON response: %s", exc)
    except Exception as exc:
        logger.error("Sentiment: Claude batch call failed: %s", exc, exc_info=True)

    # ── 4. Assemble SentimentOutput for every bundle ───────────────────────────
    outputs: list[SentimentOutput] = []
    for bundle in bundles:
        sym      = bundle.symbol
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

    with_news = sum(1 for o in outputs if o.news_count_24h > 0)
    logger.info(
        "Sentiment batch complete: %d/%d stocks had Finnhub headlines; "
        "%d received a real score from Claude",
        with_news, len(bundles), len(raw_scores),
    )
    return outputs


# ── Legacy single-stock shim (kept for backward compatibility) ─────────────────

async def run_sentiment(bundle: AgentInputBundle) -> SentimentOutput:
    """
    Deprecated single-stock entry point.  Wraps run_sentiment_batch() for any
    callers that still use the old per-stock signature.
    """
    results = await run_sentiment_batch([bundle])
    return results[0] if results else SentimentOutput(symbol=bundle.symbol, score=50)
