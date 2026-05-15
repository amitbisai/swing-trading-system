"""
Create all tables from db.models (dev/staging only).
For production, use Alembic migrations.
Run from repo root: python scripts/setup_db.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))


async def setup() -> None:
    from db.models import Base
    from db.session import engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("All tables created.")


if __name__ == "__main__":
    asyncio.run(setup())
