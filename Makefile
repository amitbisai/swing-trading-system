.PHONY: dev ingest agents test lint fmt install push

# ── Dev servers ───────────────────────────────────────────────────────────────
# Starts backend + frontend together.
# On Windows: if & doesn't work in your shell, open two terminals instead:
#   Terminal 1: cd backend && uvicorn main:app --reload --port 8000
#   Terminal 2: cd frontend && npm run dev
dev:
	cd backend && uvicorn main:app --reload --port 8000 &
	cd frontend && npm run dev

# ── Data pipeline ─────────────────────────────────────────────────────────────
ingest:
	python backend/jobs/ingest.py

# ── Agent orchestrator ────────────────────────────────────────────────────────
agents:
	cd backend && python -m agents.orchestrator

# ── Tests ─────────────────────────────────────────────────────────────────────
test:
	pytest tests/ -v

# ── Code quality ──────────────────────────────────────────────────────────────
lint:
	cd backend && ruff check .

fmt:
	cd backend && black . && ruff check --fix .

# ── Install all deps ──────────────────────────────────────────────────────────
install:
	cd backend && pip install -e ".[dev]"
	cd frontend && npm install

# ── Git: stage, commit (interactive), push ────────────────────────────────────
# Usage: make push
# You will be prompted to type a commit message, then Enter.
push:
	git add -A
	@read -p "Commit message: " msg && git commit -m "$$msg"
	git push origin main
