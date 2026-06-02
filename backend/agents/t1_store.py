"""
T1 scan persistence — save daily TA snapshots for all T1 stocks to DB and
query for the API.

Called from the orchestrator after synthesize_node completes.
Keeps 30 days of history; older rows are pruned automatically.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from agents.models import (
    AgentInputBundle,
    PatternOutput,
    SentimentOutput,
    TAOutput,
    TradeTier,
)
from db.models import Stock, T1Scan
from db.session import async_session_factory

logger = logging.getLogger(__name__)

_RETENTION_DAYS = 30  # keep this many calendar days of scan history


# ── Directional scoring helpers (mirrors synthesizer.py) ─────────────────────

def _ta_short_score(ta: TAOutput, entry_price: float) -> int:
    """Bearish TA score — mirrors synthesizer._ta_short_score."""
    score = 0

    if ta.rsi_14 is not None:
        if ta.rsi_14 > 70:
            score += 30
        elif ta.rsi_14 > 60:
            score += 20
        elif ta.rsi_14 >= 40:
            score += 10
        elif ta.rsi_14 >= 30:
            score += 5

    if ta.macd_hist is not None:
        if ta.macd_hist < 0:
            score += 30
        else:
            score += 5

    below_sma20 = (entry_price < ta.sma_20) if ta.sma_20 else None
    below_sma50 = (entry_price < ta.sma_50) if ta.sma_50 else None
    sma_downtrend = (ta.sma_20 < ta.sma_50) if (ta.sma_20 and ta.sma_50) else None

    if below_sma20:
        score += 15
    if below_sma50:
        score += 15
    if sma_downtrend:
        score += 10

    return min(100, max(0, score))


def _pattern_short_score(pat: PatternOutput, entry_price: float) -> int:
    """Bearish pattern score — mirrors synthesizer._pattern_short_score."""
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
    bonus += 5  if "DOJI"              in detected else 0
    bonus -= 15 if "HAMMER"            in detected else 0
    bonus -= 20 if "BULLISH_ENGULFING" in detected else 0
    bonus -= 10 if "VOLUME_BREAKOUT"   in detected else 0
    bonus -= 5  if "UPTREND"           in detected else 0

    return max(0, min(100, base + bonus))


# ── Public API ────────────────────────────────────────────────────────────────

async def save_t1_scan(
    bundles: list[AgentInputBundle],
    ta_results: list[TAOutput],
    pattern_results: list[PatternOutput],
    sentiment_results: list[SentimentOutput],
    suggestion_symbols: set[str],
    scan_date: date | None = None,
) -> None:
    """
    Upsert one row per T1 bundle into t1_scans and prune rows older than
    _RETENTION_DAYS.  T2 bundles are silently skipped.
    """
    t1_bundles = [b for b in bundles if b.tier == TradeTier.T1]
    if not t1_bundles:
        logger.info("T1 store: no T1 bundles to save")
        return

    scan_date = scan_date or date.today()
    cutoff = scan_date - timedelta(days=_RETENTION_DAYS)

    # Build fast lookup maps keyed by symbol
    ta_map:   dict[str, TAOutput]        = {r.symbol: r for r in ta_results}
    pat_map:  dict[str, PatternOutput]   = {r.symbol: r for r in pattern_results}
    sent_map: dict[str, SentimentOutput] = {r.symbol: r for r in sentiment_results}

    # Batch-fetch sectors from the stocks table
    t1_symbols = [b.symbol for b in t1_bundles]
    async with async_session_factory() as session:
        rows = await session.execute(
            select(Stock.symbol, Stock.sector).where(Stock.symbol.in_(t1_symbols))
        )
        sector_map: dict[str, str | None] = {row.symbol: row.sector for row in rows}

        # ── Prune old rows ────────────────────────────────────────────────────
        await session.execute(delete(T1Scan).where(T1Scan.scan_date < cutoff))

        # ── Upsert today's rows ───────────────────────────────────────────────
        saved = 0
        for bundle in t1_bundles:
            sym = bundle.symbol
            entry = bundle.entry_price
            if entry <= 0:
                continue  # skip stocks without a valid price

            ta   = ta_map.get(sym,   TAOutput(symbol=sym, score=50))
            pat  = pat_map.get(sym,  PatternOutput(symbol=sym, score=50))
            sent = sent_map.get(sym, SentimentOutput(symbol=sym, score=50))

            ta_long_score    = ta.score
            ta_short         = _ta_short_score(ta, entry)
            pat_long_score   = pat.score
            pat_short        = _pattern_short_score(pat, entry)
            sent_long        = sent.score
            sent_short       = 100 - sent.score

            bullish_conf = (ta_long_score + sent_long  + pat_long_score) // 3
            bearish_conf = (ta_short      + sent_short + pat_short)      // 3

            direction = "LONG" if bullish_conf >= bearish_conf else "SHORT"

            patterns_str = (
                ",".join(pat.patterns_detected) if pat.patterns_detected else None
            )

            values: dict = {
                "symbol":             sym,
                "scan_date":          scan_date,
                "price":              round(entry, 4),
                "rsi_14":             round(ta.rsi_14,   2) if ta.rsi_14   is not None else None,
                "macd_hist":          round(ta.macd_hist, 6) if ta.macd_hist is not None else None,
                "sma_20":             round(ta.sma_20,   4) if ta.sma_20   is not None else None,
                "sma_50":             round(ta.sma_50,   4) if ta.sma_50   is not None else None,
                "atr_14":             round(ta.atr_14,   4) if ta.atr_14   is not None else None,
                "bb_upper":           round(ta.bb_upper, 4) if ta.bb_upper is not None else None,
                "bb_lower":           round(ta.bb_lower, 4) if ta.bb_lower is not None else None,
                "rvol":               round(bundle.volume_ratio,    2) if bundle.volume_ratio    else None,
                "avg_volume_20d":     int(bundle.avg_volume_20d)       if bundle.avg_volume_20d  else None,
                "support_level":      round(pat.support_level,    4) if pat.support_level    is not None else None,
                "resistance_level":   round(pat.resistance_level, 4) if pat.resistance_level is not None else None,
                "patterns_detected":  patterns_str,
                "ta_score":           ta_long_score,
                "pattern_score":      pat_long_score,
                "sentiment_score":    sent.score,
                "bullish_confidence": bullish_conf,
                "bearish_confidence": bearish_conf,
                "signal_direction":   direction,
                "made_signal":        sym in suggestion_symbols,
                "sector":             sector_map.get(sym),
            }

            stmt = (
                pg_insert(T1Scan)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=["symbol", "scan_date"],
                    set_={k: v for k, v in values.items() if k not in ("symbol", "scan_date")},
                )
            )
            await session.execute(stmt)
            saved += 1

        await session.commit()

    logger.info(
        "T1 store: saved %d scan results for %s (pruned rows before %s)",
        saved, scan_date, cutoff,
    )


async def get_recent_t1_scans(days: int = 30, signal_only: bool = True) -> list[T1Scan]:
    """
    Fetch the last `days` calendar days of T1 scan results, newest first.

    signal_only=True (default) — return only rows where made_signal=True,
    i.e. the stocks the AI orchestrator promoted to a final T1 suggestion.
    This is the "T1 Scan History" view: a clean record of every stock that
    cleared all agent gates on each nightly run.

    signal_only=False — return all 146+ screened stocks (used for debugging).
    """
    cutoff = date.today() - timedelta(days=days)
    async with async_session_factory() as session:
        q = (
            select(T1Scan)
            .where(T1Scan.scan_date >= cutoff)
        )
        if signal_only:
            q = q.where(T1Scan.made_signal.is_(True))
        q = q.order_by(T1Scan.scan_date.desc(), T1Scan.bullish_confidence.desc())
        rows = await session.execute(q)
        return list(rows.scalars().all())
