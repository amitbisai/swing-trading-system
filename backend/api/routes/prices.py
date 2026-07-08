"""
Prices route — latest available close price per symbol from daily_prices.

GET /api/prices/latest?symbols=AAPL,MSFT,GOOGL
Returns { "AAPL": 189.50, "MSFT": 415.23, ... } — only symbols found in DB.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas import ApiResponse
from db.models import DailyPnL, DailyPrice, PaperTrade, T2Scan
from db.session import get_db

router = APIRouter()


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/latest", response_model=ApiResponse[dict[str, float]])
async def get_latest_prices(
    symbols: str = Query(..., description="Comma-separated ticker symbols, e.g. AAPL,MSFT"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, float]]:
    """
    Return the most-recent close price from daily_prices for each requested symbol.
    Symbols not found in the DB are silently omitted from the response.
    """
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        return ApiResponse(data={}, timestamp=_ts())

    # Subquery: latest price_date per symbol
    subq = (
        select(
            DailyPrice.symbol,
            func.max(DailyPrice.price_date).label("max_date"),
        )
        .where(DailyPrice.symbol.in_(symbol_list))
        .group_by(DailyPrice.symbol)
        .subquery()
    )

    rows = await db.execute(
        select(DailyPrice.symbol, DailyPrice.close)
        .join(
            subq,
            (DailyPrice.symbol == subq.c.symbol)
            & (DailyPrice.price_date == subq.c.max_date),
        )
    )

    prices: dict[str, float] = {row[0]: float(row[1]) for row in rows}
    price_dates: dict[str, object] = {}
    date_rows = await db.execute(
        select(subq.c.symbol, subq.c.max_date)
    )
    for sym, d in date_rows:
        price_dates[sym] = d

    # Overlay with the hourly mark-to-market prices: during market hours the
    # intraday job upserts near-live prices into daily_pnl for open trades —
    # fresher than the nightly EOD close in daily_prices.
    pnl_subq = (
        select(
            PaperTrade.symbol,
            func.max(DailyPnL.pnl_date).label("max_date"),
        )
        .join(DailyPnL, DailyPnL.trade_id == PaperTrade.id)
        .where(PaperTrade.symbol.in_(symbol_list))
        .group_by(PaperTrade.symbol)
        .subquery()
    )
    pnl_rows = await db.execute(
        select(PaperTrade.symbol, DailyPnL.close_price, DailyPnL.pnl_date)
        .join(DailyPnL, DailyPnL.trade_id == PaperTrade.id)
        .join(
            pnl_subq,
            (PaperTrade.symbol == pnl_subq.c.symbol)
            & (DailyPnL.pnl_date == pnl_subq.c.max_date),
        )
    )
    for sym, close_price, pnl_date in pnl_rows:
        # use the intraday mark when it is at least as recent as the EOD row
        if sym not in price_dates or pnl_date >= price_dates[sym]:
            prices[sym] = float(close_price)

    # For any symbols still missing from daily_prices (e.g. newly discovered T2
    # stocks whose first ingest hasn't run yet), fall back to the most recent
    # price stored in the t2_scans table by the screener.
    missing = [s for s in symbol_list if s not in prices]
    if missing:
        t2_subq = (
            select(
                T2Scan.symbol,
                func.max(T2Scan.scan_date).label("max_date"),
            )
            .where(T2Scan.symbol.in_(missing))
            .group_by(T2Scan.symbol)
            .subquery()
        )
        t2_rows = await db.execute(
            select(T2Scan.symbol, T2Scan.price)
            .join(
                t2_subq,
                (T2Scan.symbol == t2_subq.c.symbol)
                & (T2Scan.scan_date == t2_subq.c.max_date),
            )
        )
        for row in t2_rows:
            prices[row[0]] = float(row[1])

    return ApiResponse(data=prices, timestamp=_ts())
