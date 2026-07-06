"""
Backtest harness — replays history through the SAME rules the live system
trades: ATR stops/targets, SPY-200DMA regime filter, market-pulse-scaled
top-N entries, risk-based sizing, daily deployment budget + cash reserve,
gap-chase guard, intraday-low stop checks, chandelier trailing, breakeven,
target extension, and 14-day time exits.

Where it reuses production code directly (pure functions):
    risk.stop_target.compute_stop_target      risk.position_sizing.compute_position_size
    risk.market_pulse.entries_allowed         risk.entry_guards.is_gap_chase
    paper_trading.engine.EntryPlan / per_trade_cash_cap

Honest divergences from live (unavoidable without historical snapshots):
    * Sentiment is fixed at neutral 50 (no historical news archive)
    * T2 momentum screener is excluded (depends on live Yahoo screeners
      and as-of fundamentals) — this backtests the T1 strategy only
    * T1 earnings gate is off (no historical earnings calendar)
    * Confidence therefore = (ta_score + 50 + pattern_score) // 3

Usage (from backend/):
    python -m backtest.run_backtest                          # 2 years, top-5
    python -m backtest.run_backtest --start 2024-01-01 --end 2025-12-31
    python -m backtest.run_backtest --sample 150 --top-n 3 --min-confidence 60
    python -m backtest.run_backtest --exit-mode close        # EOD-close exits only

Outputs: summary table to stdout; trades + equity CSVs to backtest_results/.
"""

from __future__ import annotations

import argparse
import logging
import pickle
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

# ── Ensure backend/ is on sys.path ────────────────────────────────────────────
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

for _c in [_BACKEND_DIR, _BACKEND_DIR.parent]:
    if (_c / ".env").exists():
        load_dotenv(_c / ".env")
        break

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from config import settings  # noqa: E402
from data.fetcher import fetch_ohlcv_sync  # noqa: E402
from db.seed import TIER1_STOCKS  # noqa: E402
from paper_trading.engine import EntryPlan, per_trade_cash_cap  # noqa: E402
from risk.entry_guards import is_gap_chase  # noqa: E402
from risk.market_pulse import entries_allowed  # noqa: E402
from risk.position_sizing import compute_position_size  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")
log = logging.getLogger("backtest")

_CACHE_DIR = _BACKEND_DIR / "backtest" / ".cache"
_RESULTS_DIR = _BACKEND_DIR.parent / "backtest_results"

_WARMUP_DAYS = 320          # calendar days of extra history for 200DMA etc.
_MAX_CANDIDATES = 40        # mirrors synthesizer _MAX_SUGGESTIONS
_NEUTRAL_SENTIMENT = 50


# ── Data loading ──────────────────────────────────────────────────────────────

def load_data(
    symbols: list[str], start: date, end: date, use_cache: bool = True
) -> dict[str, pd.DataFrame]:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = f"ohlcv_{start}_{end}_{len(symbols)}.pkl"
    cache_file = _CACHE_DIR / key

    if use_cache and cache_file.exists():
        log.info("Loading cached OHLCV from %s", cache_file.name)
        with open(cache_file, "rb") as f:
            return pickle.load(f)

    fetch_start = start - timedelta(days=_WARMUP_DAYS)
    log.info(
        "Downloading OHLCV for %d symbols (%s → %s) — first run takes a few minutes…",
        len(symbols), fetch_start, end,
    )
    data = fetch_ohlcv_sync(symbols, fetch_start, end)
    log.info("Downloaded data for %d / %d symbols", len(data), len(symbols))

    with open(cache_file, "wb") as f:
        pickle.dump(data, f)
    return data


