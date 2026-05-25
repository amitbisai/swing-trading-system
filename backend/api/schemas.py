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


class CloseTradeRequest(BaseModel):
    exit_price: Decimal = Field(..., gt=0, description="Price at which the trade is closed.")
    exit_reason: str = Field(
        default="MANUAL_CLOSE",
        description="Reason for closing. Default: MANUAL_CLOSE.",
    )


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


class T2ScanOut(BaseModel):
    id:                 int
    symbol:             str
    scan_date:          date
    signal_tier:        str            # A | B | C
    t2_score:           float
    price:              Decimal
    market_cap:         Decimal | None
    rvol:               float
    avg_volume_30d:     Decimal | None
    revenue_growth:     float | None
    earnings_growth:    float | None
    pct_below_52w_high: float | None
    float_shares:       Decimal | None
    short_ratio:        float | None
    sector:             str | None
    industry:           str | None
    risk_flags:         list[str]      # parsed from comma-separated DB field
    signal_summary:     str | None
    catalyst_hint:      str | None
    news_summary:       str | None
    news_verdict:       str | None     # SUPPORTS | NEUTRAL | CONTRADICTS

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_row(cls, row: object) -> "T2ScanOut":
        """Convert ORM T2Scan to schema — parses risk_flags string."""
        from db.models import T2Scan as T2ScanModel  # noqa: PLC0415
        r: T2ScanModel = row  # type: ignore[assignment]
        flags_raw = r.risk_flags or ""
        flags = [f.strip() for f in flags_raw.split(",") if f.strip()]
        return cls(
            id                 = r.id,
            symbol             = r.symbol,
            scan_date          = r.scan_date,
            signal_tier        = r.signal_tier,
            t2_score           = float(r.t2_score),
            price              = r.price,
            market_cap         = r.market_cap,
            rvol               = float(r.rvol),
            avg_volume_30d     = r.avg_volume_30d,
            revenue_growth     = float(r.revenue_growth) if r.revenue_growth is not None else None,
            earnings_growth    = float(r.earnings_growth) if r.earnings_growth is not None else None,
            pct_below_52w_high = float(r.pct_below_52w_high) if r.pct_below_52w_high is not None else None,
            float_shares       = r.float_shares,
            short_ratio        = float(r.short_ratio) if r.short_ratio is not None else None,
            sector             = r.sector,
            industry           = r.industry,
            risk_flags         = flags,
            signal_summary     = r.signal_summary,
            catalyst_hint      = r.catalyst_hint,
            news_summary       = r.news_summary,
            news_verdict       = r.news_verdict,
        )


class AnalyticsSummary(BaseModel):
    as_of: date
    capital: CapitalStats
    trades: TradeStats
    suggestions: SuggestionStats
