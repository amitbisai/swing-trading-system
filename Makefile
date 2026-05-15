.PHONY: dev test ingest agents lint fmt install

# ── Dev servers ───────────────────────────────────────────────────────────────
# On Unix/WSL/Git Bash: starts backend in background, frontend in foreground.
# On Windows cmd: open two terminals and run each command separately.
dev:
	cd backend && uvicorn main:app --reload --port 8000 &
	cd frontend && npm run dev

# ── Tests ─────────────────────────────────────────────────────────────────────
test:
	pytest tests/ -v

# ── Data pipeline (run manually) ──────────────────────────────────────────────
ingest:
	cd backend && python -m data.ingest

# ── Agent orchestrator (run manually for today) ───────────────────────────────
agents:
	cd backend && python -m agents.orchestrator

# ── Code quality ──────────────────────────────────────────────────────────────
lint:
	cd backend && ruff check . && black --check .

fmt:
	cd backend && black . && ruff check --fix .

# ── Install all deps ──────────────────────────────────────────────────────────
install:
	cd backend && pip install -e ".[dev]"
	cd frontend && npm install
