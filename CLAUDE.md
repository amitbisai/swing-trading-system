# Swing Trading System — Project Context

## What this is
An AI-powered swing trading suggestion system for medium-term positions (3–14 days).
No broker integration. Paper trading only (EOD price simulation).
Mobile-first PWA frontend. No active intraday trading.

## Architecture decisions
- **Two-tier stock universe:**
  - Tier 1: 147 large-cap liquid stocks (S&P 500). Lower risk.
  - Tier 2: Dynamic daily screen for high-volume momentum stocks (volume > 3× 20d avg). Higher risk.
- **Data:** yfinance for daily OHLCV (primary). Alpha Vantage free tier for sentiment (25 calls/day, optional).
- **AI agents:** LangGraph orchestrator → 4 parallel sub-agents (Scanner, TA, Sentiment, Pattern) → LLM synthesizer (Claude claude-sonnet-4-6). 30s timeout per agent.
- **Risk engine:** T1 stop-loss 2% / target 4%. T2 stop-loss 4% / target 10%. Max 2% capital per trade. Max 8 open positions.
- **Paper trading:** Entry at next-day open. Exit at EOD close. Daily mark-to-market. No broker API.
- **Database:** Supabase (PostgreSQL). 6 tables: stocks, daily_prices, suggestions, paper_trades, daily_pnl, portfolio_snapshots.
- **Backend:** FastAPI (Python 3.12). Hosted on Railway or Render.
- **Frontend:** Next.js 14 PWA. Hosted on Vercel.
- **Scheduler:** Celery + Redis. Nightly ingest at 21:30 UTC, agents at 22:00 UTC (Mon–Fri).

## Stack
- Python 3.12 (backend, agents, data pipeline)
- FastAPI + uvicorn
- LangGraph + LangChain + Anthropic SDK
- SQLAlchemy (async) + asyncpg + Alembic
- yfinance, pandas, pandas-ta
- Next.js 14 + Tailwind CSS + recharts + SWR
- Supabase (hosted PostgreSQL)
- Celery + Redis

## Key conventions
- All money values stored as `numeric(12,4)` in DB — never floats; use `Decimal` in Python
- Scores always 0–100 integers
- Dates always stored as `date` (not timestamp) for EOD data
- Agent outputs must be Pydantic models — no raw dicts passed between agents
- All API endpoints return `{ data, error, timestamp }` envelope
- Environment variables in `.env` (never committed). See `.env.example`.
- Python: black formatter (line-length 100), ruff linter
- TypeScript: strict mode, no `any`

## Commands
```bash
make dev          # start backend (port 8000) + frontend (port 3000)
make ingest       # run EOD data ingest now  (calls python -m data.ingest)
make agents       # run orchestrator manually for today
make lint         # ruff + black --check
make fmt          # black + ruff --fix
make install      # pip install -e ".[dev]" + npm install
pytest            # run all tests (mocked DB, no live Supabase needed)
cd frontend && npm run type-check   # TypeScript strict check
```

---

## Actual file structure (as of 2026-05-15)

