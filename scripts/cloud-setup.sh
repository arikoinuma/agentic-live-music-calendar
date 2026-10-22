#!/usr/bin/env bash
# Brings a Claude Code on the web sandbox to the state `make setup` gives a laptop.
#
# Why this exists separately from the Makefile: the sandbox has no Docker daemon, so
# `make db-up` / `make db-wait` cannot run there. This script installs Postgres from apt
# and points the app at it instead. Everything else mirrors `make setup`: uv sync, pnpm
# install, the env files, migrate, seed.
#
# Ollama is deliberately NOT installed. The agent worker's live extraction needs a local
# model server that a CPU sandbox cannot run at a useful speed, and the test suite does
# not need one (agent_worker/tests mock the model client). So live extraction is out of
# scope in the cloud; see docs/dev/env-setup.md for the laptop path.
#
# Wired up by .claude/settings.json as a SessionStart hook. It is a no-op outside a
# remote session, so running it on a laptop does nothing; set FORCE=1 to run it anyway.
#
# The script is idempotent: every step checks before it installs, so a second session
# on an already-prepared machine is quick.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ] && [ "${FORCE:-}" != "1" ]; then
  exit 0
fi

log() { echo "[cloud-setup] $*" >&2; }

# Runs a command with its output held back. On success the output is discarded so the
# hook stays quiet; on failure it is printed. Without this, `set -e` would exit with no
# message, which is the hardest failure to diagnose from a sandbox transcript.
quiet() {
  local out
  out="$(mktemp)"
  if ! "$@" > "$out" 2>&1; then
    log "FAILED: $*"
    cat "$out" >&2
    rm -f "$out"
    exit 1
  fi
  rm -f "$out"
}

# The sandbox usually runs as root with no sudo binary; a laptop-style user needs sudo.
if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
  RUN_AS_PG="runuser -u postgres --"
else
  SUDO="sudo"
  RUN_AS_PG="sudo -u postgres"
fi

# ---------------------------------------------------------------------
# Postgres (replaces docker-compose.yml)
# ---------------------------------------------------------------------
# Version note: docker-compose.yml and CI use postgres:18. Ubuntu's apt repo ships
# whatever major version the image's release pins (16 on 24.04). The migrations and the
# DB tests use only standard SQL, so this is a known, accepted difference. If a test
# ever depends on a PG18-only feature, switch to the PGDG apt repo.

if ! command -v psql > /dev/null 2>&1; then
  log "installing postgresql from apt"
  quiet $SUDO apt-get update -qq
  quiet env DEBIAN_FRONTEND=noninteractive $SUDO apt-get install -y -qq postgresql postgresql-contrib
fi

# `service` is the only start command that works in a container with no systemd.
if ! $RUN_AS_PG psql -tAc "select 1" > /dev/null 2>&1; then
  log "starting postgres"
  $SUDO service postgresql start > /dev/null
  for _ in $(seq 1 30); do
    $RUN_AS_PG pg_isready -q && break
    sleep 1
  done
fi

# Match the password and database names that .env.example and the test fixtures expect.
$RUN_AS_PG psql -qc "ALTER USER postgres PASSWORD 'postgres';" > /dev/null
if [ "$($RUN_AS_PG psql -tAc "select count(*) from pg_database where datname = 'calendar_dev'")" = "0" ]; then
  $RUN_AS_PG createdb calendar_dev
fi
# calendar_test is created by the test fixtures themselves (they DROP and CREATE it), so
# it is not pre-created here.

# ---------------------------------------------------------------------
# uv and Python (replaces `brew install uv` + `uv python install 3.13`)
# ---------------------------------------------------------------------

export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv > /dev/null 2>&1; then
  log "installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh > /dev/null 2>&1
fi
quiet uv python install 3.13
(cd "$REPO/apps/api" && quiet uv sync --locked)

# ---------------------------------------------------------------------
# Node and pnpm (replaces nvm + `corepack enable pnpm`)
# ---------------------------------------------------------------------
# Node is not installed here. The CI and the laptop both use Node 24; if the sandbox
# image ships a different major, say so loudly rather than installing a second Node
# behind its back.

NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo none)"
if [ "$NODE_MAJOR" != "24" ]; then
  log "WARNING: node is '$NODE_MAJOR', the project expects 24 (CI uses 24)"
fi

if ! command -v pnpm > /dev/null 2>&1; then
  corepack enable pnpm > /dev/null 2>&1 || npm install -g pnpm > /dev/null 2>&1
fi
(cd "$REPO" && quiet pnpm install --frozen-lockfile)

# ---------------------------------------------------------------------
# Env files (the same copy `make setup` makes; both are git-ignored)
# ---------------------------------------------------------------------
# .env.example already points DATABASE_URL at localhost:5432/calendar_dev, which is
# where this script just put Postgres, so no edits are needed.

if [ ! -f "$REPO/apps/api/.env" ]; then
  cp "$REPO/apps/api/.env.example" "$REPO/apps/api/.env"
fi
if [ ! -f "$REPO/apps/calendar/.env.local" ]; then
  echo "API_BASE_URL=http://localhost:8000" > "$REPO/apps/calendar/.env.local"
fi

# ---------------------------------------------------------------------
# Schema and seed data (same as `make migrate seed`)
# ---------------------------------------------------------------------

(cd "$REPO/apps/api" && quiet uv run alembic upgrade head)
(cd "$REPO/apps/api" && quiet uv run python -m scripts.seed)

# Persist PATH for the rest of the session. CLAUDE_ENV_FILE is set by the harness for
# SessionStart hooks; without it, later Bash calls would not find uv in ~/.local/bin.
if [ -n "${CLAUDE_ENV_FILE:-}" ] && ! grep -qF ".local/bin" "$CLAUDE_ENV_FILE" 2>/dev/null; then
  echo "export PATH=\"$HOME/.local/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
fi

# The end-to-end suite (B6, `make e2e`) needs a browser. A cloud session cannot download
# Playwright's own and ships an older Chromium at /opt/pw-browsers/chromium; tell the
# suite where it is, the same way as PATH above. `make check` runs the suite, so without
# this every cloud `make check` would fail on a missing browser.
if [ -n "${CLAUDE_ENV_FILE:-}" ] && [ -x /opt/pw-browsers/chromium ] && ! grep -qF "E2E_CHROMIUM_PATH" "$CLAUDE_ENV_FILE" 2>/dev/null; then
  echo "export E2E_CHROMIUM_PATH=/opt/pw-browsers/chromium" >> "$CLAUDE_ENV_FILE"
fi

log "ready. Next: 'make check' verifies everything. 'make dev' is not available here"
log "(it needs Docker); run 'make api' and 'make web' in two shells instead."
