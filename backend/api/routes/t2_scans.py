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
