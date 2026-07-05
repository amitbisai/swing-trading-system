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
    # Dynamic exit management
    original_stop: Decimal | None = None
    original_target: Decimal | None = None
    levels_updated_at: date | None = None
    adjustment_note: str | None = None

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
    initial_capital: Decimal | None = None   # settings value, for return calc

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


class PersistentPickOut(BaseModel):
    """A symbol repeatedly surfaced by the system over the recent window."""
    symbol: str
    total_days: int          # distinct days seen across suggestions + T2 scans
    suggestion_days: int     # days it appeared as a final suggestion
    t2_scan_days: int        # days it passed the T2 screener
    window_days: int         # look-back window used
    last_seen: date
    tier: str | None = None              # from most recent suggestion, if any
    latest_confidence: int | None = None
    latest_direction: str | None = None


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


class T1ScanOut(BaseModel):
    id: int
    symbol: str
    scan_date: date
    price: Decimal
    rsi_14: float | None
    macd_hist: float | None
    sma_20: Decimal | None
    sma_50: Decimal | None
    atr_14: float | None
    bb_upper: Decimal | None
    bb_lower: Decimal | None
    rvol: float | None
    avg_volume_20d: Decimal | None
    support_level: Decimal | None
    resistance_level: Decimal | None
    patterns_detected: list[str]  # parsed from comma-separated DB field
    ta_score: int
    pattern_score: int
    sentiment_score: int
    bullish_confidence: int
    bearish_confidence: int
    signal_direction: str  # LONG | SHORT
    made_signal: bool
    sector: str | None

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_row(cls, row: object) -> "T1ScanOut":
        """Convert ORM T1Scan to schema — parses patterns_detected string."""
        from db.models import T1Scan as T1ScanModel  # noqa: PLC0415

        r: T1ScanModel = row  # type: ignore[assignment]
        raw = r.patterns_detected or ""
        patterns = [p.strip() for p in raw.split(",") if p.strip()]
        return cls(
            id=r.id,
            symbol=r.symbol,
            scan_date=r.scan_date,
            price=r.price,
            rsi_14=float(r.rsi_14) if r.rsi_14 is not None else None,
            macd_hist=float(r.macd_hist) if r.macd_hist is not None else None,
            sma_20=r.sma_20,
            sma_50=r.sma_50,
            atr_14=float(r.atr_14) if r.atr_14 is not None else None,
            bb_upper=r.bb_upper,
            bb_lower=r.bb_lower,
            rvol=float(r.rvol) if r.rvol is not None else None,
            avg_volume_20d=r.avg_volume_20d,
            support_level=r.support_level,
            resistance_level=r.resistance_level,
            patterns_detected=patterns,
            ta_score=r.ta_score,
            pattern_score=r.pattern_score,
            sentiment_score=r.sentiment_score,
            bullish_confidence=r.bullish_confidence,
            bearish_confidence=r.bearish_confidence,
            signal_direction=r.signal_direction,
            made_signal=r.made_signal,
            sector=r.sector,
        )


class MarketPulseOut(BaseModel):
    score: int                       # 0–100
    label: str                       # STRONG | UPTREND | NEUTRAL | WEAK | AVOID
    entries_allowed: int             # today's pulse-scaled entry count
    max_entries_per_day: int         # the user's configured top-N cap
    spy_close: float | None = None
    spy_sma50: float | None = None
    spy_sma200: float | None = None
    breadth_pct: float | None = None  # fraction of tracked stocks above their 50DMA


class TierPerformance(BaseModel):
    tier: str                   # T1 | T2
    closed_trades: int
    winning_trades: int
    win_rate_pct: float
    total_realized_pnl: Decimal


class AnalyticsSummary(BaseModel):
    as_of: date
    capital: CapitalStats
    trades: TradeStats
    suggestions: SuggestionStats
    tiers: list[TierPerformance] = []


# ── Financial Analysis ────────────────────────────────────────────────────────

class EarningsEventOut(BaseModel):
    date_str: str | None = None
    days_until: int | None = None


class QuarterlyResultOut(BaseModel):
    period: str
    revenue: float | None = None
    gross_profit: float | None = None
    net_income: float | None = None


class FinancialSummaryOut(BaseModel):
    symbol: str
    name: str
    sector: str
    industry: str
    price: float
    market_cap: float | None = None
    pe_ratio: float | None = None
    forward_pe: float | None = None
    revenue_growth_yoy: float | None = None
    net_margin: float | None = None
    debt_to_equity: float | None = None
    free_cash_flow: float | None = None
    analyst_recommendation: str | None = None
    analyst_target_price: float | None = None
    next_earnings: EarningsEventOut | None = None
    quarterly_results: list[QuarterlyResultOut] = []
    trade_readiness: str                  # "GO" | "CAUTION" | "AVOID"
    risk_flags: list[str] = []
    claude_view: str
    fetched_at: str
