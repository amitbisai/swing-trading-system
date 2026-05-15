import asyncio

from celery import Celery

from config import settings

celery_app = Celery(
    "swing_trading",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
)


@celery_app.task(name="tasks.run_nightly_ingest")
def run_nightly_ingest() -> dict:
    from scheduler.ingest_job import run_ingest

    result = asyncio.run(run_ingest())
    return {
        "status": "ok",
        "target_date": result.target_date.isoformat(),
        "upserted": result.rows_upserted,
        "skipped": result.rows_skipped,
        "missing": result.symbols_missing,
        "duration_seconds": result.duration_seconds,
    }


@celery_app.task(name="tasks.run_nightly_agents")
def run_nightly_agents() -> dict:
    from datetime import date

    from agents.orchestrator import run_orchestrator
    from paper_trading.engine import accept_suggestions, process_eod

    async def _run():
        results = await run_orchestrator()
        today = date.today()
        opened = await accept_suggestions(today)
        await process_eod(today)
        return len(results), opened

    suggestions, opened = asyncio.run(_run())
    return {"status": "ok", "suggestions_generated": suggestions, "trades_opened": opened}
