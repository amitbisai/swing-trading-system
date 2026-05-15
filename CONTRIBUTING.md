# Contributing

## Branch naming

All branches must use one of these prefixes:

| Prefix | Use for |
|---|---|
| `feature/` | New functionality (new page, new agent capability, new API endpoint) |
| `fix/` | Bug fixes (incorrect calculation, broken UI, failed query) |
| `data/` | Data pipeline changes (fetcher, ingest job, DB schema, migrations) |
| `agent/` | AI agent changes (orchestrator, scanner, TA, sentiment, pattern, synthesizer) |

**Format:** `<prefix>/<short-slug>`

```
feature/tier-comparison-chart
fix/stop-loss-short-direction
data/backfill-historical-prices
agent/pattern-doji-detection
```

Avoid `main`, `master`, `dev`, or bare issue numbers as branch names.

## Workflow

1. Branch off `main` using the naming convention above.
2. Keep branches focused — one logical change per PR.
3. All CI checks must pass before merging (pytest, ruff, Next.js build).
4. Squash-merge into `main`.

## Commit messages

Use the imperative mood, present tense:

```
Add T1 vs T2 win rate comparison chart
Fix unrealized P&L sign for SHORT positions
Bump yfinance to 0.2.40
```

No ticket numbers in commit messages — put those in the PR description.

## Local setup

```bash
# Install all dependencies
make install

# Start backend + frontend
make dev

# Run tests
pytest

# Run linters
make lint

# Auto-fix formatting
make fmt
```

## CI

GitHub Actions runs on every push to `main` and every PR:

- **Backend:** `ruff` lint → `black` format check → `pytest`
- **Frontend:** TypeScript type-check → `next build`

Fix any failures before requesting review.

## Environment variables

Copy `.env.example` to `.env` and fill in your values. Never commit `.env`.

Required for local development:

```
DATABASE_URL=postgresql+asyncpg://...
ANTHROPIC_API_KEY=sk-ant-...
ALPHA_VANTAGE_API_KEY=        # optional — sentiment agent falls back to score=50
INITIAL_CAPITAL=100000
```
