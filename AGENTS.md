# Agentic Live Music Calendar

An agentic live music calendar for Minneapolis/St. Paul: scheduled agents read venue
calendar pages, extract show listings with a local open-weight model, validate and
reconcile them, and a Next.js frontend renders the result. Also a deliberate learning
project — agent orchestration, validation of agentic output, auditability, Python, and
React/Next.js from scratch.

## Read before writing code

Language-specific style guides live in `docs/references/`. **Read the relevant one before
non-trivial work in that stack** — both are current, repo-aware, and contradict a lot of
stale training data (Next.js 16 and FastAPI/Pydantic v2 both moved recently).

| Stack | Guide | Also read |
|---|---|---|
| Python / FastAPI / agents | `docs/references/fastapi-style-guide.md` | `apps/api/AGENTS.md` |
| Next.js / React / Tailwind | `docs/references/nextjs-style-guide.md` | `apps/calendar/AGENTS.md` |

Each guide ends with an **Anti-patterns** table of mistakes agents actually make. When
reviewing a diff in that stack, check it against that table.

## Documentation map

Design decisions are already made and written down. Check here before proposing an
approach — most "what should we do about X" questions have an answer with reasoning.

| Question | Document |
|---|---|
| What is this and what must it do? | `docs/arch/project-overview.md` |
| What does each screen do? | `docs/arch/requirements-initial.md` |
| How is it built, and why? | `docs/arch/arch-initial.md` |
| What's the database schema? | `docs/arch/data-model-initial.md` |
| What's the API's shape? | `docs/dev/api-contract.md` |
| What are we building next? | `docs/dev/v1-build-plan.md` |
| How was the environment set up? | `docs/dev/env-setup.md` |
| What non-obvious thing bit us before? | `docs/dev/notes.md` |

When a real debugging session turns up something non-obvious, add it to `docs/dev/notes.md`.
When a design decision gets made, record it where the surrounding reasoning lives.

## Commands

`make help` lists everything. The ones that matter:

```
make dev              # Postgres + FastAPI + Next.js together
make check            # everything CI runs — do this before claiming done
make types            # regenerate lib/api-types.ts after changing app/schemas.py
make migration m="…"  # autogenerate an Alembic migration
make db-shell         # psql against local Postgres
```

Never hand-edit `apps/calendar/lib/api-types.ts` or `apps/calendar/lib/fixtures/` — both
are generated from `apps/api/app/schemas.py` and `app/sample_data.py`. `make contract-check`
(part of `make check`, and its own CI job) fails if they're stale.

## Layout

```
apps/api/        FastAPI service + agent worker (Python, uv) — outside Turborepo
apps/calendar/   Public Next.js app, port 3000
apps/admin/      Untouched template; no v1 role (arch-initial.md §7)
packages/ui/     @repo/ui — shared shadcn components
docs/            Architecture, dev runbooks, style guides
```

Turborepo governs the JS/TS task graph only. `apps/api` has its own tooling (uv, ruff,
mypy, pytest) and is not in the pipeline.

## Conventions

- **Comments explain why, not what.** This codebase is unusually comment-dense on purpose:
  it's a learning project, and the reasoning behind a decision is the point. Match that —
  but comment the non-obvious choice, not the obvious line.
- **Cite the source of a decision.** When code implements something a doc specifies, name
  the doc and section. When it deliberately departs, say so and why.
- **Don't build what has nothing to consume it.** This repo consistently defers rather than
  scaffolds — see `arch-initial.md` §11 for the deferred list. A field that's always empty
  or a service nothing calls is worse than its absence.
- **Verify, don't assume.** Claims in this repo's docs were checked against real behavior.
  Keep that standard: run it before saying it works.

## Current phase

`docs/dev/v1-build-plan.md` is the active plan: get the whole thing running locally, with
real agent writes and a real calendar UI. Two tracks (Python/agent, Next.js) meeting at the
API contract. Nothing hosted is in scope — Vercel, Railway, and Neon are deployed and left
alone.

Tasks in that plan are marked **[fill-in]** (scaffold with dense guiding comments, the human
implements) or **[written]** (write it complete, then walk through it). Respect the marking.
