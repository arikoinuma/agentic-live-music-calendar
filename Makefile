# Local development entry points.
#
# The goal is that "run the app" is one command rather than three
# terminals and a remembered incantation. `make dev` is that command;
# everything else here exists because some part of it is occasionally
# needed on its own.
#
# Not a build system — Turborepo handles the JS task graph and uv
# handles Python. This is a front door to both, plus Docker.

SHELL := /bin/bash
API_DIR := apps/api
WEB := calendar

.DEFAULT_GOAL := help
.PHONY: help setup dev api web db db-up db-down db-reset db-shell db-wait worker eval-graph \
        migrate migration seed fixtures types contract-check designation-check test coverage lint typecheck \
        e2e check clean

help: ## Show this help
	@echo "Agentic Live Music Calendar — local development"
	@echo
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'
	@echo

# ---------------------------------------------------------------------
# First run
# ---------------------------------------------------------------------

setup: ## First-time setup: install deps, start Postgres, migrate
	@test -f $(API_DIR)/.env || { \
		echo "Creating $(API_DIR)/.env from .env.example"; \
		cp $(API_DIR)/.env.example $(API_DIR)/.env; \
	}
	pnpm install
	cd $(API_DIR) && uv sync
	$(MAKE) db-up db-wait migrate seed
	@echo
	@echo "Setup complete. Run 'make dev'."

# ---------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------

dev: db-up db-wait ## Run Postgres + FastAPI + Next.js together
	@echo "  API  -> http://localhost:8000  (docs at /docs)"
	@echo "  Web  -> http://localhost:3000"
	@echo "  Ctrl-C stops both."
	@echo
	@trap 'kill 0' EXIT INT TERM; \
	$(MAKE) --no-print-directory api & \
	$(MAKE) --no-print-directory web & \
	wait
# On Ctrl-C the terminal signals the whole foreground process group, so
# uvicorn and next both get the SIGINT directly and shut down cleanly —
# verified, no orphaned listeners on 8000 or 3000. The `kill 0` above
# covers the other exit paths, where only the recipe shell would
# otherwise notice. The gap it does not cover: `kill <make-pid>` from a
# different terminal, which leaves the children running because make
# never runs its trap. Use `kill -- -<pgid>` if you ever need that.

api: ## Run FastAPI alone, with reload
	cd $(API_DIR) && uv run uvicorn app.main:app --reload --port 8000

web: ## Run Next.js alone
	pnpm --filter $(WEB) dev

# ---------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------

db: db-up db-wait ## Start Postgres and wait for it to accept connections

db-up: ## Start the Postgres and MongoDB containers
	@docker info > /dev/null 2>&1 || { \
		echo "Docker isn't running. Start Docker Desktop and try again."; \
		exit 1; \
	}
	docker compose up -d

db-down: ## Stop the Postgres and MongoDB containers (keeps data)
	docker compose down

db-reset: ## Destroy the database volumes (Postgres and MongoDB) and rebuild from migrations
	@echo "This deletes all local database data."
	@read -p "Continue? [y/N] " ok; [ "$$ok" = "y" ] || exit 1
	docker compose down -v
	$(MAKE) db-up db-wait migrate seed

db-shell: ## Open psql against the local database
	docker compose exec postgres psql -U postgres -d calendar_dev

worker: ## Run the agent worker once: all venues, or VENUE=<id> (needs make db-up and Ollama)
	cd $(API_DIR) && uv run python -m agent_worker.main $(if $(VENUE),--venue $(VENUE))

# C5 (docs/dev/implementations/c5-pipeline-eval-harness.md): scores a full graph run against the hand-written labels. Calls the
# model, so it is local only and NOT part of `make check` or CI. Optional: SET (gated|informational|held_out|all), ONLY, RUNS,
# SCENARIO (repeat|sequence|overlap|perturbed), THRESHOLD, MAX_ATTEMPTS, KEEP_DB=1. The scratch database `calendar_eval` is made on
# the server DATABASE_URL names (or EVAL_DATABASE_URL, if set); it must be local.
eval-graph: ## Score the whole pipeline on labelled pages (local only: needs make db-up, Ollama, the fixtures)
	@test -n "$(LABEL)" || { echo "usage: make eval-graph LABEL=<name> [SET=...] [ONLY=...] [RUNS=n] [SCENARIO=...] [THRESHOLD=x] [MAX_ATTEMPTS=n] [KEEP_DB=1]"; exit 2; }
	cd $(API_DIR) && uv run python -m agent_worker.eval.graph_eval --label $(LABEL) $(if $(SET),--set $(SET)) $(if $(ONLY),--only "$(ONLY)") $(if $(RUNS),--runs $(RUNS)) $(if $(SCENARIO),--scenario $(SCENARIO)) $(if $(THRESHOLD),--threshold $(THRESHOLD)) $(if $(MAX_ATTEMPTS),--max-attempts $(MAX_ATTEMPTS)) $(if $(KEEP_DB),--keep-db)

db-wait: ## Block until Postgres and MongoDB accept connections
	@echo -n "Waiting for Postgres and MongoDB"
	@for i in $$(seq 1 30); do \
		if docker compose exec -T postgres pg_isready -U postgres -q 2>/dev/null \
			&& docker compose exec -T mongo mongosh --quiet --eval 'db.runCommand({ping:1}).ok' > /dev/null 2>&1; then \
			echo " ready."; exit 0; \
		fi; \
		echo -n "."; sleep 1; \
	done; \
	echo " timed out after 30s."; exit 1

# ---------------------------------------------------------------------
# Schema and fixtures
# ---------------------------------------------------------------------

