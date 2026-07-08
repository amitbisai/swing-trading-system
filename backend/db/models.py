from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Stock(Base):
    __tablename__ = "stocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(100), nullable=True)
    exchange: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tier: Mapped[str] = mapped_column(String(2), nullable=False)  # T1 | T2
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    daily_prices: Mapped[list["DailyPrice"]] = relationship(
        "DailyPrice", back_populates="stock", foreign_keys="DailyPrice.symbol",
        primaryjoin="Stock.symbol == DailyPrice.symbol",
    )
    suggestions: Mapped[list["Suggestion"]] = relationship(
        "Suggestion", back_populates="stock", foreign_keys="Suggestion.symbol",
        primaryjoin="Stock.symbol == Suggestion.symbol",
    )


class DailyPrice(Base):
    __tablename__ = "daily_prices"
    __table_args__ = (
        UniqueConstraint("symbol", "price_date", name="uq_daily_prices_symbol_date"),
        Index("ix_daily_prices_symbol_date", "symbol", "price_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(
        String(20), ForeignKey("stocks.symbol", ondelete="CASCADE"), nullable=False
    )
    price_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    high: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    low: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    close: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    adj_close: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)

    stock: Mapped["Stock"] = relationship(
        "Stock", back_populates="daily_prices", foreign_keys=[symbol]
    )


