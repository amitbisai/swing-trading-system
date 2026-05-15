from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from db.models import DailyPrice, Stock

router = APIRouter()


@router.get("/")
async def list_stocks(
    tier: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Stock).where(Stock.is_active == True)
    if tier:
        stmt = stmt.where(Stock.tier == tier)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return {
        "data": [{"symbol": r.symbol, "name": r.name, "tier": r.tier} for r in rows],
        "error": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/{symbol}/prices")
async def get_stock_prices(
    symbol: str,
    days: int = Query(default=30, le=365),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(DailyPrice)
        .where(DailyPrice.symbol == symbol)
        .order_by(DailyPrice.price_date.desc())
        .limit(days)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return {
        "data": [
            {
                "date": r.price_date.isoformat(),
                "open": str(r.open),
                "high": str(r.high),
                "low": str(r.low),
                "close": str(r.close),
                "volume": r.volume,
            }
            for r in reversed(rows)
        ],
        "error": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