# ── Vectorized indicators — mirror agents/ta_agent.py + agents/pattern.py ─────

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Per-day indicator/score columns for one symbol (matches live agents)."""
    out = pd.DataFrame(index=df.index)
    close, high, low, open_ = df["Close"], df["High"], df["Low"], df["Open"]
    volume = df["Volume"]

    # RSI-14 (Wilder, matches ta_agent._rsi)
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out["rsi"] = 100 - (100 / (1 + rs))

    # MACD histogram (matches ta_agent._macd)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    out["macd_hist"] = macd_line - macd_line.ewm(span=9, adjust=False).mean()

    # ATR-14 (Wilder, matches ta_agent._atr)
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    out["atr"] = tr.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()

    out["sma20"] = close.rolling(20).mean()
    out["sma50"] = close.rolling(50, min_periods=20).mean()
    out["close"] = close
    out["open"] = open_
    out["high"] = high
    out["low"] = low

    # ── TA long score (mirror ta_agent._composite_score) ──────────────────────
    rsi = out["rsi"]
    rsi_pts = np.select(
        [rsi < 30, rsi < 40, rsi <= 60, rsi <= 70], [30, 25, 20, 10], default=0
    )
    macd_pts = np.where(out["macd_hist"] > 0, 30, 10)
    sma_pts = (
        np.where(close > out["sma20"], 15, 0)
        + np.where(close > out["sma50"], 15, 0)
        + np.where(out["sma20"] > out["sma50"], 10, 0)
    )
    out["ta_long"] = np.clip(rsi_pts + macd_pts + sma_pts, 0, 100)

    # ── TA short score (mirror synthesizer._ta_short_score) ───────────────────
    rsi_s = np.select(
        [rsi > 70, rsi > 60, rsi >= 40, rsi >= 30], [30, 20, 10, 5], default=0
    )
    macd_s = np.where(out["macd_hist"] < 0, 30, 5)
    sma_s = (
        np.where(close < out["sma20"], 15, 0)
        + np.where(close < out["sma50"], 15, 0)
        + np.where(out["sma20"] < out["sma50"], 10, 0)
    )
    out["ta_short"] = np.clip(rsi_s + macd_s + sma_s, 0, 100)

    # ── Pattern score (mirror agents/pattern.py, vectorized) ──────────────────
    high20 = high.rolling(20).max()
    low20 = low.rolling(20).min()
    price_range = high20 - low20

    body = (close - open_).abs()
    upper_wick = high - pd.concat([close, open_], axis=1).max(axis=1)
    lower_wick = pd.concat([close, open_], axis=1).min(axis=1) - low
    total_range = high - low
    valid = total_range > 0

    hammer = valid & (lower_wick >= 2 * body) & (upper_wick < body)
    star = valid & (upper_wick >= 2 * body) & (lower_wick < body)
    engulf = (
        (close > open_)
        & (prev_close < open_.shift(1))
        & (close > open_.shift(1))
        & (open_ < prev_close)
    )
    uptrend = (close > out["sma20"]) & (out["sma20"] > out["sma50"])
    downtrend = (close < out["sma20"]) & (out["sma20"] < out["sma50"])
    avg_vol20 = volume.rolling(20).mean()
    vol_brk = (volume > 1.5 * avg_vol20) & (close > prev_close)

    dist_sup = ((close - low20) / price_range).where(price_range > 0)
    base_long = (100 - dist_sup * 100).clip(0, 100).fillna(50)
    bonus_long = (
        hammer.astype(int) * 15 + engulf.astype(int) * 20 + vol_brk.astype(int) * 10
        + uptrend.astype(int) * 5 - star.astype(int) * 15 - downtrend.astype(int) * 10
    )
    out["pat_long"] = (base_long + bonus_long).clip(0, 100)

    dist_res = ((high20 - close) / price_range).where(price_range > 0)
    base_short = (100 - dist_res * 100).clip(0, 100).fillna(50)
    bonus_short = (
        star.astype(int) * 15 + downtrend.astype(int) * 10
        - hammer.astype(int) * 15 - engulf.astype(int) * 20
        - vol_brk.astype(int) * 10 - uptrend.astype(int) * 5
    )
    # doji bonus for shorts (mirror _pattern_short_score's +5 DOJI)
    doji = valid & (body <= 0.1 * total_range)
    out["pat_short"] = (base_short + bonus_short + doji.astype(int) * 5).clip(0, 100)

    # ── Confidence (mirror synthesizer, sentiment fixed neutral) ──────────────
    out["conf_long"] = (out["ta_long"] + _NEUTRAL_SENTIMENT + out["pat_long"]) // 3
    out["conf_short"] = (out["ta_short"] + (100 - _NEUTRAL_SENTIMENT) + out["pat_short"]) // 3
    return out


# ── Simulation types ──────────────────────────────────────────────────────────

@dataclass
class Position:
    symbol: str
    direction: str
    shares: int
    entry_price: float
    entry_date: date
    stop: float
    target: float
    initial_risk: float
    cost: float
    highest_close: float
    lowest_close: float
    levels_adjusted: bool = False


@dataclass
class ClosedTrade:
    symbol: str
    direction: str
    shares: int
    entry_date: date
    entry_price: float
    exit_date: date
    exit_price: float
    exit_reason: str
    pnl: float
    holding_days: int


@dataclass
class PendingEntry:
    symbol: str
    direction: str
    signal_close: float
    stop: float
    target: float
    confidence: int
    pulse_score: int
    allowed: int


@dataclass
class BacktestResult:
    equity: pd.Series = field(default_factory=pd.Series)
    trades: list[ClosedTrade] = field(default_factory=list)
    daily_signals: list[int] = field(default_factory=list)
    daily_pulse: list[int] = field(default_factory=list)


# ── Core simulation ───────────────────────────────────────────────────────────

def _exit_check(pos: Position, o: float, h: float, l: float, c: float,  # noqa: E741
                d: date, exit_mode: str) -> tuple[str, float] | None:
    """Return (reason, price) if the position exits today. Stop has priority."""
    if exit_mode == "intrabar":
        if pos.direction == "LONG":
            if o <= pos.stop:
                return "STOP_HIT", o          # gapped through the stop
            if l <= pos.stop:
                return "STOP_HIT", pos.stop
            if o >= pos.target:
                return "TARGET_HIT", o
            if h >= pos.target:
                return "TARGET_HIT", pos.target
        else:
            if o >= pos.stop:
                return "STOP_HIT", o
            if h >= pos.stop:
                return "STOP_HIT", pos.stop
            if o <= pos.target:
                return "TARGET_HIT", o
            if l <= pos.target:
                return "TARGET_HIT", pos.target
    else:   # close-only (matches the live EOD check exactly)
        if pos.direction == "LONG":
            if c <= pos.stop:
                return "STOP_HIT", c
            if c >= pos.target:
                return "TARGET_HIT", c
        else:
            if c >= pos.stop:
                return "STOP_HIT", c
            if c <= pos.target:
                return "TARGET_HIT", c

    if settings.max_holding_days > 0 and (d - pos.entry_date).days >= settings.max_holding_days:
        return "TIME_EXIT", c
    return None


def _manage_position(pos: Position, row: pd.Series) -> None:
    """Nightly dynamic exits — mirrors paper_trading/trade_manager.py."""
    c = row["close"]
    atr = row["atr"]
    if not np.isfinite(atr) or atr <= 0:
        return
    is_long = pos.direction == "LONG"
    profit = (c - pos.entry_price) if is_long else (pos.entry_price - c)
    r_mult = profit / pos.initial_risk if pos.initial_risk > 0 else 0.0

    if is_long:
        pos.highest_close = max(pos.highest_close, c)
    else:
        pos.lowest_close = min(pos.lowest_close, c)

    # breakeven
    if r_mult >= settings.breakeven_after_r:
        be = pos.entry_price
        if (is_long and be > pos.stop) or (not is_long and be < pos.stop):
            pos.stop = be
            pos.levels_adjusted = True

    # chandelier trail (in profit only)
    if profit > 0:
        ch = (
            pos.highest_close - atr * settings.trail_stop_atr_mult
            if is_long
            else pos.lowest_close + atr * settings.trail_stop_atr_mult
        )
        if (is_long and ch > pos.stop) or (not is_long and ch < pos.stop):
            pos.stop = ch
            pos.levels_adjusted = True

    # target extension when trend intact + >= 60% of move captured
    sma20, sma50, mh = row["sma20"], row["sma50"], row["macd_hist"]
    trend_ok = (
        (c > sma20 > sma50 and mh > 0) if is_long else (c < sma20 < sma50 and mh < 0)
    )
    denom = (pos.target - pos.entry_price) if is_long else (pos.entry_price - pos.target)
    progress = (profit / denom) if denom > 0 else 0.0
    if trend_ok and progress >= 0.60:
        ext = c + atr * settings.target_extend_atr_mult if is_long else c - atr * settings.target_extend_atr_mult
        if (is_long and ext > pos.target) or (not is_long and ext < pos.target):
            pos.target = ext
            pos.levels_adjusted = True


def run_simulation(
    ind: dict[str, pd.DataFrame],
    spy: pd.DataFrame,
    start: date,
    end: date,
    top_n: int,
    min_confidence: int,
    exit_mode: str,
    long_only: bool = False,
) -> BacktestResult:
    initial = float(settings.initial_capital)
    cash = initial
    positions: list[Position] = []
    pending: list[PendingEntry] = []
    result = BacktestResult()
    equity_curve: dict[pd.Timestamp, float] = {}

    # SPY context (regime + trend part of the pulse)
    spy_close = spy["Close"]
    spy_sma50 = spy_close.rolling(50).mean()
    spy_sma200 = spy_close.rolling(200).mean()
    ema12 = spy_close.ewm(span=12, adjust=False).mean()
    ema26 = spy_close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    spy_macd_hist = macd_line - macd_line.ewm(span=9, adjust=False).mean()

    # breadth: fraction of symbols with close > sma50, per day
    closes = pd.DataFrame({s: df["close"] for s, df in ind.items()})
    sma50s = pd.DataFrame({s: df["sma50"] for s, df in ind.items()})
    breadth = (closes > sma50s).sum(axis=1) / closes.notna().sum(axis=1).clip(lower=1)

    days = [d for d in spy.index if start <= d.date() <= end]

    for ts in days:
        d = ts.date()

        # ── 1. Execute yesterday's signals at today's open ────────────────────
        if pending:
            # NAV convention mirrors the live engine: capital = cash + invested
            invested = sum(p.cost for p in positions)
            capital = cash + invested
            plan = EntryPlan(
                as_of=d,
                capital=Decimal(str(round(capital, 4))),
                cash=Decimal(str(round(cash, 4))),
                entered_today=0,
                deployed_today=Decimal("0"),
                allowed_today=pending[0].allowed if pending else 0,
                pulse_score=pending[0].pulse_score if pending else 0,
                pulse_label="",
            )
            held = {p.symbol for p in positions}
            opened = 0
            spent = Decimal("0")
            for pe in sorted(pending, key=lambda x: x.confidence, reverse=True):
                if pe.symbol in held:
                    continue
                df = ind.get(pe.symbol)
                if df is None or ts not in df.index:
                    continue
                o = float(df.loc[ts, "open"])
                if not np.isfinite(o) or o <= 0:
                    continue

                cash_cap = per_trade_cash_cap(plan, opened, spent)
                if cash_cap <= 0:
                    break
                if is_gap_chase(
                    pe.direction, Decimal(str(pe.signal_close)), Decimal(str(o)),
                    settings.max_entry_gap_pct,
                ):
                    continue

                # re-anchor stop/target distances to the actual open
                stop = o - (pe.signal_close - pe.stop)
                target = o + (pe.target - pe.signal_close)
                shares = compute_position_size(
                    plan.capital, Decimal(str(o)), Decimal(str(round(stop, 4))),
                    available_cash=cash_cap,
                )
                if shares <= 0:
                    continue

                cost = shares * o
                cash -= cost
                positions.append(Position(
                    symbol=pe.symbol, direction=pe.direction, shares=shares,
                    entry_price=o, entry_date=d, stop=stop, target=target,
                    initial_risk=abs(o - stop), cost=cost,
                    highest_close=o, lowest_close=o,
                ))
                held.add(pe.symbol)
                opened += 1
                spent += Decimal(str(cost))
            pending = []

        # ── 2. Exit checks with today's OHLC ──────────────────────────────────
        survivors: list[Position] = []
        for pos in positions:
            df = ind.get(pos.symbol)
            if df is None or ts not in df.index:
                survivors.append(pos)
                continue
            row = df.loc[ts]
            hit = _exit_check(
                pos, float(row["open"]), float(row["high"]),
                float(row["low"]), float(row["close"]), d, exit_mode,
            )
            if hit is None:
                survivors.append(pos)
                continue
            reason, px = hit
            pnl = (
                (px - pos.entry_price) * pos.shares
                if pos.direction == "LONG"
                else (pos.entry_price - px) * pos.shares
            )
            cash += pos.cost + pnl
            result.trades.append(ClosedTrade(
                symbol=pos.symbol, direction=pos.direction, shares=pos.shares,
                entry_date=pos.entry_date, entry_price=pos.entry_price,
                exit_date=d, exit_price=px, exit_reason=reason, pnl=pnl,
                holding_days=(d - pos.entry_date).days,
            ))
        positions = survivors

        # ── 3. Nightly dynamic exit management ────────────────────────────────
        if settings.dynamic_exits_enabled:
            for pos in positions:
                df = ind.get(pos.symbol)
                if df is not None and ts in df.index:
                    _manage_position(pos, df.loc[ts])

        # ── 4. Generate tonight's signals (execute tomorrow at open) ──────────
        sc = spy_close.get(ts)
        s200 = spy_sma200.get(ts)
        regime_ok = (
            not settings.regime_filter_enabled
            or (pd.notna(s200) and pd.notna(sc) and sc > s200)
        )

        # market pulse (mirror risk/market_pulse.py scoring)
        trend_pts = 0.0
        if pd.notna(s200) and sc > s200:
            trend_pts += 20
        s50 = spy_sma50.get(ts)
        if pd.notna(s50) and sc > s50:
            trend_pts += 15
        if pd.notna(s50) and pd.notna(s200) and s50 > s200:
            trend_pts += 10
        mh = spy_macd_hist.get(ts)
        if pd.notna(mh) and mh > 0:
            trend_pts += 15
        b = breadth.get(ts)
        pulse = int(round(min(max(
            trend_pts + (40 * b if pd.notna(b) else trend_pts * 40 / 60), 0), 100)))
        allowed = entries_allowed(top_n, pulse)
        result.daily_pulse.append(pulse)

        n_signals = 0
        if regime_ok and allowed > 0:
            candidates: list[PendingEntry] = []
            for sym, df in ind.items():
                if ts not in df.index:
                    continue
                row = df.loc[ts]
                if not np.isfinite(row["atr"]) or not np.isfinite(row["sma50"]):
                    continue
                cl, cs = int(row["conf_long"]), int(row["conf_short"])
                direction, conf = ("LONG", cl) if cl >= cs else ("SHORT", cs)
                if long_only and direction == "SHORT":
                    continue
                if conf < min_confidence:
                    continue
                c = float(row["close"])
                atr = float(row["atr"])
                # ATR stop/target with the same clamps as risk/stop_target.py
                stop_dist = atr * settings.atr_stop_mult
                tgt_dist = atr * settings.atr_target_mult
                clamped = min(max(stop_dist, c * 0.01), c * 0.10)
                if clamped != stop_dist:
                    tgt_dist = clamped * (settings.atr_target_mult / settings.atr_stop_mult)
                    stop_dist = clamped
                if direction == "SHORT":
                    stop, target = c + stop_dist, c - tgt_dist
                else:
                    stop, target = c - stop_dist, c + tgt_dist
                candidates.append(PendingEntry(
                    symbol=sym, direction=direction, signal_close=c,
                    stop=stop, target=target, confidence=conf,
                    pulse_score=pulse, allowed=allowed,
                ))
            candidates.sort(key=lambda x: x.confidence, reverse=True)
            pending = candidates[:_MAX_CANDIDATES]
            n_signals = len(pending)
        result.daily_signals.append(n_signals)

        # ── 5. Mark equity at close ────────────────────────────────────────────
        unrl = 0.0
        for pos in positions:
            px = _mark(ind, pos, ts, "close")
            unrl += (
                (px - pos.entry_price) * pos.shares
                if pos.direction == "LONG"
                else (pos.entry_price - px) * pos.shares
            )
        invested = sum(p.cost for p in positions)
        equity_curve[ts] = cash + invested + unrl

    result.equity = pd.Series(equity_curve).sort_index()
    return result


def _mark(ind: dict[str, pd.DataFrame], pos: Position, ts: pd.Timestamp, col: str) -> float:
    df = ind.get(pos.symbol)
    if df is None:
        return pos.entry_price
    if ts in df.index and np.isfinite(df.loc[ts, col]):
        return float(df.loc[ts, col])
    prior = df.loc[:ts, col].dropna()
    return float(prior.iloc[-1]) if len(prior) else pos.entry_price


# ── Reporting ─────────────────────────────────────────────────────────────────

def report(result: BacktestResult, spy: pd.DataFrame, start: date, end: date,
           top_n: int, min_confidence: int, exit_mode: str) -> None:
    eq = result.equity
    trades = result.trades
    initial = float(settings.initial_capital)

    if eq.empty:
        print("No equity data produced — check date range / data availability.")
        return

    final = float(eq.iloc[-1])
    total_ret = (final / initial - 1) * 100
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    cagr = ((final / initial) ** (1 / years) - 1) * 100
    running_max = eq.cummax()
    max_dd = float(((eq - running_max) / running_max).min()) * 100

    spy_in = spy["Close"].loc[(spy.index.date >= start) & (spy.index.date <= end)]
    spy_ret = (float(spy_in.iloc[-1]) / float(spy_in.iloc[0]) - 1) * 100 if len(spy_in) > 1 else 0.0

    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    gross_win = sum(t.pnl for t in wins)
    gross_loss = -sum(t.pnl for t in losses)
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    by_reason: dict[str, int] = {}
    for t in trades:
        by_reason[t.exit_reason] = by_reason.get(t.exit_reason, 0) + 1

    print()
    print("=" * 68)
    print(f"  BACKTEST  {start} to {end}   (top-{top_n}, min-conf {min_confidence}, "
          f"{exit_mode} exits)")
    print("=" * 68)
    print(f"  Initial capital     : ${initial:>12,.0f}")
    print(f"  Final equity        : ${final:>12,.0f}")
    print(f"  Total return        : {total_ret:>+11.2f}%      SPY buy&hold: {spy_ret:+.2f}%")
    print(f"  CAGR                : {cagr:>+11.2f}%")
    print(f"  Max drawdown        : {max_dd:>11.2f}%")
    print("-" * 68)
    if not trades:
        print("  Trades              : 0")
    else:
        print(f"  Trades              : {len(trades):>6}   "
              f"({len(wins)}W / {len(losses)}L — win rate "
              f"{100 * len(wins) / len(trades):.1f}%)")
        print(f"  Profit factor       : {pf:>10.2f}")
        print(f"  Avg win / avg loss  : ${gross_win / max(len(wins), 1):>8,.0f} / "
              f"${-gross_loss / max(len(losses), 1):>8,.0f}")
        print(f"  Avg holding days    : {sum(t.holding_days for t in trades) / len(trades):>8.1f}")
        print(f"  Exits by reason     : " + "  ".join(f"{k}={v}" for k, v in sorted(by_reason.items())))
    sig = result.daily_signals
    if sig:
        print(f"  Signals/day         : avg {sum(sig) / len(sig):.1f}   "
              f"zero-signal days: {sum(1 for s in sig if s == 0)}/{len(sig)}")
    pl = result.daily_pulse
    if pl:
        print(f"  Market pulse        : avg {sum(pl) / len(pl):.0f}/100")
    print("=" * 68)

    # ── CSVs ──────────────────────────────────────────────────────────────────
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    trades_csv = _RESULTS_DIR / f"trades_{stamp}.csv"
    equity_csv = _RESULTS_DIR / f"equity_{stamp}.csv"
    pd.DataFrame([t.__dict__ for t in trades]).to_csv(trades_csv, index=False)
    eq_df = pd.DataFrame({"equity": eq})
    eq_df["spy_normalized"] = (
        spy_in / float(spy_in.iloc[0]) * initial if len(spy_in) else np.nan
    )
    eq_df.to_csv(equity_csv)
    print(f"  Saved: {trades_csv}")
    print(f"  Saved: {equity_csv}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Backtest the T1 swing strategy")
    ap.add_argument("--start", type=date.fromisoformat,
                    default=date.today() - timedelta(days=730))
    ap.add_argument("--end", type=date.fromisoformat, default=date.today())
    ap.add_argument("--top-n", type=int, default=5)
    ap.add_argument("--min-confidence", type=int, default=63)
    ap.add_argument("--sample", type=int, default=0,
                    help="Use only every k-th symbol to hit ~N total (0 = all 501)")
    ap.add_argument("--exit-mode", choices=["intrabar", "close"], default="intrabar",
                    help="intrabar = stops checked vs daily low/high (realistic); "
                         "close = EOD close only (matches the live engine exactly)")
    ap.add_argument("--long-only", action="store_true",
                    help="Skip SHORT signals entirely")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    symbols = [s for s, _, _ in TIER1_STOCKS]
    if args.sample and args.sample < len(symbols):
        step = max(1, len(symbols) // args.sample)
        symbols = symbols[::step][: args.sample]

    data = load_data(symbols + [settings.regime_symbol], args.start, args.end,
                     use_cache=not args.no_cache)
    spy = data.pop(settings.regime_symbol, None)
    if spy is None or spy.empty:
        print("FATAL: no SPY data — cannot compute regime/pulse.")
        sys.exit(1)

    log.info("Computing indicators for %d symbols…", len(data))
    ind = {s: compute_indicators(df) for s, df in data.items() if len(df) >= 60}

    result = run_simulation(
        ind, spy, args.start, args.end,
        top_n=args.top_n, min_confidence=args.min_confidence, exit_mode=args.exit_mode,
        long_only=args.long_only,
    )
    report(result, spy, args.start, args.end, args.top_n, args.min_confidence, args.exit_mode)


if __name__ == "__main__":
    main()
