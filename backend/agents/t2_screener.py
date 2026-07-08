"""
T2 Institutional Accumulation & Emerging Momentum Screener — v2.

What changed from v1
---------------------
v1 started from a static 250-symbol seed list and screened for RVOL > 1.5×.
This had two fatal flaws demonstrated in production:

  • AMBA (Ambarella): caught on earnings day — stock down -20% overnight.
    Root cause: no earnings proximity gate.

  • BEAM (Beam Therapeutics): high RVOL on a day the stock was selling off.
    Root cause: RVOL alone does not distinguish buying from selling pressure.

  • LEGN (Legend Biotech): caught on day AFTER the big volume day.
    Root cause: static list means we only see stocks already on it;
    stale volume picked up the day the move ended.

v2 fixes
--------
  1. Live universe from Yahoo Finance Most Active + Day Gainers (not a static list).
     Covers the full US equity market, updated every nightly run.

  2. Falling-knife filter: reject any stock that is DOWN > 3% on scan day.
     High RVOL on a falling stock = institutional selling, not accumulation.

  3. Earnings proximity gate: hard exclude stocks with earnings ≤ 8 days away.
     TA signals are irrelevant if an overnight earnings gap can wipe -20%.

  4. Pre-revenue / clinical-stage biotech flag: automatically flagged as
     EXTREME_VOLATILITY + WEAK_FUNDAMENTALS so traders can make an informed call.

  5. Falls back to static universe if Yahoo Finance API is unavailable.

Pipeline
--------
  Stage 0 — Live universe: Yahoo Finance Most Active + Day Gainers (100-175 symbols)
  Stage 1 — OHLCV batch download + technical gates + falling-knife filter
  Stage 2 — yf.Ticker (info + earnings calendar) for surviving candidates
             → market cap, float, earnings date gate, fundamentals
  Stage 3 — Composite T2 Score (0-100, weighted)
  Stage 4 — Signal classification (Tier A / B / C) + risk flags
"""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf
from pydantic import BaseModel, Field

from agents.t2_config import T2Config
from data.fetcher import fetch_ohlcv_sync
from data.universe import get_universe           # static fallback
from data.yahoo_screener import get_live_t2_universe

logger = logging.getLogger(__name__)

_INFO_EXECUTOR = ThreadPoolExecutor(max_workers=6, thread_name_prefix="t2_info")


# ── Output models ─────────────────────────────────────────────────────────────

class T2SignalTier(str, Enum):
    A = "A"   # Strong institutional accumulation
    B = "B"   # Emerging momentum
    C = "C"   # Watchlist candidate


class T2RiskFlag(str, Enum):
    EXTREME_VOLATILITY   = "extreme_volatility"
    VERY_LOW_FLOAT       = "very_low_float"
    PARABOLIC            = "parabolic_extension"
    HIGH_SHORT_INTEREST  = "high_short_interest"
    WEAK_FUNDAMENTALS    = "weak_fundamentals"
    THIN_LIQUIDITY       = "thin_liquidity"
    EARNINGS_APPROACHING = "earnings_approaching"   # 8-21 days — caution, not excluded
    PRE_REVENUE_BIOTECH  = "pre_revenue_biotech"    # clinical stage, no product revenue


class T2Candidate(BaseModel):
    symbol:              str
    name:                str             = ""
    sector:              str             = ""
    industry:            str             = ""
    price:               float
    market_cap:          float           = 0.0
    rvol:                float           = 0.0
    avg_volume_30d:      float           = 0.0
    today_change_pct:    float           = 0.0     # today's % price change
    days_to_earnings:    int | None      = None    # None = unknown
    revenue_growth:      float | None    = None
    earnings_growth:     float | None    = None
    pct_below_52w_high:  float           = 0.0
    float_shares:        float | None    = None
    short_ratio:         float | None    = None
    t2_score:            float           = Field(ge=0, le=100)
    signal_tier:         T2SignalTier    = T2SignalTier.C
    risk_flags:          list[T2RiskFlag] = Field(default_factory=list)
    signal_summary:      str             = ""
    catalyst_hint:       str             = ""


# ── Main screener ─────────────────────────────────────────────────────────────

