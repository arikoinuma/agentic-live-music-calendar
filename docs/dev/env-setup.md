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

Install via the official script rather than `brew install nvm` — Homebrew's own package explicitly disclaims upstream support for the brew-managed version.

- [ ] `curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash` — this appends the `NVM_DIR` init lines to the profile file for your *current default shell* (check with `echo $SHELL`)
- [ ] Open a new terminal window and confirm `nvm --version` works before continuing. If your Mac's default shell is bash rather than zsh (check via `dscl . -read ~ UserShell`), either switch to zsh first (`chsh -s /bin/zsh`, then log out and back in — GUI apps like VS Code cache the old shell in their session environment until then) or manually add the init lines to `~/.bash_profile` as well, since login bash shells don't source `~/.bashrc` automatically
- [ ] `nvm install 24 && nvm use 24 && nvm alias default 24` (24 is the current Active LTS line)
- [ ] `which node` — confirm it resolves inside `~/.nvm/versions/node/...`, not `/opt/homebrew/bin/node`. If you have a pre-existing Homebrew-installed Node shadowing nvm's, `brew uninstall node` so nvm is the only source of truth (Homebrew's Node build also omits `corepack`, so the next step will fail with "command not found" if it wins)
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
- [ ] Markdown Preview Mermaid Support (`bierner.markdown-mermaid`) — renders the diagrams already in `docs/arch/arch-initial.md` inline

---

## Phase 1: Repo and monorepo scaffolding

- [ ] `gh repo create agentic-live-music-calendar --public --clone && cd agentic-live-music-calendar`
- [ ] `pnpm dlx create-turbo@latest .` — the target directory must have no files besides `.git`, `.gitignore`, and `docs` (its allow-list, checked by exact name, is narrower than it looks — even a renamed `README.md.bak` counts as a conflict); scaffolds `apps/` (two Next.js apps, `web` and `docs`, by default) and `packages/`
- [ ] Rename the generated apps to match the project's actual apps (e.g. `apps/web` → `apps/calendar`, `apps/docs` → `apps/admin`). A folder rename alone isn't enough — Turborepo and pnpm key off the `"name"` field in each app's `package.json`, not the folder name, so update that too (and any `--filter=` references, e.g. in `README.md`), then re-run `pnpm install` so the lockfile picks up the new package names
- [ ] `mkdir apps/api && cd apps/api && uv init --python 3.13 && cd ../..` — the FastAPI backend and agent worker share this directory
- [ ] Confirm `packages/ui` (shared component library) exists; the template splits shared config into `packages/eslint-config` and `packages/typescript-config` rather than one combined `packages/config` — that's fine, just note the actual names
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
      - pgdata:/var/lib/postgresql

volumes:
  pgdata:
```

  The volume mounts at `/var/lib/postgresql` (the parent directory), not `/var/lib/postgresql/data` — Postgres 18+ images manage a version-specific subdirectory underneath themselves and refuse to start if a volume is mounted directly at the old `.../data` path

- [ ] `docker compose up -d`
- [ ] Confirm it's reachable: `docker compose exec postgres psql -U postgres -c '\conninfo'`
- [ ] Create `apps/api/.env` (git-ignored) with a local `DATABASE_URL` pointing at that container

---

## Phase 3: Backend skeleton (`apps/api`)

- go to the app directory `apps/api`
- [ ] `uv add fastapi "uvicorn[standard]" "sqlalchemy[asyncio]" asyncpg alembic pydantic-settings structlog slowapi fastmcp resend` — the brackets need quoting under zsh (macOS's default shell), which treats unquoted `[...]` as a glob pattern and errors with "no matches found" rather than passing it through literally the way bash does. Run from inside `apps/api` (created in Phase 1) — `uv add` needs an existing `pyproject.toml`
- [ ] `uv add --dev pytest pytest-asyncio ruff mypy polyfactory`
- [ ] Write a minimal `app/main.py` with two routes — `/health` (returns 200, no dependencies, proves the process is up) and `/health/db` (runs `SELECT 1` against Postgres, proves the connection works) — and an `app/config.py` `Settings` class (via `pydantic-settings`) reading `DATABASE_URL`
- [ ] Confirm it runs: `uv run uvicorn app.main:app --reload`, hit both `http://localhost:8000/health` and `http://localhost:8000/health/db`
- [ ] `uv run alembic init migrations`, point its `env.py` at the `Settings`-provided `DATABASE_URL`
- [ ] Write the first migration for the earliest schema slice — `Metro` and `Venue` are enough to prove the pipe works; the rest of the schema comes later, in Claude Code
- [ ] `uv run alembic upgrade head`
- [ ] Confirm `uv run ruff check .` and `uv run pytest` both run clean, even against a trivial placeholder test

---

## Phase 4: Frontend skeleton (`apps/calendar`, shared UI via `packages/ui`)

Since `calendar` and `admin` both need shared components (buttons, dropdowns, etc.), shadcn/ui components go into `packages/ui`, not into either app individually. This needs more manual setup than a single-app install: shadcn's CLI has no auto-retrofit for an existing monorepo like this one — its only monorepo awareness is the `--monorepo` flag, which scaffolds a brand-new project from scratch rather than adapting an existing one. Everything below was verified against the actual CLI, not assumed from docs.

