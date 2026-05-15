"""
Celery Beat schedule.
Start with: celery -A scheduler.tasks.celery_app beat --loglevel=info
Worker:     celery -A scheduler.tasks.celery_app worker --loglevel=info
"""
from celery.schedules import crontab

from scheduler.tasks import celery_app

celery_app.conf.beat_schedule = {
    # EOD ingest — 30 min after NYSE close (4:30 PM ET = 21:30 UTC, Mon–Fri)
    "nightly-ingest": {
        "task": "tasks.run_nightly_ingest",
        "schedule": crontab(hour=21, minute=30, day_of_week="1-5"),
    },
    # Agent run — 60 min after close, after data is ready
    "nightly-agents": {
        "task": "tasks.run_nightly_agents",
        "schedule": crontab(hour=22, minute=0, day_of_week="1-5"),
    },
}
