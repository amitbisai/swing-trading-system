"""
T2 scan persistence — save screener results to DB and query for the API.

Called from scanner.py after the T2 screen completes.
Keeps 30 days of history; older rows are pruned automatically.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from agents.t2_screener import T2Candidate
from db.models import T2Scan
from db.session import async_session_factory

logger = logging.getLogger(__name__)

_RETENTION_DAYS = 30   # keep this many calendar days of scan history


async def save_t2_scan(
    candidates: list[T2Candidate],
    news_map: dict[str, dict[str, str]],
    scan_date: date | None = None,
) -> None:
    """
    Upsert T2 scan results into the t2_scans table and prune old rows.
    news_map: {symbol: {"summary": "...", "verdict": "SUPPORTS|NEUTRAL|CONTRADICTS"}}
    """
    if not candidates:
        return

    scan_date = scan_date or date.today()
    cutoff    = scan_date - timedelta(days=_RETENTION_DAYS)

    async with async_session_factory() as session:
        # ── Prune old rows ────────────────────────────────────────────────────
        await session.execute(
            delete(T2Scan).where(T2Scan.scan_date < cutoff)
        )

        # ── Upsert today's results ────────────────────────────────────────────
        for c in candidates:
            news  = news_map.get(c.symbol, {})
            flags = ",".join(f.value for f in c.risk_flags)

            stmt = (
                pg_insert(T2Scan)
                .values(
                    symbol            = c.symbol,
                    scan_date         = scan_date,
                    signal_tier       = c.signal_tier.value,
                    t2_score          = c.t2_score,
                    price             = c.price,
                    market_cap        = int(c.market_cap) if c.market_cap else None,
                    rvol              = c.rvol,
                    avg_volume_30d    = int(c.avg_volume_30d) if c.avg_volume_30d else None,
                    revenue_growth    = c.revenue_growth,
                    earnings_growth   = c.earnings_growth,
                    pct_below_52w_high= c.pct_below_52w_high,
                    float_shares      = int(c.float_shares) if c.float_shares else None,
                    short_ratio       = c.short_ratio,
                    sector            = c.sector or None,
                    industry          = c.industry or None,
                    risk_flags        = flags or None,
                    signal_summary    = c.signal_summary or None,
                    catalyst_hint     = c.catalyst_hint or None,
                    news_summary      = news.get("summary") or None,
                    news_verdict      = news.get("verdict") or "NEUTRAL",
                )
                .on_conflict_do_update(
                    index_elements=["symbol", "scan_date"],
                    set_={
                        "signal_tier":       c.signal_tier.value,
                        "t2_score":          c.t2_score,
                        "price":             c.price,
                        "market_cap":        int(c.market_cap) if c.market_cap else None,
                        "rvol":              c.rvol,
                        "avg_volume_30d":    int(c.avg_volume_30d) if c.avg_volume_30d else None,
                        "revenue_growth":    c.revenue_growth,
                        "earnings_growth":   c.earnings_growth,
                        "pct_below_52w_high":c.pct_below_52w_high,
                        "float_shares":      int(c.float_shares) if c.float_shares else None,
                        "short_ratio":       c.short_ratio,
                        "sector":            c.sector or None,
                        "industry":          c.industry or None,
                        "risk_flags":        flags or None,
                        "signal_summary":    c.signal_summary or None,
                        "catalyst_hint":     c.catalyst_hint or None,
                        "news_summary":      news.get("summary") or None,
                        "news_verdict":      news.get("verdict") or "NEUTRAL",
                    },
                )
            )
            await session.execute(stmt)

        await session.commit()

    logger.info(
        "T2 store: saved %d scan results for %s (pruned rows before %s)",
        len(candidates), scan_date, cutoff,
    )


async def get_recent_t2_scans(days: int = 30) -> list[T2Scan]:
    """Fetch the last `days` calendar days of T2 scan results, newest first."""
    cutoff = date.today() - timedelta(days=days)
    async with async_session_factory() as session:
        rows = await session.execute(
            select(T2Scan)
            .where(T2Scan.scan_date >= cutoff)
            .order_by(T2Scan.scan_date.desc(), T2Scan.t2_score.desc())
        )
        return list(rows.scalars().all())


async def count_t2_scans(days: int = 30) -> tuple[int, int]:
    """
    Returns (total_rows, rows_in_date_range).
    Used by the diagnostic /api/t2-scans/count endpoint.
    """
    cutoff = date.today() - timedelta(days=days)
    async with async_session_factory() as session:
        total_result = await session.execute(
            select(func.count()).select_from(T2Scan)
        )
        total: int = total_result.scalar_one()

        in_range_result = await session.execute(
            select(func.count()).select_from(T2Scan).where(T2Scan.scan_date >= cutoff)
        )
        in_range: int = in_range_result.scalar_one()

    return total, in_range
