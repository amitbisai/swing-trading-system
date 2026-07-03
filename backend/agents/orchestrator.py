"""
LangGraph orchestrator — scan → TA+Pattern → Sentiment → Synthesize.

Graph topology
--------------
    scan_node
        │
    ta_pattern_node   (TA ‖ Pattern, all stocks, fully parallel)
        │
    sentiment_node    (Finnhub headlines + Claude Haiku batch — covers ALL stocks)
        │
    synthesize_node
        │
    save_t1_node
        │
       END

Sentiment uses Finnhub (60 calls/min free tier) to fetch recent headlines for
every stock, then scores them all in a single Claude Haiku call.  This replaces
the old Alpha Vantage approach (25 calls/day) which left 83% of T1 stocks at a
useless default score of 50.

Run manually:
    cd backend && python -m agents.orchestrator
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
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
from agents.sentiment import run_sentiment_batch
from agents.synthesizer import run_synthesizer
from agents.t1_store import save_t1_scan
from agents.ta_agent import run_ta
from data.fetcher import fetch_ohlcv

logger = logging.getLogger(__name__)

_AGENT_TIMEOUT: float = 30.0   # seconds per individual TA/Pattern agent call


# ── State ─────────────────────────────────────────────────────────────────────

class OrchestratorState(TypedDict):
    scanner_outputs:   list[ScannerOutput]
    bundles:           list[AgentInputBundle]
    ta_results:        list[TAOutput]
    sentiment_results: list[SentimentOutput]
    pattern_results:   list[PatternOutput]
    suggestions:       list[SynthesisOutput]
    regime_bullish:    bool


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


# ── Graph nodes ───────────────────────────────────────────────────────────────

async def scan_node(state: OrchestratorState) -> OrchestratorState:
    """
    Query DB for active T1 stocks + run the T2 momentum screener.
    Populates scanner_outputs and bundles.
    """
    scanner_outputs, bundles = await run_scanner()
    state["scanner_outputs"] = scanner_outputs
    state["bundles"] = bundles

    # Market regime check (SPY vs 200DMA) — determines whether today's
    # suggestions are persisted as active (auto-tradable) or inactive.
    from risk.regime import is_market_bullish
    state["regime_bullish"] = await is_market_bullish()

    logger.info("scan_node: %d symbols selected", len(bundles))
    return state


async def ta_pattern_node(state: OrchestratorState) -> OrchestratorState:
    """
    Stage 1 of analysis — run TA and Pattern agents in parallel for ALL stocks.

    OHLCV data is fetched ONCE in a single bulk yfinance call, then the same
    DataFrame is passed to both TA and Pattern for each stock.  This replaces
    the old design (2 × N individual yfinance downloads) which saturated the
    4-worker thread pool and caused every Pattern call to time out.
    """
    bundles = state["bundles"]
    if not bundles:
        state["ta_results"]      = []
        state["pattern_results"] = []
        return state

    # ── Single bulk OHLCV prefetch for all symbols ────────────────────────────
    symbols = [b.symbol for b in bundles]
    today   = date.today()
    start   = today - timedelta(days=90)   # matches _HISTORY_DAYS in ta_agent / pattern

    logger.info("ta_pattern_node: prefetching OHLCV for %d symbols (%s → %s)", len(symbols), start, today)
    ohlcv_map = await fetch_ohlcv(symbols, start, today)
    logger.info(
        "ta_pattern_node: OHLCV prefetch done — %d/%d symbols have data",
        len(ohlcv_map), len(symbols),
    )

    # ── TA and Pattern run fully in parallel, reusing the prefetched data ─────
    ta_coros = [
        _guarded(run_ta(b, df=ohlcv_map.get(b.symbol)), TAOutput(symbol=b.symbol, score=50))
        for b in bundles
    ]
    pattern_coros = [
        _guarded(run_pattern(b, df=ohlcv_map.get(b.symbol)), PatternOutput(symbol=b.symbol, score=50))
        for b in bundles
    ]

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
    Stage 2 of analysis — Finnhub headlines + Claude batch sentiment for ALL stocks.

    Replaces the old Alpha Vantage per-stock approach (25-call/day budget meant
    only the top-25 stocks got real scores; the other 122 defaulted to 50).

    run_sentiment_batch() fetches Finnhub news for every symbol (~3 min for 147
    stocks) then scores them all in a single Claude Haiku call, so every stock
    enters synthesis with a real sentiment signal.
    """
    bundles = state["bundles"]

    if not bundles:
        state["sentiment_results"] = []
        return state

    try:
        sentiment_list = await run_sentiment_batch(bundles)
    except Exception as exc:
        logger.error(
            "sentiment_node: batch call failed — falling back to neutral scores: %s", exc,
            exc_info=True,
        )
        sentiment_list = [SentimentOutput(symbol=b.symbol, score=50) for b in bundles]

    state["sentiment_results"] = sentiment_list
    logger.info("sentiment_node: scored %d symbols", len(sentiment_list))
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
        regime_ok=state.get("regime_bullish", True),
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
        "regime_bullish":    True,
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
