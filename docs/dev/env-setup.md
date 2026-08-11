# Setup Guide: Local Environment to Live Deployment

A sequential runbook from a blank MacBook Pro to all four services (Next.js, FastAPI, agent worker, Postgres) live in their hosted environments. Each phase builds on the last — work through them in order. This is scaffolding, not features: the goal is every layer proven to talk to every other layer, with nothing behind it yet but health checks and one evaluated model choice. That's the actual handoff point to Claude Code.

---

## Phase 0: Machine setup

### Core tools

- [ ] Homebrew, if not already present: `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"`
- [ ] Git (usually preinstalled via Xcode Command Line Tools — confirm with `git --version`, or `brew install git`)
- [ ] GitHub CLI: `brew install gh`, then `gh auth login`
- [ ] Docker Desktop: `brew install --cask docker`, then launch it once from Applications so the daemon starts

### Python, via uv

`uv` is the current standard for Python — it replaces pip, venv, and pyenv in one tool and manages Python versions itself, so there's no separate Python installer step.

- [ ] `brew install uv`
- [ ] `uv python install 3.13`
- [ ] Confirm: `uv python list`

### Node.js, via nvm

- [ ] `brew install nvm`, then follow brew's printed instructions to add it to `~/.zshrc`
- [ ] `nvm install 24 && nvm use 24 && nvm alias default 24` (24 is the current Active LTS line)
- [ ] `corepack enable pnpm` — pnpm is what Turborepo's own docs recommend for a monorepo like this

### Ollama, for local model inference

- [ ] `brew install --cask ollama`, launch once from Applications
- [ ] Model pulls happen in Phase 5, once there's something concrete to evaluate them against

### VS Code extensions

Install via the Extensions panel (⌘⇧X):

- [ ] Python (`ms-python.python`) — includes Pylance
- [ ] Ruff (`charliermarsh.ruff`) — inline lint/format matching the CLI tool already in use
- [ ] ESLint (`dbaeumer.vscode-eslint`)
- [ ] Tailwind CSS IntelliSense (`bradlc.vscode-tailwindcss`)
- [ ] Docker (`ms-azuretools.vscode-docker`)
- [ ] PostgreSQL (`ms-ossdata.vscode-pgsql`) and MongoDB for VS Code (`mongodb.mongodb-vscode`) — browse both databases directly from the editor once they exist
- [ ] Markdown Preview Mermaid Support (`bierner.markdown-mermaid`) — renders the diagrams already in `ARCHITECTURE.md` inline

---

## Phase 1: Repo and monorepo scaffolding

- [ ] `gh repo create agentic-live-music-calendar --public --clone && cd agentic-live-music-calendar`
- [ ] `pnpm dlx create-turbo@latest .` — scaffolds `apps/` and `packages/`
- [ ] Confirm the generated app becomes `apps/web` (rename if the template names it differently)
- [ ] `mkdir apps/api && cd apps/api && uv init --python 3.13 && cd ../..` — the FastAPI backend and agent worker share this directory
- [ ] Confirm `packages/ui` (shadcn-based component library) and `packages/config` (shared TS/ESLint config) exist; create them if the template didn't
- [ ] First commit, push to GitHub

---

## Phase 2: Local Postgres

- [ ] At the repo root, create `docker-compose.yml`:

```yaml
services:
  postgres:
    image: postgres:18
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: calendar_dev
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
```

- [ ] `docker compose up -d`
- [ ] Confirm it's reachable: `docker compose exec postgres psql -U postgres -c '\conninfo'`
- [ ] Create `apps/api/.env` (git-ignored) with a local `DATABASE_URL` pointing at that container

---

## Phase 3: Backend skeleton (`apps/api`)

- [ ] `uv add fastapi uvicorn[standard] sqlalchemy[asyncio] asyncpg alembic pydantic-settings structlog slowapi fastmcp resend`
- [ ] `uv add --dev pytest pytest-asyncio ruff mypy polyfactory`
- [ ] Write a minimal `app/main.py` with two routes — `/health` (returns 200, no dependencies, proves the process is up) and `/health/db` (runs `SELECT 1` against Postgres, proves the connection works) — and an `app/config.py` `Settings` class (via `pydantic-settings`) reading `DATABASE_URL`
- [ ] Confirm it runs: `uv run uvicorn app.main:app --reload`, hit both `http://localhost:8000/health` and `http://localhost:8000/health/db`
- [ ] `uv run alembic init migrations`, point its `env.py` at the `Settings`-provided `DATABASE_URL`
- [ ] Write the first migration for the earliest schema slice — `Metro` and `Venue` are enough to prove the pipe works; the rest of the schema comes later, in Claude Code
- [ ] `uv run alembic upgrade head`
- [ ] Confirm `uv run ruff check .` and `uv run pytest` both run clean, even against a trivial placeholder test

