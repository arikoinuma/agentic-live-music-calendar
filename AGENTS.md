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
| How is a given milestone being implemented? | `docs/dev/implementations/` |

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
- **Every file is understandable to an engineer who has never seen this app.** Each module
  opens with a docstring saying what it is and how to read it. Each class, function, and
  logical block says what it is for at a high level, so nobody has to reverse-engineer a
  chunk of code to learn its role. This sits alongside the "why, not what" rule: explain
  the purpose of a block, not the syntax of its lines.
- **Tests state what they prove.** Every test opens with a comment beginning `Proves:`
  that says what behavior it pins down and why that matters, plus the failure it would
  catch where that isn't obvious. Group tests under labelled section comments, and explain
  each helper and fixture in plain terms. Tests that read their expectations from the code
  under test can't catch that code being wrong, so say where the expected values come from.
- **Comment-only passes must not change code.** When adding or revising comments across
  files, snapshot the files first and compare syntax trees (ignoring comments and
  docstrings) afterwards, then run `make check`. See A1's comment pass for the pattern.
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

Tasks in that plan are marked **[fill-in]** or **[written]** (write it complete, then walk
through it). Respect the marking — the next section is what [fill-in] means in practice.

## [fill-in] tasks — Ari types the lines that carry the lesson

A task is marked [fill-in] because a few lines in it teach something that reading finished code
doesn't. **The deliverable for a [fill-in] task is a scaffold with deliberate gaps, not working
code.**

1. **Write everything around the lesson** — imports, types, signatures, wiring, markup,
   boilerplate, and the tests (which stay red).
2. **Leave the 1–3 spots where the concept lives as `TODO(Ari)` blocks**, each a few lines at
   most. Every block has three parts:
   - **Lesson** — the idea, and why it's done this way *here*, citing the doc that decided it.
   - **Code** — the near-exact lines, in a comment, complete enough to type or paste. Speed
     matters (Oct 8 update): a gap should cost minutes, not research.
   - **Check** — the test that goes green when it's right, and the most likely way to get it wrong.

   The placeholder must fail loudly (`raise NotImplementedError("TODO(Ari)")` /
   `throw new Error("TODO(Ari)")`) so the tests stay red rather than passing by accident.
3. **Stop and hand off**: list each `TODO(Ari)` as a file:line link with its one-line lesson,
   plus the command that runs its tests. Don't fill them in.

```python
# TODO(Ari) — Lesson: the soft delete only considers shows inside the window this fetch covered
#   (data-model-initial.md, set-diff). A page listing two weeks must not "remove" week three.
# Code:
#   covered = {s.key for s in stored if window.start <= s.date <= window.end}
#   removed = covered - {e.key for e in extracted}
# Check: test_reconcile.py::test_soft_delete_respects_window — forgetting the window filter
#   deletes every show past the page's horizon.
raise NotImplementedError("TODO(Ari)")
```

**"Go ahead", "implement B2", "proceed with the plan" mean: carry out the plan, and for
[fill-in] steps the plan is the scaffold.** They don't give permission to fill `TODO(Ari)`
blocks. Fill a block only when Ari asks for that block (or file) by name — "fill in the TODOs in
`reconcile.py`", "complete it for me". When you do, keep the Lesson comment as an ordinary
comment.

**Picking the gaps:** choose lines where the concept lives, not where most of the typing is.
Good gaps: the `searchParams` → API-query mapping, the composite-key match that decides insert
vs. update, the routing function's branch conditions. Bad gaps: JSX markup, import lists,
Pydantic field declarations. If no line in a [fill-in] task meets that bar, say so in the
implementation plan and propose re-marking it [written] — don't invent a gap.

Implementation plans (below) name each [fill-in] step's `TODO(Ari)` blocks and their lessons, so
the reviewer can check that the gaps are the right ones.

## Implementation plans — written down, then reviewed by a different model

Before non-trivial implementation work (any milestone in the build plan), **do not start
coding from a plan that only exists in a chat or a scratch file.**

1. Write the plan to `docs/dev/implementations/<milestone>-<slug>.md` (e.g.
   `a1-data-layer.md`): context, test approach, steps, critical files, verification. Header
   records status, author model, reviewer model, and date.Pause here and wait for the next steps to take place, do not proceed to coding without explicit approval.
2. **A different model than the one that wrote the plan reviews it before any code is
   written.** The reviewer reads the plan against the docs it cites and the actual code, and
   returns numbered findings with severity: wrong assumptions, gaps versus the docs, risky
   steps, holes in the tests.
3. The author resolves every finding in the plan file under a `## Review` section — fixed, or
   rejected with a one-line reason — and the user approves the reviewed plan before
   implementation starts.
4. Tests come first (build plan §3), so the reviewer checks the test approach too.
