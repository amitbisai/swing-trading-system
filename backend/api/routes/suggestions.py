from datetime import date, datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas import ApiResponse, SuggestionOut
from db.models import Suggestion
from db.session import get_db

router = APIRouter()


def _to_out(r: Suggestion) -> SuggestionOut:
    entry = float(r.entry_price)
    stop = float(r.stop_loss)
    target = float(r.target_price)
    risk = entry - stop
    rr = round((target - entry) / risk, 2) if risk > 0 else 0.0
    return SuggestionOut(
        id=r.id,
        symbol=r.symbol,
        tier=r.tier,
        direction=r.direction,
        confidence_score=r.confidence_score,
        entry_price=r.entry_price,
        stop_loss=r.stop_loss,
        target_price=r.target_price,
        risk_reward=rr,
        rationale=r.rationale,
        as_of_date=r.as_of_date,
        ta_score=r.ta_score,
        sentiment_score=r.sentiment_score,
        pattern_score=r.pattern_score,
        is_active=r.is_active,
    )


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── GET /suggestions ──────────────────────────────────────────────────────────

@router.get("/", response_model=ApiResponse[list[SuggestionOut]])
async def list_suggestions(
    date: Annotated[date | None, Query(alias="date", description="Filter by as_of_date (YYYY-MM-DD)")] = None,
    tier: Annotated[str | None, Query(description="T1 or T2")] = None,
    direction: Annotated[str | None, Query(alias="action", description="LONG or SHORT")] = None,
    active_only: Annotated[bool, Query(description="Return only is_active=true suggestions")] = True,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[SuggestionOut]]:
    stmt = select(Suggestion).order_by(
        Suggestion.as_of_date.desc(), Suggestion.confidence_score.desc()
    )
    if date:
        stmt = stmt.where(Suggestion.as_of_date == date)
    if tier:
        stmt = stmt.where(Suggestion.tier == tier.upper())
    if direction:
        stmt = stmt.where(Suggestion.direction == direction.upper())
    if active_only:
        stmt = stmt.where(Suggestion.is_active == True)

    rows = (await db.execute(stmt)).scalars().all()
    return ApiResponse(data=[_to_out(r) for r in rows], timestamp=_ts())


# ── GET /suggestions/{id} ─────────────────────────────────────────────────────

@router.get("/{suggestion_id}", response_model=ApiResponse[SuggestionOut])
async def get_suggestion(
    suggestion_id: int,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[SuggestionOut]:
    row = await db.get(Suggestion, suggestion_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Suggestion {suggestion_id} not found")
    return ApiResponse(data=_to_out(row), timestamp=_ts())
