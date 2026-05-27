"""
Scanner agent — determines which stocks enter the analysis pipeline.

T1: every active stock in the DB (S&P 500 large-caps, always tracked)
T2: nightly institutional-accumulation / momentum screen via T2Screener
    — uses a broad mid-cap universe (~250 symbols), multi-stage filtering,
      composite T2 Score, and Tier A/B/C classification.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from agents.models import AgentInputBundle, ScannerOutput, TradeTier
from agents.t2_config import T2Config
from agents.t2_news import get_news_summaries
from agents.t2_screener import T2Candidate, T2Screener
from agents.t2_store import save_t2_scan
from data.fetcher import fetch_ohlcv
from db.models import Stock
from db.session import async_session_factory

logger = logging.getLogger(__name__)

# T1 OHLCV history window (enough for 20d avg volume in existing agents)
_T1_HISTORY_DAYS = 30


async def run_scanner() -> tuple[list[ScannerOutput], list[AgentInputBundle]]:
    """
    Returns (scanner_outputs, bundles) — both lists are index-aligned.
    Bundles carry price and volume data so downstream agents skip redundant fetches.
    """
    today = date.today()

    # ── T1: load from DB ──────────────────────────────────────────────────────
    t1_symbols = await _load_t1_symbols()
    t1_set = set(t1_symbols)
    logger.info("Scanner: %d T1 symbols loaded from DB", len(t1_symbols))

    # ── T2: institutional accumulation / momentum screen ──────────────────────
    cfg = T2Config.from_env()
    screener = T2Screener(cfg)
    t2_candidates: list[T2Candidate] = await screener.run(exclude_symbols=t1_set)
    t2_symbols = [c.symbol for c in t2_candidates]
    t2_meta: dict[str, T2Candidate] = {c.symbol: c for c in t2_candidates}

    logger.info(
        "Scanner: %d T2 candidates from screener  (Tier A=%d  B=%d  C=%d)",
        len(t2_candidates),
        sum(1 for c in t2_candidates if c.signal_tier.value == "A"),
        sum(1 for c in t2_candidates if c.signal_tier.value == "B"),
        sum(1 for c in t2_candidates if c.signal_tier.value == "C"),
    )

    # ── Upsert new T2 symbols into stocks table (FK requirement) ──────────────
    if t2_candidates:
        await _upsert_t2_stocks(t2_candidates)

        # ── News validation (best-effort) ─────────────────────────────────────
        news_map: dict[str, dict[str, str]] = {}
        try:
            logger.info("Scanner: fetching news & running Claude validation for %d T2 candidates",
                        len(t2_candidates))
            news_map = await get_news_summaries(t2_candidates)
            logger.info("Scanner: T2 news validation complete")
        except Exception as exc:
            logger.warning("Scanner: T2 news step failed — scan will be saved without news: %s", exc)

        # ── Persist scan results (always runs, even if news fetch failed) ──────
        try:
            await save_t2_scan(t2_candidates, news_map)
            logger.info("Scanner: T2 scan results saved to DB")
        except Exception as exc:
            logger.warning("Scanner: T2 store step failed (non-fatal): %s", exc)

    # ── T1 OHLCV fetch (T2 OHLCV already fetched inside the screener) ────────
    t1_start = today - timedelta(days=_T1_HISTORY_DAYS)
    t1_data = await fetch_ohlcv(t1_symbols, t1_start, today)

    # ── Build outputs ─────────────────────────────────────────────────────────
    outputs: list[ScannerOutput] = []
    bundles: list[AgentInputBundle] = []

    # T1 entries — derived from fresh OHLCV
    for symbol in t1_symbols:
        df = t1_data.get(symbol)
        if df is None or df.empty:
            logger.debug("Scanner: no OHLCV for T1 %s — skipping", symbol)
            continue
        try:
            latest    = df.iloc[-1]
            price     = float(latest["Close"])
            avg_vol   = float(latest["avg_volume_20d"])
            today_vol = float(latest["Volume"])
            ratio     = round(today_vol / avg_vol, 2) if avg_vol > 0 else 0.0

            outputs.append(ScannerOutput(
                symbol=symbol, tier=TradeTier.T1,
                avg_volume_20d=round(avg_vol, 0),
                volume_ratio=ratio, price=round(price, 4),
            ))
            bundles.append(AgentInputBundle(
                symbol=symbol, tier=TradeTier.T1, as_of_date=today,
                entry_price=round(price, 4),
                avg_volume_20d=round(avg_vol, 0), volume_ratio=ratio,
            ))
        except Exception as exc:
            logger.warning("Scanner: T1 %s build failed — %s", symbol, exc)

    # T2 entries — price/volume data comes from T2Candidate (already screened)
    for symbol in t2_symbols:
        meta = t2_meta[symbol]
        try:
            outputs.append(ScannerOutput(
                symbol=symbol, tier=TradeTier.T2,
                avg_volume_20d=round(meta.avg_volume_30d, 0),
                volume_ratio=round(meta.rvol, 2),
                price=round(meta.price, 4),
                market_cap=meta.market_cap if meta.market_cap > 0 else None,
            ))
            bundles.append(AgentInputBundle(
                symbol=symbol, tier=TradeTier.T2, as_of_date=today,
                entry_price=round(meta.price, 4),
                avg_volume_20d=round(meta.avg_volume_30d, 0),
                volume_ratio=round(meta.rvol, 2),
            ))
        except Exception as exc:
            logger.warning("Scanner: T2 %s build failed — %s", symbol, exc)

    logger.info(
        "Scanner complete: %d symbols (%d T1, %d T2)",
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


async def _upsert_t2_stocks(candidates: list[T2Candidate]) -> None:
    """Ensure T2 symbols exist in stocks table with enriched metadata."""
    async with async_session_factory() as session:
        for c in candidates:
            stmt = (
                pg_insert(Stock)
                .values(
                    symbol=c.symbol,
                    name=c.name or c.symbol,
                    sector=c.sector or None,
                    tier="T2",
                    is_active=True,
                )
                .on_conflict_do_update(
                    index_elements=["symbol"],
                    set_={
                        "name":      c.name or c.symbol,
                        "sector":    c.sector or None,
                        "tier":      "T2",
                        "is_active": True,
                    },
                )
            )
            await session.execute(stmt)
        await session.commit()