```
swing-trading-system/
├── .env.example                    # template — copy to .env and fill in
├── .gitignore
├── .github/
│   └── workflows/
│       └── ci.yml                  # GitHub Actions: pytest + ruff + next build
├── CLAUDE.md                       # this file
├── CONTRIBUTING.md                 # branch naming, commit style, workflow
├── Makefile                        # dev shortcuts
├── pyrightconfig.json              # points pyright at backend/
├── pytest.ini                      # asyncio_mode=auto, testpaths=tests, pythonpath=backend
├── read-me.txt                     # quick-start notes
│
├── backend/
│   ├── pyproject.toml              # hatchling build, all deps, black/ruff config
│   ├── alembic.ini                 # script_location = db/migrations
│   ├── config.py                   # pydantic-settings Settings (DATABASE_URL, API keys, etc.)
│   ├── main.py                     # FastAPI app factory, 5 routers, global error handler
│   │
│   ├── agents/
│   │   ├── models.py               # Pydantic I/O models: AgentInputBundle, ScannerOutput,
│   │   │                           #   TAOutput, SentimentOutput, PatternOutput, SynthesisOutput
│   │   ├── orchestrator.py         # LangGraph StateGraph: scan → analyze (parallel) → synthesize
│   │   ├── scanner.py              # T1 DB query + T2 momentum screener; upserts T2 stocks
│   │   ├── ta_agent.py             # RSI + MACD + SMA composite score (90d window)
│   │   ├── sentiment.py            # Alpha Vantage news sentiment → 0–100; early-exit if no key
│   │   ├── pattern.py              # Candlestick patterns + trend + volume breakout detection
│   │   └── synthesizer.py          # Claude LLM call → rationale + final suggestion rows
│   │
│   ├── api/
│   │   ├── dependencies.py         # get_db() async generator for FastAPI Depends
│   │   ├── schemas.py              # ApiResponse[T], SuggestionOut, PaperTradeOut,
│   │   │                           #   OpenTradeRequest/Response, PortfolioSnapshotOut,
│   │   │                           #   AnalyticsSummary (nested CapitalStats/TradeStats/SuggestionStats)
│   │   └── routes/
│   │       ├── suggestions.py      # GET /api/suggestions/?date&tier&action&active_only
│   │       │                       # GET /api/suggestions/{id}
│   │       ├── paper_trades.py     # GET /api/paper-trades/?status=open|closed|all
│   │       │                       # POST /api/paper-trades/ (open trade, auto-size, 409 on dupe)
│   │       ├── portfolio.py        # GET /api/portfolio/snapshot?date
│   │       │                       # GET /api/portfolio/history?days=30
│   │       ├── analytics.py        # GET /api/analytics/summary (single-query aggregates)
│   │       └── stocks.py           # GET /api/stocks/?tier=T1|T2
│   │
│   ├── data/
│   │   ├── fetcher.py              # fetch_ohlcv(tickers, start, end) → dict[str, DataFrame]
│   │   │                           #   7 columns: Open High Low Close AdjClose Volume avg_volume_20d
│   │   │                           #   batches at 100, handles MultiIndex, drops delisted tickers
│   │   ├── ingest.py               # module entry point used by `make ingest`
│   │   └── alpha_vantage.py        # Alpha Vantage news sentiment fetcher (rate-limited)
│   │
│   ├── db/
│   │   ├── models.py               # 6 SQLAlchemy ORM models:
│   │   │                           #   Stock, DailyPrice, Suggestion, PaperTrade, DailyPnL,
│   │   │                           #   PortfolioSnapshot — all with FK constraints + indexes
│   │   ├── session.py              # async_session_factory + get_db() generator
│   │   ├── seed.py                 # 147 S&P 500 T1 stocks with ON CONFLICT DO UPDATE
│   │   └── migrations/
│   │       ├── env.py              # Alembic async env — load_dotenv + create_async_engine
│   │       ├── script.py.mako
│   │       └── versions/
│   │           └── 0001_initial_schema.py   # creates all 6 tables + indexes; downgrade drops in reverse FK order
│   │
│   ├── paper_trading/
│   │   ├── engine.py               # open_trade(), update_open_trades(), get_portfolio_snapshot()
│   │   │                           #   NAV: cash = initial + cumulative_realized - invested
│   │   │                           #        total = cash + invested + unrealized_pnl
│   │   └── mark_to_market.py       # check_exit(close, stop, target, direction) → "STOP_HIT"|"TARGET_HIT"|None
│   │
│   ├── risk/
│   │   ├── position_sizing.py      # auto-size shares: max 2% capital at risk per trade
│   │   └── stop_target.py          # T1: stop -2% / target +4%. T2: stop -4% / target +10%
│   │
│   └── scheduler/
│       ├── ingest_job.py           # run_ingest(as_of?) — fetches 30d OHLCV, upserts daily_prices
│       │                           #   run standalone: python -m scheduler.ingest_job
│       ├── tasks.py                # Celery task definitions (run_nightly_ingest, run_nightly_agents)
│       └── jobs.py                 # Celery Beat schedule:
│                                   #   21:30 UTC Mon–Fri → ingest (3:00 AM IST)
│                                   #   22:00 UTC Mon–Fri → agents (3:30 AM IST)
│
├── frontend/
│   ├── next.config.js              # try/catch wraps next-pwa (graceful if not installed)
│   ├── tailwind.config.ts          # dark slate-900/800/700 palette
│   ├── postcss.config.js
│   ├── tsconfig.json               # strict mode, path alias @/ → ./
│   ├── package.json                # Next 14, SWR, recharts, lucide-react, tailwind, next-pwa
│   │
│   ├── public/
│   │   └── manifest.json           # PWA manifest (name, icons, theme_color #0f172a)
│   │
│   ├── app/                        # Next.js App Router
│   │   ├── globals.css             # dark-first: bg-slate-900, color-scheme: dark
│   │   ├── layout.tsx              # RootLayout — integrates <Nav />, pb-20 sm:pb-0
│   │   ├── page.tsx                # / → redirect to /suggestions
│   │   ├── suggestions/
│   │   │   └── page.tsx            # filter pills (T1/T2, LONG/SHORT, active-only)
│   │   │                           #   2-col grid of SuggestionCard
│   │   ├── portfolio/
│   │   │   └── page.tsx            # stats bar + open/closed tabs
│   │   │                           #   PositionCard (open) | ClosedPositionCard (closed)
│   │   └── analytics/
│   │       └── page.tsx            # capital stats + EquityCurveChart + trade stats
│   │                               #   + TierComparisonChart + signal coverage
│   │
│   ├── components/
│   │   ├── nav.tsx                 # desktop top bar + mobile fixed bottom tab bar
│   │   ├── stat-card.tsx           # metric card with positive/negative/mono variants
│   │   ├── suggestion-card.tsx     # ConfidenceBar + ScorePill + price grid + "Open Trade" button
│   │   ├── position-card.tsx       # PositionCard (stop→entry→target progress bar)
│   │   │                           # ClosedPositionCard (realized P&L + exit reason)
│   │   ├── analytics-chart.tsx     # EquityCurveChart — recharts AreaChart of cumulative P&L
│   │   ├── tier-comparison.tsx     # TierComparisonChart — recharts BarChart T1 vs T2 win rate
│   │   ├── portfolio-table.tsx     # legacy table component (kept for reference)
│   │   └── ui/                     # reserved for shadcn/ui primitives (empty)
│   │
│   └── lib/
│       ├── api.ts                  # SWR hooks: useSuggestions, usePaperTrades, usePortfolioSnapshot,
│       │                           #   usePortfolioHistory, useAnalyticsSummary, useStocks
│       │                           #   Mutation: openTrade(suggestion_id, shares?)
│       ├── types.ts                # TypeScript interfaces matching API shapes:
│       │                           #   Suggestion, PaperTrade, PortfolioSnapshot, AnalyticsSummary, …
│       └── utils.ts                # cn(), formatCurrency(), formatPct(), formatChange(), daysSince()
│
├── scripts/
│   ├── seed_stocks.py              # one-off: populate stocks table (calls db/seed.py)
│   └── setup_db.py                 # one-off: create tables via SQLAlchemy metadata
│
└── tests/
    ├── conftest.py                 # session-scoped AsyncClient with mocked DB (no live Supabase)
    ├── test_api.py                 # API endpoint smoke tests
    ├── test_agents.py              # agent output model validation
    └── test_risk.py                # position sizing + stop/target calculations
```

