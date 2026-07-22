"""
Nightly agents entry point — standalone, Railway-deployable.

Runs the full LangGraph pipeline:
  scan_node → analyze_node (TA ‖ Sentiment ‖ Pattern) → synthesize_node

Writes Suggestion rows to Supabase. Idempotent — running twice on the
same day replaces today's suggestions rather than duplicating them.

Usage
-----
    python backend/jobs/run_agents.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# ── Ensure backend/ is on sys.path before any internal imports ────────────────
_BACKEND_DIR = Path(__file__).resolve().parent.parent   # .../backend/
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402
from agents.orchestrator import run_orchestrator  # noqa: E402

# ── Load .env ─────────────────────────────────────────────────────────────────
for _candidate in [
    Path(__file__).parent,
    Path(__file__).parent.parent,
    Path(__file__).parent.parent.parent,
]:
    if (_candidate / ".env").exists():
        load_dotenv(_candidate / ".env")
        break

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("run_agents")

# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    from datetime import date

    from notify import send_telegram

    log.info("=" * 60)
    log.info("Nightly agents run starting")
    log.info("=" * 60)

    try:
        suggestions = await run_orchestrator()
    except Exception as exc:
        log.error("Orchestrator failed: %s", exc, exc_info=True)
        await send_telegram(
            f"❌ <b>Nightly agents run FAILED</b>\n"
            f"Orchestrator error: <code>{str(exc)[:500]}</code>\n"
            f"Check the Railway agents Cron Runs log."
        )
        sys.exit(1)

    print()
    print("=" * 60)
    print(f"  Agents run complete — {len(suggestions)} suggestion(s)")
    print("=" * 60)
    for s in suggestions:
        print(
            f"  {s.symbol:<6}  {s.direction.value:<5}  "
            f"entry={s.entry_price:.2f}  "
            f"stop={s.stop_loss:.2f}  "
            f"target={s.target_price:.2f}  "
            f"confidence={s.confidence_score}"
        )
    print("=" * 60)

    if not suggestions:
        log.warning("No suggestions generated — check scanner and synthesizer logs above.")

    # ── Paper trading: auto-entry + EOD processing ─────────────────────────────
    # accept_suggestions opens trades from today's ACTIVE suggestions (regime
    # filter marks suggestions inactive on bear days, so nothing opens then).
    # process_eod marks all open trades to market, applies stop/target/time
    # exits, and writes the daily portfolio snapshot.
    from config import settings
    from paper_trading.engine import accept_suggestions, process_eod

    today = date.today()
    if settings.auto_entry_mode == "nightly":
        try:
            opened = await accept_suggestions(today)
            log.info("Paper trading: %d new trade(s) opened", opened)
        except Exception as exc:
            log.error("accept_suggestions failed: %s", exc, exc_info=True)
    else:
        log.info(
            "Paper trading: auto-entry deferred to the hourly intraday job "
            "(AUTO_ENTRY_MODE=intraday) — trades will open at live prices next market morning"
        )

    eod_note = "EOD ✅"
    try:
        await process_eod(today)
        log.info("Paper trading: EOD processing + portfolio snapshot complete")
    except Exception as exc:
        log.error("process_eod failed: %s", exc, exc_info=True)
        eod_note = f"EOD ❌ ({str(exc)[:120]})"

    # ── Heartbeat: success summary to Telegram ────────────────────────────────
    # If neither ✅ nor ❌ arrives by ~4 AM IST, the process was killed outright.
    t1_n = sum(1 for s in suggestions if s.tier.value == "T1")
    t2_n = len(suggestions) - t1_n
    top = ", ".join(
        f"{s.symbol} {s.confidence_score}"
        for s in sorted(suggestions, key=lambda x: -x.confidence_score)[:5]
    ) or "none"
    await send_telegram(
        f"✅ <b>Nightly run complete — {today}</b>\n"
        f"Signals: {len(suggestions)} ({t1_n} T1, {t2_n} T2)\n"
        f"Top: {top}\n"
        f"{eod_note}"
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except SystemExit:
        raise
    except Exception as exc:
        # Last-resort alert for crashes outside the guarded sections
        try:
            from notify import send_telegram
            asyncio.run(send_telegram(
                f"❌ <b>Nightly agents job CRASHED</b>\n<code>{str(exc)[:500]}</code>"
            ))
        except Exception:
            pass
        raise
