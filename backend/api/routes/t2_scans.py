"""
GET /api/t2-scans/  — last N days of T2 screener results.

Query params:
  days=30   how many calendar days of history to return (max 90)
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query

from agents.t2_store import get_recent_t2_scans
from api.schemas import ApiResponse, T2ScanOut

router = APIRouter()


@router.get("/", response_model=ApiResponse[list[T2ScanOut]])
async def list_t2_scans(
    days: int = Query(default=30, ge=1, le=90, description="Calendar days of history"),
) -> ApiResponse[list[T2ScanOut]]:
    rows = await get_recent_t2_scans(days=days)
    data = [T2ScanOut.from_orm_row(r) for r in rows]
    return ApiResponse(
        data=data,
        error=None,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
