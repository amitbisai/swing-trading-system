from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas import AnalyticsSummary, ApiResponse, CapitalStats, SuggestionStats, TradeStats
from config import settings
from db.models import PaperTrade, PortfolioSnapshot, Suggestion
from db.session import get_db

router = APIRouter()

_ZERO = Decimal("0")


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── GET /analytics/summary ────────────────────────────────────────────────────

@router.get("/summary", response_model=ApiResponse[AnalyticsSummary])
async def get_summary(db: AsyncSession = Depends(get_db)) -> ApiResponse[AnalyticsSummary]:
    today = date.today()

    # ── Trade stats ───────────────────────────────────────────────────────────
    trade_agg = (await db.execute(
        select(
            func.count().label("total"),
            func.count().filter(PaperTrade.is_open == True).label("open"),
            func.count().filter(PaperTrade.is_open == False).label("closed"),
            func.count()
            .filter(PaperTrade.is_open == False, PaperTrade.realized_pnl > 0)
            .label("winners"),
            func.count()
            .filter(PaperTrade.is_open == False, PaperTrade.realized_pnl <= 0)
            .label("losers"),
            func.coalesce(
                func.sum(PaperTrade.realized_pnl).filter(PaperTrade.is_open == False),
                _ZERO,
            ).label("total_realized"),
            func.coalesce(
                func.avg(PaperTrade.realized_pnl).filter(PaperTrade.is_open == False),
                _ZERO,
            ).label("avg_realized"),
            func.max(PaperTrade.realized_pnl).filter(PaperTrade.is_open == False).label("best"),
            func.min(PaperTrade.realized_pnl).filter(PaperTrade.is_open == False).label("worst"),
        )
    )).one()

    closed = int(trade_agg.closed)
    winners = int(trade_agg.winners)
    win_rate = round(winners / closed * 100, 1) if closed > 0 else 0.0

    trades = TradeStats(
        open_trades=int(trade_agg.open),
        closed_trades=closed,
        winning_trades=winners,
        losing_trades=int(trade_agg.losers),
        win_rate_pct=win_rate,
        total_realized_pnl=Decimal(str(trade_agg.total_realized)),
        avg_realized_pnl=Decimal(str(round(float(trade_agg.avg_realized), 4))),
        best_trade_pnl=Decimal(str(trade_agg.best)) if trade_agg.best is not None else None,
        worst_trade_pnl=Decimal(str(trade_agg.worst)) if trade_agg.worst is not None else None,
    )

    # ── Capital stats ─────────────────────────────────────────────────────────
    latest_snap = (await db.execute(
        select(PortfolioSnapshot)
        .order_by(PortfolioSnapshot.snapshot_date.desc())
        .limit(1)
    )).scalar_one_or_none()

    if latest_snap:
        current_capital = Decimal(str(latest_snap.total_capital))
        unrealized = Decimal(str(latest_snap.unrealized_pnl))
        cumulative_realized = Decimal(str(latest_snap.cumulative_realized_pnl))
    else:
        current_capital = settings.initial_capital
        unrealized = _ZERO
        cumulative_realized = _ZERO

    initial = settings.initial_capital
    total_return_pct = round(
        float((current_capital - initial) / initial * 100), 2
    ) if initial > 0 else 0.0

    capital = CapitalStats(
        initial_capital=initial,
        current_capital=current_capital,
        total_return_pct=total_return_pct,
        unrealized_pnl=unrealized,
        cumulative_realized_pnl=cumulative_realized,
    )

    # ── Suggestion stats ──────────────────────────────────────────────────────
    suggestion_agg = (await db.execute(
        select(
            func.count().label("total"),
            func.count().filter(Suggestion.as_of_date == today).label("today"),
            func.coalesce(func.avg(Suggestion.confidence_score), 0).label("avg_conf"),
        )
    )).one()

    sugg = SuggestionStats(
        total_suggestions=int(suggestion_agg.total),
        suggestions_today=int(suggestion_agg.today),
        avg_confidence=round(float(suggestion_agg.avg_conf), 1),
    )

    return ApiResponse(
        data=AnalyticsSummary(
            as_of=today,
            capital=capital,
            trades=trades,
            suggestions=sugg,
        ),
        timestamp=_ts(),
    )
