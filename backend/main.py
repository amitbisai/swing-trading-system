from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes import analytics, paper_trades, portfolio, stocks, suggestions
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(suggestions.router,  prefix="/api/suggestions",  tags=["suggestions"])
app.include_router(paper_trades.router, prefix="/api/paper-trades",  tags=["paper-trades"])
app.include_router(portfolio.router,    prefix="/api/portfolio",     tags=["portfolio"])
app.include_router(stocks.router,       prefix="/api/stocks",        tags=["stocks"])
app.include_router(analytics.router,    prefix="/api/analytics",     tags=["analytics"])


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