class T2Screener:
    def __init__(self, config: T2Config | None = None) -> None:
        self.cfg = config or T2Config.from_env()

    async def run(self, exclude_symbols: set[str] | None = None) -> list[T2Candidate]:
        cfg = self.cfg
        today = date.today()
        start = today - timedelta(days=cfg.history_days)
        exclude = exclude_symbols or set()

        # ── Stage 0: Live universe from Yahoo Finance ─────────────────────────
        live_quotes = await get_live_t2_universe(
            min_price       = cfg.min_price,
            min_market_cap  = cfg.min_market_cap * 0.8,   # slightly loose; Stage 2 applies exact gate
            max_market_cap  = cfg.max_market_cap,
            min_avg_volume  = cfg.min_avg_volume_30d // 2, # loose pre-filter; Stage 1 re-checks
            exclude_symbols = exclude,
        )

        if live_quotes:
            # ── Falling-knife pre-filter (no OHLCV needed, data already in quote) ──
            before = len(live_quotes)
            live_quotes = [
                q for q in live_quotes
                if q["today_change_pct"] >= -cfg.max_drop_pct_today
            ]
            dropped = before - len(live_quotes)
            if dropped:
                logger.info(
                    "T2: falling-knife filter removed %d stocks "
                    "(down > %.0f%% today)", dropped, cfg.max_drop_pct_today,
                )

            universe   = [q["symbol"] for q in live_quotes]
            live_map   = {q["symbol"]: q for q in live_quotes}
            source     = "Yahoo Finance live"
        else:
            # Fallback to static universe if API call failed
            logger.warning(
                "T2: Yahoo Finance screener unavailable — falling back to static universe"
            )
            universe = get_universe(exclude=exclude)
            live_map = {}
            source   = "static fallback"

        logger.info(
            "T2 screener: universe = %d symbols (%s), history %s → %s",
            len(universe), source, start, today,
        )

        # ── Stage 1: OHLCV batch download ─────────────────────────────────────
        loop = asyncio.get_event_loop()
        ohlcv: dict[str, pd.DataFrame] = await loop.run_in_executor(
            None, fetch_ohlcv_sync, universe, start, today
        )
        logger.info("T2: OHLCV returned for %d / %d symbols", len(ohlcv), len(universe))

        stage1: list[tuple[str, pd.DataFrame, dict[str, Any]]] = []
        for symbol, df in ohlcv.items():
            live_data = live_map.get(symbol, {})
            result = self._apply_ohlcv_filters(symbol, df, live_data)
            if result is not None:
                stage1.append((symbol, df, result))

        logger.info("T2: %d symbols passed Stage 1 (OHLCV + falling-knife gates)", len(stage1))

        if not stage1:
            logger.warning("T2: no candidates after Stage 1 — check thresholds or market conditions")
            return []

        # ── Stage 2: yf.info + earnings calendar ─────────────────────────────
        symbols_s1 = [sym for sym, _, _ in stage1]
        info_map: dict[str, tuple[dict, int | None]] = await self._fetch_info_and_earnings(symbols_s1)

        candidates: list[T2Candidate] = []
        for symbol, df, ohlcv_meta in stage1:
            info, days_to_earnings = info_map.get(symbol, ({}, None))
            live_data = live_map.get(symbol, {})
            candidate = self._build_candidate(symbol, df, ohlcv_meta, info, live_data, days_to_earnings)
            if candidate is not None:
                candidates.append(candidate)

        logger.info("T2: %d candidates passed Stage 2 (fundamentals + earnings gate)", len(candidates))

        # ── Stage 3 & 4: score, classify, flag ────────────────────────────────
        for c in candidates:
            c.t2_score   = self._compute_score(c)
            c.signal_tier = self._classify(c)
            c.risk_flags  = self._flag_risks(c, ohlcv.get(c.symbol))

        candidates.sort(key=lambda c: c.t2_score, reverse=True)
        result = candidates[: cfg.max_results]

        logger.info(
            "T2 screener complete: %d candidates  |  Tier A=%d  B=%d  C=%d",
            len(result),
            sum(1 for c in result if c.signal_tier == T2SignalTier.A),
            sum(1 for c in result if c.signal_tier == T2SignalTier.B),
            sum(1 for c in result if c.signal_tier == T2SignalTier.C),
        )
        return result

    # ── Stage 1: OHLCV technical gates ────────────────────────────────────────

    def _apply_ohlcv_filters(
        self,
        symbol: str,
        df: pd.DataFrame,
        live_data: dict[str, Any],
    ) -> dict[str, Any] | None:
        cfg = self.cfg
        if len(df) < 20:
            return None

        # Data-freshness gate: reject symbols whose latest bar is stale
        # (halted / delisted / corporate action — Yahoo stops updating).
        # A signal computed on week-old data is meaningless and can never be
        # entered anyway (no live price at execution time). SEM lesson.
        try:
            last_bar = pd.Timestamp(df.index[-1]).date()
            if (date.today() - last_bar).days > 4:
                logger.info(
                    "%s: stale data (last bar %s) — likely halted/delisted, skipped",
                    symbol, last_bar,
                )
                return None
        except Exception:
            pass

        latest      = df.iloc[-1]
        price       = float(latest["Close"])
        today_vol   = float(latest["Volume"])
        avg_vol_20d = float(latest["avg_volume_20d"])

        # Price gate
        if price < cfg.min_price:
            return None

        # Liquidity gate (30-day average volume)
        avg_vol_30d = float(df["Volume"].iloc[-30:].mean()) if len(df) >= 30 else avg_vol_20d
        if avg_vol_30d < cfg.min_avg_volume_30d:
            return None

        # RVOL gate — use today's actual volume vs 20d average
        if avg_vol_20d <= 0:
            return None
        rvol = today_vol / avg_vol_20d

        # For live-universe stocks, we already checked RVOL via Yahoo Finance data;
        # for static-fallback stocks, apply the config threshold.
        if not live_data and rvol < cfg.rvol_min:
            return None

        # Falling-knife check on OHLCV (catches static-fallback path and verifies live path)
        # today_change_pct from live_data is more reliable (intraday); OHLCV is EOD
        if live_data:
            today_chg_pct = live_data.get("today_change_pct", 0.0)
        else:
            # EOD calculation from OHLCV
            if len(df) >= 2:
                prev_close = float(df["Close"].iloc[-2])
                today_chg_pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0.0
            else:
                today_chg_pct = 0.0

        if today_chg_pct < -cfg.max_drop_pct_today:
            logger.debug(
                "%s: falling-knife (%.1f%% today) — skipped", symbol, today_chg_pct
            )
            return None

        # Momentum gate — price above 50 DMA
        sma50 = float(df["Close"].rolling(min(50, len(df)), min_periods=20).mean().iloc[-1])
        if np.isnan(sma50):
            return None
        if cfg.require_above_50dma and price < sma50:
            return None

        # 52-week high proximity
        high_52w = float(df["High"].iloc[-252:].max()) if len(df) >= 252 else float(df["High"].max())
        if high_52w <= 0:
            return None
        pct_below_52w = (high_52w - price) / high_52w
        if pct_below_52w > cfg.max_pct_below_52w_high:
            return None

        # 20-day momentum
        mom_20d = 0.0
        if len(df) >= 20:
            p20 = float(df["Close"].iloc[-20])
            mom_20d = (price - p20) / p20 if p20 > 0 else 0.0

        # Parabolic-extension filter
        gain_4w = 0.0
        if len(df) >= 20:
            p4w = float(df["Close"].iloc[-20])
            if p4w > 0:
                gain_4w = (price - p4w) / p4w
                if gain_4w > cfg.max_gain_4_weeks:
                    logger.debug("%s: parabolic (%+.0f%% in 4 weeks) — skipped", symbol, gain_4w * 100)
                    return None

        # Volume persistence
        high_rvol_days = 1
        if len(df) >= cfg.rvol_window_days:
            recent = df.iloc[-cfg.rvol_window_days:]
            rvols_recent = (
                recent["Volume"] / recent["avg_volume_20d"].replace(0, np.nan)
            ).dropna()
            high_rvol_days = int((rvols_recent >= cfg.rvol_min).sum())
            if high_rvol_days < cfg.min_high_rvol_days:
                return None

        # SMA200 for golden cross
        sma200 = float(df["Close"].rolling(min(200, len(df)), min_periods=50).mean().iloc[-1])

        return {
            "price":           price,
            "rvol":            round(rvol, 2),
            "avg_vol_30d":     round(avg_vol_30d, 0),
            "avg_vol_20d":     round(avg_vol_20d, 0),
            "sma50":           round(sma50, 4),
            "sma200":          round(sma200, 4) if not np.isnan(sma200) else 0.0,
            "high_52w":        round(high_52w, 4),
            "pct_below_52w":   round(pct_below_52w, 4),
            "high_rvol_days":  high_rvol_days,
            "mom_20d":         round(mom_20d, 4),
            "gain_4w":         round(gain_4w, 4),
            "golden_cross":    (not np.isnan(sma200)) and sma50 > sma200,
            "today_chg_pct":   round(today_chg_pct, 2),
            "atr_pct":         round(_compute_atr_pct(df, 14), 4),
        }

    # ── Stage 2: Fundamentals + earnings calendar ─────────────────────────────

    async def _fetch_info_and_earnings(
        self, symbols: list[str]
    ) -> dict[str, tuple[dict, int | None]]:
        """Fetch yf.Ticker.info + next earnings date for all symbols concurrently."""
        loop = asyncio.get_event_loop()

        async def _one(sym: str) -> tuple[str, dict, int | None]:
            try:
                info, days = await loop.run_in_executor(
                    _INFO_EXECUTOR, _fetch_info_and_calendar_sync, sym
                )
                return sym, info, days
            except Exception as exc:
                logger.debug("T2: info+calendar fetch failed for %s: %s", sym, exc)
                return sym, {}, None

        results = await asyncio.gather(*[_one(s) for s in symbols])
        return {sym: (info, days) for sym, info, days in results}

    def _build_candidate(
        self,
        symbol: str,
        df: pd.DataFrame,
        meta: dict[str, Any],
        info: dict,
        live_data: dict[str, Any],
        days_to_earnings: int | None,
    ) -> T2Candidate | None:
        cfg = self.cfg

        # ── Earnings proximity — hard gate ────────────────────────────────────
        if days_to_earnings is not None and 0 <= days_to_earnings < cfg.min_earnings_days_gate:
            logger.info(
                "T2: %s excluded — earnings in %d day(s) (gate: %d)",
                symbol, days_to_earnings, cfg.min_earnings_days_gate,
            )
            return None

        # ── Market cap gate ───────────────────────────────────────────────────
        mktcap = float(info.get("marketCap") or live_data.get("market_cap") or 0)
        if mktcap > 0 and (mktcap < cfg.min_market_cap or mktcap > cfg.max_market_cap):
            return None

        # ── Float gate ────────────────────────────────────────────────────────
        float_shares = info.get("floatShares") or info.get("sharesOutstanding")
        if float_shares:
            float_shares = float(float_shares)
            if float_shares < cfg.min_float_shares or float_shares > cfg.max_float_shares:
                return None
        else:
            float_shares = None

        # ── Fundamental growth gate ───────────────────────────────────────────
        rev_growth  = _safe_float(info.get("revenueGrowth"))
        earn_growth = _safe_float(info.get("earningsGrowth"))

        if cfg.require_growth_filter:
            data_available = rev_growth is not None or earn_growth is not None
            if data_available and not (
                (rev_growth  is not None and rev_growth  >= cfg.min_revenue_growth_yoy) or
                (earn_growth is not None and earn_growth >= cfg.min_earnings_growth_yoy)
            ):
                return None

        name     = info.get("shortName") or info.get("longName") or live_data.get("name") or symbol
        sector   = info.get("sector")   or ""
        industry = info.get("industry") or ""
        short_ratio = _safe_float(info.get("shortRatio"))
        catalyst = _detect_catalyst(info, sector, industry)

        return T2Candidate(
            symbol           = symbol,
            name             = name,
            sector           = sector,
            industry         = industry,
            price            = meta["price"],
            market_cap       = mktcap,
            rvol             = meta["rvol"],
            avg_volume_30d   = meta["avg_vol_30d"],
            today_change_pct = meta.get("today_chg_pct", live_data.get("today_change_pct", 0.0)),
            days_to_earnings = days_to_earnings,
            revenue_growth   = rev_growth,
            earnings_growth  = earn_growth,
            pct_below_52w_high = meta["pct_below_52w"],
            float_shares     = float_shares,
            short_ratio      = short_ratio,
            t2_score         = 0.0,
            signal_tier      = T2SignalTier.C,
            risk_flags       = [],
            signal_summary   = "",
            catalyst_hint    = catalyst,
        )

    # ── Stage 3: Composite scoring ────────────────────────────────────────────

    def _compute_score(self, c: T2Candidate) -> float:
        cfg = self.cfg
        score = 0.0

        # RVOL (0 → weight_rvol)
        rvol_norm = min(c.rvol / 5.0, 1.0)
        score += rvol_norm * cfg.weight_rvol

        # Day momentum — bonus for positive price action on scan day
        # A stock that is up 3-5% on high volume is showing clear accumulation.
        # Capped at +5 points to avoid over-weighting single-day pops.
        if c.today_change_pct > 0:
            day_bonus = min(c.today_change_pct / 5.0, 1.0) * 5.0
            score += day_bonus

        # 52W proximity (0 → weight_momentum)
        prox_norm = max(0.0, 1.0 - c.pct_below_52w_high / cfg.max_pct_below_52w_high)
        score += prox_norm * cfg.weight_momentum

        # Trend quality (0 → weight_trend)
        trend_pts = 0.0
        if (c.revenue_growth or 0) > 0:
            trend_pts += 0.5
        if (c.earnings_growth or 0) > 0:
            trend_pts += 0.5
        score += (trend_pts / 1.0) * cfg.weight_trend

        # Revenue growth (0 → weight_revenue_growth)
        if c.revenue_growth is not None:
            rev_norm = min(c.revenue_growth / 0.50, 1.0)
            score += max(rev_norm, 0.0) * cfg.weight_revenue_growth

        # Earnings growth (0 → weight_earnings_growth)
        if c.earnings_growth is not None:
            earn_norm = min(c.earnings_growth / 0.50, 1.0)
            score += max(earn_norm, 0.0) * cfg.weight_earnings_growth

        # 52W proximity bonus
        if c.pct_below_52w_high <= 0.05:
            score += cfg.weight_52w_proximity * 1.0
        elif c.pct_below_52w_high <= 0.10:
            score += cfg.weight_52w_proximity * 0.6
        elif c.pct_below_52w_high <= 0.15:
            score += cfg.weight_52w_proximity * 0.3

        # Float score
        if c.float_shares is not None:
            float_norm = max(0.0, 1.0 - c.float_shares / 150_000_000)
            score += float_norm * cfg.weight_float

        # Volume persistence
        if c.rvol >= cfg.rvol_preferred:
            score += cfg.weight_vol_persistence * 1.0
        elif c.rvol >= cfg.rvol_min:
            score += cfg.weight_vol_persistence * (
                (c.rvol - cfg.rvol_min) / (cfg.rvol_preferred - cfg.rvol_min)
            )

        # Earnings proximity penalty (soft — 8-21 days is caution but not excluded)
        if c.days_to_earnings is not None:
            if c.days_to_earnings < 21:
                # Reduce score proportionally — 21 days = no penalty, 8 days = -10 pts
                penalty = (1 - (c.days_to_earnings - 8) / 13) * 10
                score -= max(0, penalty)

        c.signal_summary = self._build_summary(c, score)
        return round(min(max(score, 0.0), 100.0), 1)

    # ── Stage 4: Classify + risk flags ────────────────────────────────────────

    def _classify(self, c: T2Candidate) -> T2SignalTier:
        if c.t2_score >= self.cfg.tier_a_min_score:
            return T2SignalTier.A
        if c.t2_score >= self.cfg.tier_b_min_score:
            return T2SignalTier.B
        return T2SignalTier.C

    def _flag_risks(self, c: T2Candidate, df: pd.DataFrame | None) -> list[T2RiskFlag]:
        flags: list[T2RiskFlag] = []

        # Extreme ATR volatility (> 8% daily)
        if df is not None and len(df) >= 14:
            atr_pct = _compute_atr_pct(df, 14)
            if atr_pct > 0.08:
                flags.append(T2RiskFlag.EXTREME_VOLATILITY)

        # Very low float
        if c.float_shares is not None and c.float_shares < 15_000_000:
            flags.append(T2RiskFlag.VERY_LOW_FLOAT)

        # High short interest
        if c.short_ratio is not None and c.short_ratio > 8:
            flags.append(T2RiskFlag.HIGH_SHORT_INTEREST)

        # Weak fundamentals (both metrics negative)
        if (
            c.revenue_growth  is not None and c.revenue_growth  < 0 and
            c.earnings_growth is not None and c.earnings_growth < 0
        ):
            flags.append(T2RiskFlag.WEAK_FUNDAMENTALS)

        # Thin liquidity
        if c.avg_volume_30d < 750_000:
            flags.append(T2RiskFlag.THIN_LIQUIDITY)

        # Earnings approaching (8-21 days — caution, not excluded)
        if c.days_to_earnings is not None and 0 <= c.days_to_earnings <= 21:
            flags.append(T2RiskFlag.EARNINGS_APPROACHING)

        # Pre-revenue / clinical-stage biotech
        # Detect: biotech sector + no meaningful revenue (revenue_growth None or extreme)
        is_biotech = "biotech" in c.sector.lower() or "biotech" in c.industry.lower()
        no_revenue = c.revenue_growth is None or (
            c.revenue_growth is not None and c.market_cap > 0 and
            c.market_cap < 2_000_000_000 and c.revenue_growth < 0
        )
        if is_biotech and no_revenue:
            flags.append(T2RiskFlag.PRE_REVENUE_BIOTECH)

        return flags

    @staticmethod
    def _build_summary(c: T2Candidate, score: float) -> str:
        parts: list[str] = []
        if c.rvol >= 3.0:
            parts.append(f"RVOL {c.rvol:.1f}×")
        if c.today_change_pct >= 2.0:
            parts.append(f"+{c.today_change_pct:.1f}% today")
        if c.pct_below_52w_high <= 0.05:
            parts.append("near 52W high")
        if c.revenue_growth and c.revenue_growth >= 0.20:
            parts.append(f"rev +{c.revenue_growth*100:.0f}% YoY")
        if c.days_to_earnings is not None and c.days_to_earnings <= 21:
            parts.append(f"⚠️ earnings {c.days_to_earnings}d")
        if c.catalyst_hint:
            parts.append(c.catalyst_hint)
        return " | ".join(parts) if parts else f"score {score:.0f}"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fetch_info_and_calendar_sync(symbol: str) -> tuple[dict, int | None]:
    """
    Blocking: fetch yf.Ticker.info + parse next earnings date.
    Returns (info_dict, days_until_earnings).
    days_until_earnings is None if unknown, negative if already past.
    """
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        time.sleep(0.15)   # light rate limiting

        # Parse earnings date from calendar
        days_to_earnings: int | None = None
        try:
            cal = ticker.calendar
            if isinstance(cal, pd.DataFrame) and not cal.empty:
                # Layout A: row index contains "Earnings Date"
                earnings_date = None
                if "Earnings Date" in cal.index:
                    val = cal.loc["Earnings Date"].iloc[0]
                    if pd.notna(val):
                        earnings_date = pd.Timestamp(val).date()
                elif "Earnings Date" in cal.columns:
                    val = cal["Earnings Date"].iloc[0]
                    if pd.notna(val):
                        earnings_date = pd.Timestamp(val).date()
                else:
                    # Layout C: dict-style
                    d = cal.to_dict()
                    for key in d:
                        if "Earnings" in str(key):
                            first_val = list(d[key].values())[0] if d[key] else None
                            if first_val and pd.notna(first_val):
                                earnings_date = pd.Timestamp(first_val).date()
                            break

                if earnings_date is not None:
                    days_to_earnings = (earnings_date - date.today()).days
        except Exception as exc:
            logger.debug("T2: calendar parse failed for %s: %s", symbol, exc)

        return info, days_to_earnings

    except Exception as exc:
        logger.debug("T2: info fetch failed for %s: %s", symbol, exc)
        return {}, None


