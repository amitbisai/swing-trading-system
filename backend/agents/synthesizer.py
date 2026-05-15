"""
Synthesizer — aggregates TA / Sentiment / Pattern scores, gates on a minimum
confidence threshold, then calls Claude to write a 2-sentence rationale and
persists the accepted suggestions to Supabase.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from sqlalchemy import delete

from agents.models import (
    AgentInputBundle,
    Direction,
    PatternOutput,
    SentimentOutput,
    SynthesisOutput,
    TAOutput,
)
from config import settings
from db.models import Suggestion
from db.session import async_session_factory
from risk.stop_target import compute_stop_target

logger = logging.getLogger(__name__)

_MIN_CONFIDENCE = 55   # suggestions below this score are dropped


async def run_synthesizer(
    bundles: list[AgentInputBundle],
    ta_results: list[TAOutput],
    sentiment_results: list[SentimentOutput],
    pattern_results: list[PatternOutput],
) -> list[SynthesisOutput]:
    llm = ChatAnthropic(model=settings.llm_model, api_key=settings.anthropic_api_key)
    suggestions: list[SynthesisOutput] = []

    for bundle, ta, sent, pat in zip(bundles, ta_results, sentiment_results, pattern_results):
        combined_score = (ta.score + sent.score + pat.score) // 3

        if combined_score < _MIN_CONFIDENCE:
            logger.debug(
                "Synthesizer: %s dropped (score %d < %d)",
                bundle.symbol, combined_score, _MIN_CONFIDENCE,
            )
            continue

        # Use price from scanner bundle — avoids a redundant yfinance call
        entry_price = bundle.entry_price
        if entry_price <= 0:
            logger.warning("Synthesizer: %s has no entry price — skipping", bundle.symbol)
            continue

        stop, target = compute_stop_target(entry_price, bundle.tier)
        rationale = await _llm_rationale(llm, bundle, ta, sent, pat, combined_score)

        suggestions.append(
            SynthesisOutput(
                symbol=bundle.symbol,
                tier=bundle.tier,
                direction=Direction.LONG,
                confidence_score=combined_score,
                entry_price=entry_price,
                stop_loss=stop,
                target_price=target,
                rationale=rationale,
                ta_score=ta.score,
                sentiment_score=sent.score,
                pattern_score=pat.score,
                as_of_date=bundle.as_of_date,
            )
        )

    await _persist_suggestions(suggestions)
    return suggestions


async def _persist_suggestions(suggestions: list[SynthesisOutput]) -> None:
    if not suggestions:
        return

    as_of = suggestions[0].as_of_date

    async with async_session_factory() as session:
        # Re-running the orchestrator today is idempotent — delete first
        await session.execute(delete(Suggestion).where(Suggestion.as_of_date == as_of))

        for s in suggestions:
            session.add(
                Suggestion(
                    symbol=s.symbol,
                    tier=s.tier.value,
                    direction=s.direction.value,
                    confidence_score=s.confidence_score,
                    entry_price=Decimal(str(round(s.entry_price, 4))),
                    stop_loss=Decimal(str(round(s.stop_loss, 4))),
                    target_price=Decimal(str(round(s.target_price, 4))),
                    rationale=s.rationale,
                    as_of_date=s.as_of_date,
                    ta_score=s.ta_score,
                    sentiment_score=s.sentiment_score,
                    pattern_score=s.pattern_score,
                )
            )

        await session.commit()
        logger.info("Persisted %d suggestion(s) for %s", len(suggestions), as_of)


async def _llm_rationale(
    llm: ChatAnthropic,
    bundle: AgentInputBundle,
    ta: TAOutput,
    sent: SentimentOutput,
    pat: PatternOutput,
    score: int,
) -> str:
    patterns_str = ", ".join(pat.patterns_detected) if pat.patterns_detected else "none"
    prompt = (
        f"You are a swing trading analyst. Summarize in exactly 2 concise sentences "
        f"why {bundle.symbol} ({bundle.tier.value}) is a swing trade candidate. "
        f"Entry: ${bundle.entry_price:.2f}. "
        f"TA score: {ta.score}/100 (RSI={ta.rsi_14}, MACD hist={ta.macd_hist}). "
        f"Sentiment: {sent.score}/100 ({sent.news_count_24h} news items, "
        f"avg sentiment={sent.headline_sentiment}). "
        f"Pattern: {pat.score}/100 (patterns: {patterns_str}, "
        f"support={pat.support_level}, resistance={pat.resistance_level}). "
        f"Overall confidence: {score}/100."
    )
    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        return str(response.content)
    except Exception as exc:
        logger.error("LLM rationale failed for %s: %s", bundle.symbol, exc)
        return (
            f"{bundle.symbol} shows a combined confidence score of {score}/100 "
            f"across technical, sentiment, and pattern analysis."
        )
