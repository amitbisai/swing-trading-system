from datetime import date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas import ApiResponse, PortfolioSnapshotOut
from db.models import PortfolioSnapshot
from db.session import get_db

router = APIRouter()


def _to_out(r: PortfolioSnapshot) -> PortfolioSnapshotOut:
    return PortfolioSnapshotOut(
        snapshot_date=r.snapshot_date,
        total_capital=r.total_capital,
        cash_balance=r.cash_balance,
        invested_capital=r.invested_capital,
        unrealized_pnl=r.unrealized_pnl,
        realized_pnl_today=r.realized_pnl_today,
        cumulative_realized_pnl=r.cumulative_realized_pnl,
        open_positions=r.open_positions,
    )


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── GET /portfolio/snapshot ───────────────────────────────────────────────────

@router.get("/snapshot", response_model=ApiResponse[PortfolioSnapshotOut])
async def get_snapshot(
    date: Annotated[
        date | None,
        Query(alias="date", description="Snapshot date (YYYY-MM-DD). Defaults to latest."),
    ] = None,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[PortfolioSnapshotOut]:
    if date:
        row = (await db.execute(
            select(PortfolioSnapshot).where(PortfolioSnapshot.snapshot_date == date)
        )).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"No snapshot found for {date}")
    else:
        row = (await db.execute(
            select(PortfolioSnapshot)
            .order_by(PortfolioSnapshot.snapshot_date.desc())
            .limit(1)
        )).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="No portfolio snapshots exist yet")

    return ApiResponse(data=_to_out(row), timestamp=_ts())


# ── GET /portfolio/history ────────────────────────────────────────────────────

@router.get("/history", response_model=ApiResponse[list[PortfolioSnapshotOut]])
async def get_history(
    days: Annotated[int, Query(ge=1, le=365, description="Number of trailing days")] = 30,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[PortfolioSnapshotOut]]:
    cutoff = date.today() - timedelta(days=days)
    rows = (await db.execute(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.snapshot_date >= cutoff)
        .order_by(PortfolioSnapshot.snapshot_date.asc())
    )).scalars().all()

    return ApiResponse(data=[_to_out(r) for r in rows], timestamp=_ts())