## Database schema (Supabase PostgreSQL)

| Table | Key columns |
|---|---|
| `stocks` | symbol PK, name, sector, tier (T1/T2), is_active |
| `daily_prices` | (symbol, price_date) UK, open/high/low/close/adj_close numeric(12,4), volume bigint |
| `suggestions` | id, symbol FK, tier, direction, confidence_score, entry/stop/target prices, ta/sentiment/pattern scores, rationale, is_active |
| `paper_trades` | id, suggestion_id FK, shares, capital_at_risk, entry/exit price & date, exit_reason, realized_pnl, is_open |
| `daily_pnl` | trade_id FK, pnl_date, close_price, unrealized_pnl |
| `portfolio_snapshots` | snapshot_date, total/cash/invested capital, unrealized_pnl, cumulative_realized_pnl |

## Environment variables (see .env.example)

```
DATABASE_URL=postgresql+asyncpg://...        # Supabase connection string
ANTHROPIC_API_KEY=sk-ant-...                 # required for synthesizer agent
ALPHA_VANTAGE_API_KEY=                       # optional — sentiment falls back to score=50
INITIAL_CAPITAL=100000
MAX_OPEN_POSITIONS=8
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
NEXT_PUBLIC_API_URL=http://localhost:8000    # frontend env var
```

## Nightly data flow

```
21:30 UTC (3:00 AM IST) — Celery Beat fires run_nightly_ingest
  └─ scheduler/ingest_job.py
       └─ data/fetcher.py → yfinance bulk download → upsert daily_prices

22:00 UTC (3:30 AM IST) — Celery Beat fires run_nightly_agents
  └─ agents/orchestrator.py (LangGraph)
       ├─ scanner.py         → selects T1 stocks + screens T2 momentum
       ├─ ta_agent.py   ┐
       ├─ sentiment.py  ├── parallel, 30s timeout each
       ├─ pattern.py    ┘
       └─ synthesizer.py    → Claude LLM → writes suggestions table
```

## Manual triggers (no Celery needed)

```bash
# From backend/
python -m scheduler.ingest_job    # fetch today's prices
python -m agents.orchestrator     # generate today's signals
```
