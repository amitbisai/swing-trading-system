from datetime import date as date_type, datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas import ApiResponse, PaperTradeOut, PortfolioSnapshotOut
from config import settings
from db.models import DailyPnL, DailyPrice, PaperTrade, PortfolioSnapshot
from db.session import get_db
from paper_trading.engine import compute_nav

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
        initial_capital=settings.initial_capital,
    )


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _latest_prices_for_open_trades(db: AsyncSession) -> dict[str, Decimal]:
    """
    Best available price per open-trade symbol:
    1. the trade's most recent DailyPnL close (the intraday job keeps this
       near-live during market hours),
    2. else the symbol's latest daily_prices close,
    3. else the trade's own entry price (unrealized = 0 until data arrives).
    """
    trades: list[PaperTrade] = list(
        (await db.execute(
            select(PaperTrade).where(PaperTrade.is_open == True)
        )).scalars().all()
    )
    prices: dict[str, Decimal] = {}
    for t in trades:
        pnl_row = (await db.execute(
            select(DailyPnL.close_price)
            .where(DailyPnL.trade_id == t.id)
            .order_by(DailyPnL.pnl_date.desc())
            .limit(1)
        )).scalar_one_or_none()
        if pnl_row is not None:
            prices[t.symbol] = Decimal(str(pnl_row))
            continue

        px_row = (await db.execute(
            select(DailyPrice.close)
            .where(DailyPrice.symbol == t.symbol)
            .order_by(DailyPrice.price_date.desc())
            .limit(1)
        )).scalar_one_or_none()
        prices[t.symbol] = (
            Decimal(str(px_row)) if px_row is not None else Decimal(str(t.entry_price))
        )
    return prices


# ── GET /portfolio/snapshot ───────────────────────────────────────────────────

@router.get("/snapshot", response_model=ApiResponse[PortfolioSnapshotOut])
async def get_snapshot(
    date: Annotated[
        date_type | None,
        Query(alias="date", description="Snapshot date (YYYY-MM-DD). Omit for a live view."),
    ] = None,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[PortfolioSnapshotOut]:
    """
    With ?date= — return the persisted snapshot for that day (for backtest review).
    Without    — compute NAV live from current trades, so opening a trade
                 reduces cash immediately and closing one increases it.
    """
    if date:
        row = (await db.execute(
            select(PortfolioSnapshot).where(PortfolioSnapshot.snapshot_date == date)
        )).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"No snapshot found for {date}")
        return ApiResponse(data=_to_out(row), timestamp=_ts())

    # ── Live view ──────────────────────────────────────────────────────────────
    today = date_type.today()
    prices = await _latest_prices_for_open_trades(db)
    values = await compute_nav(db, today, live_prices=prices)

    out = PortfolioSnapshotOut(
        snapshot_date=values["snapshot_date"],
        total_capital=values["total_capital"],
        cash_balance=values["cash_balance"],
        invested_capital=values["invested_capital"],
        unrealized_pnl=values["unrealized_pnl"],
        realized_pnl_today=values["realized_pnl_today"],
        cumulative_realized_pnl=values["cumulative_realized_pnl"],
        open_positions=values["open_positions"],
        initial_capital=settings.initial_capital,
    )
    return ApiResponse(data=out, timestamp=_ts())


# ── GET /portfolio/positions ──────────────────────────────────────────────────

@router.get("/positions", response_model=ApiResponse[list[PaperTradeOut]])
async def get_positions(
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[PaperTradeOut]]:
    """Currently open paper-trade positions."""
    rows = (await db.execute(
        select(PaperTrade)
        .where(PaperTrade.is_open == True)
        .order_by(PaperTrade.entry_date.desc(), PaperTrade.id.desc())
    )).scalars().all()
    data = [PaperTradeOut.model_validate(r) for r in rows]
    return ApiResponse(data=data, timestamp=_ts())


# ── GET /portfolio/history ────────────────────────────────────────────────────

@router.get("/history", response_model=ApiResponse[list[PortfolioSnapshotOut]])
async def get_history(
    days: Annotated[int, Query(ge=1, le=365, description="Number of trailing days")] = 30,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[PortfolioSnapshotOut]]:
    cutoff = date_type.today() - timedelta(days=days)
    rows = (await db.execute(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.snapshot_date >= cutoff)
        .order_by(PortfolioSnapshot.snapshot_date.asc())
    )).scalars().all()

    return ApiResponse(data=[_to_out(r) for r in rows], timestamp=_ts())