---

## Phase 4: Frontend skeleton (`apps/web`)

- [ ] `pnpm dlx shadcn@latest init` — also wires up Tailwind
- [ ] `pnpm dlx shadcn@latest add button` to confirm the component pipeline works
- [ ] `pnpm add @js-temporal/polyfill --filter web`
- [ ] Build one server component on the home page that calls `apps/api`'s `/health` endpoint server-side via `fetch` (per the BFF pattern) and renders the result — the smallest possible proof Next.js and FastAPI can talk to each other
- [ ] `pnpm --filter web dev`, visit `localhost:3000`, confirm the health-check result renders

---

## Phase 5: Model download and evaluation

The architecture doc calls for a small-to-mid open-weight model, but "small-to-mid" isn't itself a decision — it's a size class. This phase turns it into an actual choice, validated against the real task, before any orchestration code is written around it.

- [ ] Pull 2–3 candidate models sized to your hardware, per the tiers in the architecture doc's model-selection note — for example `ollama pull gemma3:4b`, `ollama pull qwen3:4b`, and one step up (`gemma3:12b` or similar) if your machine has the headroom
- [ ] Collect 4–5 real venue calendar pages from your metro's actual venue list as static fixtures (save the raw HTML/text — a link to the live page will drift). Deliberately pick a messy mix: clean single-act listings, multi-act/ambiguous-order listings, a "load more" pagination pattern, and one JS-rendered page. Save these under `apps/api/agent_worker/eval/fixtures/`
- [ ] Write the extraction Pydantic schema now (venue, date, time, act name(s), the ambiguity flags, ticket info, confidence, from `ARCHITECTURE.md` Section 7) — it needs to exist before anything can be evaluated against it
- [ ] Write a small, throwaway evaluation script: for each fixture, for each candidate model, run the same extraction prompt through `instructor` against that model, and record the output
- [ ] Compare results by hand on three axes: does the structured output match what's actually on the page, does the model follow the schema reliably or does `instructor` need to retry it often, and is the confidence score roughly calibrated to how genuinely ambiguous each fixture is
- [ ] Pick one model as the local-dev default based on that comparison — an actual decision, not the earlier placeholder guess

---

## Phase 6: Agent worker orchestration

Worth being precise about the library choice before writing any code: the architecture doc calls for LangGraph plus the `openai` SDK directly, not the broader LangChain framework — a deliberate choice to avoid a heavier abstraction layer on top of a provider-agnostic API that's already simple. `langgraph` doesn't pull in `langchain` as a hard dependency for a graph shaped like this one.

