"""
Financial Analysis Agent — on-demand fundamental snapshot for any ticker.

Design rationale
----------------
The "AMBA problem": a stock can look perfect on TA (high RVOL, breakout,
uptrend) yet be days away from an earnings release that tanks it -20%.
This agent surfaces that risk BEFORE a position is entered.

Data sources
------------
  • yfinance  ticker.info         — price, market cap, PE, margins, growth, analyst
  • yfinance  ticker.calendar      — next earnings date (most reliable free source)
  • yfinance  ticker.quarterly_income_stmt — last 4 quarters of revenue / net income
  • Claude (claude-sonnet-4-6)    — 2-sentence swing-trade assessment

Trade readiness tiers
---------------------
  AVOID   — earnings ≤ 7 days away  OR  ≥ 2 red-flag conditions
  CAUTION — earnings 8-14 days away  OR  1 red-flag condition
  GO      — no material flags

Run standalone:
    cd backend && python -m agents.financial_agent AMBA NVDA TSLA
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd
import yfinance as yf
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

from agents.fin_models import EarningsEvent, FinancialSummary, QuarterlyResult
from config import settings

logger = logging.getLogger(__name__)

_MAX_QUARTERS = 4


# ── yfinance helpers (sync, run in executor) ──────────────────────────────────

def _fetch_info(symbol: str) -> dict[str, Any]:
    """Fetch ticker.info — returns empty dict on failure."""
    try:
        t = yf.Ticker(symbol)
        return t.info or {}
    except Exception as exc:
        logger.warning("financial_agent: yfinance info failed for %s: %s", symbol, exc)
        return {}


def _fetch_calendar(symbol: str) -> pd.DataFrame | None:
    """Fetch ticker.calendar — returns None on failure."""
    try:
        t = yf.Ticker(symbol)
        cal = t.calendar
        if isinstance(cal, pd.DataFrame) and not cal.empty:
            return cal
        return None
    except Exception as exc:
        logger.warning("financial_agent: calendar failed for %s: %s", symbol, exc)
        return None


def _fetch_quarterly(symbol: str) -> pd.DataFrame | None:
    """Fetch quarterly income statement — returns None on failure."""
    try:
        t = yf.Ticker(symbol)
        stmt = t.quarterly_income_stmt
        if isinstance(stmt, pd.DataFrame) and not stmt.empty:
            return stmt
        return None
    except Exception as exc:
        logger.warning("financial_agent: quarterly_income_stmt failed for %s: %s", symbol, exc)
        return None


# ── Earnings date parsing ─────────────────────────────────────────────────────

def _parse_earnings(calendar: pd.DataFrame | None) -> EarningsEvent | None:
    """
    Extract the next earnings date from yfinance calendar.

    The calendar DataFrame structure varies by yfinance version — we try
    multiple known layouts gracefully.
    """
    if calendar is None:
        return None

    try:
        earnings_date: date | None = None

        # Layout A: single-column DataFrame with row index "Earnings Date"
        if "Earnings Date" in calendar.index:
            val = calendar.loc["Earnings Date"].iloc[0]
            if pd.notna(val):
                earnings_date = pd.Timestamp(val).date()

        # Layout B: row-oriented with "Earnings Date" as first-column value
        elif "Earnings Date" in calendar.columns:
            val = calendar["Earnings Date"].iloc[0]
            if pd.notna(val):
                earnings_date = pd.Timestamp(val).date()

        # Layout C: new yfinance format — dict-like with "Earnings Date" key
        elif hasattr(calendar, "to_dict"):
            d = calendar.to_dict()
            for key in d:
                if "Earnings" in str(key):
                    first_val = list(d[key].values())[0] if d[key] else None
                    if first_val and pd.notna(first_val):
                        earnings_date = pd.Timestamp(first_val).date()
                    break

        if earnings_date is None:
            return None

        today = date.today()
        # Only surface future earnings (or very recent — within last 2 days)
        days_until = (earnings_date - today).days
        if days_until < -2:
            return None   # past earnings, not relevant

        return EarningsEvent(
            date_str=earnings_date.isoformat(),
            days_until=days_until,
        )

    except Exception as exc:
        logger.debug("financial_agent: earnings parse error: %s", exc)
        return None


# ── Quarterly results parsing ─────────────────────────────────────────────────

def _parse_quarterly(stmt: pd.DataFrame | None) -> list[QuarterlyResult]:
    """Extract last 4 quarters of revenue + net income."""
    if stmt is None:
        return []

    results: list[QuarterlyResult] = []
    try:
        # Columns are dates (most recent first), rows are line items
        cols = stmt.columns[:_MAX_QUARTERS]   # last 4 quarters

        revenue_row: pd.Series | None = None
        gross_row: pd.Series | None = None
        net_row: pd.Series | None = None

        for idx in stmt.index:
            idx_str = str(idx).lower()
            if "total revenue" in idx_str:
                revenue_row = stmt.loc[idx]
            elif "gross profit" in idx_str:
                gross_row = stmt.loc[idx]
            elif "net income" in idx_str and net_row is None:
                net_row = stmt.loc[idx]

        for col in cols:
            period = str(col)[:10]  # YYYY-MM-DD
            rev = float(revenue_row[col]) if revenue_row is not None and pd.notna(revenue_row[col]) else None
            gp  = float(gross_row[col])   if gross_row  is not None and pd.notna(gross_row[col])  else None
            ni  = float(net_row[col])     if net_row    is not None and pd.notna(net_row[col])    else None

            results.append(QuarterlyResult(period=period, revenue=rev, gross_profit=gp, net_income=ni))

    except Exception as exc:
        logger.debug("financial_agent: quarterly parse error: %s", exc)

    return results


# ── Risk flag detection ───────────────────────────────────────────────────────

def _compute_risk_flags(
    next_earnings: EarningsEvent | None,
    info: dict[str, Any],
    quarterly: list[QuarterlyResult],
) -> list[str]:
    flags: list[str] = []

    # ── Earnings proximity ─────────────────────────────────────────────────────
    if next_earnings and next_earnings.days_until is not None:
        d = next_earnings.days_until
        if d <= 7:
            flags.append(f"🔴 Earnings in {d} day(s) — high gap risk")
        elif d <= 14:
            flags.append(f"🟠 Earnings in {d} days — consider waiting")

    # ── Revenue trend ──────────────────────────────────────────────────────────
    rev_growth = info.get("revenueGrowth")  # TTM YoY
    if rev_growth is not None and rev_growth < -0.05:
        flags.append(f"🔴 Revenue declining YoY ({rev_growth:+.1%})")

    # ── Profitability ──────────────────────────────────────────────────────────
    net_margin = info.get("profitMargins")
    if net_margin is not None and net_margin < -0.05:
        flags.append(f"🔴 Unprofitable — net margin {net_margin:.1%}")

    # ── Debt ───────────────────────────────────────────────────────────────────
    de = info.get("debtToEquity")
    if de is not None and de > 200:   # yfinance returns this as percentage points
        flags.append(f"🟡 High debt/equity ({de/100:.1f}×)")

    # ── Short interest ────────────────────────────────────────────────────────
    short_ratio = info.get("shortRatio")
    if short_ratio is not None and short_ratio > 5:
        flags.append(f"🟡 High short ratio ({short_ratio:.1f} days to cover)")

    # ── Valuation ─────────────────────────────────────────────────────────────
    fwd_pe = info.get("forwardPE")
    if fwd_pe is not None and fwd_pe > 60:
        flags.append(f"🟠 Richly valued — forward PE {fwd_pe:.0f}×")

    # ── Latest quarter loss check ─────────────────────────────────────────────
    if quarterly:
        latest = quarterly[0]
        if latest.net_income is not None and latest.net_income < 0:
            loss_m = abs(latest.net_income) / 1_000_000
            flags.append(f"🔴 Latest quarter net loss (${loss_m:.0f}M)")

    return flags


# ── Trade readiness ───────────────────────────────────────────────────────────

def _trade_readiness(flags: list[str], next_earnings: EarningsEvent | None) -> str:
    """
    Return "GO", "CAUTION", or "AVOID" based on flag count and earnings proximity.
    Hard AVOID for imminent earnings regardless of flag count.
    """
    # Hard AVOID: earnings within 7 days (gap risk too high)
    if next_earnings and next_earnings.days_until is not None and next_earnings.days_until <= 7:
        return "AVOID"

    red_count = sum(1 for f in flags if f.startswith("🔴"))
    any_flag = len(flags)

    if red_count >= 2 or any_flag >= 3:
        return "AVOID"
    if red_count >= 1 or any_flag >= 1:
        return "CAUTION"
    return "GO"


# ── Claude assessment ─────────────────────────────────────────────────────────

async def _claude_view(symbol: str, info: dict[str, Any], flags: list[str],
                       next_earnings: EarningsEvent | None, readiness: str) -> str:
    """
    Ask Claude for a 2-sentence swing-trade assessment.
    Falls back to a deterministic summary if the API call fails.
    """
    if not settings.anthropic_api_key:
        return f"{readiness}: Claude API key not configured."

    flags_text = "\n".join(flags) if flags else "None identified."
    earnings_text = (
        f"Next earnings: {next_earnings.date_str} ({next_earnings.days_until} days away)"
        if next_earnings else "Earnings date: unknown"
    )

    name    = info.get("longName", symbol)
    price   = info.get("currentPrice") or info.get("regularMarketPrice") or "N/A"
    mktcap  = info.get("marketCap")
    pe      = info.get("trailingPE") or info.get("forwardPE")
    rev_g   = info.get("revenueGrowth")
    sector  = info.get("sector", "Unknown")

    mktcap_str = f"${mktcap/1e9:.1f}B" if mktcap else "N/A"
    pe_str     = f"{pe:.1f}×" if pe else "N/A"
    rev_g_str  = f"{rev_g:+.1%}" if rev_g is not None else "N/A"

    prompt = (
        f"You are a professional swing trader assessing {name} ({symbol}) for a 3-14 day trade.\n\n"
        f"Key facts:\n"
        f"  Price: ${price}  |  Market cap: {mktcap_str}  |  Sector: {sector}\n"
        f"  PE: {pe_str}  |  Revenue growth YoY: {rev_g_str}\n"
        f"  {earnings_text}\n"
        f"  Trade readiness: {readiness}\n"
        f"  Risk flags:\n{flags_text}\n\n"
        "Write exactly 2 sentences: first sentence states whether this is suitable for a swing trade "
        "right now and the single most important reason. Second sentence covers the primary risk or "
        "opportunity the trader must monitor. Be direct, specific, no hedging."
    )

    try:
        llm = ChatAnthropic(
            model=settings.llm_model,
            api_key=settings.anthropic_api_key,
            max_tokens=256,
        )
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        return str(response.content).strip()
    except Exception as exc:
        logger.warning("financial_agent: Claude call failed for %s: %s", symbol, exc)
        if readiness == "GO":
            return f"{symbol} shows no major fundamental red flags for a swing trade. Monitor price action around key support/resistance levels."
        return f"{symbol} has {len(flags)} risk flag(s): {readiness} stance. Review flags before entering any position."


# ── Main entry point ──────────────────────────────────────────────────────────

async def get_financial_summary(symbol: str) -> FinancialSummary:
    """
    Build a complete FinancialSummary for *symbol*.

    Network calls are run in a thread pool (yfinance is sync).
    Claude assessment is awaited last, after all data is assembled.
    """
    sym = symbol.upper().strip()
    logger.info("financial_agent: fetching data for %s", sym)

    loop = asyncio.get_event_loop()

    # Run all three yfinance calls concurrently in the thread pool
    info, calendar, quarterly_stmt = await asyncio.gather(
        loop.run_in_executor(None, _fetch_info, sym),
        loop.run_in_executor(None, _fetch_calendar, sym),
        loop.run_in_executor(None, _fetch_quarterly, sym),
    )

    # ── Parse raw data ────────────────────────────────────────────────────────
    next_earnings = _parse_earnings(calendar)
    quarterly     = _parse_quarterly(quarterly_stmt)
    flags         = _compute_risk_flags(next_earnings, info, quarterly)
    readiness     = _trade_readiness(flags, next_earnings)

    # ── Claude assessment (async, uses already-fetched data) ──────────────────
    claude_text = await _claude_view(sym, info, flags, next_earnings, readiness)

    # ── Assemble output ────────────────────────────────────────────────────────
    price = (
        info.get("currentPrice")
        or info.get("regularMarketPrice")
        or info.get("previousClose")
        or 0.0
    )

    # Revenue growth YoY: prefer explicit field, fall back to quarterly calc
    rev_growth_yoy: float | None = info.get("revenueGrowth")
    if rev_growth_yoy is None and len(quarterly) >= 4:
        r_new = quarterly[0].revenue
        r_old = quarterly[3].revenue   # 4 quarters ago ≈ same quarter last year
        if r_new and r_old and r_old != 0:
            rev_growth_yoy = (r_new - r_old) / abs(r_old)

    fetched_at = datetime.now(timezone.utc).isoformat()

    return FinancialSummary(
        symbol          = sym,
        name            = info.get("longName") or info.get("shortName") or sym,
        sector          = info.get("sector") or "Unknown",
        industry        = info.get("industry") or "Unknown",
        price           = float(price),
        market_cap      = info.get("marketCap"),
        pe_ratio        = info.get("trailingPE"),
        forward_pe      = info.get("forwardPE"),
        revenue_growth_yoy = rev_growth_yoy,
        net_margin      = info.get("profitMargins"),
        debt_to_equity  = (info.get("debtToEquity") or 0) / 100 if info.get("debtToEquity") else None,
        free_cash_flow  = info.get("freeCashflow"),
        analyst_recommendation = info.get("recommendationKey"),
        analyst_target_price   = info.get("targetMeanPrice"),
        next_earnings   = next_earnings,
        quarterly_results = quarterly,
        trade_readiness = readiness,
        risk_flags      = flags,
        claude_view     = claude_text,
        fetched_at      = fetched_at,
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import json
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent))
    logging.basicConfig(level=logging.INFO, format="%(levelname)s — %(message)s")

    symbols = sys.argv[1:] if len(sys.argv) > 1 else ["AMBA", "NVDA"]

    async def _main() -> None:
        for sym in symbols:
            summary = await get_financial_summary(sym)
            print(f"\n{'='*60}")
            print(f"  {summary.symbol}  {summary.name}")
            print(f"  Price: ${summary.price:.2f}  |  Readiness: {summary.trade_readiness}")
            if summary.next_earnings:
                print(f"  Next earnings: {summary.next_earnings.date_str} ({summary.next_earnings.days_until}d)")
            print(f"  Flags: {summary.risk_flags or 'None'}")
            print(f"  Claude: {summary.claude_view}")

    asyncio.run(_main())
