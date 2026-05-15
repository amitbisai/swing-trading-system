"""
Nightly EOD ingest job.

Fetches OHLCV for every active stock from yfinance and upserts into daily_prices.
We fetch the last 30 days so that the 20-day average volume is meaningful from
day one, even if daily_prices is empty.

Usage
-----
    # from backend/
    python -m scheduler.ingest_job

    # or trigger via Celery task (see scheduler/tasks.py)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from data.fetcher import fetch_ohlcv
from db.models import DailyPrice, Stock
from db.session import async_session_factory

logger = logging.getLogger(__name__)

# How many calendar days back to fetch.  30 gives enough history for a 20d avg.
_HISTORY_DAYS = 30


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class IngestResult:
    target_date: date
    symbols_queried: int
    symbols_fetched: int
    rows_upserted: int
    rows_skipped: int           # symbol returned data but not for target_date
    symbols_missing: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    def __str__(self) -> str:
        return (
            f"IngestResult({self.target_date}): "
            f"{self.rows_upserted} upserted, "
            f"{self.rows_skipped} skipped, "
            f"{len(self.symbols_missing)} missing — "
            f"{self.duration_seconds:.1f}s"
        )


# ── Main entry point ──────────────────────────────────────────────────────────

async def run_ingest(as_of: date | None = None) -> IngestResult:
    """
    Fetch EOD OHLCV for all active stocks and upsert into daily_prices.

    Parameters
    ----------
    as_of:
        The trading date to ingest.  Defaults to today.  Pass an explicit date
        to backfill a specific day.
    """
    t0 = time.monotonic()
    target_date = as_of or date.today()
    fetch_start = target_date - timedelta(days=_HISTORY_DAYS)

    # ── 1. Load active symbols from DB ────────────────────────────────────────
    symbols = await _load_active_symbols()
    if not symbols:
        logger.warning("No active stocks found in DB — skipping ingest")
        return IngestResult(
            target_date=target_date,
            symbols_queried=0,
            symbols_fetched=0,
            rows_upserted=0,
            rows_skipped=0,
            duration_seconds=time.monotonic() - t0,
        )

    logger.info(
        "Starting ingest for %s — fetching %d symbols (%s → %s)",
        target_date, len(symbols), fetch_start, target_date,
    )

    # ── 2. Bulk fetch from yfinance ───────────────────────────────────────────
    data = await fetch_ohlcv(symbols, fetch_start, target_date)

    missing = sorted(set(symbols) - set(data.keys()))
    if missing:
        logger.warning("No data returned for %d symbol(s): %s", len(missing), missing)

    # ── 3. Upsert into daily_prices ───────────────────────────────────────────
    upserted = 0
    skipped = 0

    async with async_session_factory() as session:
        for symbol, df in data.items():
            # Normalise index to plain date objects for comparison
            try:
                df.index = df.index.normalize().date  # type: ignore[attr-defined]
            except AttributeError:
                import pandas as pd
                df.index = pd.to_datetime(df.index).normalize().map(lambda ts: ts.date())

            if target_date not in df.index:
                logger.debug("%s: target date %s not in returned data", symbol, target_date)
                skipped += 1
                continue

            row = df.loc[target_date]

            stmt = (
                insert(DailyPrice)
                .values(
                    symbol=symbol,
                    price_date=target_date,
                    open=_to_decimal(row["Open"]),
                    high=_to_decimal(row["High"]),
                    low=_to_decimal(row["Low"]),
                    close=_to_decimal(row["Close"]),
                    adj_close=_to_decimal(row["AdjClose"]),
                    volume=int(row["Volume"]),
                )
                .on_conflict_do_update(
                    index_elements=["symbol", "price_date"],
                    set_={
                        "open": _to_decimal(row["Open"]),
                        "high": _to_decimal(row["High"]),
                        "low": _to_decimal(row["Low"]),
                        "close": _to_decimal(row["Close"]),
                        "adj_close": _to_decimal(row["AdjClose"]),
                        "volume": int(row["Volume"]),
                    },
                )
            )
            await session.execute(stmt)
            upserted += 1

        await session.commit()

    duration = time.monotonic() - t0
    result = IngestResult(
        target_date=target_date,
        symbols_queried=len(symbols),
        symbols_fetched=len(data),
        rows_upserted=upserted,
        rows_skipped=skipped,
        symbols_missing=missing,
        duration_seconds=duration,
    )
    logger.info(str(result))
    return result


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _load_active_symbols() -> list[str]:
    async with async_session_factory() as session:
        rows = await session.execute(
            select(Stock.symbol).where(Stock.is_active == True).order_by(Stock.symbol)
        )
        return [r[0] for r in rows]


def _to_decimal(value: object) -> Decimal:
    return Decimal(str(round(float(value), 4)))


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent))
    result = asyncio.run(run_ingest())
    print(result)
