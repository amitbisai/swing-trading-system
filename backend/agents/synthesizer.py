"""
Synthesizer — scores each stock for LONG and SHORT setups independently,
picks the stronger direction, gates on minimum confidence, then calls Claude
to write a 2-sentence rationale and persists the top-20 suggestions.

Scoring model (0-100 each axis):
  LONG  confidence = (ta_long_score  + sentiment_score       + pattern_long_score)  // 3
  SHORT confidence = (ta_short_score + (100-sentiment_score) + pattern_short_score) // 3

Direction is whichever axis scores higher.  Both must clear _MIN_CONFIDENCE
(60) to be included.  Final list is sorted by confidence and capped at
_MAX_SUGGESTIONS (20).
"""

from __future__ import annotations

import logging
import random
from datetime import date
from decimal import Decimal

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from sqlalchemy import delete, update

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

_MIN_CONFIDENCE  = 63    # minimum confidence score to emit a suggestion
_MAX_SUGGESTIONS = 40    # cap on daily signals (T1 + T2 combined)


# ── Directional scoring ───────────────────────────────────────────────────────

def _ta_long_score(ta: TAOutput) -> int:
    """Bullish TA score — already computed by ta_agent; reuse directly."""
    return ta.score


def _ta_short_score(ta: TAOutput, entry_price: float) -> int:
    """
    Bearish TA score computed from raw TA indicators (mirror of bullish logic).

    RSI overbought + negative MACD + price below SMAs → high score = good SHORT.
    """
    score = 0

    # ── RSI (30 pts) ──────────────────────────────────────────────────────────
    if ta.rsi_14 is not None:
        if ta.rsi_14 > 70:
            score += 30        # overbought — strong short setup
        elif ta.rsi_14 > 60:
            score += 20
        elif ta.rsi_14 >= 40:
            score += 10        # neutral
        elif ta.rsi_14 >= 30:
            score += 5
        # < 30 = oversold = bullish → 0 bearish pts

    # ── MACD histogram (30 pts) ───────────────────────────────────────────────
    if ta.macd_hist is not None:
        if ta.macd_hist < 0:
            score += 30        # bearish momentum
        else:
            score += 5         # bullish momentum → small bearish adjustment

    # ── Price vs SMAs (40 pts) ────────────────────────────────────────────────
    below_sma20  = (entry_price < ta.sma_20)  if ta.sma_20  else None
    below_sma50  = (entry_price < ta.sma_50)  if ta.sma_50  else None
    sma_downtrend = (ta.sma_20 < ta.sma_50)  if (ta.sma_20 and ta.sma_50) else None

    if below_sma20:
        score += 15
    if below_sma50:
        score += 15
    if sma_downtrend:
        score += 10

    return min(100, max(0, score))


def _pattern_long_score(pat: PatternOutput) -> int:
    """Bullish pattern score — already computed; reuse directly."""
    return pat.score


def _pattern_short_score(pat: PatternOutput, entry_price: float) -> int:
    """
    Bearish pattern score: high score = close to resistance + bearish signals.
    """
    # Base: proximity to resistance (100 = at resistance = ideal short entry)
    if pat.support_level and pat.resistance_level:
        price_range = pat.resistance_level - pat.support_level
        if price_range > 0:
            dist_from_resistance = (pat.resistance_level - entry_price) / price_range
            base = max(0, min(100, int(100 - dist_from_resistance * 100)))
        else:
            base = 50
    else:
        base = 50

    bonus = 0
    detected = pat.patterns_detected
    bonus += 15 if "SHOOTING_STAR"     in detected else 0
    bonus += 10 if "DOWNTREND"         in detected else 0
    bonus += 5  if "DOJI"              in detected else 0   # indecision near resistance
    bonus -= 15 if "HAMMER"            in detected else 0
    bonus -= 20 if "BULLISH_ENGULFING" in detected else 0
    bonus -= 10 if "VOLUME_BREAKOUT"   in detected else 0
    bonus -= 5  if "UPTREND"           in detected else 0

    return max(0, min(100, base + bonus))


def _score_and_direction(
    bundle: AgentInputBundle,
    ta: TAOutput,
    sent: SentimentOutput,
    pat: PatternOutput,
) -> tuple[Direction, int, int, int]:
    """
    Compute LONG and SHORT confidence scores; return the stronger direction.

    Returns: (direction, confidence, ta_score_used, pattern_score_used)
    """
    entry = bundle.entry_price

    ta_long     = _ta_long_score(ta)
    ta_short    = _ta_short_score(ta, entry)
    pat_long    = _pattern_long_score(pat)
    pat_short   = _pattern_short_score(pat, entry)
    sent_long   = sent.score
    sent_short  = 100 - sent.score   # negative news supports shorts

    long_conf  = (ta_long  + sent_long  + pat_long)  // 3
    short_conf = (ta_short + sent_short + pat_short) // 3

    if long_conf >= short_conf:
        return Direction.LONG,  long_conf,  ta_long,  pat_long
    else:
        return Direction.SHORT, short_conf, ta_short, pat_short


# ── Main synthesizer ──────────────────────────────────────────────────────────

