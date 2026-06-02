"""
Financial Analysis API endpoint.

GET /api/financials/{symbol}
    Returns a FinancialSummaryOut with earnings risk, fundamentals,
    quarterly trend, risk flags, and a Claude 2-sentence swing-trade view.

GET /api/financials/batch?symbols=AMBA,NVDA,TSLA
    Returns a list of FinancialSummaryOut (runs concurrently, max 10).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from agents.financial_agent import get_financial_summary
from api.schemas import ApiResponse, FinancialSummaryOut

router = APIRouter()
logger = logging.getLogger(__name__)

_MAX_BATCH = 10


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_out(summary) -> FinancialSummaryOut:
    """Convert FinancialSummary (agent model) → FinancialSummaryOut (API schema)."""
    from api.schemas import EarningsEventOut, QuarterlyResultOut  # noqa: PLC0415

    return FinancialSummaryOut(
        symbol                 = summary.symbol,
        name                   = summary.name,
        sector                 = summary.sector,
        industry               = summary.industry,
        price                  = summary.price,
        market_cap             = summary.market_cap,
        pe_ratio               = summary.pe_ratio,
        forward_pe             = summary.forward_pe,
        revenue_growth_yoy     = summary.revenue_growth_yoy,
        net_margin             = summary.net_margin,
        debt_to_equity         = summary.debt_to_equity,
        free_cash_flow         = summary.free_cash_flow,
        analyst_recommendation = summary.analyst_recommendation,
        analyst_target_price   = summary.analyst_target_price,
        next_earnings          = (
            EarningsEventOut(
                date_str   = summary.next_earnings.date_str,
                days_until = summary.next_earnings.days_until,
            )
            if summary.next_earnings else None
        ),
        quarterly_results = [
            QuarterlyResultOut(
                period      = q.period,
                revenue     = q.revenue,
                gross_profit= q.gross_profit,
                net_income  = q.net_income,
            )
            for q in summary.quarterly_results
        ],
        trade_readiness        = summary.trade_readiness,
        risk_flags             = summary.risk_flags,
        claude_view            = summary.claude_view,
        fetched_at             = summary.fetched_at,
    )


@router.get("/{symbol}", response_model=ApiResponse[FinancialSummaryOut])
async def get_financial(symbol: str):
    """Fetch fundamental + earnings analysis for a single ticker."""
    sym = symbol.upper().strip()
    if not sym or len(sym) > 10:
        raise HTTPException(status_code=400, detail="Invalid ticker symbol")

    try:
        summary = await get_financial_summary(sym)
        return ApiResponse(data=_to_out(summary), error=None, timestamp=_now())
    except Exception as exc:
        logger.error("financials/%s: %s", sym, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/", response_model=ApiResponse[list[FinancialSummaryOut]])
async def get_financials_batch(
    symbols: str = Query(..., description="Comma-separated tickers, e.g. AMBA,NVDA,TSLA"),
):
    """Fetch fundamental + earnings analysis for up to 10 tickers concurrently."""
    raw = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not raw:
        raise HTTPException(status_code=400, detail="No symbols provided")
    if len(raw) > _MAX_BATCH:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {_MAX_BATCH} symbols per batch request",
        )

    try:
        results = await asyncio.gather(
            *[get_financial_summary(sym) for sym in raw],
            return_exceptions=True,
        )
    except Exception as exc:
        logger.error("financials/batch: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    outputs: list[FinancialSummaryOut] = []
    for sym, res in zip(raw, results):
        if isinstance(res, Exception):
            logger.warning("financials/batch: %s failed — %s", sym, res)
            # Return a minimal error placeholder so the UI can show it
            from api.schemas import FinancialSummaryOut  # noqa: PLC0415
            outputs.append(
                FinancialSummaryOut(
                    symbol          = sym,
                    name            = sym,
                    sector          = "Unknown",
                    industry        = "Unknown",
                    price           = 0.0,
                    trade_readiness = "CAUTION",
                    risk_flags      = [f"⚠️ Data fetch failed: {res}"],
                    claude_view     = "Could not retrieve data for this symbol.",
                    fetched_at      = _now(),
                )
            )
        else:
            outputs.append(_to_out(res))

    return ApiResponse(data=outputs, error=None, timestamp=_now())