class Suggestion(Base):
    __tablename__ = "suggestions"
    __table_args__ = (
        UniqueConstraint("symbol", "as_of_date", name="uq_suggestions_symbol_date"),
        Index("ix_suggestions_symbol_date", "symbol", "as_of_date"),
        Index("ix_suggestions_as_of_date", "as_of_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(
        String(20), ForeignKey("stocks.symbol", ondelete="CASCADE"), nullable=False
    )
    tier: Mapped[str] = mapped_column(String(2), nullable=False)
    direction: Mapped[str] = mapped_column(String(5), nullable=False)  # LONG | SHORT
    confidence_score: Mapped[int] = mapped_column(Integer, nullable=False)  # 0–100
    entry_price: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    stop_loss: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    target_price: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    ta_score: Mapped[int] = mapped_column(Integer, nullable=False)          # 0–100
    sentiment_score: Mapped[int] = mapped_column(Integer, nullable=False)   # 0–100
    pattern_score: Mapped[int] = mapped_column(Integer, nullable=False)     # 0–100
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    stock: Mapped["Stock"] = relationship(
        "Stock", back_populates="suggestions", foreign_keys=[symbol]
    )
    paper_trades: Mapped[list["PaperTrade"]] = relationship(
        "PaperTrade", back_populates="suggestion"
    )


class PaperTrade(Base):
    __tablename__ = "paper_trades"
    __table_args__ = (
        Index("ix_paper_trades_symbol", "symbol"),
        Index("ix_paper_trades_is_open", "is_open"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    suggestion_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("suggestions.id", ondelete="RESTRICT"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    direction: Mapped[str] = mapped_column(String(5), nullable=False)  # LONG | SHORT
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    entry_price: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    shares: Mapped[int] = mapped_column(Integer, nullable=False)
    capital_at_risk: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)  # entry_price * shares
    stop_loss: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    target_price: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    exit_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(
        String(20), nullable=True  # STOP_HIT | TARGET_HIT | TIME_EXIT | MANUAL
    )
    realized_pnl: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    is_open: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Dynamic exit management (nightly trade manager)
    original_stop: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    original_target: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    levels_updated_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    adjustment_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    suggestion: Mapped["Suggestion"] = relationship(
        "Suggestion", back_populates="paper_trades"
    )
    daily_pnl: Mapped[list["DailyPnL"]] = relationship(
        "DailyPnL", back_populates="trade"
    )


class DailyPnL(Base):
    __tablename__ = "daily_pnl"
    __table_args__ = (
        UniqueConstraint("trade_id", "pnl_date", name="uq_daily_pnl_trade_date"),
        Index("ix_daily_pnl_trade_date", "trade_id", "pnl_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("paper_trades.id", ondelete="CASCADE"), nullable=False
    )
    pnl_date: Mapped[date] = mapped_column(Date, nullable=False)
    close_price: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)  # EOD price used for MTM
    unrealized_pnl: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)

    trade: Mapped["PaperTrade"] = relationship(
        "PaperTrade", back_populates="daily_pnl"
    )


class T2Scan(Base):
    """
    One row per (symbol, scan_date) — stores the raw T2 screener output
    plus the AI-validated news summary.  Older than 30 days is pruned nightly.
    """
    __tablename__ = "t2_scans"
    __table_args__ = (
        UniqueConstraint("symbol", "scan_date", name="uq_t2_scans_symbol_date"),
        Index("ix_t2_scans_scan_date", "scan_date"),
        Index("ix_t2_scans_symbol",    "symbol"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(
        String(20), ForeignKey("stocks.symbol", ondelete="CASCADE"), nullable=False
    )
    scan_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Screener outputs
    signal_tier:        Mapped[str]           = mapped_column(String(1), nullable=False)   # A|B|C
    t2_score:           Mapped[float]         = mapped_column(Numeric(5, 1), nullable=False)
    price:              Mapped[float]         = mapped_column(Numeric(12, 4), nullable=False)
    market_cap:         Mapped[float | None]  = mapped_column(Numeric(20, 0), nullable=True)
    rvol:               Mapped[float]         = mapped_column(Numeric(8, 2), nullable=False)
    avg_volume_30d:     Mapped[float | None]  = mapped_column(Numeric(20, 0), nullable=True)
    revenue_growth:     Mapped[float | None]  = mapped_column(Numeric(8, 4), nullable=True)
    earnings_growth:    Mapped[float | None]  = mapped_column(Numeric(8, 4), nullable=True)
    pct_below_52w_high: Mapped[float | None]  = mapped_column(Numeric(8, 4), nullable=True)
    float_shares:       Mapped[float | None]  = mapped_column(Numeric(20, 0), nullable=True)
    short_ratio:        Mapped[float | None]  = mapped_column(Numeric(8, 2), nullable=True)
    sector:             Mapped[str | None]    = mapped_column(String(100), nullable=True)
    industry:           Mapped[str | None]    = mapped_column(String(200), nullable=True)
    risk_flags:         Mapped[str | None]    = mapped_column(Text, nullable=True)         # comma-separated
    signal_summary:     Mapped[str | None]    = mapped_column(Text, nullable=True)
    catalyst_hint:      Mapped[str | None]    = mapped_column(String(200), nullable=True)
    news_summary:       Mapped[str | None]    = mapped_column(Text, nullable=True)         # Claude-generated
    news_verdict:       Mapped[str | None]    = mapped_column(String(20), nullable=True)   # SUPPORTS|NEUTRAL|CONTRADICTS
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class T1Scan(Base):
    """
    One row per (symbol, scan_date) — stores the raw T1 TA snapshot for every
    S&P 500 stock the orchestrator processes.  Older than 30 days is pruned
    nightly.  made_signal=True when the stock also appears in suggestions today.
    """

    __tablename__ = "t1_scans"
    __table_args__ = (
        UniqueConstraint("symbol", "scan_date", name="uq_t1_scans_symbol_date"),
        Index("ix_t1_scans_scan_date", "scan_date"),
        Index("ix_t1_scans_symbol", "symbol"),
        Index("ix_t1_scans_made_signal", "made_signal"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(
        String(20), ForeignKey("stocks.symbol", ondelete="CASCADE"), nullable=False
    )
    scan_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Price
    price: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)

    # TA indicators
    rsi_14: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    macd_hist: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    sma_20: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    sma_50: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    atr_14: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    bb_upper: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    bb_lower: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)

    # Volume
    rvol: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    avg_volume_20d: Mapped[float | None] = mapped_column(Numeric(16, 0), nullable=True)

    # Pattern
    support_level: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    resistance_level: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    patterns_detected: Mapped[str | None] = mapped_column(Text, nullable=True)  # comma-sep

    # Composite scores
    ta_score: Mapped[int] = mapped_column(Integer, nullable=False)
    pattern_score: Mapped[int] = mapped_column(Integer, nullable=False)
    sentiment_score: Mapped[int] = mapped_column(Integer, nullable=False)
    bullish_confidence: Mapped[int] = mapped_column(Integer, nullable=False)
    bearish_confidence: Mapped[int] = mapped_column(Integer, nullable=False)
    signal_direction: Mapped[str] = mapped_column(String(5), nullable=False)  # LONG | SHORT

    # Whether this stock made it to suggestions today
    made_signal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Denormalised for fast reads
    sector: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MarketPulseLog(Base):
    """
    One row per day — the market pulse computed at entry-planning time.
    Persisted so trade outcomes can be analyzed against the market context
    that existed at entry (not reconstructible after the fact).
    """
    __tablename__ = "market_pulse_log"
    __table_args__ = (UniqueConstraint("pulse_date", name="uq_market_pulse_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pulse_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False)          # 0–100
    label: Mapped[str] = mapped_column(String(10), nullable=False)
    breadth_pct: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    spy_close: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    spy_sma50: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    spy_sma200: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TradeOutcome(Base):
    """
    Outcome analytics — one row per CLOSED trade, joining the signal-time
    variables (what the system believed) with the realized result (what
    actually happened). The raw material for tuning: win rate / avg R by
    sentiment bucket, TA bucket, tier, pulse regime, exit reason, etc.
    """
    __tablename__ = "trade_outcomes"
    __table_args__ = (
        UniqueConstraint("trade_id", name="uq_trade_outcomes_trade"),
        Index("ix_trade_outcomes_tier", "tier"),
        Index("ix_trade_outcomes_exit_reason", "exit_reason"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("paper_trades.id", ondelete="CASCADE"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    tier: Mapped[str] = mapped_column(String(2), nullable=False)
    direction: Mapped[str] = mapped_column(String(5), nullable=False)

    # ── Outcome ───────────────────────────────────────────────────────────────
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    exit_date: Mapped[date] = mapped_column(Date, nullable=False)
    holding_days: Mapped[int] = mapped_column(Integer, nullable=False)
    exit_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)
    entry_price: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    exit_price: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    shares: Mapped[int] = mapped_column(Integer, nullable=False)
    realized_pnl: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    return_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)   # pnl / cost × 100
    r_multiple: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)   # pnl / initial risk
    levels_adjusted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # ── Signal-time variables (from the suggestion) ───────────────────────────
    confidence_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ta_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sentiment_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pattern_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── T2 screener variables (null for T1 trades) ────────────────────────────
    t2_score: Mapped[float | None] = mapped_column(Numeric(5, 1), nullable=True)
    t2_rvol: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    t2_signal_tier: Mapped[str | None] = mapped_column(String(1), nullable=True)
    news_verdict: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # ── Market context at entry ───────────────────────────────────────────────
    pulse_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pulse_label: Mapped[str | None] = mapped_column(String(10), nullable=True)
    breadth_pct: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)

    # ── Trade trajectory (exit-tuning analytics) ──────────────────────────────
    # MFE/MAE: best/worst price excursion DURING the hold, vs entry.
    mfe_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    mae_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    mfe_r: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    mae_r: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    # realized gain ÷ max available gain (1.0 = perfect exit; <0 = lost despite MFE)
    exit_efficiency: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    # what the stock did AFTER we exited — backfilled by the nightly job
    post_exit_5d_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    post_exit_10d_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"
    __table_args__ = (UniqueConstraint("snapshot_date", name="uq_portfolio_snapshot_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    total_capital: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    cash_balance: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    invested_capital: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    unrealized_pnl: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    realized_pnl_today: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    cumulative_realized_pnl: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    open_positions: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
