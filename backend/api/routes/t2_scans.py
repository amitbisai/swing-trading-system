"""
GET /api/t2-scans/  — last N days of T2 screener results.

Query params:
  days=30   how many calendar days of history to return (max 90)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Query

from agents.t2_store import get_recent_t2_scans, count_t2_scans
from api.schemas import ApiResponse, T2ScanOut
from data.yahoo_screener import get_live_t2_universe

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/", response_model=ApiResponse[list[T2ScanOut]])
async def list_t2_scans(
    days: int = Query(default=30, ge=1, le=90, description="Calendar days of history"),
) -> ApiResponse[list[T2ScanOut]]:
    rows = await get_recent_t2_scans(days=days)
    data: list[T2ScanOut] = []
    for r in rows:
        try:
            data.append(T2ScanOut.from_orm_row(r))
        except Exception as exc:
            # Log the bad row but keep going — don't let one row kill the whole response
            logger.warning(
                "T2ScanOut.from_orm_row failed for row id=%s symbol=%s: %s",
                getattr(r, "id", "?"),
                getattr(r, "symbol", "?"),
                exc,
            )
    return ApiResponse(
        data=data,
        error=None,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/count")
async def count_t2_scans_endpoint(
    days: int = Query(default=30, ge=1, le=90),
) -> dict:
    """Diagnostic endpoint — returns raw row count without ORM serialisation."""
    total, in_range = await count_t2_scans(days=days)
    return {
        "total_rows": total,
        f"rows_last_{days}_days": in_range,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/universe")
async def live_t2_universe() -> dict:
    """
    Diagnostic endpoint — fetches the live Stage 0 T2 universe RIGHT NOW
    (Yahoo Finance Most Active + Day Gainers, merged and pre-filtered).

    This is the pool of stocks that would enter Stage 1 if the screener ran at
    this moment.  Useful for checking coverage during market hours.

    No falling-knife filter is applied here so you can see ALL candidates
    including the ones that would be rejected by the -3% drop gate.
    """
    from agents.t2_config import T2Config  # noqa: PLC0415

    cfg = T2Config.from_env()

    # Fetch without the falling-knife or price gates — show everything
    quotes = await get_live_t2_universe(
        min_price      = 1.0,          # wide — show all
        min_market_cap = 50_000_000,   # wide — show all
        max_market_cap = cfg.max_market_cap,
        min_avg_volume = 50_000,       # wide — show all
    )

    # Annotate each quote with whether it would survive Stage 0 gates
    results = []
    for q in sorted(quotes, key=lambda x: x.get("rvol", 0), reverse=True):
        chg = q.get("today_change_pct", 0.0)
        price = q.get("price", 0.0)
        mktcap = q.get("market_cap", 0)
        avg_vol = q.get("avg_volume_10d", 0)
        rvol = q.get("rvol", 0.0)

        gates_pass = (
            price >= cfg.min_price
            and mktcap >= cfg.min_market_cap * 0.8
            and avg_vol >= cfg.min_avg_volume_30d // 2
            and chg >= -cfg.max_drop_pct_today
        )
        reject_reason = (
            "falling_knife" if chg < -cfg.max_drop_pct_today
            else "low_price" if price < cfg.min_price
            else "low_cap" if mktcap < cfg.min_market_cap * 0.8
            else "low_volume" if avg_vol < cfg.min_avg_volume_30d // 2
            else None
        )

        results.append({
            "symbol":           q["symbol"],
            "name":             q.get("name", q["symbol"]),
            "price":            round(price, 2),
            "change_pct":       round(chg, 2),
            "rvol":             round(rvol, 2),
            "avg_volume_10d":   avg_vol,
            "market_cap_M":     round(mktcap / 1e6, 0) if mktcap else None,
            "passes_stage0":    gates_pass,
            "reject_reason":    reject_reason,
        })

    passes = sum(1 for r in results if r["passes_stage0"])
    return {
        "total_fetched": len(results),
        "passes_stage0": passes,
        "rejected":      len(results) - passes,
        "note": "Stocks that pass Stage 0 then go through OHLCV technical gates (Stage 1) and fundamentals/earnings (Stage 2)",
        "stocks": results,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
