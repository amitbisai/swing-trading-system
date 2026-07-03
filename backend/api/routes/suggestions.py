from datetime import date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas import ApiResponse, PersistentPickOut, SuggestionOut
from db.models import Suggestion, T2Scan
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
        # Explicit date requested — show that date's signals regardless of active flag
        stmt = stmt.where(Suggestion.as_of_date == date)
    elif active_only:
        # No explicit date + active_only → restrict to the latest run date only.
        # This ensures signals from previous runs never bleed through even if
        # is_active hasn't been flipped yet (e.g. no agents run today).
        latest_date_subq = (
            select(func.max(Suggestion.as_of_date))
            .where(Suggestion.is_active == True)
            .scalar_subquery()
        )
        stmt = stmt.where(Suggestion.as_of_date == latest_date_subq)
    else:
        # active_only=False with no date → return full history (for analytics / debug)
        pass

    if tier:
        stmt = stmt.where(Suggestion.tier == tier.upper())
    if direction:
        stmt = stmt.where(Suggestion.direction == direction.upper())
    if active_only:
        stmt = stmt.where(Suggestion.is_active == True)

    rows = (await db.execute(stmt)).scalars().all()
    return ApiResponse(data=[_to_out(r) for r in rows], timestamp=_ts())


# ── GET /suggestions/persistent ───────────────────────────────────────────────
# NOTE: must be declared before /{suggestion_id} or "persistent" is captured
# by the int path parameter.

@router.get("/persistent", response_model=ApiResponse[list[PersistentPickOut]])
async def list_persistent_picks(
    window: Annotated[int, Query(ge=2, le=30, description="Look-back window in calendar days")] = 7,
    min_days: Annotated[int, Query(ge=2, le=10, description="Min distinct days to flag")] = 3,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[PersistentPickOut]]:
    """
    Symbols the system keeps surfacing: appeared on >= min_days distinct days
    within the window, counting both final suggestions and T2 screener passes.
    Repeated appearance across independent daily scans is the multi-day
    accumulation footprint worth prioritising.
    """
    cutoff = date.today() - timedelta(days=window)

    sugg_q = (
        select(Suggestion.symbol.label("symbol"), Suggestion.as_of_date.label("seen"))
        .where(Suggestion.as_of_date >= cutoff)
    )
    t2_q = (
        select(T2Scan.symbol.label("symbol"), T2Scan.scan_date.label("seen"))
        .where(T2Scan.scan_date >= cutoff)
    )
    union_sq = sugg_q.union(t2_q).subquery()

    combined = (await db.execute(
        select(
            union_sq.c.symbol,
            func.count(func.distinct(union_sq.c.seen)).label("total_days"),
            func.max(union_sq.c.seen).label("last_seen"),
        )
        .group_by(union_sq.c.symbol)
        .having(func.count(func.distinct(union_sq.c.seen)) >= min_days)
        .order_by(func.count(func.distinct(union_sq.c.seen)).desc())
    )).all()

    if not combined:
        return ApiResponse(data=[], timestamp=_ts())

    symbols = [r.symbol for r in combined]

    # Per-source day counts
    sugg_counts = dict((await db.execute(
        select(Suggestion.symbol, func.count(func.distinct(Suggestion.as_of_date)))
        .where(Suggestion.as_of_date >= cutoff, Suggestion.symbol.in_(symbols))
        .group_by(Suggestion.symbol)
    )).all())
    t2_counts = dict((await db.execute(
        select(T2Scan.symbol, func.count(func.distinct(T2Scan.scan_date)))
        .where(T2Scan.scan_date >= cutoff, T2Scan.symbol.in_(symbols))
        .group_by(T2Scan.symbol)
    )).all())

    # Most recent suggestion metadata per symbol (tier / confidence / direction)
    latest_sugg_rows = (await db.execute(
        select(Suggestion)
        .where(Suggestion.symbol.in_(symbols), Suggestion.as_of_date >= cutoff)
        .order_by(Suggestion.as_of_date.desc())
    )).scalars().all()
    latest_by_symbol: dict[str, Suggestion] = {}
    for s in latest_sugg_rows:
        latest_by_symbol.setdefault(s.symbol, s)

    data = []
    for r in combined:
        latest = latest_by_symbol.get(r.symbol)
        data.append(PersistentPickOut(
            symbol=r.symbol,
            total_days=int(r.total_days),
            suggestion_days=int(sugg_counts.get(r.symbol, 0)),
            t2_scan_days=int(t2_counts.get(r.symbol, 0)),
            window_days=window,
            last_seen=r.last_seen,
            tier=latest.tier if latest else None,
            latest_confidence=latest.confidence_score if latest else None,
            latest_direction=latest.direction if latest else None,
        ))

    return ApiResponse(data=data, timestamp=_ts())


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
