"""
GET /api/t1-scans/  — last N days of T1 TA scan snapshots.

Query params:
  days=30            calendar days of history to return (max 90)
  signal_only=true   only return stocks promoted to a final T1 suggestion
                     (default true — mirrors the "AI Signals → T1" view)
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query

from agents.t1_store import get_recent_t1_scans
from api.schemas import ApiResponse, T1ScanOut

router = APIRouter()


@router.get("/", response_model=ApiResponse[list[T1ScanOut]])
async def list_t1_scans(
    days: int = Query(default=30, ge=1, le=90, description="Calendar days of history"),
    signal_only: bool = Query(
        default=True,
        description="When true (default), only return stocks that became a final T1 signal",
    ),
) -> ApiResponse[list[T1ScanOut]]:
    rows = await get_recent_t1_scans(days=days, signal_only=signal_only)
    data = [T1ScanOut.from_orm_row(r) for r in rows]
    return ApiResponse(
        data=data,
        error=None,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
