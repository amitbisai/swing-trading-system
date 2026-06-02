"""
Pydantic models for the Financial Analysis agent.

Kept in a separate file so API schemas.py can import them without
pulling in the heavy yfinance / LangChain dependencies that live in
financial_agent.py.
"""

from __future__ import annotations

from pydantic import BaseModel


class EarningsEvent(BaseModel):
    date_str: str | None = None        # ISO date "YYYY-MM-DD"
    days_until: int | None = None      # negative = already passed


class QuarterlyResult(BaseModel):
    period: str                        # "YYYY-MM-DD" of period end
    revenue: float | None = None       # total revenue, USD
    gross_profit: float | None = None
    net_income: float | None = None


class FinancialSummary(BaseModel):
    symbol: str
    name: str
    sector: str
    industry: str
    price: float
    market_cap: float | None = None
    pe_ratio: float | None = None
    forward_pe: float | None = None
    revenue_growth_yoy: float | None = None   # fraction, e.g. 0.15 = +15%
    net_margin: float | None = None           # fraction
    debt_to_equity: float | None = None       # ratio, e.g. 1.2
    free_cash_flow: float | None = None       # USD
    analyst_recommendation: str | None = None # "buy" | "hold" | "sell" | etc.
    analyst_target_price: float | None = None
    next_earnings: EarningsEvent | None = None
    quarterly_results: list[QuarterlyResult] = []
    trade_readiness: str                      # "GO" | "CAUTION" | "AVOID"
    risk_flags: list[str] = []               # emoji-prefixed human-readable strings
    claude_view: str
    fetched_at: str                           # ISO datetime UTC
