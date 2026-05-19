"""
Nightly EOD ingest job — standalone, Railway-deployable.

Fetches the last 30 days of OHLCV data for every active stock from yfinance
and upserts into the daily_prices table in Supabase (PostgreSQL).

The 30-day window ensures the 20-day average volume is meaningful from day one,
even on a fresh database. avg_volume_20d is computed and logged per row but is
not stored (daily_prices schema has no such column); it is re-derived on demand
by the TA agent from the raw OHLCV history.

Usage
-----
    python backend/jobs/ingest.py               # ingest today's close
    python backend/jobs/ingest.py 2026-05-14    # backfill a specific date
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from dotenv import load_dotenv
import pandas as pd
import yfinance as yf
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# ── Load .env before anything else ───────────────────────────────────────────
# Walk up from this file's location to find .env (works from any cwd)
for _candidate in [
    Path(__file__).parent,
    Path(__file__).parent.parent,
    Path(__file__).parent.parent.parent,
]:
    _dotenv_path = _candidate / ".env"
    if _dotenv_path.exists():
        load_dotenv(_dotenv_path)
        break

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("ingest")

# ── Config ────────────────────────────────────────────────────────────────────

_RAW_URL = os.environ.get("DATABASE_URL", "")
if not _RAW_URL:
    log.error("DATABASE_URL is not set — add it to your .env file and retry.")
    sys.exit(1)

# Normalise to asyncpg dialect regardless of what was supplied
DATABASE_URL = (
    _RAW_URL
    .replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    .replace("postgres://", "postgresql+asyncpg://")
)
if not DATABASE_URL.startswith("postgresql+asyncpg://"):
    # bare "postgresql://" case
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

HISTORY_DAYS = 30   # calendar days to fetch (ensures 20-bar rolling avg has data)
BATCH_SIZE   = 100  # tickers per yfinance call (keeps URL length safe)


# ── DB helpers ────────────────────────────────────────────────────────────────

def _make_session_factory():
    engine = create_async_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        # statement_cache_size=0 is required when connecting through Supabase's
        # PgBouncer (transaction mode), which doesn't support prepared statements.
        connect_args={"statement_cache_size": 0, "command_timeout": 60},
    )
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


def _to_decimal(value: object) -> Decimal | None:
    try:
        f = float(value)  # type: ignore[arg-type]
        if f != f:         # NaN check
            return None
        return Decimal(str(round(f, 4)))
    except (TypeError, ValueError, InvalidOperation):
        return None


async def _load_active_symbols(session: AsyncSession) -> list[str]:
    result = await session.execute(
        text("SELECT symbol FROM stocks WHERE is_active = true ORDER BY symbol")
    )
    return [row[0] for row in result]


# ── yfinance fetch ────────────────────────────────────────────────────────────

def _fetch_batch(
    tickers: list[str],
    start: date,
    end: date,
) -> dict[str, pd.DataFrame]:
    """
    Download OHLCV for a batch of tickers via yfinance.
    Returns dict[symbol → DataFrame] with columns:
        Open, High, Low, Close, AdjClose, Volume, avg_volume_20d
    Silently drops tickers that returned no usable data.
    """
    if not tickers:
        return {}

    raw = yf.download(
        tickers=tickers,
        start=start.isoformat(),
        # yfinance end date is exclusive, add 1 day to include target_date
        end=(end + timedelta(days=1)).isoformat(),
        auto_adjust=True,
        progress=False,
        threads=True,
    )

    if raw.empty:
        return {}

    results: dict[str, pd.DataFrame] = {}

    def _process(df: pd.DataFrame, symbol: str) -> None:
        # Rename "Adj Close" → "AdjClose" if present; fall back to Close
        df = df.copy()
        if "Adj Close" in df.columns:
            df = df.rename(columns={"Adj Close": "AdjClose"})
        if "AdjClose" not in df.columns:
            df["AdjClose"] = df["Close"]

        df = df.dropna(subset=["Close"])
        if df.empty:
            return

        df["avg_volume_20d"] = (
            df["Volume"].rolling(window=20, min_periods=1).mean().round(0)
        )
        results[symbol] = df

    if len(tickers) == 1:
        _process(raw, tickers[0])
    else:
        # Multi-ticker: MultiIndex columns — (field, symbol)
        for symbol in tickers:
            try:
                df = raw.xs(symbol, axis=1, level=1)
            except KeyError:
                continue
            _process(df, symbol)

    return results


# ── Upsert ────────────────────────────────────────────────────────────────────

_UPSERT_SQL = text("""
    INSERT INTO daily_prices
        (symbol, price_date, open, high, low, close, adj_close, volume)
    VALUES
        (:symbol, :price_date, :open, :high, :low, :close, :adj_close, :volume)
    ON CONFLICT (symbol, price_date) DO UPDATE SET
        open      = EXCLUDED.open,
        high      = EXCLUDED.high,
        low       = EXCLUDED.low,
        close     = EXCLUDED.close,
        adj_close = EXCLUDED.adj_close,
        volume    = EXCLUDED.volume