migrate: ## Apply all pending Alembic migrations
	cd $(API_DIR) && uv run alembic upgrade head

migration: ## Autogenerate a migration: make migration m="add show table"
	@test -n "$(m)" || { echo 'Usage: make migration m="what changed"'; exit 1; }
	cd $(API_DIR) && uv run alembic revision --autogenerate -m "$(m)"
	@echo
	@echo "Read the generated file before applying it. Alembic's"
	@echo "autogenerate is reliable for tables and columns and unreliable"
	@echo "for enum types and constraint changes."

seed: ## Create the metro and starting venues (safe to re-run)
	cd $(API_DIR) && uv run python -m scripts.seed

fixtures: ## Regenerate the frontend JSON fixtures from app/testing/sample_data.py
	cd $(API_DIR) && uv run python -m scripts.generate_fixtures

types: ## Regenerate lib/api-types.ts from FastAPI's OpenAPI schema
	cd $(API_DIR) && uv run python -m scripts.dump_openapi
	pnpm exec openapi-typescript $(API_DIR)/openapi.json -o apps/$(WEB)/lib/api-types.ts

# The commit this branch left main at. Right in CI and for a branch of one milestone; for anything else pass
# BASE=<commit before the work began> (a milestone's Implementation log names it). Fetch first: a stale origin/main
# makes the base too old and the check flags other people's lines.
BASE ?= $(shell git merge-base origin/main HEAD 2>/dev/null)

designation-check: ## Fail if lines added since BASE use a bare D5/K2/PR1-3 outside their plan (docs/dev/conventions.md)
	@python3 scripts/check_designations.py $(BASE)

contract-check: ## Fail if the generated contract output is stale
	@snap=$$(mktemp -d); \
	cp apps/$(WEB)/lib/api-types.ts $$snap/ 2>/dev/null || true; \
	cp -R apps/$(WEB)/lib/fixtures $$snap/ 2>/dev/null || true; \
	$(MAKE) --no-print-directory types fixtures > /dev/null; \
	if diff -q $$snap/api-types.ts apps/$(WEB)/lib/api-types.ts > /dev/null 2>&1 \
	   && diff -r -q $$snap/fixtures apps/$(WEB)/lib/fixtures > /dev/null 2>&1; then \
		rm -rf $$snap; \
		echo "Generated contract output is current."; \
	else \
		echo; \
		echo "STALE: the generated contract output did not match."; \
		echo "app/schemas.py, the routers, or app/testing/sample_data.py changed"; \
		echo "without a regen. It has just been regenerated in place —"; \
		echo "review the diff and commit it."; \
		echo; \
		diff -u $$snap/api-types.ts apps/$(WEB)/lib/api-types.ts | head -40 || true; \
		diff -r -u $$snap/fixtures apps/$(WEB)/lib/fixtures | head -40 || true; \
		rm -rf $$snap; \
		exit 1; \
	fi

# ---------------------------------------------------------------------
# Checks — these mirror .github/workflows/ci.yml
# ---------------------------------------------------------------------

check: lint typecheck test contract-check designation-check e2e ## Run everything CI runs

lint: ## ruff + eslint
	cd $(API_DIR) && uv run ruff check .
	pnpm turbo run lint

typecheck: ## mypy + tsc
	cd $(API_DIR) && uv run mypy
	pnpm turbo run check-types

# REQUIRE_DB=1: the DB tests skip when Postgres is down, and `make check` is the
# "done" gate — it must not go green with the whole DB suite skipped.
test: ## pytest (DB tests required) + vitest
	cd $(API_DIR) && REQUIRE_DB=1 uv run pytest
	pnpm turbo run test

# Report only, not part of `make check` or CI (A7-D1): read the Missing column; there is no threshold on purpose.
coverage: ## pytest with branch coverage of app/ and agent_worker/ (report only; needs Postgres)
	cd $(API_DIR) && REQUIRE_DB=1 uv run coverage run -m pytest
	cd $(API_DIR) && uv run coverage report

# End-to-end tests (B6, moved onto Postgres by C2). Playwright starts its own stack, so this
# needs no running `make dev`: the real FastAPI app on a throwaway `calendar_e2e` database
# loaded with the sample world and a frozen clock (8101), a pass-through proxy (8102) and
# `next start` on a production build (3100). Other ports than `make dev` on purpose, so the
# two never collide. It does need Postgres running locally (`make db-up`; a cloud session
# already has it): the harness rebuilds `calendar_e2e` on every run and refuses any other
# database name or a non-local host (apps/api/app/testing/e2e_database.py). Chromium: a laptop runs
# `pnpm --filter calendar exec playwright install chromium` once; a cloud session sets
# E2E_CHROMIUM_PATH (scripts/cloud-setup.sh does). Extra Playwright arguments go in
# E2E_ARGS, e.g. make e2e E2E_ARGS="--repeat-each=3".
# The build's API_BASE_URL only has to exist: every route is dynamic, so nothing is
# fetched at build time (apps/calendar/AGENTS.md).
E2E_ARGS ?=
e2e: ## Playwright end-to-end tests (builds the app, starts API + proxy + Next)
	API_BASE_URL=http://127.0.0.1:8102 pnpm --filter $(WEB) build
	pnpm --filter $(WEB) exec playwright test $(E2E_ARGS)

clean: ## Remove caches and build output
	rm -rf .turbo apps/*/.turbo apps/*/.next
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	rm -rf $(API_DIR)/.mypy_cache $(API_DIR)/.pytest_cache $(API_DIR)/.ruff_cache $(API_DIR)/.coverage $(API_DIR)/htmlcov
