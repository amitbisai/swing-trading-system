"""Add t1_scans table — daily TA snapshots for all T1 (S&P 500) stocks.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-27 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── t1_scans ──────────────────────────────────────────────────────────────
    op.create_table(
        "t1_scans",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("scan_date", sa.Date(), nullable=False),
        # Price
        sa.Column("price", sa.Numeric(12, 4), nullable=False),
        # TA indicators
        sa.Column("rsi_14", sa.Numeric(6, 2), nullable=True),
        sa.Column("macd_hist", sa.Numeric(10, 6), nullable=True),
        sa.Column("sma_20", sa.Numeric(12, 4), nullable=True),
        sa.Column("sma_50", sa.Numeric(12, 4), nullable=True),
        sa.Column("atr_14", sa.Numeric(10, 4), nullable=True),
        sa.Column("bb_upper", sa.Numeric(12, 4), nullable=True),
        sa.Column("bb_lower", sa.Numeric(12, 4), nullable=True),
        # Volume
        sa.Column("rvol", sa.Numeric(6, 2), nullable=True),
        sa.Column("avg_volume_20d", sa.Numeric(16, 0), nullable=True),
        # Pattern
        sa.Column("support_level", sa.Numeric(12, 4), nullable=True),
        sa.Column("resistance_level", sa.Numeric(12, 4), nullable=True),
        sa.Column("patterns_detected", sa.Text(), nullable=True),
        # Scores
        sa.Column("ta_score", sa.Integer(), nullable=False),
        sa.Column("pattern_score", sa.Integer(), nullable=False),
        sa.Column("sentiment_score", sa.Integer(), nullable=False),
        sa.Column("bullish_confidence", sa.Integer(), nullable=False),
        sa.Column("bearish_confidence", sa.Integer(), nullable=False),
        sa.Column("signal_direction", sa.String(5), nullable=False),
        # Signal flag
        sa.Column("made_signal", sa.Boolean(), nullable=False, server_default=sa.false()),
        # Denormalised
        sa.Column("sector", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["symbol"], ["stocks.symbol"], name="fk_t1_scans_symbol", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("symbol", "scan_date", name="uq_t1_scans_symbol_date"),
    )
    op.create_index("ix_t1_scans_scan_date",   "t1_scans", ["scan_date"])
    op.create_index("ix_t1_scans_symbol",       "t1_scans", ["symbol"])
    op.create_index("ix_t1_scans_made_signal",  "t1_scans", ["made_signal"])


def downgrade() -> None:
    op.drop_table("t1_scans")
