# Swing Trading System — Technical Documentation

> **Status:** live (paper trading) · **Last updated:** 2026-07-06
> **Scope:** complete end-to-end reference — architecture, all trading logic,
> deployment, database schema, configuration, backtesting, and features not
> visible in the frontend. Update this file whenever behaviour changes.

---

## Table of contents

1. [System overview](#1-system-overview)
2. [Deployment topology (Railway / Vercel / Supabase)](#2-deployment-topology)
3. [Nightly signal pipeline — step by step](#3-nightly-signal-pipeline)
4. [T2 momentum screener](#4-t2-momentum-screener)
5. [Entry engine (hourly, next-morning)](#5-entry-engine)
6. [Exit engine & dynamic trade management](#6-exit-engine--dynamic-trade-management)
7. [Position sizing & capital pacing](#7-position-sizing--capital-pacing)
8. [Database schema — every table](#8-database-schema)
9. [Configuration — every variable](#9-configuration)
10. [API endpoints](#10-api-endpoints)
11. [Frontend pages](#11-frontend-pages)
12. [Backtesting harness](#12-backtesting-harness)
13. [Outcome analytics (feedback loop)](#13-outcome-analytics)
14. [Features not visible in the frontend](#14-features-not-visible-in-the-frontend)
15. [Operations: manual triggers, logs, resets](#15-operations)
16. [Decision log — why the parameters are what they are](#16-decision-log)

---

## 1. System overview

An AI-assisted **swing trading suggestion system** for 3–14 day positions.
Paper trading only — no broker integration. Signals are generated **once per
night** after US market close; trades are **executed automatically** the next
market morning at live prices and managed hourly during market hours.

```
                        ┌──────────────── GitHub (main) ────────────────┐
                        │ every push auto-deploys everything below      │
                        └───────────────────────────────────────────────┘
   Railway (backend)                                     Vercel (frontend)
┌─────────────────────────────────────────────┐   ┌──────────────────────────┐
│ web            FastAPI API (always on)      │◄──│ Next.js 14 PWA           │
│ ingest-service cron 21:30 UTC  Mon–Fri      │   │ Signals / Portfolio /    │
│ agents         cron 22:00 UTC  Mon–Fri      │   │ Analytics / Financials   │
│ hourly-rates   cron 13:30–20:30 UTC hourly  │   └──────────────────────────┘
└──────────────────────┬──────────────────────┘
                       ▼
             Supabase (PostgreSQL)  ·  yfinance (prices)  ·  Finnhub (news)
             Anthropic Claude (sentiment scoring + trade rationale)
```

**Two-tier stock universe**

| Tier | Universe | Risk profile | Entry priority |
|---|---|---|---|
| **T1** | 501 S&P 500 stocks (static list, `db/seed.py`) | Lower — large-cap liquid | Fills the pulse-scaled top-N daily slots |
| **T2** | Live daily screen of Yahoo Finance Most-Active / Day-Gainers | Higher — momentum mid-caps | Rare; **always entered** (count-exempt, max 5/day) |

---

## 2. Deployment topology

### Railway project layout

There are **two Railway projects** (historical accident, works fine):

| Project | Service | Type | Build | Start command | Schedule (UTC) |
|---|---|---|---|---|---|
| `observant-truth` | **web** | always-on HTTP | nixpacks (root `nixpacks.toml`, venv at `/app/venv` to bypass Ubuntu 24.04 PEP 668) | `cd backend && /app/venv/bin/uvicorn main:app --host 0.0.0.0 --port $PORT` | — |
| `noble-upliftment` | **ingest-service** | cron | `Dockerfile.railway` | `python backend/jobs/ingest.py` | `30 21 * * 1-5` |
| `noble-upliftment` | **agents** | cron | `Dockerfile.agents` | `python backend/jobs/run_agents.py` | `0 22 * * 1-5` |
| `noble-upliftment` | **hourly-rates** | cron | `Dockerfile.agents` | `python backend/jobs/intraday_update.py` | `30 13-20 * * 1-5` |

**How Railway cron works:** at the scheduled time Railway boots the built
container, runs the start command, and considers the run complete when the
process exits. Logs live under each service's *Cron Runs* panel (per-execution),
not the Deploy Logs tab. A new git push rebuilds the image; the next cron tick
uses the new code.

Key deployment facts:

- **Config-as-code:** root `railway.toml` sets only the builder; per-service
  start commands / cron schedules are set in the Railway dashboard (Settings →
  Deploy). Never re-add `startCommand` to `railway.toml` — it locks the
  dashboard field for *all* services.
- **Env vars are per-service** — Railway does not share them. Adding a new
  variable means adding it to each of the 4 services.
- `CORS_ORIGINS=*` on the web service (Vercel preview URLs rotate per deploy;
  code disables `allow_credentials` automatically when wildcard).
- **Frontend:** Vercel project rooted at `frontend/`, env var
  `NEXT_PUBLIC_API_URL=https://swing-trading-system-production.up.railway.app`
  (no trailing slash — a trailing slash causes `//api/...` 404s).

### Timeline of a full trading day (UTC)

```
21:30  ingest-service   fetch 30d OHLCV for all active stocks → daily_prices
22:00  agents           full signal pipeline (section 3) → suggestions
                        + EOD exits + dynamic management + snapshot
13:30  hourly-rates     (next market morning) first run: auto-entry at live
  …                     prices, then hourly: exit checks + mark-to-market
20:30  hourly-rates     last intraday run of the day
```

---

## 3. Nightly signal pipeline

Entry point: `backend/jobs/run_agents.py` → `agents/orchestrator.py`
(LangGraph state machine). Nodes run in this order:

### 3.1 `scan_node` — universe selection
- **T1:** all `stocks` rows where `tier='T1' AND is_active` (501 symbols).
- **T2:** runs the 5-stage screener (section 4); upserts new T2 symbols into
  `stocks`; fetches news per candidate (Finnhub) + Claude validation verdict;
  persists everything to `t2_scans`.
- **Market regime check:** SPY vs its 200-day SMA (`risk/regime.py`).
  Result is carried in state; a bearish regime does NOT stop the pipeline —
  it marks tonight's suggestions `is_active=false` (visible, not tradable).
  Fails open (bullish) if SPY data is unavailable.

### 3.2 `ta_pattern_node` — technical analysis (parallel)
One bulk yfinance download (90 days) for all symbols, then per symbol:

- **TA composite score 0–100** (`agents/ta_agent.py`):
  - RSI-14 (Wilder): <30 → 30 pts · <40 → 25 · ≤60 → 20 · ≤70 → 10 · else 0
  - MACD histogram: positive → 30 pts, negative → 10
  - Price vs SMAs: above SMA20 +15 · above SMA50 +15 · SMA20>SMA50 +10
  - Also computes **ATR-14** (used later for stops) and Bollinger bands.
- **Pattern score 0–100** (`agents/pattern.py`):
  - Base = proximity to 20-day support (100 = at support)
  - Bonuses: HAMMER +15, BULLISH_ENGULFING +20, VOLUME_BREAKOUT +10,
    UPTREND +5; penalties: SHOOTING_STAR −15, DOWNTREND −10.

### 3.3 `sentiment_node` — news sentiment
Finnhub headlines for every symbol (60 calls/min free tier), then ONE batched
Claude Haiku call scores all symbols 0–100. Fallback on failure: neutral 50.

### 3.4 `synthesize_node` — scoring, gating, persistence
For each stock (`agents/synthesizer.py`):

1. `long_conf  = (ta_long  + sentiment       + pattern_long)  // 3`
   `short_conf = (ta_short + (100−sentiment) + pattern_short) // 3`
   Direction = the higher one.
2. **LONG_ONLY gate** (default on): SHORT candidates are discarded.
   *(Backtest-validated — see section 16.)*
3. **Minimum confidence:** 63 (`_MIN_CONFIDENCE`). Below → dropped.
4. **Stop/target:** ATR-based (`risk/stop_target.py`):
   `stop = entry − 1.5×ATR14`, `target = entry + 3.0×ATR14`
   (stop distance clamped to 1–10 % of entry; target rescaled to keep 2:1).
   Falls back to fixed percentages (T1 2 %/4 %, T2 4 %/10 %) when ATR missing.
5. Candidates sorted by confidence (ties randomised so A–F tickers don't
   always win), then:
6. **T1 earnings gate** (`risk/entry_guards.py`): candidates in the top 50
   are checked against yfinance's earnings calendar; T1 names reporting
   within `T1_MIN_EARNINGS_DAYS` (8) are dropped **before** the cap, so
   their slots backfill. Fail-open when the calendar is unavailable.
7. Cap at 40 suggestions; Claude writes a 2-sentence rationale per signal;
   rows written to `suggestions` (previous day's rows deactivated first —
   idempotent delete-then-insert for same-day reruns).

### 3.5 `save_t1_node` — T1 scan history
Full TA snapshot of every T1 stock (whether or not it became a signal) into
`t1_scans` — powers the "T1 Scan History" tab and future analysis.

### 3.6 Paper-trading tail (still inside run_agents.py)
- `AUTO_ENTRY_MODE=intraday` (default): **no entries tonight** — deferred to
  next morning's hourly job. (`nightly` mode would enter immediately at the
  suggestion's EOD price.)
- `process_eod(today)`: EOD exit checks → dynamic trade management →
  portfolio snapshot → `sync_trade_outcomes()` (sections 6, 13).

---

## 4. T2 momentum screener

`agents/t2_screener.py` — "institutional accumulation" pipeline (v2):

| Stage | What happens | Kills a candidate when… |
|---|---|---|
| **0. Live universe** | Yahoo Finance Most Active + Day Gainers (≈100–175 symbols), minus T1 | down >3 % today (falling-knife pre-filter) |
| **1. OHLCV gates** | bulk 260-day download | price < $10 · avg vol < 500k · RVOL < 1.5 · below 50DMA · >25 % under 52-wk high · up >150 % in 4 weeks (parabolic) · <1 of last 3 days with high RVOL |
| **2. Fundamentals** | `yf.Ticker.info` + earnings calendar per survivor | **earnings within 8 days (hard gate)** · market cap outside $300M–$100B · float outside 5M–500M |
| **3. Scoring** | composite T2 score 0–100: RVOL 20, momentum/52-wk proximity 30, trend 15, revenue+earnings growth 20, float 5, volume persistence 10, day-move bonus ≤5, earnings-proximity penalty ≤−10 | — |
| **4. Classification** | Tier A ≥65 · Tier B ≥45 · Tier C rest; risk flags (extreme volatility, low float, high short interest, weak fundamentals, thin liquidity, earnings 8–21d, pre-revenue biotech) | — |

Top `T2_MAX_RESULTS` (20) survive. Each gets Finnhub news + a Claude verdict
(`SUPPORTS` / `NEUTRAL` / `CONTRADICTS`) stored in `t2_scans`.

**Zero-result days are normal and intentional** — momentum setups cluster by
regime; the screener refusing to produce candidates in chop is a feature.

---

## 5. Entry engine

Entry point: `backend/jobs/intraday_update.py`, hourly during market hours.
The analysis system is **not** re-run intraday — this job only executes
against last night's signals. Sequence per run:

1. **Market-hours guard:** 9:30–16:00 America/New_York (zoneinfo; falls back
   to a fixed 13:30–21:00 UTC window). `--force` overrides for testing.
2. **Live prices** fetched only for open positions + today's active
   suggestions (yfinance `fast_info`, 5-minute-history fallback) — never the
   full universe.
3. **Entry plan** (`paper_trading/engine.plan_entries`):
   - Live NAV (capital, cash).
   - **Market pulse 0–100** (`risk/market_pulse.py`):
     SPY trend 60 pts (close>200DMA +20, close>50DMA +15, golden cross +10,
     MACD hist>0 +15) + **breadth** 40 pts (% of tracked stocks above their
     own 50DMA, computed from `daily_prices`). Pulse is also persisted to
     `market_pulse_log` for outcome analytics.
   - **Entries allowed today** = user's top-N cap (`app_settings`
     `max_entries_per_day`, default 5, editable from the Analytics page)
     scaled by a linear ramp: score <30 → 0 entries (sit out) · 30…85 →
     linear from 1 to N · ≥85 → full N.
4. **Entry loop**, T2 candidates first, then T1 by confidence:
   - **T2 exemption:** T2 entries don't consume top-N count slots (they are
     rare and heavily pre-screened) but respect every other rail, plus a
     hard `MAX_T2_ENTRIES_PER_DAY` (5) ceiling.
   - Skip if the symbol is already held.
   - **Budget check** (`per_trade_cash_cap`, section 7).
   - **Gap-chase guard:** skip if live price ran more than
     `MAX_ENTRY_GAP_PCT` (1.5 %) *in the trade's favour* past the signal
     entry — the scored setup no longer exists. Re-checked hourly, so an
     intraday pullback can still fill. Adverse gaps are not blocked.
   - Stop/target distances from the suggestion are **re-anchored** to the
     live entry price (preserves the ATR geometry).
   - Position sized (section 7) and the trade opened
     (`paper_trades` row, `original_stop`/`original_target` preserved).
5. Exit checks + mark-to-market + snapshot (section 6).

Counts are re-read from the DB each run, so successive hourly runs can never
exceed the daily caps.

---

## 6. Exit engine & dynamic trade management

An open trade can close through five paths:

| Exit | Where checked | Reason code |
|---|---|---|
| Stop breach at live price | hourly job | `STOP_HIT` |
| Target reached at live price | hourly job | `TARGET_HIT` |
| Stop/target at EOD close | nightly `update_open_trades` (DB prices, yfinance fallback) | `STOP_HIT` / `TARGET_HIT` |
| **Time exit** — held ≥ `MAX_HOLDING_DAYS` (14 calendar ≈ 10 trading) | both | `TIME_EXIT` |
| Manual close from the Portfolio page | `POST /api/paper-trades/{id}/close` | `MANUAL_CLOSE` |

### Nightly dynamic management (`paper_trading/trade_manager.py`)

Runs between EOD exits and the snapshot, on every surviving open position.
**Ratchets only — never loosens.** For LONG (mirrored for SHORT):

1. **Breakeven:** once profit ≥ `BREAKEVEN_AFTER_R` (1.0) × original risk,
   stop moves to at least the entry price.
2. **Chandelier trail:** when in profit, stop = *highest close since entry*
   − `TRAIL_STOP_ATR_MULT` (3.0) × ATR14. Only ever rises.
3. **Target extension:** when the trend is intact (close > SMA20 > SMA50 and
   MACD hist > 0) **and** ≥60 % of the move to target is captured, target is
   raised to close + `TARGET_EXTEND_ATR_MULT` (2.0) × ATR — strong trends
   don't get capped at the original level.

Adjustments stamp `levels_updated_at` + a human-readable `adjustment_note`
on the trade; the Portfolio card shows a blue ring, a "Levels updated" badge,
the struck-through original levels, and the note. The hourly job reads
stop/target from the DB, so adjusted levels are enforced automatically.

---

## 7. Position sizing & capital pacing

### Per-trade sizing (`risk/position_sizing.py`)

```
shares = min(  (RISK_PER_TRADE_PCT × capital) / |entry − stop|     ← risk budget (1 %)
             ,  position_value_cap / entry )                        ← see below
position_value_cap = min( MAX_POSITION_PCT × capital                ← 15 %
                        , per-trade cash cap from pacing rules )
```

A stop-out therefore loses at most ~1 % of capital; a single position never
exceeds 15 % of capital. Works for LONG and SHORT (absolute risk distance).

### Daily capital pacing (`paper_trading/engine.per_trade_cash_cap`)

- **Daily deployment budget:** at most `MAX_DAILY_DEPLOYMENT_PCT` (25 %) of
  capital put to work per day, split **evenly across the day's remaining
  allowed entries** (so the first entry can't starve the rest).
- **Cash reserve floor:** cash never drops below `MIN_CASH_RESERVE_PCT`
  (10 %) of capital.
- Combined with the 14-day time exit recycling capital, the account can
  never be locked out of trading.

NAV convention (mirrors `compute_nav`):
`cash = initial + Σ realized − Σ invested` · `total = cash + invested + unrealized`.

---

## 8. Database schema

Supabase PostgreSQL. Money columns are `numeric(12,4)`; scores are 0–100
integers; EOD dates are `date` (not timestamp).

| Table | Written by | Purpose / key columns |
|---|---|---|
| `stocks` | seed script, T2 scanner | Universe. `symbol` PK, `name`, `sector`, `tier` (T1/T2), `is_active`. 501 T1 rows seeded; T2 rows upserted as discovered. |
| `daily_prices` | ingest-service (nightly) | EOD OHLCV, ~30-day rolling window. Unique `(symbol, price_date)`. Also feeds breadth calc + live-snapshot pricing. |
| `suggestions` | synthesizer (nightly) | One row per signal: `tier`, `direction`, `confidence_score`, `entry_price`, `stop_loss`, `target_price`, `ta/sentiment/pattern_score`, `rationale` (Claude), `as_of_date`, `is_active` (false on bear-regime days or when superseded). |
| `paper_trades` | entry/exit engines, manual API | One row per trade. Entry/exit price+date, `shares`, `capital_at_risk` (= entry×shares), `stop_loss`/`target_price` (live, ratcheted), **`original_stop`/`original_target`** (entry-time levels), **`levels_updated_at`**, **`adjustment_note`**, `exit_reason`, `realized_pnl`, `is_open`. |
| `daily_pnl` | hourly + nightly MTM (upsert) | Per-trade daily mark-to-market: `close_price`, `unrealized_pnl`. Unique `(trade_id, pnl_date)`. Latest row per trade doubles as the live price source for the on-demand snapshot. |
| `portfolio_snapshots` | nightly + hourly (upsert on date) | Daily NAV: `total_capital`, `cash_balance`, `invested_capital`, `unrealized_pnl`, `realized_pnl_today`, `cumulative_realized_pnl`, `open_positions`. Feeds the equity curve. |
| `t1_scans` | save_t1_node (nightly) | Full TA snapshot per T1 stock per day (RSI, MACD, SMAs, ATR, patterns, all scores, `made_signal`). 30-day retention. |
| `t2_scans` | T2 scanner (nightly) | Screener output per candidate per day: `t2_score`, `signal_tier` (A/B/C), `rvol`, fundamentals, `risk_flags`, `news_summary`, `news_verdict`. 30-day retention. |
| `app_settings` | Analytics page via API | Runtime key-value overrides (created on first use). Currently: `max_entries_per_day`. Lets the UI change strategy knobs without redeploying. |
| `market_pulse_log` | entry planning (daily upsert) | Daily pulse snapshot: `score`, `label`, `breadth_pct`, SPY close/50DMA/200DMA. Preserves entry-time market context for outcome analysis. |
| `trade_outcomes` | outcome sync (on every close) | **The feedback-loop table** — one row per closed trade joining signal-time variables (confidence/ta/sentiment/pattern, T2 score/rvol/tier/news verdict), market context at entry (pulse, breadth), and results (`realized_pnl`, `return_pct`, **`r_multiple`** vs original planned risk, `exit_reason`, `holding_days`, `levels_adjusted`). |

Notes:
- `app_settings`, `market_pulse_log`, `trade_outcomes` use
  `CREATE TABLE IF NOT EXISTS` on first write — no Alembic migration needed.
- `paper_trades.capital_at_risk` is a legacy name: it holds **position value**
  (entry × shares), not the risk amount.

---

## 9. Configuration

All backend settings live in `backend/config.py` (pydantic-settings), read
from environment variables / `.env`. Defaults shown; every one is overridable
per Railway service.

### Credentials & infrastructure

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Supabase asyncpg connection string (PgBouncer port 6543; `statement_cache_size=0` handled in code) |
| `ANTHROPIC_API_KEY` | Claude — sentiment batch scoring + suggestion rationales |
| `FINNHUB_API_KEY` | News headlines for sentiment + T2 validation |
| `ALPHA_VANTAGE_API_KEY` | Legacy, unused for sentiment |
| `CORS_ORIGINS` | `*` in production (see section 2) |
| `NEXT_PUBLIC_API_URL` | Frontend → backend base URL (Vercel env var) |
| `LLM_MODEL` | `claude-sonnet-4-6` (rationales); sentiment uses Haiku |

### Strategy knobs (validated defaults)

| Variable | Default | Effect |
|---|---|---|
| `INITIAL_CAPITAL` | 100000 | Paper account start |
| `LONG_ONLY` | **true** | Skip SHORT signals entirely *(backtest: +18.0 % → +32.5 %)* |
| `RISK_PER_TRADE_PCT` | 0.01 | Stop-out loses ≤1 % of capital |
| `MAX_POSITION_PCT` | 0.15 | Max 15 % of capital in one stock |
| `MAX_DAILY_DEPLOYMENT_PCT` | 0.25 | Max 25 % of capital deployed per day |
| `MIN_CASH_RESERVE_PCT` | 0.10 | Cash floor never invested |
| `MAX_ENTRIES_PER_DAY` | 5 | Top-N ceiling (runtime-overridable via Analytics page) |
| `MAX_T2_ENTRIES_PER_DAY` | 5 | Hard cap on count-exempt T2 entries |
| `MAX_OPEN_POSITIONS` | 0 | 0 = unlimited total open positions |
| `MAX_HOLDING_DAYS` | 14 | Time exit (calendar days; 0 = off) *(21d tested worse)* |
| `ATR_STOP_MULT` | 1.5 | Stop distance ×ATR14 *(2.5 tested worse)* |
| `ATR_TARGET_MULT` | 3.0 | Target distance ×ATR14 (2:1 reward:risk) |
| `T1/T2_STOP_LOSS/TARGET_PCT` | 2/4, 4/10 % | Fallback only, when ATR missing |
| `REGIME_FILTER_ENABLED` / `REGIME_SYMBOL` | true / SPY | Bear regime (SPY<200DMA) → suggestions inactive |
| `AUTO_ENTRY_MODE` | intraday | `intraday` = enter next morning at live prices via hourly job; `nightly` = enter right after agents run (fallback if hourly service is absent) |
| `T1_MIN_EARNINGS_DAYS` | 8 | Drop T1 signals reporting within N days (0 = off) |
| `MAX_ENTRY_GAP_PCT` | 0.015 | Gap-chase guard threshold (0 = off) |
| `DYNAMIC_EXITS_ENABLED` | true | Nightly trailing/breakeven/extension |
| `TRAIL_STOP_ATR_MULT` | 3.0 | Chandelier trail width |
| `TARGET_EXTEND_ATR_MULT` | 2.0 | Target extension distance |
| `BREAKEVEN_AFTER_R` | 1.0 | Move stop to entry after +1R |
| `T2_*` (12 vars) | see `.env.example` | T2 screener thresholds (market cap, RVOL, price, float, scores…) |

### Runtime settings (`app_settings` table — no redeploy)

| Key | Set from | Effect |
|---|---|---|
| `max_entries_per_day` | Analytics page "Top-N trades per day" | Overrides `MAX_ENTRIES_PER_DAY` at every entry run |

---

## 10. API endpoints

Base: `https://swing-trading-system-production.up.railway.app`. All responses
use the `{ data, error, timestamp }` envelope.

| Endpoint | Purpose |
|---|---|
| `GET /health` | Health check (Railway monitor) |
| `GET /api/suggestions/?date&tier&action&active_only` | Signals list |
| `GET /api/suggestions/persistent?window=7&min_days=3` | **Repeat picks** — symbols surfaced ≥3 of last 7 days across suggestions + T2 scans |
| `GET /api/suggestions/{id}` | Single suggestion |
| `GET /api/paper-trades/?status=open\|closed\|all` | Trades |
| `POST /api/paper-trades/` | Open trade from a suggestion (auto-sized if `shares` omitted) |
| `POST /api/paper-trades/{id}/close` | Manual close at given price |
| `GET /api/portfolio/snapshot` | **Live NAV** (no date param → computed on demand: buys reduce cash instantly) |
| `GET /api/portfolio/snapshot?date=` | Persisted snapshot for a day |
| `GET /api/portfolio/positions` | Open positions |
| `GET /api/portfolio/history?days=` | Snapshot series (equity curve) |
| `GET /api/analytics/summary` | Capital / trade / per-tier / suggestion stats |
| `GET /api/analytics/market-pulse` | Today's pulse + entries allowed |
| `GET /api/analytics/pulse-history?days=` | Daily pulse log (timeline strip) |
| `GET /api/analytics/outcomes` | **Outcome analytics** — win rate / avg R / MFE / MAE / exit efficiency / post-exit follow-through bucketed by every signal variable |
| `POST /api/backtest/run` · `GET /api/backtest/status` | **In-browser backtesting** — start a run (409 if one is active), poll for progress/result. Runs in a worker thread on the web service; sample capped at 250 symbols for memory. Last result held in process memory. |
| `GET /api/strategy-settings/` · `PUT` | Read/update runtime knobs (top-N) |
| `GET /api/t1-scans/?days&signal_only` | T1 scan history |
| `GET /api/t2-scans/?days` · `/count` · `/universe` | T2 scan history · row-count diagnostic · live Stage-0 universe preview |
| `GET /api/stocks/?tier=` | Universe list |
| `GET /api/prices/latest?symbols=` | Latest close per symbol |
| `GET /api/financials/{symbol}` · `/?symbols=` | On-demand fundamental snapshot + Claude read |

---

## 11. Frontend pages

Next.js 14 App Router, dark-mode PWA, SWR polling.

| Page | Contents |
|---|---|
| `/suggestions` (Signals) | Tabs: **AI Signals** (cards with confidence bar, sub-scores, ATR stop/target, R:R, rationale, Open-Trade button, 🔥 persistence badge + "Repeat picks" strip) · **T1 Scan History** · **T2 Scan History** (tier badges, risk flags, news verdicts) |
| `/portfolio` | 6-card capital summary (live NAV) · open positions (progress bar stop→entry→target, unrealized P&L, **"Levels updated" badge with struck-through originals**, Sell/Close) · closed trades (P&L, exit reason incl. TIME_EXIT) |
| `/analytics` | Two tabs. **Performance:** strategy card (editable top-N + live pulse row) · 30-day pulse timeline strip · capital + trade stats · **outcome explorer** (win rate / avg R per bucket of any signal variable) · **exit-tuning card** (MFE/MAE/efficiency/post-exit per exit reason, with auto-generated insights at n≥10) · T1-vs-T2 win rates · signal coverage. **Backtest:** parameter form (dates, top-N, min-confidence, sample, exit mode, long-only, ATR/holding overrides) → run with live progress → results with metrics grid + equity-vs-SPY chart + exit breakdown |
| `/financials` | Ad-hoc fundamental lookup per ticker |

---

## 12. Backtesting harness

`backend/backtest/run_backtest.py` — replays history through the **same
rules** the live system trades. Runs two ways: the CLI below, or from the
**Analytics → Backtest tab** (which calls `POST /api/backtest/run`; one run
at a time, sample ≤250, progress polled every 3 s).

```bash
make backtest                                   # 2 years, all 501, top-5
cd backend && python -m backtest.run_backtest \
    --start 2024-07-01 --end 2026-07-01 \
    --top-n 5 --min-confidence 63 --sample 150 \
    --exit-mode intrabar --long-only
# any strategy env var overrides too:
ATR_STOP_MULT=2.0 python -m backtest.run_backtest --long-only
```

**What it replays faithfully** (imports the production functions where pure):
next-morning-open entries, ATR stops/targets with identical clamps, regime
filter, market pulse + linear exposure ramp (breadth from the same universe),
risk sizing + daily budget + cash reserve (`EntryPlan`/`per_trade_cash_cap`),
gap-chase guard, chandelier/breakeven/target-extension, 14-day time exits.
`--exit-mode intrabar` (default) checks stops against each day's **low/high**
— harsher and more realistic than the live EOD check; `--exit-mode close`
reproduces the live engine exactly.

**Documented divergences** (no historical snapshots exist): sentiment fixed
at neutral 50 · T2 screener excluded (T1 strategy only) · earnings gate off.

**Mechanics:** downloads OHLCV once via yfinance (cached in
`backend/backtest/.cache/*.pkl`), vectorises all indicator/score math
(mirrors ta_agent + pattern + synthesizer), simulates day by day, prints a
summary (return, CAGR, max drawdown vs SPY buy-&-hold, win rate, profit
factor, exits by reason, signals/day, avg pulse) and writes
`backtest_results/trades_*.csv` + `equity_*.csv`. Both dirs are gitignored.

---

## 13. Outcome analytics

The live feedback loop for the variables the backtest **cannot** test
(sentiment, T2 screener, news verdicts):

- Every day the entry planner logs the market pulse to `market_pulse_log`.
- Every trade close triggers `sync_trade_outcomes()`
  (`paper_trading/outcomes.py`) — an **idempotent backfill** that writes one
  `trade_outcomes` row per closed trade (missed calls self-heal on the next
  nightly run).
- Analyze via `GET /api/analytics/outcomes` (bucketed win rate / avg
  R-multiple / total P&L per variable) or SQL directly, e.g.:

```sql
-- Does the sentiment score actually predict profitability?
SELECT width_bucket(sentiment_score, 0, 100, 5) AS bucket,
       COUNT(*), ROUND(AVG(r_multiple), 2) AS avg_r
FROM trade_outcomes GROUP BY 1 ORDER BY 1;

-- Is the Claude news verdict worth anything on T2 trades?
SELECT news_verdict, COUNT(*), AVG(r_multiple)
FROM trade_outcomes WHERE tier = 'T2' GROUP BY 1;
```

Meaningful bucket sizes need ~50–100 closed trades (≈2–3 months at the
current entry rate).

---

## 14. Features not visible in the frontend

Things that exist and run but have no UI surface:

1. **Market regime filter** — bear-market suggestions persist as inactive
   (only side effect visible: empty "Active only" signal list).
2. **Linear pulse→entries ramp** — the Analytics card shows today's number,
   but the scaling logic/thresholds live in `risk/market_pulse.py`.
3. **T2 count-exemption + 5/day hard cap** — entry-queue behaviour only
   observable in Railway logs.
4. **T1 earnings gate** — dropped candidates are logged, never displayed.
5. **Gap-chase guard** — skipped entries appear only in hourly-job logs.
6. **Capital pacing** (daily budget split, cash reserve) — enforced silently.
7. **Time exits** — visible only as a TIME_EXIT chip on closed trades.
8. **Outcome analytics tables** — API/SQL only.
9. **Backtest harness** — local CLI only.
10. **`app_settings` runtime store** — generic key-value; only top-N is
    currently exposed in the UI.
11. **Idempotent upserts everywhere** (DailyPnL, snapshots, pulse log) — the
    hourly and nightly jobs can overlap or re-run without duplicates.
12. **Fail-open philosophy** — regime/pulse/earnings/breadth checks degrade
    to permissive defaults on data-source outages (logged as warnings), so a
    yfinance hiccup throttles rather than halts the system.

---

## 15. Operations

### Manual triggers (local, uses `.env`)

```bash
python backend/jobs/ingest.py                 # EOD ingest now
python backend/jobs/run_agents.py             # full nightly pipeline now
python backend/jobs/intraday_update.py --force  # hourly cycle, skip hours guard
make backtest                                 # backtest
make test / make lint / make fmt              # QA
```

### Logs & diagnostics

- Cron run logs: Railway dashboard → service → **Cron Runs** → click a run
  (the CLI `railway logs` does not return cron-execution logs).
- API smoke tests: `/health`, `/api/t2-scans/count`,
  `/api/analytics/market-pulse`.
- Deploy failures: see `railway_deploy_troubleshooting` notes — the three
  historical failure modes were (a) domain generated on a cron service,
  (b) PEP 668 pip failure (fixed by venv in `nixpacks.toml` at repo root),
  (c) CORS/trailing-slash issues between Vercel and Railway.

### Full paper-trading reset

```sql
DELETE FROM daily_pnl;          -- FK order matters
DELETE FROM trade_outcomes;
DELETE FROM paper_trades;
DELETE FROM portfolio_snapshots;
-- capital automatically reads INITIAL_CAPITAL again (NAV is derived, not stored)
```

### Adding a strategy knob (pattern)

1. Add field to `backend/config.py` with default + comment.
2. Document in `.env.example`.
3. If runtime-changeable from the UI: read via
   `db.app_settings.get_int_setting(key, settings.default)` and expose in
   `api/routes/strategy_settings.py`.
4. **Backtest it before changing the default** (section 12).

---

## 16. Decision log

Parameters chosen by **evidence**, not preference. Full 501-stock, 2-year
backtests (2024-07 → 2026-07, intrabar exits):

| Experiment | Result | Decision |
|---|---|---|
| Baseline (with shorts) | +18.0 %, maxDD −14.4 %, PF 1.14 | replaced |
| **Long-only** | **+32.5 %, maxDD −10.3 %, PF 1.26** | **adopted (`LONG_ONLY=true`)** — shorts netted ~$0 directly but consumed slots/budget from winning longs |
| Long-only + 2.5×ATR stops | +26.1 %, win rate 50.9 % | rejected — higher win rate but lower return (bigger risk/share → smaller positions) |
| Long-only + 21-day time exit | +27.3 % | rejected — 14 days better |
| Long-only + spike filter sweep (0/2.5/3/3.5 %) | 2.5 %: +32.9 %, maxDD −9.22 % · 3 %: +31.1 %, −8.41 % · 3.5 %: +31.3 %, −9.15 % | **2.5 % adopted** (`T1_MAX_SIGNAL_DAY_GAIN_PCT=0.025`) — only setting that dominates no-filter on return AND drawdown AND trade count (XOM post-mortem, 2026-07-10; grounded in the short-term reversal literature: Lehmann 1990, Jegadeesh 1990) |
| SPY buy & hold (benchmark) | +36.8 %, deeper drawdown | system trades ~4 pts of return for roughly half the drawdown |

Earlier design lessons encoded in code:
- **XOM** (bought the morning after a +3.9 % pop; move mean-reverted, −1.06R) → T1 spike filter.
- **SEM** (Yahoo data frozen for a week; screener signalled at a stale price) → data-freshness gates in both scanners.
- **AMBA** (earnings gap −20 %) → 8-day earnings gates (T2 stage 2, T1 synthesizer).
- **BEAM** (high RVOL on a selloff) → falling-knife filter (reject >3 % down days).
- **LEGN** (stale static list) → live Yahoo universe for T2.
- Discrete exposure tiers couldn't produce 4-of-5 entries → linear ramp.
- Fixed-% stops ignored volatility → ATR-based with clamps.

---

*End of document. Keep this file updated with every behavioural change — it
is the single source of truth for how the system trades.*