""")


async def _upsert_symbol(
    session: AsyncSession,
    symbol: str,
    df: pd.DataFrame,
    target_date: date,
) -> bool:
    """
    Write the row for target_date into daily_prices.
    Returns True if written, False if target_date not present in df.
    """
    # Normalise DatetimeIndex to plain date objects
    try:
        idx = df.index.normalize().date  # type: ignore[attr-defined]
    except AttributeError:
        idx = pd.to_datetime(df.index).normalize().map(lambda ts: ts.date())

    df = df.copy()
    df.index = idx

    if target_date not in df.index:
        return False

    row = df.loc[target_date]

    params = {
        "symbol":     symbol,
        "price_date": target_date,
        "open":       _to_decimal(row.get("Open")),
        "high":       _to_decimal(row.get("High")),
        "low":        _to_decimal(row.get("Low")),
        "close":      _to_decimal(row.get("Close")),
        "adj_close":  _to_decimal(row.get("AdjClose", row.get("Close"))),
        "volume":     int(row.get("Volume") or 0),
    }

    # Log avg_volume_20d for visibility even though it isn't stored
    avg20 = _to_decimal(row.get("avg_volume_20d"))
    if avg20:
        log.debug("%s  close=%.2f  vol=%d  avg20d_vol=%.0f",
                  symbol, float(params["close"] or 0), params["volume"], float(avg20))

    if params["close"] is None:
        return False

    await session.execute(_UPSERT_SQL, params)
    return True


# ── Main ──────────────────────────────────────────────────────────────────────

async def run(target_date: date | None = None) -> None:
    target_date = target_date or date.today()
    fetch_start = target_date - timedelta(days=HISTORY_DAYS)

    log.info("=" * 60)
    log.info("Nightly ingest  |  target: %s  |  window: %s -> %s",
             target_date, fetch_start, target_date)
    log.info("=" * 60)

    engine, Session = _make_session_factory()

    succeeded:  list[str]       = []
    skipped:    list[str]       = []   # fetched but target_date absent (holiday/weekend)
    failed:     dict[str, str]  = {}   # symbol → error reason

    try:
        async with Session() as session:
            symbols = await _load_active_symbols(session)

        if not symbols:
            log.error("No active stocks found. Run scripts/seed_stocks.py first.")
            return

        log.info("Loaded %d active symbols from DB", len(symbols))
        total_batches = (len(symbols) + BATCH_SIZE - 1) // BATCH_SIZE

        for batch_idx, batch_start in enumerate(range(0, len(symbols), BATCH_SIZE), 1):
            batch = symbols[batch_start : batch_start + BATCH_SIZE]
            log.info("Batch %d/%d — fetching %d tickers from yfinance…",
                     batch_idx, total_batches, len(batch))

            # ── fetch ──────────────────────────────────────────────────────
            try:
                data = _fetch_batch(batch, fetch_start, target_date)
            except Exception as exc:
                log.error("yfinance fetch failed for batch %d: %s", batch_idx, exc)
                for sym in batch:
                    failed[sym] = f"batch download error: {exc}"
                continue

            no_data = sorted(set(batch) - set(data))
            if no_data:
                log.warning("%d tickers returned no data: %s", len(no_data), no_data)
                for sym in no_data:
                    failed[sym] = "no data returned by yfinance (delisted or API error)"

            # ── upsert ─────────────────────────────────────────────────────
            async with Session() as session:
                for symbol in batch:
                    if symbol not in data:
                        continue
                    try:
                        written = await _upsert_symbol(session, symbol, data[symbol], target_date)
                        if written:
                            succeeded.append(symbol)
                        else:
                            log.debug("%s: %s not in returned data (holiday/weekend?)",
                                      symbol, target_date)
                            skipped.append(symbol)
                    except Exception as exc:
                        log.warning("%s upsert failed: %s", symbol, exc)
                        failed[symbol] = str(exc)

                try:
                    await session.commit()
                    log.info("Batch %d/%d committed — %d rows written so far",
                             batch_idx, total_batches, len(succeeded))
                except Exception as exc:
                    log.error("Commit failed for batch %d: %s — rolling back", batch_idx, exc)
                    await session.rollback()

    finally:
        await engine.dispose()

    # ── Summary ───────────────────────────────────────────────────────────────
    total = len(symbols)
    print()
    print("=" * 60)
    print(f"  Ingest complete  —  {target_date}")
    print("=" * 60)
    print(f"  Total symbols  : {total}")
    print(f"  OK  Upserted   : {len(succeeded)}")
    print(f"  --  Skipped    : {len(skipped)}  (target date absent - holiday/weekend)")
    print(f"  !!  Failed     : {len(failed)}")
    if failed:
        print()
        print("  Failed symbols:")
        for sym, reason in sorted(failed.items()):
            print(f"    {sym:<8}  {reason}")
    print("=" * 60)

    if failed and len(failed) == total:
        log.error("Every ticker failed — check DATABASE_URL and network.")
        sys.exit(1)


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    _target: date | None = None
    if len(sys.argv) > 1:
        try:
            _target = date.fromisoformat(sys.argv[1])
        except ValueError:
            log.error("Bad date argument %r — expected YYYY-MM-DD", sys.argv[1])
            sys.exit(1)
    asyncio.run(run(_target))
