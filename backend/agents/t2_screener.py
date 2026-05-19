"""
T2 Institutional Accumulation & Emerging Momentum Screener.

Pipeline (runs every nightly EOD cron):
  Stage 1 — OHLCV batch download (fast, ~300 symbols in a few batches)
             → price gate, liquidity gate, RVOL gate,
               momentum gate (price vs DMA), 52W high proximity,
               volume persistence, parabolic-extension filter
  Stage 2 — yf.Ticker.info for surviving candidates (~20-80 stocks)
             → market cap, float, fundamentals (revenue/earnings growth),
               sector/industry, 52W high cross-check
  Stage 3 — Composite T2 Score (0-100, weighted)
  Stage 4 — Signal classification (Tier A / B / C) + risk flags

Returns a list[T2Candidate] sorted by t2_score descending.
The scanner converts these to ScannerOutput / AgentInputBundle for the rest of
the pipeline, so no other files need to understand T2Candidate internals.
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
from data.universe import get_universe

logger = logging.getLogger(__name__)

# Dedicated thread pool for blocking yfinance .info calls
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


class T2Candidate(BaseModel):
    symbol:            str
    name:              str             = ""
    sector:            str             = ""
    industry:          str             = ""
    price:             float
    market_cap:        float           = 0.0
    rvol:              float           = 0.0    # today_vol / avg_20d_vol
    avg_volume_30d:    float           = 0.0
    revenue_growth:    float | None    = None   # YoY decimal (0.25 = 25 %)
    earnings_growth:   float | None    = None   # YoY decimal
    pct_below_52w_high: float          = 0.0   # 0.05 = 5 % below 52W high
    float_shares:      float | None    = None
    short_ratio:       float | None    = None
    t2_score:          float           = Field(ge=0, le=100)
    signal_tier:       T2SignalTier    = T2SignalTier.C
    risk_flags:        list[T2RiskFlag] = Field(default_factory=list)
    signal_summary:    str             = ""
    catalyst_hint:     str             = ""    # keyword-based catalyst tag


# ── Main screener class ───────────────────────────────────────────────────────

class T2Screener:
    """
    Full T2 screening pipeline.

    Usage:
        screener = T2Screener(T2Config.from_env())
        candidates = await screener.run(exclude_symbols={"AAPL", "MSFT", ...})
        symbols = [c.symbol for c in candidates]
    """

    def __init__(self, config: T2Config | None = None) -> None:
        self.cfg = config or T2Config.from_env()

    async def run(self, exclude_symbols: set[str] | None = None) -> list[T2Candidate]:
        cfg = self.cfg
        today = date.today()
        start = today - timedelta(days=cfg.history_days)

        # ── Stage 1: OHLCV batch download ─────────────────────────────────────
        universe = get_universe(exclude=exclude_symbols)
        logger.info("T2 screener: universe = %d symbols, history %s → %s",
                    len(universe), start, today)

        loop = asyncio.get_event_loop()
        ohlcv: dict[str, pd.DataFrame] = await loop.run_in_executor(
            None, fetch_ohlcv_sync, universe, start, today
        )
        logger.info("T2: OHLCV returned for %d / %d symbols", len(ohlcv), len(universe))

        # ── Stage 1 filters (pure price/volume, no network) ───────────────────
        stage1: list[tuple[str, pd.DataFrame, dict[str, Any]]] = []
        for symbol, df in ohlcv.items():
            result = self._apply_ohlcv_filters(symbol, df)
            if result is not None:
                stage1.append((symbol, df, result))

        logger.info("T2: %d symbols passed Stage 1 (OHLCV gates)", len(stage1))

        if not stage1:
            logger.warning("T2: no candidates after OHLCV filters — check universe/thresholds")
            return []

        # ── Stage 2: yf.info for surviving candidates ─────────────────────────
        symbols_s1 = [sym for sym, _, _ in stage1]
        info_map: dict[str, dict] = await self._fetch_info_batch(symbols_s1)

        candidates: list[T2Candidate] = []
        for symbol, df, ohlcv_meta in stage1:
            info = info_map.get(symbol, {})
            candidate = self._build_candidate(symbol, df, ohlcv_meta, info)
            if candidate is not None:
                candidates.append(candidate)

        logger.info("T2: %d candidates passed Stage 2 (fundamentals/market-cap)", len(candidates))

        # ── Stage 3 & 4: score, rank, classify ───────────────────────────────
        for c in candidates:
            c.t2_score = self._compute_score(c)
            c.signal_tier = self._classify(c)
            c.risk_flags = self._flag_risks(c, ohlcv.get(c.symbol))

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

    # ── Stage 1: OHLCV gates ─────────────────────────────────────────────────

    def _apply_ohlcv_filters(
        self,
        symbol: str,
        df: pd.DataFrame,
    ) -> dict[str, Any] | None:
        """
        Return a dict of computed OHLCV metrics if the stock passes all gates,
        or None if it fails.
        """
        cfg = self.cfg
        if len(df) < 50:                                # not enough history
            return None

        latest        = df.iloc[-1]
        price         = float(latest["Close"])
        today_vol     = float(latest["Volume"])
        avg_vol_20d   = float(latest["avg_volume_20d"])

        # ── Price gate ────────────────────────────────────────────────────────
        if price < cfg.min_price:
            return None

        # ── Liquidity gate (30-day average volume) ────────────────────────────
        # Use last 30 rows of the volume series for the 30d avg
        avg_vol_30d = float(df["Volume"].iloc[-30:].mean()) if len(df) >= 30 else avg_vol_20d
        if avg_vol_30d < cfg.min_avg_volume_30d:
            return None

        # ── RVOL gate ─────────────────────────────────────────────────────────
        if avg_vol_20d <= 0:
            return None
        rvol = today_vol / avg_vol_20d
        if rvol < cfg.rvol_min:
            return None

        # ── Compute SMAs ──────────────────────────────────────────────────────
        close = df["Close"]
        sma50  = float(close.rolling(50,  min_periods=40).mean().iloc[-1])
        sma200 = float(close.rolling(200, min_periods=150).mean().iloc[-1])

        if np.isnan(sma50) or np.isnan(sma200):
            return None

        # ── Momentum gates ────────────────────────────────────────────────────
        if cfg.require_above_50dma and price < sma50:
            return None
        if cfg.require_above_200dma and price < sma200:
            return None

        # ── 52-week high proximity ────────────────────────────────────────────
        high_52w = float(df["High"].iloc[-252:].max()) if len(df) >= 252 else float(df["High"].max())
        if high_52w <= 0:
            return None
        pct_below_52w = (high_52w - price) / high_52w
        if pct_below_52w > cfg.max_pct_below_52w_high:
            return None

        # ── Volume persistence (at least N of last `window` sessions > rvol_min)
        if len(df) >= cfg.rvol_window_days:
            recent = df.iloc[-cfg.rvol_window_days :]
            rvols_recent = (
                recent["Volume"] /
                recent["avg_volume_20d"].replace(0, np.nan)
            ).dropna()
            high_rvol_days = int((rvols_recent >= cfg.rvol_min).sum())
            if high_rvol_days < cfg.min_high_rvol_days:
                return None
        else:
            high_rvol_days = 1

        # ── Parabolic-extension filter ────────────────────────────────────────
        # Drop stocks up > max_gain_4_weeks over the last 20 trading days
        if len(df) >= 20:
            price_4w_ago = float(df["Close"].iloc[-20])
            if price_4w_ago > 0:
                gain_4w = (price - price_4w_ago) / price_4w_ago
                if gain_4w > cfg.max_gain_4_weeks:
                    logger.debug("%s: parabolic (%+.0f%% in 4 weeks) — skipped", symbol, gain_4w * 100)
                    return None
        else:
            gain_4w = 0.0

        # ── 20-day momentum ───────────────────────────────────────────────────
        mom_20d = (price - float(df["Close"].iloc[-20])) / float(df["Close"].iloc[-20]) if len(df) >= 20 else 0.0

        # ── ATR % (volatility measure) ────────────────────────────────────────
        atr_pct = _compute_atr_pct(df, periods=14)

        return {
            "price":           price,
            "rvol":            round(rvol, 2),
            "avg_vol_30d":     round(avg_vol_30d, 0),
            "avg_vol_20d":     round(avg_vol_20d, 0),
            "sma50":           round(sma50, 4),
            "sma200":          round(sma200, 4),
            "high_52w":        round(high_52w, 4),
            "pct_below_52w":   round(pct_below_52w, 4),
            "high_rvol_days":  high_rvol_days,
            "mom_20d":         round(mom_20d, 4),
            "atr_pct":         round(atr_pct, 4),
            "gain_4w":         round(gain_4w, 4),
            "golden_cross":    sma50 > sma200,
        }

    # ── Stage 2: Fundamentals + market-cap ────────────────────────────────────

    async def _fetch_info_batch(self, symbols: list[str]) -> dict[str, dict]:
        """Fetch yf.Ticker.info for all symbols concurrently."""
        loop = asyncio.get_event_loop()

        async def _one(sym: str) -> tuple[str, dict]:
            try:
                info = await loop.run_in_executor(_INFO_EXECUTOR, _fetch_info_sync, sym)
                return sym, info
            except Exception as exc:
                logger.debug("T2: info fetch failed for %s: %s", sym, exc)
                return sym, {}

        results = await asyncio.gather(*[_one(s) for s in symbols])
        return dict(results)

    def _build_candidate(
        self,
        symbol: str,
        df: pd.DataFrame,
        meta: dict[str, Any],
        info: dict,
    ) -> T2Candidate | None:
        cfg = self.cfg

        # ── Market cap gate ───────────────────────────────────────────────────
        mktcap = float(info.get("marketCap") or 0)
        if mktcap > 0 and (mktcap < cfg.min_market_cap or mktcap > cfg.max_market_cap):
            logger.debug("%s: market cap $%.0fM out of range", symbol, mktcap / 1e6)
            return None

        # ── Float gate ────────────────────────────────────────────────────────
        float_shares = info.get("floatShares") or info.get("sharesOutstanding")
        if float_shares:
            float_shares = float(float_shares)
            if float_shares < cfg.min_float_shares or float_shares > cfg.max_float_shares:
                logger.debug("%s: float %.1fM out of range", symbol, float_shares / 1e6)
                return None
        else:
            float_shares = None

        # ── Fundamental growth gate ───────────────────────────────────────────
        rev_growth = _safe_float(info.get("revenueGrowth"))
        earn_growth = _safe_float(info.get("earningsGrowth"))

        if cfg.require_growth_filter:
            rev_ok  = rev_growth  is not None and rev_growth  >= cfg.min_revenue_growth_yoy
            earn_ok = earn_growth is not None and earn_growth >= cfg.min_earnings_growth_yoy
            # pass if EITHER metric is available and meets threshold
            data_available = rev_growth is not None or earn_growth is not None
            if data_available and not (rev_ok or earn_ok):
                logger.debug(
                    "%s: growth below threshold (rev=%.0f%% earn=%.0f%%)",
                    symbol,
                    (rev_growth or 0) * 100,
                    (earn_growth or 0) * 100,
                )
                return None

        # ── Enrich with info fields ───────────────────────────────────────────
        name    = info.get("shortName") or info.get("longName") or symbol
        sector  = info.get("sector")   or ""
        industry = info.get("industry") or ""
        short_ratio = _safe_float(info.get("shortRatio"))

        # ── Catalyst hint (keyword-based) ─────────────────────────────────────
        catalyst = _detect_catalyst(info, sector, industry)

        return T2Candidate(
            symbol=symbol,
            name=name,
            sector=sector,
            industry=industry,
            price=meta["price"],
            market_cap=mktcap,
            rvol=meta["rvol"],
            avg_volume_30d=meta["avg_vol_30d"],
            revenue_growth=rev_growth,
            earnings_growth=earn_growth,
            pct_below_52w_high=meta["pct_below_52w"],
            float_shares=float_shares,
            short_ratio=short_ratio,
            t2_score=0.0,          # computed next
            signal_tier=T2SignalTier.C,
            risk_flags=[],
            signal_summary="",
            catalyst_hint=catalyst,
        )

    # ── Stage 3: Composite scoring ────────────────────────────────────────────

    def _compute_score(self, c: T2Candidate) -> float:
        cfg = self.cfg
        score = 0.0

        # RVOL strength (0 → weight_rvol)
        rvol_norm = min(c.rvol / 5.0, 1.0)           # 5× = full score
        score += rvol_norm * cfg.weight_rvol

        # Momentum quality (0 → weight_momentum)
        # Reward: close to 52W high (but not parabolic)
        prox_norm = max(0.0, 1.0 - c.pct_below_52w_high / cfg.max_pct_below_52w_high)
        score += prox_norm * cfg.weight_momentum

        # Trend quality (0 → weight_trend)
        # Based on golden cross and positive 20d momentum
        trend_pts = 0.0
        # (We don't have sma50/sma200 on the candidate directly, proxy via revenue/earnings)
        # Best proxy available: pct_below_52w_high already handled above
        # Add partial credit if we have positive revenue growth
        if (c.revenue_growth or 0) > 0:
            trend_pts += 0.5
        if (c.earnings_growth or 0) > 0:
            trend_pts += 0.5
        score += (trend_pts / 1.0) * cfg.weight_trend

        # Revenue growth (0 → weight_revenue_growth)
        if c.revenue_growth is not None:
            rev_norm = min(c.revenue_growth / 0.50, 1.0)  # 50 % growth = full score
            score += max(rev_norm, 0.0) * cfg.weight_revenue_growth

        # Earnings growth (0 → weight_earnings_growth)
        if c.earnings_growth is not None:
            earn_norm = min(c.earnings_growth / 0.50, 1.0)
            score += max(earn_norm, 0.0) * cfg.weight_earnings_growth

        # 52W high proximity (0 → weight_52w_proximity)
        # Already computed in momentum; give separate score for being within 5 %
        if c.pct_below_52w_high <= 0.05:
            score += cfg.weight_52w_proximity * 1.0
        elif c.pct_below_52w_high <= 0.10:
            score += cfg.weight_52w_proximity * 0.6
        elif c.pct_below_52w_high <= 0.15:
            score += cfg.weight_52w_proximity * 0.3

        # Float score (0 → weight_float)
        if c.float_shares is not None:
            # Reward smaller floats (10M=perfect, 150M=0)
            ideal_max = 150_000_000
            float_norm = max(0.0, 1.0 - c.float_shares / ideal_max)
            score += float_norm * cfg.weight_float

        # Volume persistence: already baked into gate; give bonus for preferred RVOL
        if c.rvol >= cfg.rvol_preferred:
            score += cfg.weight_vol_persistence * 1.0
        elif c.rvol >= cfg.rvol_min:
            score += cfg.weight_vol_persistence * (c.rvol - cfg.rvol_min) / (cfg.rvol_preferred - cfg.rvol_min)

        c.signal_summary = self._build_summary(c, score)
        return round(min(score, 100.0), 1)

    # ── Stage 4: Classify + risk flags ────────────────────────────────────────

    def _classify(self, c: T2Candidate) -> T2SignalTier:
        if c.t2_score >= self.cfg.tier_a_min_score:
            return T2SignalTier.A
        if c.t2_score >= self.cfg.tier_b_min_score:
            return T2SignalTier.B
        return T2SignalTier.C

    def _flag_risks(self, c: T2Candidate, df: pd.DataFrame | None) -> list[T2RiskFlag]:
        flags: list[T2RiskFlag] = []

        # Extreme ATR volatility (> 8 % daily)
        if df is not None and len(df) >= 14:
            atr_pct = _compute_atr_pct(df, 14)
            if atr_pct > 0.08:
                flags.append(T2RiskFlag.EXTREME_VOLATILITY)

        # Very low float
        if c.float_shares is not None and c.float_shares < 15_000_000:
            flags.append(T2RiskFlag.VERY_LOW_FLOAT)

        # High short interest (> 20 % of float)
        if c.short_ratio is not None and c.short_ratio > 8:
            flags.append(T2RiskFlag.HIGH_SHORT_INTEREST)

        # Weak fundamentals (both metrics negative)
        if (
            c.revenue_growth is not None and c.revenue_growth < 0 and
            c.earnings_growth is not None and c.earnings_growth < 0
        ):
            flags.append(T2RiskFlag.WEAK_FUNDAMENTALS)

        # Thin liquidity (avg 30d vol < 750K — just above the gate threshold)
        if c.avg_volume_30d < 750_000:
            flags.append(T2RiskFlag.THIN_LIQUIDITY)

        return flags

    @staticmethod
    def _build_summary(c: T2Candidate, score: float) -> str:
        parts: list[str] = []
        if c.rvol >= 3.0:
            parts.append(f"RVOL {c.rvol:.1f}×")
        if c.pct_below_52w_high <= 0.05:
            parts.append("near 52W high")
        if c.revenue_growth and c.revenue_growth >= 0.20:
            parts.append(f"rev +{c.revenue_growth*100:.0f}% YoY")
        if c.earnings_growth and c.earnings_growth >= 0.20:
            parts.append(f"earn +{c.earnings_growth*100:.0f}% YoY")
        if c.catalyst_hint:
            parts.append(c.catalyst_hint)
        return " | ".join(parts) if parts else f"score {score:.0f}"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fetch_info_sync(symbol: str) -> dict:
    """Blocking yfinance info fetch — runs in thread pool."""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        # Small sleep to avoid rate-limiting
        time.sleep(0.15)
        return info
    except Exception as exc:
        logger.debug("_fetch_info_sync(%s) failed: %s", symbol, exc)
        return {}


def _safe_float(v: Any) -> float | None:
    try:
        f = float(v)
        return None if (f != f) else f     # NaN check
    except (TypeError, ValueError):
        return None


def _compute_atr_pct(df: pd.DataFrame, periods: int = 14) -> float:
    """
    Average True Range as a % of closing price.
    True Range = max(H-L, |H-PrevC|, |L-PrevC|)
    """
    try:
        h  = df["High"]
        l  = df["Low"]
        c  = df["Close"]
        pc = c.shift(1)
        tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        atr  = float(tr.rolling(periods, min_periods=periods // 2).mean().iloc[-1])
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
    """Keyword scan of company description + sector/industry for catalyst tagging."""
    text = " ".join([
        str(info.get("longBusinessSummary", "")),
        sector, industry,
    ]).lower()

    for keywords, label in _CATALYST_KEYWORDS:
        if any(kw in text for kw in keywords):
            return label
    return ""