- [ ] Install Tailwind CSS in `apps/calendar` manually first — `shadcn init` does **not** do this for you, despite what older guides (including an earlier version of this doc) suggest; it fails preflight if Tailwind isn't already present. Add `tailwindcss`, `@tailwindcss/postcss`, `postcss` as dependencies, create `postcss.config.mjs` with the `@tailwindcss/postcss` plugin, and add `@import "tailwindcss";` to the top of `app/globals.css`
- [ ] Add `"paths": { "@/*": ["./*"] }` under `compilerOptions` in `apps/calendar/tsconfig.json` — shadcn's init also refuses to proceed without a resolvable import alias
- [ ] In `packages/ui`, add the same kind of alias pointing at its own source: `"paths": { "@repo/ui/*": ["./src/*"] }` in `packages/ui/tsconfig.json`. This is required for the next step — shadcn resolves aliases via `tsconfig.json`, not the package's `exports` map
- [ ] Hand-write `packages/ui/components.json` — running `shadcn init` directly inside `packages/ui` fails, since its framework-detection only recognizes actual app frameworks (Next.js, Vite, etc.), not a bare shared package:

  ```json
  {
    "$schema": "https://ui.shadcn.com/schema.json",
    "style": "base-nova",
    "rsc": true,
    "tsx": true,
    "tailwind": {
      "css": "src/styles/globals.css",
      "baseColor": "neutral",
      "cssVariables": true
    },
    "iconLibrary": "lucide",
    "aliases": {
      "components": "@repo/ui/components",
      "utils": "@repo/ui/lib/utils",
      "hooks": "@repo/ui/hooks",
      "ui": "@repo/ui/components"
    }
  }
  ```

  Create `packages/ui/src/styles/globals.css` with `@import "tailwindcss";` to match the `tailwind.css` path above
- [ ] `pnpm dlx shadcn@latest add utils -c packages/ui` first — this creates `src/lib/utils.ts` (the `cn` helper other components import) and correctly installs its own npm dependencies (`clsx`, `tailwind-merge`)
- [ ] `pnpm dlx shadcn@latest add button -c packages/ui` to confirm the shared-component pipeline works end to end
- [ ] Check `packages/ui/package.json` against what the new component actually imports before moving on — shadcn's registry data is occasionally incomplete, and the CLI just silently skips installing what it doesn't know about. The check, concretely:
  1. Open the file the CLI just created (e.g. `packages/ui/src/components/button.tsx`) and look at its `import` lines.
  2. For each one that isn't a relative import (`./...`) or one of your own `@repo/ui/...` aliases, note the package name — e.g. `import { Button as ButtonPrimitive } from "@base-ui/react/button"` → package `@base-ui/react`; `import { cva } from "class-variance-authority"` → package `class-variance-authority`.
  3. Check each of those against `dependencies` in `packages/ui/package.json`. Confirmed firsthand that `button` in the default "Base UI" style needs exactly those two and neither is listed there, even though the CLI reports success — so this isn't hypothetical, it'll reproduce.
  4. `pnpm add` whatever's missing, scoped to the workspace: `pnpm add @base-ui/react class-variance-authority --filter @repo/ui` (note the filter name is the `"name"` field from `package.json`, `@repo/ui` — not the directory name `ui`)
- [ ] Run `pnpm dlx shadcn@latest init` in `apps/calendar` too (now that Tailwind + the alias are in place), and set its `components.json` `aliases.ui` to `@repo/ui/components` — this way any app-specific composite component you generate there still pulls shared primitives from `@repo/ui` instead of duplicating them locally
- [ ] `pnpm add @js-temporal/polyfill --filter calendar`
- [ ] Build one server component on the home page that calls `apps/api`'s `/health` endpoint server-side via `fetch` (per the BFF pattern) and renders the result — the smallest possible proof Next.js and FastAPI can talk to each other
- [ ] `pnpm --filter calendar dev`, visit `localhost:3000`, confirm the health-check result renders

---

## Phase 5: Model download and evaluation

The architecture doc calls for a small-to-mid open-weight model, but "small-to-mid" isn't itself a decision — it's a size class. This phase turns it into an actual choice, validated against the real task, before any orchestration code is written around it.

