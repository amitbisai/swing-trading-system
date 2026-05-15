"""
Scanner agent — determines which stocks enter the analysis pipeline.

T1: every active stock in the DB (large-cap, always tracked)
T2: daily momentum screen (volume > 3× 20d avg), dynamically added to stocks table
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from agents.models import AgentInputBundle, ScannerOutput, TradeTier
from data.fetcher import fetch_ohlcv, get_tier2_candidates
from db.models import Stock
from db.session import async_session_factory

logger = logging.getLogger(__name__)

_HISTORY_DAYS = 30  # enough to compute 20d avg volume


async def run_scanner() -> tuple[list[ScannerOutput], list[AgentInputBundle]]:
    """
    Returns (scanner_outputs, bundles) — both lists are index-aligned.
    Bundles carry price and volume data so downstream agents skip redundant fetches.
    """
    today = date.today()
    start = today - timedelta(days=_HISTORY_DAYS)

    # ── T1: load from DB ──────────────────────────────────────────────────────
    t1_symbols = await _load_t1_symbols()
    logger.info("Scanner: %d T1 symbols loaded from DB", len(t1_symbols))

    # ── T2: dynamic momentum screen ───────────────────────────────────────────
    t2_symbols = await get_tier2_candidates(volume_ratio_threshold=3.0, max_results=10)
    # Remove any T2 symbol already covered as T1
    t1_set = set(t1_symbols)
    t2_symbols = [s for s in t2_symbols if s not in t1_set]
    logger.info("Scanner: %d T2 momentum candidates", len(t2_symbols))

    all_symbols = t1_symbols + t2_symbols

    # ── Bulk OHLCV fetch ──────────────────────────────────────────────────────
    data = await fetch_ohlcv(all_symbols, start, today)

    # ── Upsert any new T2 symbols into stocks table ───────────────────────────
    if t2_symbols:
        await _upsert_t2_stocks(t2_symbols)

    # ── Build outputs ─────────────────────────────────────────────────────────
    outputs: list[ScannerOutput] = []
    bundles: list[AgentInputBundle] = []

    for symbol in all_symbols:
        tier = TradeTier.T1 if symbol in t1_set else TradeTier.T2
        df = data.get(symbol)

        if df is None or df.empty:
            logger.debug("Scanner: no data for %s — skipping", symbol)
            continue

        try:
            latest = df.iloc[-1]
            price = float(latest["Close"])
            avg_vol = float(latest["avg_volume_20d"])
            today_vol = float(latest["Volume"])
            ratio = round(today_vol / avg_vol, 2) if avg_vol > 0 else 0.0

            scanner_out = ScannerOutput(
                symbol=symbol,
                tier=tier,
                avg_volume_20d=round(avg_vol, 0),
                volume_ratio=ratio,
                price=round(price, 4),
            )
            bundle = AgentInputBundle(
                symbol=symbol,
                tier=tier,
                as_of_date=today,
                entry_price=round(price, 4),
                avg_volume_20d=round(avg_vol, 0),
                volume_ratio=ratio,
            )
            outputs.append(scanner_out)
            bundles.append(bundle)

        except Exception as exc:
            logger.warning("Scanner: failed to build output for %s — %s", symbol, exc)
            continue

    logger.info(
        "Scanner complete: %d symbols ready (%d T1, %d T2)",
        len(outputs),
        sum(1 for o in outputs if o.tier == TradeTier.T1),
        sum(1 for o in outputs if o.tier == TradeTier.T2),
    )
    return outputs, bundles


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _load_t1_symbols() -> list[str]:
    async with async_session_factory() as session:
        rows = await session.execute(
            select(Stock.symbol)
            .where(Stock.is_active == True, Stock.tier == "T1")
            .order_by(Stock.symbol)
        )
        return [r[0] for r in rows]


async def _upsert_t2_stocks(symbols: list[str]) -> None:
    """Ensure T2 symbols exist in the stocks table (FK required for suggestions)."""
    async with async_session_factory() as session:
        for sym in symbols:
            stmt = (
                pg_insert(Stock)
                .values(symbol=sym, name=sym, tier="T2", is_active=True)
                .on_conflict_do_update(
                    index_elements=["symbol"],
                    set_={"tier": "T2", "is_active": True},
                )
            )
            await session.execute(stmt)
        await session.commit()