async def run_synthesizer(
    bundles: list[AgentInputBundle],
    ta_results: list[TAOutput],
    sentiment_results: list[SentimentOutput],
    pattern_results: list[PatternOutput],
) -> list[SynthesisOutput]:

    llm = ChatAnthropic(model=settings.llm_model, api_key=settings.anthropic_api_key)

    candidates: list[SynthesisOutput] = []

    # Shuffle input order so that when stocks tie on confidence score, alphabetical
    # bias (from the scanner's ORDER BY symbol) doesn't always favour A–F.
    # zip produces aligned tuples — shuffle them together to preserve alignment.
    combined_inputs = list(zip(bundles, ta_results, sentiment_results, pattern_results))
    random.shuffle(combined_inputs)
    logger.info(
        "Synthesizer: processing %d stocks in shuffled order — first 5: %s",
        len(combined_inputs),
        ", ".join(b.symbol for b, *_ in combined_inputs[:5]),
    )

    for bundle, ta, sent, pat in combined_inputs:

        if bundle.entry_price <= 0:
            logger.warning("Synthesizer: %s has no entry price — skipping", bundle.symbol)
            continue

        direction, confidence, ta_score_used, pat_score_used = _score_and_direction(
            bundle, ta, sent, pat
        )

        if confidence < _MIN_CONFIDENCE:
            logger.debug(
                "Synthesizer: %s %s dropped (confidence %d < %d)",
                bundle.symbol, direction.value, confidence, _MIN_CONFIDENCE,
            )
            continue

        stop, target = compute_stop_target(bundle.entry_price, bundle.tier, direction)
        rationale = await _llm_rationale(llm, bundle, ta, sent, pat, direction, confidence)

        candidates.append(
            SynthesisOutput(
                symbol=bundle.symbol,
                tier=bundle.tier,
                direction=direction,
                confidence_score=confidence,
                entry_price=bundle.entry_price,
                stop_loss=stop,
                target_price=target,
                rationale=rationale,
                ta_score=ta_score_used,
                sentiment_score=sent.score,
                pattern_score=pat_score_used,
                as_of_date=bundle.as_of_date,
            )
        )

    # Sort by confidence descending only.  Ties are broken by the random shuffle
    # applied to combined_inputs above — Python's sort is stable, so candidates
    # at equal confidence appear in the shuffled (random) order they were appended.
    # This ensures different stocks surface each day rather than always A–F.
    candidates.sort(key=lambda s: s.confidence_score, reverse=True)
    suggestions = candidates[:_MAX_SUGGESTIONS]

    if len(candidates) > _MAX_SUGGESTIONS:
        logger.info(
            "Synthesizer: %d candidates → capped to top %d",
            len(candidates), _MAX_SUGGESTIONS,
        )

    as_of = bundles[0].as_of_date if bundles else date.today()
    await _persist_suggestions(suggestions, as_of)
    return suggestions


# ── Persistence ───────────────────────────────────────────────────────────────

async def _persist_suggestions(suggestions: list[SynthesisOutput], as_of: date) -> None:
    async with async_session_factory() as session:
        # Always deactivate previous suggestions when agents run — even if today
        # produced 0 signals.  Skipping this when suggestions is empty caused old
        # signals to persist and show in the frontend on zero-signal days.
        await session.execute(
            update(Suggestion)
            .where(Suggestion.is_active == True, Suggestion.as_of_date < as_of)
            .values(is_active=False)
        )
        await session.commit()

    if not suggestions:
        logger.info("No suggestions to persist for %s — old signals deactivated.", as_of)
        return

    async with async_session_factory() as session:
        # Re-running the orchestrator today is idempotent — delete first
        # (safe because today's suggestions can't have paper trades yet)
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


# ── LLM rationale ─────────────────────────────────────────────────────────────

async def _llm_rationale(
    llm: ChatAnthropic,
    bundle: AgentInputBundle,
    ta: TAOutput,
    sent: SentimentOutput,
    pat: PatternOutput,
    direction: Direction,
    confidence: int,
) -> str:
    direction_word = "bullish long" if direction == Direction.LONG else "bearish short"
    patterns_str   = ", ".join(pat.patterns_detected) if pat.patterns_detected else "none"

    prompt = (
        f"You are a swing trading analyst. Summarize in exactly 2 concise sentences "
        f"why {bundle.symbol} ({bundle.tier.value}) is a {direction_word} swing trade candidate. "
        f"Entry: ${bundle.entry_price:.2f}. "
        f"RSI={ta.rsi_14:.1f}, MACD hist={ta.macd_hist:.4f}, "
        f"SMA20={ta.sma_20:.2f}, SMA50={ta.sma_50:.2f}. "
        f"News sentiment: {sent.score}/100 ({sent.news_count_24h} articles). "
        f"Chart patterns: {patterns_str}. "
        f"Support={pat.support_level}, Resistance={pat.resistance_level}. "
        f"Overall confidence: {confidence}/100."
    )
    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        return str(response.content)
    except Exception as exc:
        logger.error("LLM rationale failed for %s: %s", bundle.symbol, exc)
        return (
            f"{bundle.symbol} shows a {direction_word} setup with confidence {confidence}/100 "
            f"based on technical, sentiment, and pattern analysis."
        )
