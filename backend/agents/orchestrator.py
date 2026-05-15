"""
LangGraph orchestrator — scan → parallel analysis → synthesize.

Graph topology
--------------
    scan_node
        │
    analyze_node   (TA ‖ Sentiment ‖ Pattern, all parallel, 30s timeout each)
        │
    synthesize_node
        │
       END

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
from agents.ta_agent import run_ta

logger = logging.getLogger(__name__)

_AGENT_TIMEOUT: float = 30.0   # seconds per individual agent call


# ── State ─────────────────────────────────────────────────────────────────────

class OrchestratorState(TypedDict):
    scanner_outputs: list[ScannerOutput]
    bundles: list[AgentInputBundle]
    ta_results: list[TAOutput]
    sentiment_results: list[SentimentOutput]
    pattern_results: list[PatternOutput]
    suggestions: list[SynthesisOutput]


# ── Timeout / error guard ─────────────────────────────────────────────────────

async def _guarded(coro: Any, fallback: Any) -> Any:
    """
    Run *coro* with a hard 30-second timeout.
    On timeout or any exception, log the event and return *fallback*.
    This ensures a single slow/broken stock never blocks the whole pipeline.
    """
    try:
        return await asyncio.wait_for(coro, timeout=_AGENT_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning("Agent call timed out (>%.0fs)", _AGENT_TIMEOUT)
        return fallback
    except Exception as exc:
        logger.error("Agent call raised an exception: %s", exc, exc_info=True)
        return fallback


# ── Graph nodes ───────────────────────────────────────────────────────────────

async def scan_node(state: OrchestratorState) -> OrchestratorState:
    """
    Query the DB for active stocks + run the T2 momentum screener.
    Populates scanner_outputs and bundles.
    """
    scanner_outputs, bundles = await run_scanner()
    state["scanner_outputs"] = scanner_outputs
    state["bundles"] = bundles
    logger.info("scan_node: %d symbols selected", len(bundles))
    return state


async def analyze_node(state: OrchestratorState) -> OrchestratorState:
    """
    Run TA, Sentiment, and Pattern agents in parallel.

    Parallelism structure:
    - Outer gather:  3 agent types run simultaneously
    - Inner gather:  every symbol within a type runs simultaneously
    - Each individual call is wrapped in _guarded() for 30s timeout + error isolation
    """
    bundles = state["bundles"]
    if not bundles:
        state["ta_results"] = []
        state["sentiment_results"] = []
        state["pattern_results"] = []
        return state

    # Build per-symbol coroutines with fallback defaults
    ta_coros = [
        _guarded(run_ta(b), TAOutput(symbol=b.symbol, score=50))
        for b in bundles
    ]
    sentiment_coros = [
        _guarded(run_sentiment(b), SentimentOutput(symbol=b.symbol, score=50))
        for b in bundles
    ]
    pattern_coros = [
        _guarded(run_pattern(b), PatternOutput(symbol=b.symbol, score=50))
        for b in bundles
    ]

    # All three agent types fire at the same time
    ta_list, sentiment_list, pattern_list = await asyncio.gather(
        asyncio.gather(*ta_coros),
        asyncio.gather(*sentiment_coros),
        asyncio.gather(*pattern_coros),
    )

    state["ta_results"] = list(ta_list)
    state["sentiment_results"] = list(sentiment_list)
    state["pattern_results"] = list(pattern_list)

    logger.info(
        "analyze_node: TA=%d  Sentiment=%d  Pattern=%d",
        len(ta_list), len(sentiment_list), len(pattern_list),
    )
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


# ── Graph construction ────────────────────────────────────────────────────────

def _build_graph() -> Any:
    graph: StateGraph = StateGraph(OrchestratorState)

    graph.add_node("scan", scan_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("synthesize", synthesize_node)

    graph.set_entry_point("scan")
    graph.add_edge("scan", "analyze")
    graph.add_edge("analyze", "synthesize")
    graph.add_edge("synthesize", END)

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
        "scanner_outputs": [],
        "bundles": [],
        "ta_results": [],
        "sentiment_results": [],
        "pattern_results": [],
        "suggestions": [],
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