- [ ] `uv add langgraph httpx beautifulsoup4 playwright openai instructor tenacity pymongo boto3`
- [ ] `uv run playwright install chromium` (for local use; the deployed container needs its own install, covered in Phase 8)
- [ ] Define the shared state object the graph passes between nodes (a Pydantic model or `TypedDict`): venue, fetched page content, the extracted record, confidence, attempt count, and the eventual reconcile decision
- [ ] Write each pipeline stage as a plain function taking and returning that state — `fetch_node`, `extract_node`, `validate_node`, `reconcile_node`, `commit_node`, `escalate_node`, matching the diagram in `ARCHITECTURE.md` Section 7
- [ ] Wire the graph: `add_node` for each function, `add_conditional_edges` out of `validate_node` reading the state's attempt count and confidence to route to `reconcile_node`, back to `extract_node`, or to `escalate_node`
- [ ] Compile without a checkpointer, deliberately — `graph.compile()` with nothing else. This job completes in one process invocation, so there's nothing to resume
- [ ] In `extract_node`, call the model chosen in Phase 5 via the `openai` SDK client (`base_url` pointed at Ollama's local endpoint), wrapped with `instructor` so the response is validated against the Pydantic schema rather than parsed by hand
- [ ] Run the full graph against one fixture from Phase 5 end to end; confirm a plausible structured record comes out the other side
- [ ] Only after that works: swap `fetch_node` from reading a static fixture to actually calling `httpx` (or Playwright, for the venue that needs it) against a live venue page

---

## Phase 7: External service accounts

Provisioning only — nothing gets deployed yet. Capture each credential into `apps/api/.env` as you go.

- [ ] **Neon** — account, project, copy the connection string
- [ ] **MongoDB Atlas** — account, free M0 cluster, database user, copy the connection string
- [ ] **Cloudflare R2** — account, bucket, API token (S3-compatible key/secret)
- [ ] **Resend** — account, verify a sending domain (or use their sandbox domain for now), API key
- [ ] **Cloudflare Turnstile** — account, register a site, copy the site key and secret key (gates public edit/flag endpoints against bots, per `ARCHITECTURE.md` Section 7)
- [ ] **DeepInfra** (or your chosen hosted inference provider) — account, API key; confirm you can hit it with the same `openai` SDK client used against Ollama in Phase 6, just a different `base_url` — proof the local/hosted swap works as designed

*(Upstash Vector is intentionally skipped — deferred until the chat-search feature is actually built.)*

---

## Phase 8: Deploy to hosted environments

### Vercel (`apps/web`)

- [ ] `pnpm add -g vercel`, `vercel login`
- [ ] From `apps/web`: `vercel link`, then connect the project to the GitHub repo from the dashboard so pushes auto-deploy
- [ ] Install the **Neon-Vercel integration** from Vercel's marketplace, pointed at the Neon project from Phase 7 — this is what gives automatic per-preview database branches

### Railway — FastAPI service

- [ ] `brew install railway`, `railway login`
- [ ] New Railway project, connect to the GitHub repo
- [ ] Add a service pointed at `apps/api`, start command `uvicorn app.main:app --host 0.0.0.0 --port $PORT` — the always-on FastAPI service
- [ ] Environment variables: `DATABASE_URL` (Neon), the shared secret used for FastAPI ↔ Next.js auth, `TURNSTILE_SECRET_KEY`

### Railway — agent worker service

This one has a real gotcha worth taking seriously: Playwright's Python package installs fine via `uv add`, but the Chromium *binary* it needs is a separate download, and a plain buildpack deploy won't fetch it automatically. The most common way this breaks in production is discovering it the first time the deployed job tries to launch a browser and can't.

- [ ] Give this service its own `Dockerfile` (Railway uses it automatically if present in the service's root) based on Playwright's official image, `mcr.microsoft.com/playwright/python`, which already includes Chromium and the system libraries it depends on — don't build this service the same generic way as the plain-Python FastAPI service
- [ ] Start command: `python -m agent_worker.main`, configured as **cron-scheduled**, not always-on; set the crontab expression for the daily run
- [ ] Environment variables: `DATABASE_URL`, `MONGODB_URI`, R2 credentials, and the model provider variables — pointed at **DeepInfra (or your hosted provider) from Phase 7, not Ollama**. `localhost:11434` doesn't exist on Railway, and it's an easy thing to leave pointed at your laptop by accident

### Wire Vercel and Railway together

- [ ] In Vercel, set the FastAPI service's Railway URL and the shared secret as environment variables (server-only, never `NEXT_PUBLIC_`)
- [ ] In Vercel, also set `NEXT_PUBLIC_TURNSTILE_SITE_KEY` — this one is meant to be public; only the secret key stays server-only
- [ ] Redeploy `apps/web` to pick up those variables

### CI

- [ ] GitHub Actions workflow: `ruff check`, `mypy`, `pytest` for the Python side; lint/typecheck for the JS side via Turborepo — on every PR
- [ ] In the repo's branch protection settings, require that check to pass before merging to `main`

---

## Phase 9: Verify end to end

- [ ] Visit the live Vercel URL; confirm the health-check display renders successfully — Next.js (Vercel) correctly reaching FastAPI (Railway) in production
- [ ] Confirm FastAPI's `/health/db` route (built in Phase 3) shows a successful Neon connection
- [ ] Manually trigger the Railway cron service and confirm it's a **real run**, not just a connectivity check — an actual fetch against a live venue page, extraction through the hosted model, and a genuine row landing in Postgres, confirmed by querying it directly
- [ ] Open a PR against `main`; confirm CI runs, and confirm a Vercel preview deployment and a Neon preview branch both get created automatically

Every layer in the architecture doc is now live, talking to every other layer it's supposed to, running one evaluated model choice instead of a guess. Real schema and real features are Claude Code's job from here.
