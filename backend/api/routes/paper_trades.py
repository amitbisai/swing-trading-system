from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas import ApiResponse, CloseTradeRequest, OpenTradeRequest, OpenTradeResponse, PaperTradeOut
from db.models import DailyPrice, PaperTrade, Suggestion
from db.session import get_db
from paper_trading.engine import open_trade
from paper_trading.mark_to_market import compute_realized_pnl
from risk.position_sizing import compute_position_size

router = APIRouter()


def _to_out(r: PaperTrade) -> PaperTradeOut:
    return PaperTradeOut(
        id=r.id,
        suggestion_id=r.suggestion_id,
        symbol=r.symbol,
        direction=r.direction,
        entry_date=r.entry_date,
        entry_price=r.entry_price,
        shares=r.shares,
        capital_at_risk=r.capital_at_risk,
        stop_loss=r.stop_loss,
        target_price=r.target_price,
        exit_date=r.exit_date,
        exit_price=r.exit_price,
        exit_reason=r.exit_reason,
        realized_pnl=r.realized_pnl,
        is_open=r.is_open,
        original_stop=r.original_stop,
        original_target=r.original_target,
        levels_updated_at=r.levels_updated_at,
        adjustment_note=r.adjustment_note,
    )


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── GET /paper-trades ─────────────────────────────────────────────────────────

@router.get("/", response_model=ApiResponse[list[PaperTradeOut]])
async def list_paper_trades(
    status: Annotated[
        str,
        Query(description="open | closed | all", pattern="^(open|closed|all)$"),
    ] = "all",
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[PaperTradeOut]]:
    stmt = select(PaperTrade).order_by(PaperTrade.entry_date.desc(), PaperTrade.id.desc())

    if status == "open":
        stmt = stmt.where(PaperTrade.is_open == True)
    elif status == "closed":
        stmt = stmt.where(PaperTrade.is_open == False)

    rows = (await db.execute(stmt)).scalars().all()
    return ApiResponse(data=[_to_out(r) for r in rows], timestamp=_ts())


# ── POST /paper-trades ────────────────────────────────────────────────────────

@router.post("/", response_model=ApiResponse[OpenTradeResponse], status_code=201)
async def create_paper_trade(
    body: OpenTradeRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[OpenTradeResponse]:
    # Validate suggestion exists
    suggestion = await db.get(Suggestion, body.suggestion_id)
    if suggestion is None:
        raise HTTPException(status_code=404, detail=f"Suggestion {body.suggestion_id} not found")

    # Guard: don't open a duplicate position in the same symbol
    existing = (await db.execute(
        select(PaperTrade).where(
            PaperTrade.symbol == suggestion.symbol,
            PaperTrade.is_open == True,
        )
    )).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"An open position already exists for {suggestion.symbol} (trade #{existing.id})",
        )

    # ── Resolve entry price: use latest close from daily_prices if available ──
    latest_price_row = (await db.execute(
        select(DailyPrice.close)
        .where(DailyPrice.symbol == suggestion.symbol)
        .order_by(DailyPrice.price_date.desc())
        .limit(1)
    )).scalar_one_or_none()

    if latest_price_row is not None:
        entry_price = Decimal(str(latest_price_row))
        # Shift the suggestion's stop/target by the same distances relative to
        # the fresh entry price. This preserves the ATR-derived widths computed
        # at signal time (recomputing from percentages would discard them).
        stop_dist    = suggestion.entry_price - suggestion.stop_loss
        target_dist  = suggestion.target_price - suggestion.entry_price
        stop_price   = entry_price - stop_dist
        target_price = entry_price + target_dist
    else:
        entry_price  = suggestion.entry_price
        stop_price   = suggestion.stop_loss
        target_price = suggestion.target_price

    # ── Auto-size if shares not provided ──────────────────────────────────────
    auto_sized = body.shares is None
    if auto_sized:
        from config import settings
        from db.models import PortfolioSnapshot
        snap = (await db.execute(
            select(PortfolioSnapshot)
            .order_by(PortfolioSnapshot.snapshot_date.desc())
            .limit(1)
        )).scalar_one_or_none()
        capital = snap.total_capital if snap else settings.initial_capital
        shares = compute_position_size(capital, entry_price, stop_price)
        if shares == 0:
            raise HTTPException(
                status_code=422,
                detail="Position size computed as 0 shares — entry/stop spread may be too narrow",
            )
    else:
        shares = body.shares  # type: ignore[assignment]

    trade = await open_trade(
        body.suggestion_id, shares,
        entry_price=entry_price,
        stop_loss=stop_price,
        target_price=target_price,
    )
    if trade is None:
        raise HTTPException(status_code=500, detail="Failed to open trade — see server logs")

    return ApiResponse(
        data=OpenTradeResponse(trade=_to_out(trade), auto_sized=auto_sized),
        timestamp=_ts(),
    )


# ── POST /paper-trades/{id}/close ─────────────────────────────────────────────

@router.post("/{trade_id}/close", response_model=ApiResponse[PaperTradeOut])
async def close_paper_trade(
    trade_id: int,
    body: CloseTradeRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[PaperTradeOut]:
    """
    Manually close an open paper trade at the given exit_price.

    For a LONG trade this represents selling the shares.
    For a SHORT trade this represents buying back the shares.

    Realized P&L is computed as:
      LONG  → (exit_price - entry_price) × shares
      SHORT → (entry_price - exit_price) × shares
    """
    trade = await db.get(PaperTrade, trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")
    if not trade.is_open:
        raise HTTPException(status_code=409, detail=f"Trade {trade_id} is already closed")

    exit_price = Decimal(str(body.exit_price))

    trade.exit_date    = date.today()
    trade.exit_price   = exit_price
    trade.exit_reason  = body.exit_reason
    trade.realized_pnl = compute_realized_pnl(
        entry_price=trade.entry_price,
        exit_price=exit_price,
        shares=trade.shares,
        direction=trade.direction,
    )
    trade.is_open = False

    await db.commit()
    await db.refresh(trade)

    return ApiResponse(data=_to_out(trade), timestamp=_ts())
