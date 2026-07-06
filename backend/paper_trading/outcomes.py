"""
Outcome analytics — closes the feedback loop between signal-time beliefs and
realized results.

Two writers:

  log_market_pulse(as_of, pulse)  — upserts today's market pulse into
      market_pulse_log so entry-time context survives for later analysis
      (called from plan_entries on every entry run).

  sync_trade_outcomes()  — idempotent backfill: finds every CLOSED trade
      without a trade_outcomes row and writes one, joining
        paper_trades  → outcome (pnl, exit reason, R-multiple, holding days)
        suggestions   → signal-time scores (ta / sentiment / pattern / conf)
        t2_scans      → T2 screener variables (score, rvol, news verdict)
        market_pulse_log → pulse at entry date
      Called after the nightly EOD run, after hourly exits, and after manual
      closes — but because it back-scans, a missed call self-heals on the
      next run.

Analysis is then a plain SQL/pandas job over trade_outcomes, e.g.:
    SELECT width_bucket(sentiment_score, 0, 100, 5) AS bucket,
           COUNT(*), AVG(r_multiple), AVG(return_pct)
    FROM trade_outcomes GROUP BY bucket ORDER BY bucket;
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from sqlalchemy import select, text

from db.models import MarketPulseLog, PaperTrade, Suggestion, T2Scan, TradeOutcome
from db.session import async_session_factory

logger = logging.getLogger(__name__)

_ENSURE_SQL = [
    text("""
        CREATE TABLE IF NOT EXISTS market_pulse_log (
            id          serial PRIMARY KEY,
            pulse_date  date NOT NULL UNIQUE,
            score       integer NOT NULL,
            label       varchar(10) NOT NULL,
            breadth_pct numeric(6,4),
            spy_close   numeric(12,4),
            spy_sma50   numeric(12,4),
            spy_sma200  numeric(12,4),
            created_at  timestamptz NOT NULL DEFAULT now()
        )
    """),
    text("""
        CREATE TABLE IF NOT EXISTS trade_outcomes (
            id               serial PRIMARY KEY,
            trade_id         integer NOT NULL UNIQUE REFERENCES paper_trades(id) ON DELETE CASCADE,
            symbol           varchar(20) NOT NULL,
            tier             varchar(2) NOT NULL,
            direction        varchar(5) NOT NULL,
            entry_date       date NOT NULL,
            exit_date        date NOT NULL,
            holding_days     integer NOT NULL,
            exit_reason      varchar(20),
            entry_price      numeric(12,4) NOT NULL,
            exit_price       numeric(12,4),
            shares           integer NOT NULL,
            realized_pnl     numeric(12,4),
            return_pct       numeric(8,4),
            r_multiple       numeric(8,4),
            levels_adjusted  boolean NOT NULL DEFAULT false,
            confidence_score integer,
            ta_score         integer,
            sentiment_score  integer,
            pattern_score    integer,
            t2_score         numeric(5,1),
            t2_rvol          numeric(8,2),
            t2_signal_tier   varchar(1),
            news_verdict     varchar(20),
            pulse_score      integer,
            pulse_label      varchar(10),
            breadth_pct      numeric(6,4),
            created_at       timestamptz NOT NULL DEFAULT now()
        )
    """),
    text("CREATE INDEX IF NOT EXISTS ix_trade_outcomes_tier ON trade_outcomes(tier)"),
    text("CREATE INDEX IF NOT EXISTS ix_trade_outcomes_exit_reason ON trade_outcomes(exit_reason)"),
]


async def _ensure_tables(session) -> None:
    for stmt in _ENSURE_SQL:
        await session.execute(stmt)


# ── Daily market pulse log ────────────────────────────────────────────────────

async def log_market_pulse(as_of: date, pulse) -> None:
    """Upsert today's pulse (risk.market_pulse.MarketPulse) — best-effort."""
    try:
        async with async_session_factory() as session:
            await _ensure_tables(session)
            await session.execute(
                text("""
                    INSERT INTO market_pulse_log
                        (pulse_date, score, label, breadth_pct, spy_close, spy_sma50, spy_sma200)
                    VALUES (:d, :score, :label, :breadth, :close, :sma50, :sma200)
                    ON CONFLICT (pulse_date) DO UPDATE SET
                        score = EXCLUDED.score, label = EXCLUDED.label,
                        breadth_pct = EXCLUDED.breadth_pct, spy_close = EXCLUDED.spy_close,
                        spy_sma50 = EXCLUDED.spy_sma50, spy_sma200 = EXCLUDED.spy_sma200
                """),
                {
                    "d": as_of, "score": pulse.score, "label": pulse.label,
                    "breadth": pulse.breadth_pct, "close": pulse.spy_close,
                    "sma50": pulse.spy_sma50, "sma200": pulse.spy_sma200,
                },
            )
            await session.commit()
    except Exception as exc:
        logger.warning("log_market_pulse failed (non-fatal): %s", exc)


