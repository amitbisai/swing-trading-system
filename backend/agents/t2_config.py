"""
T2 Screener configuration — all thresholds in one place.

Override any default by setting the corresponding environment variable
(e.g.  T2_MIN_MARKET_CAP=500000000  in .env).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class T2Config:
    # ── Universe ──────────────────────────────────────────────────────────────
    # Maximum results returned after scoring
    max_results: int = 15

    # ── Market cap (USD) ──────────────────────────────────────────────────────
    min_market_cap: float = 300_000_000   # $300 M — avoids micro-cap manipulation
    max_market_cap: float = 15_000_000_000  # $15 B — avoids mega-cap saturation

    # ── Price ─────────────────────────────────────────────────────────────────
    min_price: float = 10.0               # avoids penny-stock behaviour

    # ── Liquidity ─────────────────────────────────────────────────────────────
    min_avg_volume_30d: int = 500_000     # 30-day average shares/day

    # ── Relative Volume (RVOL = today_vol / avg_20d_vol) ─────────────────────
    rvol_min: float = 2.0                 # minimum to enter pipeline
    rvol_preferred: float = 3.0           # preferred (used in scoring)

    # ── Momentum gates ────────────────────────────────────────────────────────
    require_above_50dma: bool = True      # price must be > 50-day SMA
    require_above_200dma: bool = True     # price must be > 200-day SMA
    max_pct_below_52w_high: float = 0.15  # must be within 15 % of 52-week high

    # ── Trend strength (gates, not hard filters — partial pass still scores) ──
    prefer_50dma_above_200dma: bool = True  # golden-cross preferred
    min_20d_momentum: float = 0.0         # 20-day price return > 0

    # ── Fundamental growth ────────────────────────────────────────────────────
    # Stock passes the fundamental gate if EITHER revenue OR earnings clears threshold
    # Set require_growth_filter=False to skip fundamentals entirely
    require_growth_filter: bool = True
    min_revenue_growth_yoy: float = 0.10  # 10 % YoY (relaxed from 20 % for coverage)
    min_earnings_growth_yoy: float = 0.10  # 10 % YoY

    # ── Float ─────────────────────────────────────────────────────────────────
    max_float_shares: int = 300_000_000   # 300 M — smaller float = stronger moves
    min_float_shares: int = 5_000_000    #   5 M — avoids extreme illiquidity

    # ── Volume sustainability ─────────────────────────────────────────────────
    # At least N of the last `rvol_window_days` sessions must have RVOL > rvol_min
    min_high_rvol_days: int = 1           # 1 of last 3 sessions (relaxed for screen)
    rvol_window_days: int = 3

    # ── Parabolic avoidance ───────────────────────────────────────────────────
    max_gain_4_weeks: float = 1.50        # drop stocks already up > 150 % in 4 weeks

    # ── Signal classification thresholds ─────────────────────────────────────
    tier_a_min_score: float = 65.0        # Tier A — strong institutional accumulation
    tier_b_min_score: float = 45.0        # Tier B — emerging momentum
    # Tier C — anything that clears all gates but scores below tier_b_min_score

    # ── Scoring weights (must sum to 100) ─────────────────────────────────────
    weight_rvol: float = 20.0
    weight_momentum: float = 20.0
    weight_trend: float = 15.0
    weight_revenue_growth: float = 10.0
    weight_earnings_growth: float = 10.0
    weight_52w_proximity: float = 10.0
    weight_float: float = 5.0
    weight_vol_persistence: float = 10.0

    # ── OHLCV history window ──────────────────────────────────────────────────
    history_days: int = 260               # ~1 trading year for 200 DMA + 52W high

    @classmethod
    def from_env(cls) -> "T2Config":
        """Return a config with defaults overridden by environment variables."""
        cfg = cls()
        _float_vars = {
            "T2_MIN_MARKET_CAP":         "min_market_cap",
            "T2_MAX_MARKET_CAP":         "max_market_cap",
            "T2_MIN_PRICE":              "min_price",
            "T2_RVOL_MIN":               "rvol_min",
            "T2_RVOL_PREFERRED":         "rvol_preferred",
            "T2_MAX_PCT_BELOW_52W_HIGH": "max_pct_below_52w_high",
            "T2_MIN_REVENUE_GROWTH":     "min_revenue_growth_yoy",
            "T2_MIN_EARNINGS_GROWTH":    "min_earnings_growth_yoy",
            "T2_MAX_GAIN_4_WEEKS":       "max_gain_4_weeks",
            "T2_TIER_A_SCORE":           "tier_a_min_score",
            "T2_TIER_B_SCORE":           "tier_b_min_score",
        }
        _int_vars = {
            "T2_MAX_RESULTS":        "max_results",
            "T2_MIN_AVG_VOLUME":     "min_avg_volume_30d",
            "T2_MAX_FLOAT_SHARES":   "max_float_shares",
            "T2_MIN_FLOAT_SHARES":   "min_float_shares",
            "T2_MIN_HIGH_RVOL_DAYS": "min_high_rvol_days",
            "T2_HISTORY_DAYS":       "history_days",
        }
        _bool_vars = {
            "T2_REQUIRE_ABOVE_50DMA":  "require_above_50dma",
            "T2_REQUIRE_ABOVE_200DMA": "require_above_200dma",
            "T2_REQUIRE_GROWTH":       "require_growth_filter",
        }
        for env_key, attr in _float_vars.items():
            v = os.environ.get(env_key)
            if v is not None:
                setattr(cfg, attr, float(v))
        for env_key, attr in _int_vars.items():
            v = os.environ.get(env_key)
            if v is not None:
                setattr(cfg, attr, int(v))
        for env_key, attr in _bool_vars.items():
            v = os.environ.get(env_key)
            if v is not None:
                setattr(cfg, attr, v.lower() in ("1", "true", "yes"))
        return cfg
