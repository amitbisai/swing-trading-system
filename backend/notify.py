"""
Telegram notifications — the nightly heartbeat.

Every job outcome is pushed to the user's Telegram so silent failures are
impossible: a ❌ message means the run failed with that error, and NO message
by ~4 AM IST means the process was killed outright (SIGKILL can't be caught).

Best-effort by design: if the token/chat id are unset (or still the
.env.example placeholders) or Telegram is unreachable, we log and move on —
notifications must never be able to break a trading run.

One-time setup:
  1. Telegram → @BotFather → /newbot → copy the token
  2. Message your new bot once (say "hi"), then open
     https://api.telegram.org/bot<TOKEN>/getUpdates and copy chat.id
  3. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID on the Railway services
"""

from __future__ import annotations

import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)


def _configured() -> bool:
    token = settings.telegram_bot_token
    chat = settings.telegram_chat_id
    if not token or not chat:
        return False
    if token.startswith("your-") or chat.startswith("your-"):
        return False   # .env.example placeholders
    return True


async def send_telegram(text: str) -> bool:
    """Send *text* to the configured chat. Returns True on success."""
    if not _configured():
        logger.debug("Telegram not configured — notification skipped")
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                json={
                    "chat_id": settings.telegram_chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
            resp.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("Telegram notification failed (non-fatal): %s", exc)
        return False