# ── Trade outcome sync ────────────────────────────────────────────────────────

async def sync_trade_outcomes() -> int:
    """Backfill trade_outcomes for closed trades missing a row. Returns count written."""
    written = 0
    async with async_session_factory() as session:
        await _ensure_tables(session)
        await session.commit()

        rows = (await session.execute(
            select(PaperTrade, Suggestion)
            .join(Suggestion, PaperTrade.suggestion_id == Suggestion.id)
            .outerjoin(TradeOutcome, TradeOutcome.trade_id == PaperTrade.id)
            .where(PaperTrade.is_open == False, TradeOutcome.id == None)
        )).all()

        if not rows:
            return 0

        for trade, sugg in rows:
            try:
                outcome = await _build_outcome(session, trade, sugg)
                session.add(outcome)
                written += 1
            except Exception as exc:
                logger.warning("outcome build failed for trade #%d: %s", trade.id, exc)

        await session.commit()

    if written:
        logger.info("sync_trade_outcomes: %d outcome row(s) written", written)
    return written


async def _build_outcome(session, trade: PaperTrade, sugg: Suggestion) -> TradeOutcome:
    exit_d = trade.exit_date or date.today()
    holding = (exit_d - trade.entry_date).days

    cost = Decimal(str(trade.entry_price)) * trade.shares
    pnl = Decimal(str(trade.realized_pnl)) if trade.realized_pnl is not None else None
    return_pct = (
        round(float(pnl / cost * 100), 4) if pnl is not None and cost > 0 else None
    )

    # R-multiple: pnl relative to the ORIGINAL planned risk (entry − initial stop)
    initial_stop = trade.original_stop if trade.original_stop is not None else trade.stop_loss
    risk_ps = abs(Decimal(str(trade.entry_price)) - Decimal(str(initial_stop)))
    total_risk = risk_ps * trade.shares
    r_multiple = (
        round(float(pnl / total_risk), 4) if pnl is not None and total_risk > 0 else None
    )

    # T2 screener context (same symbol + signal date), null for T1
    t2 = None
    if sugg.tier == "T2":
        t2 = (await session.execute(
            select(T2Scan).where(
                T2Scan.symbol == trade.symbol, T2Scan.scan_date == sugg.as_of_date
            )
        )).scalar_one_or_none()

    # Market pulse as of entry day
    pulse = (await session.execute(
        select(MarketPulseLog).where(MarketPulseLog.pulse_date == trade.entry_date)
    )).scalar_one_or_none()

    return TradeOutcome(
        trade_id=trade.id,
        symbol=trade.symbol,
        tier=sugg.tier,
        direction=trade.direction,
        entry_date=trade.entry_date,
        exit_date=exit_d,
        holding_days=holding,
        exit_reason=trade.exit_reason,
        entry_price=trade.entry_price,
        exit_price=trade.exit_price,
        shares=trade.shares,
        realized_pnl=trade.realized_pnl,
        return_pct=return_pct,
        r_multiple=r_multiple,
        levels_adjusted=trade.levels_updated_at is not None,
        confidence_score=sugg.confidence_score,
        ta_score=sugg.ta_score,
        sentiment_score=sugg.sentiment_score,
        pattern_score=sugg.pattern_score,
        t2_score=float(t2.t2_score) if t2 else None,
        t2_rvol=float(t2.rvol) if t2 else None,
        t2_signal_tier=t2.signal_tier if t2 else None,
        news_verdict=t2.news_verdict if t2 else None,
        pulse_score=pulse.score if pulse else None,
        pulse_label=pulse.label if pulse else None,
        breadth_pct=float(pulse.breadth_pct) if pulse and pulse.breadth_pct is not None else None,
    )