- [ ] Pull **one vision-capable model** as your primary candidate rather than several text-only ones — real venue pages turned up at least one case (see below) where event details are baked into an image with no text equivalent at all, which a text-only model simply cannot read regardless of prompt quality. A VLM handles ordinary text/HTML pages just fine too (vision is additive, not a tradeoff), so one model covers both cases instead of needing a text model and a vision model evaluated separately. **Confirmed by actually running both candidates against real fixtures:** `qwen3-vl:4b` answers correctly in plain chat but never reliably completes `instructor`'s structured-output flow against this project's schema — it's a "thinking" model that burns its whole token budget on internal reasoning before emitting the actual answer, regardless of `Mode` or how high `max_tokens` is raised. `gemma4:e4b` is *also* a thinking model (same `ollama show <model>` capability), but handles structured extraction reliably except on content that requires an interpretive judgment call — see the finding below and `docs/arch/arch-initial.md`'s "Model selection" section for why that's a content-shape issue, not a raw-size one. Treat any specific tag as likely stale by the time you read this — verify on `ollama.com/library` before pulling, and re-run the comparison below rather than trusting last month's answer if you're revisiting this later
- [ ] Collect 4–5 real venue calendar pages from your metro's actual venue list as static fixtures (save the raw HTML/text — a link to the live page will drift). Deliberately pick a messy mix: clean single-act listings, multi-act/ambiguous-order listings, a "load more" pagination pattern, one JS-rendered page, and at least one page where event info is embedded in images with no text equivalent — this last case is exactly why the model candidate above needs vision support. Save these under `apps/api/agent_worker/eval/fixtures/`
- [ ] Separately — not a model-evaluation concern, a fetch-strategy one — check whether any venues embed a Google Calendar widget instead of listing shows in their own markup. That's often backed by a public `.ics` feed or the Calendar API, already structured, requiring no LLM extraction at all for that venue. The architecture doc already anticipates this: fetch strategy is meant to be configurable per venue, so "hit the calendar's own feed" is just a different fetch strategy for that venue's record, not a special case bolted onto the pipeline
- [ ] Write the extraction Pydantic schema now (venue, date, time, act name(s), the ambiguity flags, ticket info, confidence, from `docs/arch/arch-initial.md` Section 7) — it needs to exist before anything can be evaluated against it
- [ ] Write a small, throwaway evaluation script: for each fixture, for each candidate model, run the same extraction prompt through `instructor` against that model, and record the output
- [ ] Compare results by hand on three axes: does the structured output match what's actually on the page, does the model follow the schema reliably or does `instructor` need to retry it often, and is the confidence score roughly calibrated to how genuinely ambiguous each fixture is
- [ ] Pick one model as the local-dev default based on that comparison — an actual decision, not the earlier placeholder guess. **Decision: `gemma4:e4b`.** `qwen3-vl:4b` was disqualified outright (see above). Against `gemma4:e4b`, confidence calibration was genuinely good — high confidence tracked correct, specific extractions; near-zero confidence tracked pages with nothing extractable, rather than confidently hallucinating. The one real failure mode: pages needing an interpretive judgment call (a non-music event mixed into an otherwise musical listing, an ambiguous date) can exhaust the token budget and fail outright via `instructor`, *independent of how much content is on the page* — confirmed directly by splitting one failing fixture into two chunks: the chunk with a stray non-music entry still failed, the larger chunk with only uniform recurring listings succeeded cleanly. Also worth carrying forward: `load_text_fixture` needs to strip a page down to visible text (e.g. via BeautifulSoup) before handing it to the model — a raw saved HTML file can be ~97% script/markup noise around a sliver of actual content, and Ollama's `num_ctx` silently defaults to a mere 4096 tokens unless explicitly overridden, so an uncleaned page can get almost entirely truncated before the model ever sees it. Both are now real behavior in `apps/api/agent_worker/eval/run_eval.py`, not just notes here.

---

## Phase 6: Agent worker orchestration

Worth being precise about the library choice before writing any code: the architecture doc calls for LangGraph plus the `openai` SDK directly, not the broader LangChain framework — a deliberate choice to avoid a heavier abstraction layer on top of a provider-agnostic API that's already simple. `langgraph` doesn't pull in `langchain` as a hard dependency for a graph shaped like this one.

- [ ] `uv add langgraph httpx beautifulsoup4 playwright openai instructor tenacity pymongo boto3`
- [ ] `uv run playwright install chromium` (for local use; the deployed container needs its own install, covered in Phase 8)
- [ ] Define the shared state object the graph passes between nodes (a Pydantic model or `TypedDict`): venue, fetched page content, the extracted record, confidence, attempt count, and the eventual reconcile decision
- [ ] Write each pipeline stage as a plain function taking and returning that state — `fetch_node`, `extract_node`, `validate_node`, `reconcile_node`, `commit_node`, `escalate_node`, matching the diagram in `docs/arch/arch-initial.md` Section 7
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
- [ ] **Cloudflare Turnstile** — account, register a site, copy the site key and secret key (gates public edit/flag endpoints against bots, per `docs/arch/arch-initial.md` Section 7)
- [ ] **DeepInfra** (or your chosen hosted inference provider) — account, API key; confirm you can hit it with the same `openai` SDK client used against Ollama in Phase 6, just a different `base_url` — proof the local/hosted swap works as designed

*(Upstash Vector is intentionally skipped — deferred until the chat-search feature is actually built.)*

---

## Phase 8: Deploy to hosted environments

### Vercel (`apps/calendar`)

- [ ] `pnpm add -g vercel`, `vercel login`
- [ ] From `apps/calendar`: `vercel link`, then connect the project to the GitHub repo from the dashboard so pushes auto-deploy
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
- [ ] Redeploy `apps/calendar` to pick up those variables

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
