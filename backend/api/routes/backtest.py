"""
Backtest API — run the strategy replay from the frontend.

Design constraints:
  * The simulator mutates global `settings` for overrides and is CPU/memory
    heavy, so exactly ONE backtest may run at a time (409 otherwise).
  * Runs in a worker thread (the simulation is synchronous pandas code);
    the frontend polls GET /status every few seconds.
  * The last completed result is kept in process memory — it survives until
    the next run or a service restart (results are also reproducible from
    the same parameters, so nothing is lost).
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()

_LOCK = threading.Lock()
_STATE: dict = {
    "running": False,
    "stage": None,          # current progress message
    "params": None,
    "started_at": None,
    "finished_at": None,
    "result": None,         # summary dict from run_backtest_programmatic
    "error": None,
}


class BacktestRequest(BaseModel):
    start: date | None = None                     # default: 1 year ago
    end: date | None = None                       # default: today
    top_n: int = Field(default=5, ge=0, le=50)
    min_confidence: int = Field(default=63, ge=0, le=100)
    sample: int = Field(default=150, ge=20, le=250,
                        description="Universe subsample size (capped to protect memory)")
    exit_mode: str = Field(default="intrabar", pattern="^(intrabar|close)$")
    long_only: bool = True
    # Optional strategy overrides
    atr_stop_mult: float | None = Field(default=None, ge=0.5, le=6.0)
    atr_target_mult: float | None = Field(default=None, ge=0.5, le=10.0)
    max_holding_days: int | None = Field(default=None, ge=0, le=60)
    max_daily_deployment_pct: float | None = Field(default=None, ge=0.05, le=1.0)
    risk_per_trade_pct: float | None = Field(default=None, ge=0.001, le=0.05)


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_in_thread(params: BacktestRequest, start: date, end: date) -> None:
    """Worker: executes the backtest and stores the outcome in _STATE."""
    from backtest.run_backtest import run_backtest_programmatic

    def progress(msg: str) -> None:
        _STATE["stage"] = msg

    overrides = {
        k: v for k, v in {
            "atr_stop_mult": params.atr_stop_mult,
            "atr_target_mult": params.atr_target_mult,
            "max_holding_days": params.max_holding_days,
            "max_daily_deployment_pct": params.max_daily_deployment_pct,
            "risk_per_trade_pct": params.risk_per_trade_pct,
        }.items() if v is not None
    }

    try:
        result = run_backtest_programmatic(
            start=start, end=end,
            top_n=params.top_n, min_confidence=params.min_confidence,
            sample=params.sample, exit_mode=params.exit_mode,
            long_only=params.long_only, overrides=overrides,
            progress=progress,
        )
        if "error" in result:
            _STATE["error"] = result["error"]
        else:
            _STATE["result"] = result
    except Exception as exc:
        logger.exception("backtest run failed")
        _STATE["error"] = str(exc)
    finally:
        _STATE["running"] = False
        _STATE["stage"] = None
        _STATE["finished_at"] = _ts()
        _LOCK.release()


@router.post("/run")
async def start_backtest(body: BacktestRequest) -> dict:
    end = body.end or date.today()
    start = body.start or (end - timedelta(days=365))
    if start >= end:
        raise HTTPException(status_code=422, detail="start must be before end")
    if (end - start).days > 1100:
        raise HTTPException(status_code=422, detail="range too long — max ~3 years")

    if not _LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A backtest is already running")

    _STATE.update({
        "running": True,
        "stage": "starting…",
        "params": body.model_dump(mode="json") | {"start": start.isoformat(), "end": end.isoformat()},
        "started_at": _ts(),
        "finished_at": None,
        "result": None,
        "error": None,
    })

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _run_in_thread, body, start, end)

    return {"data": {"started": True}, "error": None, "timestamp": _ts()}


@router.get("/status")
async def backtest_status() -> dict:
    return {
        "data": {
            "running": _STATE["running"],
            "stage": _STATE["stage"],
            "params": _STATE["params"],
            "started_at": _STATE["started_at"],
            "finished_at": _STATE["finished_at"],
            "result": _STATE["result"],
            "error": _STATE["error"],
        },
        "error": None,
        "timestamp": _ts(),
    }
