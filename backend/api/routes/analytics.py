from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas import (
    AnalyticsSummary,
    ApiResponse,
    CapitalStats,
    MarketPulseOut,
    SuggestionStats,
    TierPerformance,
    TradeStats,
)
from config import settings
from db.models import PaperTrade, PortfolioSnapshot, Suggestion
from db.session import get_db

router = APIRouter()

_ZERO = Decimal("0")


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── GET /analytics/market-pulse ───────────────────────────────────────────────

@router.get("/market-pulse", response_model=ApiResponse[MarketPulseOut])
async def get_market_pulse_endpoint() -> ApiResponse[MarketPulseOut]:
    """
    Today's market health score and the resulting entry allowance
    (the user's top-N cap scaled by market trend + breadth).
    """
    from db.app_settings import get_int_setting
    from risk.market_pulse import entries_allowed, get_market_pulse

    pulse = await get_market_pulse()
    max_daily = await get_int_setting("max_entries_per_day", settings.max_entries_per_day)
    allowed = entries_allowed(max_daily, pulse.score)

    return ApiResponse(
        data=MarketPulseOut(
            score=pulse.score,
            label=pulse.label,
            entries_allowed=allowed if allowed < 10_000 else -1,
            max_entries_per_day=max_daily,
            spy_close=pulse.spy_close,
            spy_sma50=pulse.spy_sma50,
            spy_sma200=pulse.spy_sma200,
            breadth_pct=pulse.breadth_pct,
        ),
        timestamp=_ts(),
    )


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

    # ── Per-tier performance (join trades to their suggestion's tier) ─────────
    tier_rows = (await db.execute(
        select(
            Suggestion.tier,
            func.count().label("closed"),
            func.count().filter(PaperTrade.realized_pnl > 0).label("winners"),
            func.coalesce(func.sum(PaperTrade.realized_pnl), _ZERO).label("total_pnl"),
        )
        .join(Suggestion, PaperTrade.suggestion_id == Suggestion.id)
        .where(PaperTrade.is_open == False)
        .group_by(Suggestion.tier)
        .order_by(Suggestion.tier)
    )).all()

    tiers = [
        TierPerformance(
            tier=row.tier,
            closed_trades=int(row.closed),
            winning_trades=int(row.winners),
            win_rate_pct=round(int(row.winners) / int(row.closed) * 100, 1) if row.closed else 0.0,
            total_realized_pnl=Decimal(str(row.total_pnl)),
        )
        for row in tier_rows
    ]

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
            tiers=tiers,
        ),
        timestamp=_ts(),
    )
