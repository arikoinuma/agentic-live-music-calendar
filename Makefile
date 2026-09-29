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
.PHONY: help setup dev api web db db-up db-down db-reset db-shell db-wait \
        migrate migration fixtures types contract-check test lint typecheck \
        check clean

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
	$(MAKE) db-up db-wait migrate
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

db-up: ## Start the Postgres container
	@docker info > /dev/null 2>&1 || { \
		echo "Docker isn't running. Start Docker Desktop and try again."; \
		exit 1; \
	}
	docker compose up -d

db-down: ## Stop the Postgres container (keeps data)
	docker compose down

db-reset: ## Destroy the database volume and rebuild it from migrations
	@echo "This deletes all local database data."
	@read -p "Continue? [y/N] " ok; [ "$$ok" = "y" ] || exit 1
	docker compose down -v
	$(MAKE) db-up db-wait migrate

db-shell: ## Open psql against the local database
	docker compose exec postgres psql -U postgres -d calendar_dev

db-wait: ## Block until Postgres accepts connections
	@echo -n "Waiting for Postgres"
	@for i in $$(seq 1 30); do \
		if docker compose exec -T postgres pg_isready -U postgres -q 2>/dev/null; then \
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

fixtures: ## Regenerate the frontend JSON fixtures from app/sample_data.py
	cd $(API_DIR) && uv run python -m scripts.generate_fixtures

types: ## Regenerate lib/api-types.ts from FastAPI's OpenAPI schema
	cd $(API_DIR) && uv run python -m scripts.dump_openapi
	pnpm exec openapi-typescript $(API_DIR)/openapi.json -o apps/$(WEB)/lib/api-types.ts

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
		echo "app/schemas.py, the routers, or app/sample_data.py changed"; \
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

check: lint typecheck test contract-check ## Run everything CI runs

lint: ## ruff + eslint
	cd $(API_DIR) && uv run ruff check .
	pnpm turbo run lint

typecheck: ## mypy + tsc
	cd $(API_DIR) && uv run mypy app/
	pnpm turbo run check-types

test: ## pytest
	cd $(API_DIR) && uv run pytest

clean: ## Remove caches and build output
	rm -rf .turbo apps/*/.turbo apps/*/.next
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	rm -rf $(API_DIR)/.mypy_cache $(API_DIR)/.pytest_cache $(API_DIR)/.ruff_cache
