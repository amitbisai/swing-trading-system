"""
Pydantic request / response schemas for the REST API.

All monetary fields use Decimal so JSON serialisation preserves precision.
Every response is wrapped in the { data, error, timestamp } envelope defined
in ApiResponse[T].
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


# ── Envelope ──────────────────────────────────────────────────────────────────

class ApiResponse(BaseModel, Generic[T]):
    data: T
    error: str | None = None
    timestamp: str


# ── Suggestions ───────────────────────────────────────────────────────────────

class SuggestionOut(BaseModel):
    id: int
    symbol: str
    tier: str
    direction: str
    confidence_score: int
    entry_price: Decimal
    stop_loss: Decimal
    target_price: Decimal
    risk_reward: float          # (target - entry) / (entry - stop)
    rationale: str
    as_of_date: date
    ta_score: int
    sentiment_score: int
    pattern_score: int
    is_active: bool

    model_config = {"from_attributes": True}


# ── Paper trades ──────────────────────────────────────────────────────────────

class PaperTradeOut(BaseModel):
    id: int
    suggestion_id: int
    symbol: str
    direction: str
    entry_date: date
    entry_price: Decimal
    shares: int
    capital_at_risk: Decimal
    stop_loss: Decimal
    target_price: Decimal
    exit_date: date | None = None
    exit_price: Decimal | None = None
    exit_reason: str | None = None
    realized_pnl: Decimal | None = None
    is_open: bool

    model_config = {"from_attributes": True}


class OpenTradeRequest(BaseModel):
    suggestion_id: int = Field(..., gt=0)
    shares: int | None = Field(
        default=None,
        gt=0,
        description="Number of shares. Omit to auto-size from risk settings.",
    )


class OpenTradeResponse(BaseModel):
    trade: PaperTradeOut
    auto_sized: bool            # True when shares was calculated automatically


# ── Portfolio ─────────────────────────────────────────────────────────────────

class PortfolioSnapshotOut(BaseModel):
    snapshot_date: date
    total_capital: Decimal
    cash_balance: Decimal
    invested_capital: Decimal
    unrealized_pnl: Decimal
    realized_pnl_today: Decimal
    cumulative_realized_pnl: Decimal
    open_positions: int

    model_config = {"from_attributes": True}


# ── Analytics ─────────────────────────────────────────────────────────────────

class TradeStats(BaseModel):
    open_trades: int
    closed_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float         # 0–100
    total_realized_pnl: Decimal
    avg_realized_pnl: Decimal
    best_trade_pnl: Decimal | None
    worst_trade_pnl: Decimal | None


class CapitalStats(BaseModel):
    initial_capital: Decimal
    current_capital: Decimal    # latest snapshot total_capital
    total_return_pct: float
    unrealized_pnl: Decimal
    cumulative_realized_pnl: Decimal


class SuggestionStats(BaseModel):
    total_suggestions: int
    suggestions_today: int
    avg_confidence: float


class AnalyticsSummary(BaseModel):
    as_of: date
    capital: CapitalStats
    trades: TradeStats
    suggestions: SuggestionStats
