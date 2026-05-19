"""Add t2_scans table for nightly T2 screener results + AI news validation

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-19 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "t2_scans",
        sa.Column("id",                sa.Integer(),       primary_key=True, nullable=False),
        sa.Column("symbol",            sa.String(20),      nullable=False),
        sa.Column("scan_date",         sa.Date(),          nullable=False),
        sa.Column("signal_tier",       sa.String(1),       nullable=False),
        sa.Column("t2_score",          sa.Numeric(5, 1),   nullable=False),
        sa.Column("price",             sa.Numeric(12, 4),  nullable=False),
        sa.Column("market_cap",        sa.Numeric(20, 0),  nullable=True),
        sa.Column("rvol",              sa.Numeric(8, 2),   nullable=False),
        sa.Column("avg_volume_30d",    sa.Numeric(20, 0),  nullable=True),
        sa.Column("revenue_growth",    sa.Numeric(8, 4),   nullable=True),
        sa.Column("earnings_growth",   sa.Numeric(8, 4),   nullable=True),
        sa.Column("pct_below_52w_high",sa.Numeric(8, 4),   nullable=True),
        sa.Column("float_shares",      sa.Numeric(20, 0),  nullable=True),
        sa.Column("short_ratio",       sa.Numeric(8, 2),   nullable=True),
        sa.Column("sector",            sa.String(100),     nullable=True),
        sa.Column("industry",          sa.String(200),     nullable=True),
        sa.Column("risk_flags",        sa.Text(),          nullable=True),
        sa.Column("signal_summary",    sa.Text(),          nullable=True),
        sa.Column("catalyst_hint",     sa.String(200),     nullable=True),
        sa.Column("news_summary",      sa.Text(),          nullable=True),
        sa.Column("news_verdict",      sa.String(20),      nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["symbol"], ["stocks.symbol"], ondelete="CASCADE"),
        sa.UniqueConstraint("symbol", "scan_date", name="uq_t2_scans_symbol_date"),
    )
    op.create_index("ix_t2_scans_scan_date", "t2_scans", ["scan_date"])
    op.create_index("ix_t2_scans_symbol",    "t2_scans", ["symbol"])


def downgrade() -> None:
    op.drop_index("ix_t2_scans_symbol",    table_name="t2_scans")
    op.drop_index("ix_t2_scans_scan_date", table_name="t2_scans")
    op.drop_table("t2_scans")
