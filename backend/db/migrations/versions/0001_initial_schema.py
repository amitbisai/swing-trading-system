"""Initial schema — stocks, daily_prices, suggestions, paper_trades, daily_pnl, portfolio_snapshots

Revision ID: 0001
Revises:
Create Date: 2026-05-15 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── stocks ────────────────────────────────────────────────────────────────
    op.create_table(
        "stocks",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("sector", sa.String(100), nullable=True),
        sa.Column("exchange", sa.String(20), nullable=True),
        sa.Column("tier", sa.String(2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("symbol", name="uq_stocks_symbol"),
    )
    op.create_index("ix_stocks_symbol", "stocks", ["symbol"])

    # ── daily_prices ──────────────────────────────────────────────────────────
    op.create_table(
        "daily_prices",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("price_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(12, 4), nullable=False),
        sa.Column("high", sa.Numeric(12, 4), nullable=False),
        sa.Column("low", sa.Numeric(12, 4), nullable=False),
        sa.Column("close", sa.Numeric(12, 4), nullable=False),
        sa.Column("adj_close", sa.Numeric(12, 4), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["symbol"], ["stocks.symbol"], name="fk_daily_prices_symbol", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("symbol", "price_date", name="uq_daily_prices_symbol_date"),
    )
    op.create_index("ix_daily_prices_symbol_date", "daily_prices", ["symbol", "price_date"])

    # ── suggestions ───────────────────────────────────────────────────────────
    op.create_table(
        "suggestions",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("tier", sa.String(2), nullable=False),
        sa.Column("direction", sa.String(5), nullable=False),
        sa.Column("confidence_score", sa.Integer(), nullable=False),
        sa.Column("entry_price", sa.Numeric(12, 4), nullable=False),
        sa.Column("stop_loss", sa.Numeric(12, 4), nullable=False),
        sa.Column("target_price", sa.Numeric(12, 4), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("ta_score", sa.Integer(), nullable=False),
        sa.Column("sentiment_score", sa.Integer(), nullable=False),
        sa.Column("pattern_score", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["symbol"], ["stocks.symbol"], name="fk_suggestions_symbol", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("symbol", "as_of_date", name="uq_suggestions_symbol_date"),
    )
    op.create_index("ix_suggestions_symbol_date", "suggestions", ["symbol", "as_of_date"])
    op.create_index("ix_suggestions_as_of_date", "suggestions", ["as_of_date"])

    # ── paper_trades ──────────────────────────────────────────────────────────
    op.create_table(
        "paper_trades",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("suggestion_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("direction", sa.String(5), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("entry_price", sa.Numeric(12, 4), nullable=False),
        sa.Column("shares", sa.Integer(), nullable=False),
        sa.Column("capital_at_risk", sa.Numeric(12, 4), nullable=False),
        sa.Column("stop_loss", sa.Numeric(12, 4), nullable=False),
        sa.Column("target_price", sa.Numeric(12, 4), nullable=False),
        sa.Column("exit_date", sa.Date(), nullable=True),
        sa.Column("exit_price", sa.Numeric(12, 4), nullable=True),
        sa.Column("exit_reason", sa.String(20), nullable=True),
        sa.Column("realized_pnl", sa.Numeric(12, 4), nullable=True),
        sa.Column("is_open", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["suggestion_id"],
            ["suggestions.id"],
            name="fk_paper_trades_suggestion_id",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_paper_trades_symbol", "paper_trades", ["symbol"])
    op.create_index("ix_paper_trades_is_open", "paper_trades", ["is_open"])

    # ── daily_pnl ─────────────────────────────────────────────────────────────
    op.create_table(
        "daily_pnl",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("trade_id", sa.Integer(), nullable=False),
        sa.Column("pnl_date", sa.Date(), nullable=False),
        sa.Column("close_price", sa.Numeric(12, 4), nullable=False),
        sa.Column("unrealized_pnl", sa.Numeric(12, 4), nullable=False),
        sa.ForeignKeyConstraint(
            ["trade_id"],
            ["paper_trades.id"],
            name="fk_daily_pnl_trade_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("trade_id", "pnl_date", name="uq_daily_pnl_trade_date"),
    )
    op.create_index("ix_daily_pnl_trade_date", "daily_pnl", ["trade_id", "pnl_date"])

    # ── portfolio_snapshots ───────────────────────────────────────────────────
    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("total_capital", sa.Numeric(12, 4), nullable=False),
        sa.Column("cash_balance", sa.Numeric(12, 4), nullable=False),
        sa.Column("invested_capital", sa.Numeric(12, 4), nullable=False),
        sa.Column("unrealized_pnl", sa.Numeric(12, 4), nullable=False),
        sa.Column("realized_pnl_today", sa.Numeric(12, 4), nullable=False),
        sa.Column("cumulative_realized_pnl", sa.Numeric(12, 4), nullable=False),
        sa.Column("open_positions", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("snapshot_date", name="uq_portfolio_snapshot_date"),
    )
    op.create_index("ix_portfolio_snapshots_snapshot_date", "portfolio_snapshots", ["snapshot_date"])


def downgrade() -> None:
    op.drop_table("portfolio_snapshots")
    op.drop_table("daily_pnl")
    op.drop_table("paper_trades")
    op.drop_table("suggestions")
    op.drop_table("daily_prices")
    op.drop_table("stocks")
