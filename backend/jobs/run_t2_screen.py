"""
Standalone T2 screen — run this to see today's T2 candidates.

No database required. Fetches live data from yfinance.
Takes 2-4 minutes to complete (OHLCV batch + .info calls).

Usage
-----
    python backend/jobs/run_t2_screen.py
    python backend/jobs/run_t2_screen.py --top 20   # show top 20 instead of 15
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from dotenv import load_dotenv

for _candidate in [Path(__file__).parent, Path(__file__).parent.parent, Path(__file__).parent.parent.parent]:
    if (_candidate / ".env").exists():
        load_dotenv(_candidate / ".env")
        break

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
# Quiet down noisy sub-loggers
logging.getLogger("yfinance").setLevel(logging.WARNING)
logging.getLogger("peewee").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

from agents.t2_config import T2Config  # noqa: E402
from agents.t2_screener import T2Screener, T2SignalTier  # noqa: E402
from data.universe import SEED_UNIVERSE  # noqa: E402


async def main() -> None:
    max_results = 15
    if "--top" in sys.argv:
        try:
            max_results = int(sys.argv[sys.argv.index("--top") + 1])
        except (IndexError, ValueError):
            pass

    cfg = T2Config.from_env()
    cfg.max_results = max_results

    print()
    print("=" * 70)
    print("  T2 Institutional Accumulation & Momentum Screen")
    print(f"  Universe: {len(SEED_UNIVERSE)} symbols  |  Max results: {cfg.max_results}")
    print(f"  Filters : price>${cfg.min_price}  vol>{cfg.min_avg_volume_30d:,}  "
          f"RVOL>={cfg.rvol_min}x  mcap ${cfg.min_market_cap/1e6:.0f}M-${cfg.max_market_cap/1e9:.0f}B")
    print("=" * 70)
    print("  Fetching OHLCV data … (stage 1 of 4)")
    print()

    screener = T2Screener(cfg)
    candidates = await screener.run()

    if not candidates:
        print("  No candidates passed all filters today.")
        print("  Try loosening thresholds via env vars (e.g. T2_RVOL_MIN=1.5).")
        print("=" * 70)
        return

    # ── Summary header ────────────────────────────────────────────────────────
    tier_a = [c for c in candidates if c.signal_tier == T2SignalTier.A]
    tier_b = [c for c in candidates if c.signal_tier == T2SignalTier.B]
    tier_c = [c for c in candidates if c.signal_tier == T2SignalTier.C]

    print()
    print("=" * 70)
    print(f"  {len(candidates)} candidate(s) found   "
          f"Tier A={len(tier_a)}  Tier B={len(tier_b)}  Tier C={len(tier_c)}")
    print("=" * 70)

    for c in candidates:
        tier_label = {
            T2SignalTier.A: "[A]",
            T2SignalTier.B: "[B]",
            T2SignalTier.C: "[C]",
        }[c.signal_tier]

        mcap_str = f"${c.market_cap/1e9:.1f}B" if c.market_cap >= 1e9 else (
                   f"${c.market_cap/1e6:.0f}M" if c.market_cap > 0 else "n/a")
        float_str = (f"float {c.float_shares/1e6:.0f}M" if c.float_shares else "float n/a")
        rev_str   = (f"rev {c.revenue_growth*100:+.0f}%"
                     if c.revenue_growth is not None else "rev n/a")
        earn_str  = (f"earn {c.earnings_growth*100:+.0f}%"
                     if c.earnings_growth is not None else "earn n/a")
        pct_52w   = f"{c.pct_below_52w_high*100:.1f}% off 52W high"

        flags_str = ""
        if c.risk_flags:
            flags_str = "  [!] " + ", ".join(f.value.replace("_", " ") for f in c.risk_flags)

        print()
        print(f"  {tier_label}  {c.symbol:<6}  Score={c.t2_score:>5.1f}  "
              f"RVOL={c.rvol:.1f}×  Price=${c.price:.2f}  {mcap_str}")
        print(f"      {c.name or c.symbol}")
        print(f"      {c.sector or '—'}  /  {c.industry or '—'}")
        print(f"      {float_str}  |  {rev_str}  |  {earn_str}  |  {pct_52w}")
        if c.signal_summary:
            print(f"      Signal : {c.signal_summary}")
        if c.catalyst_hint:
            print(f"      Catalyst: {c.catalyst_hint}")
        if flags_str:
            print(f"     {flags_str}")

    print()
    print("=" * 70)
    print("  Tier A = Strong institutional accumulation")
    print("  Tier B = Emerging momentum")
    print("  Tier C = Watchlist candidate")
    print("=" * 70)
    print()


if __name__ == "__main__":
    asyncio.run(main())
