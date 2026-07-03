"""
Tiny key-value settings store — lets the frontend adjust strategy knobs
(e.g. top-N entries per day) without redeploying.

Uses a raw CREATE TABLE IF NOT EXISTS on first access so no migration is
needed; values are stored as text and parsed by the caller.
"""

from __future__ import annotations

import logging

from sqlalchemy import text

from db.session import async_session_factory

logger = logging.getLogger(__name__)

_ENSURE_SQL = text("""
    CREATE TABLE IF NOT EXISTS app_settings (
        key   text PRIMARY KEY,
        value text NOT NULL
    )
""")

_GET_SQL = text("SELECT value FROM app_settings WHERE key = :key")

_SET_SQL = text("""
    INSERT INTO app_settings (key, value) VALUES (:key, :value)
    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
""")


async def get_setting(key: str, default: str | None = None) -> str | None:
    try:
        async with async_session_factory() as session:
            await session.execute(_ENSURE_SQL)
            await session.commit()
            row = (await session.execute(_GET_SQL, {"key": key})).scalar_one_or_none()
            return row if row is not None else default
    except Exception as exc:
        logger.warning("get_setting(%s) failed — using default: %s", key, exc)
        return default


async def get_int_setting(key: str, default: int) -> int:
    raw = await get_setting(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("get_int_setting(%s): bad value %r — using default %d", key, raw, default)
        return default


async def set_setting(key: str, value: str) -> None:
    async with async_session_factory() as session:
        await session.execute(_ENSURE_SQL)
        await session.execute(_SET_SQL, {"key": key, "value": value})
        await session.commit()