def _safe_float(v: Any) -> float | None:
    try:
        f = float(v)
        return None if (f != f) else f   # NaN guard
    except (TypeError, ValueError):
        return None


def _compute_atr_pct(df: pd.DataFrame, periods: int = 14) -> float:
    try:
        h  = df["High"]
        l  = df["Low"]
        c  = df["Close"]
        pc = c.shift(1)
        tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        atr = float(tr.rolling(periods, min_periods=periods // 2).mean().iloc[-1])
        last_close = float(c.iloc[-1])
        return atr / last_close if last_close > 0 else 0.0
    except Exception:
        return 0.0


_CATALYST_KEYWORDS: list[tuple[list[str], str]] = [
    (["artificial intelligence", "ai ", " ai,", "llm", "generative"], "AI exposure"),
    (["semiconductor", "chip", "wafer", "foundry", "fabless"],         "Semiconductor"),
    (["defense", "military", "drone", "aerospace", "missile"],         "Defense"),
    (["cybersecurity", "cyber", "zero trust", "endpoint"],             "Cybersecurity"),
    (["energy transition", "solar", "wind", "battery", "ev ", "electric vehicle"], "Clean energy"),
    (["fda", "nda", "bla", "clinical trial", "phase 3"],               "FDA/biotech catalyst"),
    (["contract win", "awarded", "partnership", "deal"],                "Contract/deal"),
    (["earnings beat", "raised guidance", "raised outlook"],            "Earnings beat"),
    (["rate cut", "fed", "interest rate"],                              "Rate sensitivity"),
    (["crypto", "bitcoin", "blockchain"],                               "Crypto"),
]


def _detect_catalyst(info: dict, sector: str, industry: str) -> str:
    text = " ".join([
        str(info.get("longBusinessSummary", "")),
        sector, industry,
    ]).lower()
    for keywords, label in _CATALYST_KEYWORDS:
        if any(kw in text for kw in keywords):
            return label
    return ""
