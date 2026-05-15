"""
Convenience wrapper — delegates to backend/db/seed.py.
Run from the repo root: python scripts/seed_stocks.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from db.seed import seed  # noqa: E402

if __name__ == "__main__":
    asyncio.run(seed())
