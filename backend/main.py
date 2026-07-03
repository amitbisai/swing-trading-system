from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes import (
    analytics,
    financials,
    paper_trades,
    portfolio,
    prices,
    stocks,
    strategy_settings,
    suggestions,
    t1_scans,
    t2_scans,
)
from config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="Swing Trading API",
    version="0.1.0",
    description="AI-powered swing trading suggestion system — paper trading only.",
    lifespan=lifespan,
)

_origins = settings.get_cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=("*" not in _origins),
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(suggestions.router,  prefix="/api/suggestions",  tags=["suggestions"])
app.include_router(paper_trades.router, prefix="/api/paper-trades",  tags=["paper-trades"])
app.include_router(portfolio.router,    prefix="/api/portfolio",     tags=["portfolio"])
app.include_router(stocks.router,       prefix="/api/stocks",        tags=["stocks"])
app.include_router(analytics.router,    prefix="/api/analytics",     tags=["analytics"])
app.include_router(t1_scans.router,     prefix="/api/t1-scans",      tags=["t1-scans"])
app.include_router(t2_scans.router,     prefix="/api/t2-scans",      tags=["t2-scans"])
app.include_router(prices.router,       prefix="/api/prices",        tags=["prices"])
app.include_router(financials.router,   prefix="/api/financials",    tags=["financials"])
app.include_router(strategy_settings.router, prefix="/api/strategy-settings", tags=["strategy-settings"])


# ── Global exception handler — keeps the { data, error, timestamp } envelope ─

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "data": None,
            "error": str(exc),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health", tags=["meta"])
async def health():
    return {
        "data": {"status": "ok"},
        "error": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
