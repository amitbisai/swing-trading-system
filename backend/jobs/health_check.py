"""
Database health check — run locally to verify:
  1. The DATABASE_URL connects successfully
  2. The stocks table is seeded
  3. daily_prices has recent data
  4. How many tickers have data for each of the last 5 trading dates

Usage
-----
    python backend/jobs/health_check.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# ── Load .env ────────────────────────────────────────────────────────────────
for _candidate in [
    Path(__file__).parent,
    Path(__file__).parent.parent,
    Path(__file__).parent.parent.parent,
]:
    if (_candidate / ".env").exists():
        load_dotenv(_candidate / ".env")
        break

# ── DB setup ──────────────────────────────────────────────────────────────────

_RAW_URL = os.environ.get("DATABASE_URL", "")
if not _RAW_URL:
    print("ERROR: DATABASE_URL is not set in .env")
    sys.exit(1)

DATABASE_URL = (
    _RAW_URL
    .replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    .replace("postgres://", "postgresql+asyncpg://")
)
if not DATABASE_URL.startswith("postgresql+asyncpg://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)


def _engine():
    return create_async_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        connect_args={"statement_cache_size": 0, "command_timeout": 30},
    )


# ── Checks ────────────────────────────────────────────────────────────────────

async def run() -> None:
    engine = _engine()
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ok = True

    print()
    print("=" * 62)
    print("  SwingTrader — DB Health Check")
    print(f"  {date.today()}")
    print("=" * 62)

    async with Session() as s:

        # ── 1. Connection ─────────────────────────────────────────────────
        try:
            await s.execute(text("SELECT 1"))
            _row("Connection", "OK", good=True)
        except Exception as exc:
            _row("Connection", f"FAILED  {exc}", good=False)
            print()
            print("  Cannot reach the database. Check DATABASE_URL in .env.")
            print()
            await engine.dispose()
            sys.exit(1)

        # ── 2. Stocks table ───────────────────────────────────────────────
        try:
            r = await s.execute(
                text("SELECT COUNT(*) FROM stocks WHERE is_active = true")
            )
            n_stocks = r.scalar_one()
            _row(
                "Active stocks",
                f"{n_stocks} rows" + ("" if n_stocks >= 100 else "  -- run scripts/seed_stocks.py"),
                good=n_stocks >= 100,
            )
            if n_stocks < 100:
                ok = False
        except Exception as exc:
            _row("Active stocks", f"ERROR  {exc}", good=False)
            ok = False

        # ── 3. daily_prices coverage — last 5 dates ───────────────────────
        try:
            result = await s.execute(text("""
                SELECT
                    price_date,
                    COUNT(DISTINCT symbol)  AS tickers,
                    ROUND(AVG(volume))      AS avg_volume,
                    MIN(close)              AS min_close,
                    MAX(close)              AS max_close
                FROM daily_prices
                GROUP BY price_date
                ORDER BY price_date DESC
                LIMIT 5
            """))
            rows = result.fetchall()

            if not rows:
                _row("daily_prices", "EMPTY  -- run: make ingest", good=False)
                ok = False
            else:
                latest_date   = rows[0][0]
                latest_count  = rows[0][1]
                today         = date.today()
                stale         = (today - latest_date).days > 3

                print()
                print(f"  {'Date':<12}  {'Tickers':>7}  {'Avg Vol':>12}  {'Close range':>20}")
                print(f"  {'-'*12}  {'-'*7}  {'-'*12}  {'-'*20}")
                for price_date, tickers, avg_vol, mn, mx in rows:
                    flag = "  <-- latest" if price_date == latest_date else ""
                    avg_vol_fmt = f"{int(avg_vol):,}" if avg_vol else "—"
                    print(
                        f"  {str(price_date):<12}  {tickers:>7}  {avg_vol_fmt:>12}"
                        f"  ${float(mn):>8.2f} – ${float(mx):>7.2f}{flag}"
                    )
                print()

                if stale:
                    _row(
                        "Data freshness",
                        f"STALE  latest={latest_date}  ({(today-latest_date).days}d ago)",
                        good=False,
                    )
                    ok = False
                else:
                    _row(
                        "Data freshness",
                        f"OK  latest={latest_date}",
                        good=True,
                    )

                expected = n_stocks if "n_stocks" in dir() else 147
                coverage_pct = round(latest_count / expected * 100) if expected else 0
                good_coverage = coverage_pct >= 90
                _row(
                    "Ticker coverage",
                    f"{latest_count}/{expected}  ({coverage_pct}%)",
                    good=good_coverage,
                )
                if not good_coverage:
                    ok = False

        except Exception as exc:
            _row("daily_prices", f"ERROR  {exc}", good=False)
            ok = False

        # ── 4. Suggestions table ──────────────────────────────────────────
        try:
            r = await s.execute(
                text("SELECT COUNT(*) FROM suggestions WHERE is_active = true")
            )
            n_sug = r.scalar_one()
            _row(
                "Active suggestions",
                f"{n_sug} rows" + ("  -- run: make agents" if n_sug == 0 else ""),
                good=n_sug > 0,
            )
        except Exception as exc:
            _row("Active suggestions", f"ERROR  {exc}", good=False)
            ok = False

        # ── 5. Open paper trades ──────────────────────────────────────────
        try:
            r = await s.execute(
                text("SELECT COUNT(*) FROM paper_trades WHERE is_open = true")
            )
            n_open = r.scalar_one()
            _row("Open paper trades", str(n_open), good=True)
        except Exception as exc:
            _row("Open paper trades", f"ERROR  {exc}", good=False)

    await engine.dispose()

    print()
    if ok:
        print("  RESULT:  All checks passed.")
    else:
        print("  RESULT:  One or more checks failed -- see above.")
    print("=" * 62)
    print()

    sys.exit(0 if ok else 1)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _row(label: str, value: str, *, good: bool) -> None:
    icon = "OK " if good else "!! "
    print(f"  {icon}  {label:<22}  {value}")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    asyncio.run(run())
