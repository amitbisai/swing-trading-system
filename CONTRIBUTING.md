# Contributing

## Local setup

### Prerequisites
- Python 3.11+
- Node.js 18+
- A Supabase project (free tier is fine)
- An Anthropic API key (for the agent synthesizer)

### First-time setup

```bash
# 1. Clone the repo
git clone https://github.com/amitbisai/swing-trading-system.git
cd swing-trading-system

# 2. Copy the env template and fill in your values
cp .env.example .env
# Edit .env — at minimum set DATABASE_URL and ANTHROPIC_API_KEY

# 3. Install all dependencies
make install

# 4. Run database migrations (requires Supabase DATABASE_URL to be set)
cd backend && alembic upgrade head && cd ..

# 5. Seed the stock universe (147 S&P 500 Tier-1 stocks)
python scripts/seed_stocks.py

# 6. Fetch today's prices and generate signals
make ingest    # pulls 30d OHLCV from yfinance → daily_prices table
make agents    # runs AI orchestrator → suggestions table

# 7. Start dev servers
make dev       # backend on :8000, frontend on :3000
```

### Daily commands

```bash
make dev       # start backend + frontend
make ingest    # run EOD ingest manually
make agents    # generate today's AI signals
make test      # run pytest (mocked DB — no Supabase needed)
make lint      # ruff check on backend/
make fmt       # auto-fix formatting (black + ruff --fix)
make push      # interactive: stage all → prompt for message → push to main
```

---

## Branch naming

All branches must use one of these prefixes:

| Prefix | Use for |
|---|---|
| `feature/` | New functionality — new page, new API endpoint, new agent capability |
| `fix/` | Bug fixes — incorrect calculation, broken UI, failed query |
| `data/` | Data pipeline changes — fetcher, ingest job, DB schema, migrations |
| `agent/` | AI agent changes — orchestrator, scanner, TA, sentiment, pattern, synthesizer |

**Format:** `<prefix>/<short-slug>`

```bash
git checkout -b feature/tier-comparison-chart
git checkout -b fix/stop-loss-short-direction
git checkout -b data/backfill-historical-prices
git checkout -b agent/pattern-doji-detection
```

Avoid generic names: `main`, `dev`, `test`, `wip`, or bare numbers.

---

## Workflow

### For a new feature

```bash
# 1. Branch off main
git checkout main && git pull origin main
git checkout -b feature/my-feature

# 2. Make changes and commit as you go
git add -A && git commit -m "Add RSI divergence filter to TA agent"

# 3. Push and open a PR on GitHub
git push -u origin feature/my-feature
# → Open PR at https://github.com/amitbisai/swing-trading-system/pulls
# → All CI checks must pass before merging

# 4. Merge options:
#    A. Via GitHub PR (preferred — creates a record)
#    B. Locally:
git checkout main
git merge feature/my-feature --no-ff
git push origin main
git branch -d feature/my-feature
```

### Quick one-liner push (for small fixes on main)

```bash
make push     # stages everything, prompts for message, pushes to main
```

---

## Commit messages

Use imperative mood, present tense. No ticket numbers in the message.

```
Add T1 vs T2 win rate comparison chart
Fix unrealized P&L sign for SHORT positions
Bump yfinance to 0.2.40
Remove stale MMC ticker from seed list
```

Conventional prefix is optional but welcome:

```
feat: add confidence bar to suggestion card
fix: stop-loss direction inverted for SHORT trades
data: add avg_volume_20d column to daily_prices
chore: update CI to Node 18
```

---

## CI

GitHub Actions runs on every push to `main` and every PR:

| Job | Steps |
|---|---|
| **Backend (Python 3.11)** | `ruff check` → `black --check` → `pytest` |
| **Frontend (Node 18)** | `tsc --noEmit` → `next build` |

All checks must be green before merging. Tests use a mocked DB — no live
Supabase connection is needed in CI.

---

## Environment variables

Copy `.env.example` → `.env`. Never commit `.env`.

| Variable | Required | Notes |
|---|---|---|
| `DATABASE_URL` | Yes | `postgresql+asyncpg://...` Supabase connection string |
| `ANTHROPIC_API_KEY` | Yes | For the LLM synthesizer agent |
| `ALPHA_VANTAGE_API_KEY` | No | Sentiment agent falls back to score=50 if absent |
| `SUPABASE_URL` | No | Only needed if using the Supabase Python client directly |
| `SUPABASE_KEY` | No | Supabase service role key |
| `INITIAL_CAPITAL` | Yes | Starting paper portfolio value (e.g. `100000`) |
| `ENVIRONMENT` | No | `development` \| `production` |
