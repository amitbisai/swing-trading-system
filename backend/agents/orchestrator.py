"""
LangGraph orchestrator — scan → TA+Pattern → Sentiment (top N) → Synthesize.

Graph topology
--------------
    scan_node
        │
    ta_pattern_node     (TA ‖ Pattern, all stocks, parallel)
        │
    sentiment_node      (Alpha Vantage on top-25 by TA+Pattern score only)
        │
    synthesize_node
        │
       END

Sentiment is run last so the limited Alpha Vantage budget (25 calls/day on
the free tier) is spent on stocks that already show strong technical and
pattern signals — not wasted on weak setups.

Run manually:
    cd backend && python -m agents.orchestrator
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from agents.models import (
    AgentInputBundle,
    PatternOutput,
    ScannerOutput,
    SentimentOutput,
    SynthesisOutput,
    TAOutput,
)
from agents.pattern import run_pattern
from agents.scanner import run_scanner
from agents.sentiment import run_sentiment
from agents.synthesizer import run_synthesizer
from agents.t1_store import save_t1_scan
from agents.ta_agent import run_ta

logger = logging.getLogger(__name__)

_AGENT_TIMEOUT:   float = 30.0   # seconds per individual agent call
_AV_DAILY_LIMIT:  int   = 25     # Alpha Vantage free tier: 25 calls/day


# ── State ─────────────────────────────────────────────────────────────────────

class OrchestratorState(TypedDict):
    scanner_outputs:   list[ScannerOutput]
    bundles:           list[AgentInputBundle]
    ta_results:        list[TAOutput]
    sentiment_results: list[SentimentOutput]
    pattern_results:   list[PatternOutput]
    suggestions:       list[SynthesisOutput]


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _guarded(coro: Any, fallback: Any) -> Any:
    """
    Run *coro* with a hard 30-second timeout.
    On timeout or any exception, log and return *fallback*.
    Prevents a single slow/broken stock from blocking the whole pipeline.
    """
    try:
        return await asyncio.wait_for(coro, timeout=_AGENT_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning("Agent call timed out (>%.0fs)", _AGENT_TIMEOUT)
        return fallback
    except Exception as exc:
        logger.error("Agent call raised an exception: %s", exc, exc_info=True)
        return fallback


async def _neutral(symbol: str) -> SentimentOutput:
    """Return a neutral sentiment score without making any API call."""
    return SentimentOutput(symbol=symbol, score=50)


# ── Graph nodes ───────────────────────────────────────────────────────────────

async def scan_node(state: OrchestratorState) -> OrchestratorState:
    """
    Query DB for active T1 stocks + run the T2 momentum screener.
    Populates scanner_outputs and bundles.
    """
    scanner_outputs, bundles = await run_scanner()
    state["scanner_outputs"] = scanner_outputs
    state["bundles"] = bundles
    logger.info("scan_node: %d symbols selected", len(bundles))
    return state


async def ta_pattern_node(state: OrchestratorState) -> OrchestratorState:
    """
    Stage 1 of analysis — run TA and Pattern agents in parallel for ALL stocks.

    Results are used in the next node to rank stocks before spending the
    Alpha Vantage budget on sentiment.
    """
    bundles = state["bundles"]
    if not bundles:
        state["ta_results"]      = []
        state["pattern_results"] = []
        return state

    ta_coros = [
        _guarded(run_ta(b), TAOutput(symbol=b.symbol, score=50))
        for b in bundles
    ]
    pattern_coros = [
        _guarded(run_pattern(b), PatternOutput(symbol=b.symbol, score=50))
        for b in bundles
    ]

    # TA and Pattern run fully in parallel
    ta_list, pattern_list = await asyncio.gather(
        asyncio.gather(*ta_coros),
        asyncio.gather(*pattern_coros),
    )

    state["ta_results"]      = list(ta_list)
    state["pattern_results"] = list(pattern_list)

    logger.info(
        "ta_pattern_node: TA=%d  Pattern=%d",
        len(ta_list), len(pattern_list),
    )
    return state


async def sentiment_node(state: OrchestratorState) -> OrchestratorState:
    """
    Stage 2 of analysis — run Alpha Vantage sentiment on the top-ranked stocks.

    Ranking uses (ta_score + pattern_score) so the 25-call daily budget is
    spent on stocks with the strongest technical + pattern signals.
    Remaining stocks receive a neutral score of 50 immediately.
    """
    bundles         = state["bundles"]
    ta_results      = state["ta_results"]
    pattern_results = state["pattern_results"]

    if not bundles:
        state["sentiment_results"] = []
        return state

    # Build score lookup maps
    ta_map      = {r.symbol: r.score for r in ta_results}
    pattern_map = {r.symbol: r.score for r in pattern_results}

    # Rank by combined TA + Pattern score (descending)
    ranked = sorted(
        bundles,
        key=lambda b: ta_map.get(b.symbol, 0) + pattern_map.get(b.symbol, 0),
        reverse=True,
    )
    av_quota    = min(_AV_DAILY_LIMIT, len(bundles))
    top_symbols = {b.symbol for b in ranked[:av_quota]}

    logger.info(
        "sentiment_node: Alpha Vantage quota=%d/%d  —  top symbols: %s",
        av_quota, len(bundles),
        ", ".join(b.symbol for b in ranked[:av_quota]),
    )

    # Only top-ranked stocks make real API calls; the rest skip instantly
    sentiment_coros = [
        _guarded(run_sentiment(b), SentimentOutput(symbol=b.symbol, score=50))
        if b.symbol in top_symbols
        else _neutral(b.symbol)
        for b in bundles
    ]

    sentiment_list = await asyncio.gather(*sentiment_coros)
    state["sentiment_results"] = list(sentiment_list)

    logger.info("sentiment_node: Sentiment=%d", len(sentiment_list))
    return state


async def synthesize_node(state: OrchestratorState) -> OrchestratorState:
    """
    Gate on minimum confidence, call Claude for rationale, persist to DB.
    """
    suggestions = await run_synthesizer(
        bundles=state["bundles"],
        ta_results=state["ta_results"],
        sentiment_results=state["sentiment_results"],
        pattern_results=state["pattern_results"],
    )
    state["suggestions"] = suggestions
    logger.info("synthesize_node: %d suggestion(s) generated", len(suggestions))
    return state


async def save_t1_node(state: OrchestratorState) -> OrchestratorState:
    """
    Persist T1 scan snapshots for all T1 stocks after synthesis completes.
    Failure is non-fatal — logs the error and continues to END.
    """
    try:
        suggestion_symbols = {s.symbol for s in state["suggestions"]}
        await save_t1_scan(
            bundles=state["bundles"],
            ta_results=state["ta_results"],
            pattern_results=state["pattern_results"],
            sentiment_results=state["sentiment_results"],
            suggestion_symbols=suggestion_symbols,
        )
    except Exception as exc:
        logger.error("save_t1_node failed (non-fatal): %s", exc, exc_info=True)
    return state


# ── Graph construction ────────────────────────────────────────────────────────

def _build_graph() -> Any:
    graph: StateGraph = StateGraph(OrchestratorState)

    graph.add_node("scan",       scan_node)
    graph.add_node("ta_pattern", ta_pattern_node)
    graph.add_node("sentiment",  sentiment_node)
    graph.add_node("synthesize", synthesize_node)
    graph.add_node("save_t1",    save_t1_node)

    graph.set_entry_point("scan")
    graph.add_edge("scan",       "ta_pattern")
    graph.add_edge("ta_pattern", "sentiment")
    graph.add_edge("sentiment",  "synthesize")
    graph.add_edge("synthesize", "save_t1")
    graph.add_edge("save_t1",    END)

    return graph.compile()


# ── Public entry point ────────────────────────────────────────────────────────

async def run_orchestrator() -> list[SynthesisOutput]:
    """
    Execute the full pipeline and return the generated suggestions.
    Re-entrant: calling this multiple times on the same day replaces today's
    suggestions in the DB (idempotent delete-then-insert in synthesizer).
    """
    graph = _build_graph()
    initial_state: OrchestratorState = {
        "scanner_outputs":   [],
        "bundles":           [],
        "ta_results":        [],
        "sentiment_results": [],
        "pattern_results":   [],
        "suggestions":       [],
    }
    final_state: OrchestratorState = await graph.ainvoke(initial_state)
    return final_state["suggestions"]


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent))
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")

    async def _main() -> None:
        results = await run_orchestrator()
        print(f"\n{len(results)} suggestion(s) generated.")
        for s in results:
            print(
                f"  {s.symbol:6s} {s.direction.value:5s}  "
                f"entry={s.entry_price:.2f}  stop={s.stop_loss:.2f}  "
                f"target={s.target_price:.2f}  confidence={s.confidence_score}"
            )

    asyncio.run(_main())
