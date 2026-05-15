"""
Thin compatibility shim — delegates to scheduler.ingest_job.

Run manually: python -m data.ingest
"""
import asyncio
from datetime import date


async def ingest_daily_prices(as_of: date | None = None) -> None:
    from scheduler.ingest_job import run_ingest
    result = await run_ingest(as_of)
    print(result)


if __name__ == "__main__":
    asyncio.run(ingest_daily_prices())
