# v1 Build Plan — from scaffolding to a working local app

**Status:** Draft
**Date:** September 28, 2026
**Purpose:** The plan for the phase after `env-setup.md`. That runbook's job was proving every layer can talk to every other layer. This one's job is turning that into an application that actually does something, running entirely on the local machine.

Read `env-setup.md` first for what exists and why. This document assumes `docs/arch/arch-initial.md` (design), `docs/arch/data-model-initial.md` (schema), and `docs/arch/requirements-initial.md` (screen-by-screen behavior) as the specification — it plans work against them rather than restating them.

**Explicitly out of scope this phase:** anything hosted. Vercel, Railway, Neon, and the deployed services stay as they are — working, and left alone. Nothing below requires a deploy to verify. The three hosted-service items still open in `env-setup.md` (the Railway agent worker service, DeepInfra, branch protection) stay open.

---

## 1. Where things actually stand

### 1.1 What `env-setup.md` finished

Phases 0–4 and 7–9 are genuinely done: the monorepo, local Postgres in Docker, a FastAPI service with two health routes, Alembic wired to a first migration, Tailwind + shadcn plumbed into `packages/ui`, a Next.js page calling FastAPI server-side, all three hosted services deployed and talking to each other, and CI green on every PR.

Phase 5 (model evaluation) produced a real decision — `gemma4:e4b`, validated against four real venue fixtures — plus two findings that shaped everything after it: HTML needs stripping to visible text before the model sees it, and Ollama's `num_ctx` silently defaults to 4096.

Phase 6 (agent orchestration) is the one that's genuinely mid-flight, and it's where most of the work below lands.

### 1.2 What it deliberately skipped

All of these were skipped for the same defensible reason — they'd be setup work for something with no consumer yet — and all of them stay skipped this phase: R2, Resend, Turnstile, DeepInfra, the Railway agent worker service, the Neon–Vercel integration, Upstash Vector, the FastAPI↔Next.js shared secret, and branch protection on `main`.

One skipped item *does* come back in scope here, because this phase gives it a consumer: **MongoDB raw staging**. It's already provisioned (Phase 7) and nothing writes to it. See A4.

### 1.3 Code-level findings — the gap inventory

Reading the actual code turns up more than the runbook's checkboxes suggest. These aren't new feature requests; they're places where what's written doesn't yet match what `arch-initial.md` and `requirements-initial.md` already specify. Each one is assigned to a milestone below rather than fixed ad hoc.

**Agent pipeline**

| # | Finding | Where | Lands in |
|---|---|---|---|
| G1 | `FIXTURES_DIR = ...` is a literal `Ellipsis` — dead placeholder, nothing reads it | `agent_worker/nodes.py` | A1 |
| G2 | `extract_node` has no error handling. The exact failure Phase 5 documented (a thinking model exhausting its budget on an interpretive judgment call) raises out of the node, crashes the graph, and never increments `attempt_count` — so the retry loop built to handle it can never fire | `agent_worker/nodes.py` | A3 |
| G3 | `validate_node` sets `confidence = 0` for an empty `shows` list, so a venue with a legitimately empty calendar burns all 3 retries and escalates. `page_readable` — the field added specifically to tell "confirmed empty" from "broken" apart — is never read by anything | `agent_worker/nodes.py` | A3 |
| G4 | Validation checks only confidence. The three checks `requirements-initial.md` names — completeness, plausibility, internal consistency — aren't implemented | `agent_worker/nodes.py` | A3 |
| G5 | Retries are identical re-calls. `arch-initial.md` calls for escalating the *approach* each attempt (adjusted prompt, then a larger model), which is the whole point of retrying rather than looping | `agent_worker/nodes.py` | A3 |
| G6 | `route_after_validate` compares `state.confidence >= 0.8` where the field is `float \| None`, and returns `NodeNames.ESCALATE` against a path map keyed on `NodeOutcomes.ESCALATE`. Both work only because two different `StrEnum` members happen to share the string `"escalate"` | `agent_worker/graph.py` | A3 |
| G7 | The extraction schema is missing fields `requirements-initial.md` explicitly asks agents to populate: advance/day/free admission (currently one untyped `ticket_info` string), the show's poster image, and each artist's own start time and sequence number | `agent_worker/schemas.py` | A2 |
| G8 | `ShowExtraction.time` is required, but the requirements make Date the only required field. A required time field gives the model no way to say "not stated" except by inventing one | `agent_worker/schemas.py` | A2 |
| G9 | The extraction prompt says nothing about the "ignore karaoke / open mic / party with no identifiable artist" rule. Worth noting this is the *same shape* as Phase 5's documented failure mode — a non-music entry mixed into a musical listing — so stating the rule explicitly is both a correctness fix and a reliability one | `agent_worker/nodes.py` | A2 |
| G10 | `reconcile_node`, `commit_node`, `escalate_node` are `print()` stubs | `agent_worker/nodes.py` | A5, A6 |

**Backend and data**

| # | Finding | Where | Lands in |
|---|---|---|---|
| G11 | There are no SQLAlchemy models anywhere. `arch-initial.md` Section 5 specifies "one Python package of SQLAlchemy models" shared by FastAPI and the worker; `main.py` currently issues raw `text("SELECT 1")` and the one migration is hand-written DDL with no model behind it | new `app/db/` | A1 |
| G12 | `structlog` is a dependency and is not imported anywhere. The nodes use `print()`. For a project whose stated requirement is "make the agent workflow auditable — logging," this is the gap that matters most | `agent_worker/`, `app/` | A4 |
| G13 | No seed data and no way to create any. There is no metro row and no venue row locally, so nothing can be run end to end without hand-writing SQL | new `scripts/` | A1 |
| G14 | `pytest` `testpaths = ["app"]` means any test written under `agent_worker/` won't even be collected | `apps/api/pyproject.toml` | A7 |
| G15 | mypy runs against `app/` only; `agent_worker/` has ~11 known errors | `apps/api/pyproject.toml`, CI | A7 |
| G16 | One test exists in the whole repo (`test_health.py`). No test touches the graph, the nodes, the routing logic, or the schemas | new `tests/` | A7 |
| G17 | No `.env.example`, so the required variables are discoverable only by reading `config.py` and hitting a `ValidationError` | `apps/api/` | A0 |

**Frontend**

| # | Finding | Where | Lands in |
|---|---|---|---|
| G18 | `apps/calendar` is still the `create-turbo` template — Turborepo logo, "Deploy now" CTA, `page.module.css`, the demo `Button appName="calendar"` — with the health check bolted onto it | `apps/calendar/app/` | B1 |
| G19 | Three separate button components coexist: `packages/ui/src/button.tsx` (template, takes `appName`), `packages/ui/src/components/button.tsx` (shadcn), and `apps/calendar/components/ui/button.tsx` (a third copy). The page imports the template one | `packages/ui/`, `apps/calendar/` | B1 |
| G20 | Both CSS Modules and Tailwind are active at once. Pick one; the arch doc picked Tailwind | `apps/calendar/app/` | B1 |
| G21 | `metadata` still reads `title: "Create Next App"` | `apps/calendar/app/layout.tsx` | B1 |
| G22 | `apps/admin` is 100% untouched template and has no defined role yet. `arch-initial.md` Section 7 says the MCP server "provides an operational interface without requiring a dedicated admin frontend first" — so admin has no v1 job | `apps/admin/` | see §8 |
| G23 | No API client layer, no shared types between FastAPI's Pydantic shapes and the frontend's TypeScript | `apps/calendar/lib/` | Track 0 |

---

## 2. Definition of done

This phase is finished when, on a laptop with no network access to any hosted service:

1. `docker compose up -d` and two dev commands bring up the whole stack.
2. The agent worker runs against a real venue calendar URL and writes real `show` and `artist` rows to local Postgres — insert, update, and soft-delete all exercised across two consecutive runs.
3. Every step of that run is queryable afterward from `agent_run` and `audit_log`: what was fetched, what the model returned, what validation decided, why reconcile chose what it chose, and what got written.
4. The Next.js calendar renders those rows — the real four-week vertically-scrolling, horizontally-venue-scrolling layout from `requirements-initial.md`, not a list — with venue and artist detail pages behind working links.
5. `uv run pytest` covers the agent pipeline's decision logic, not just `/health`, and CI stays green with mypy widened to `agent_worker/`.

Point 3 is the one worth being strict about. "Auditable" is a stated requirement of this project, and the only way to know it's real is to be able to answer "why does this row look like this?" entirely from the database.

---

## 3. How the two tracks work

Two tracks, alternating rather than strictly ordered:

- **Track A — Python, the agent, the data layer.** Depth on orchestration, validation, and auditability.
- **Track B — Next.js and React from scratch.** The calendar UI, built up from an empty page rather than edited down from a template.

They meet at one place: **the API contract**. Track 0 below defines it once, up front, and is the only genuinely blocking work — after it, either track can move without waiting on the other. Track B can build against a static fixture of that contract's JSON long before Track A produces real rows, which is exactly what makes the parallelism work rather than just being context-switching.

**Notation for who writes what** (per the split-by-area decision):

- **[fill-in]** — I write the file with structure, imports, and dense comments explaining what each piece must do and why; you write the implementation. Same style as `state.py`, `graph.py`, `config.py`, and the first migration.
- **[written]** — I write it complete and walk you through the non-obvious parts. Reserved for mechanical work where typing it out teaches little: model definitions, migrations, seed data, test fixtures, config.

---

## 4. Track 0 — the contract (blocking, do first)

**Status: complete**, except the one decision it deliberately leaves open. Full write-up in `docs/dev/api-contract.md`.

- [x] **[written]** `.env.example` in `apps/api/` listing every variable `Settings` requires, plus the not-yet-required ones (Mongo, R2, the shared secret) commented out so their shape is known before they're needed (G17)
- [x] **[written]** The read API's response shapes, as Pydantic models in `apps/api/app/schemas.py` — seven endpoints covering the calendar, day view, show/venue/artist details, the two list pages, and the month dropdown. The enums they share with the ORM models (A1) and the audit writes (A4) live in `apps/api/app/enums.py`, so neither layer owns the definition
- [x] **[written]** JSON fixtures under `apps/calendar/lib/fixtures/` — **generated** from those models by `apps/api/scripts/generate_fixtures.py` (`make fixtures`) rather than hand-written, so they can't drift from the contract. 21 shows over four weeks across the same four venues the Phase 5 extraction fixtures came from, deliberately including the untidy cases: no listed start time, multi-act bills, a free show, an empty day, one artist at two venues
- [ ] **[fill-in]** How TypeScript types stay in sync with the Pydantic models. **Still open** — the three options and the tradeoff that actually separates them are written out in the header of `apps/calendar/lib/types.ts`, and §7 of `api-contract.md` is a stub waiting on the answer. That file currently holds a hand-written version (option 1), which is both a real candidate and what keeps the build green while this is undecided
- [x] **[written]** A root `Makefile` so "run the app" is one command. `make setup` for a cold start, `make dev` for Postgres + FastAPI + Next.js together, plus targets for migrations, fixtures, psql, and a `make check` that mirrors CI exactly

**Verified working:** `make dev` brings up all three, `/health` and `/health/db` both answer against local Postgres, Ctrl-C leaves no orphaned listeners, and `make check` is green.

**Three decisions Track 0 made that are worth knowing before building on it** (reasoning in `api-contract.md`):

- Inherited show fields — age restriction, alcohol, setting, seating — are **resolved server-side**. The read API returns the effective value and doesn't say whether it came from the show or the venue. The write API will have to, which is the clearest case in this project for read and write shapes being different models rather than one reused out of habit.
- `Decimal` crosses the wire as a **string** (`"15.00"`), not a number, to avoid float rounding on money. And all-null admission means *not stated*, never free — `free_admission` is true only when the listing says so explicitly.
- Fields backed by deferred tables (venue/artist socials, genres, members, instrumentation) are **absent rather than always-empty**. A consumer can't tell "no Instagram" from "feature doesn't exist yet," and a permanently-`[]` field teaches the UI to render an empty state that isn't real.

## 5. Track A — Python, the agent, the data layer

### A1. The data layer — models, migrations, seed

Foundation for everything else in this track. Scope per the decision above: core calendar plus audit; the contributor/flag/submission and genre/instrument/member vocabulary tables wait for the features that read them.

- [ ] **[written]** Create `app/db/` as the shared model package `arch-initial.md` Section 5 calls for — importable by both FastAPI and `agent_worker`, with the declarative base, session factory, and an async engine that `app/main.py` switches over to using (G11)
- [ ] **[written]** SQLAlchemy models: `metro`, `venue` (filled out to the full column list), `show`, `artist`, `show_artist`, `event`, plus the enum types those need, per `data-model-initial.md` Section 2
- [ ] **[written]** SQLAlchemy models: `agent_run` and `audit_log`, per `data-model-initial.md` Section 3
- [ ] **[fill-in]** Point Alembic's `env.py` at the models' metadata so autogenerate works, then generate the migration and read what it produced before applying it. Autogenerate is reliable for tables and columns and unreliable for enum types and constraint changes — knowing which parts to check by hand is the actual skill here, and the hand-written first migration is a good comparison point
- [ ] **[written]** A seed script creating the Minneapolis/St. Paul metro row and the four venues the Phase 5 fixtures came from, with their real calendar URLs and `fetch_strategy` set appropriately (G13)
- [ ] **[fill-in]** Delete the dead `FIXTURES_DIR = ...` (G1)

### A2. The extraction schema, against the real requirements

- [ ] **[fill-in]** Bring `ShowExtraction` in line with `requirements-initial.md`'s "Agent Extraction: Fields" — replace `ticket_info` with `admission_advance` / `admission_day` / `free_admission`, add the poster `image_url`, and add per-artist start time and sequence number. That last one changes `acts: list[str]` into a list of structured objects, which is a schema shape change, not just a field addition (G7)
- [ ] **[fill-in]** Make `time` optional, and say so in its `description` — the description text is part of what `instructor` sends the model, so "leave null if the page doesn't state a start time" is an instruction, not a comment (G8)
- [ ] **[fill-in]** Add the non-music-entry exclusion rule to the extraction prompt (G9)
- [ ] **[fill-in]** Add the one-show-vs-several rule from the requirements ("listings under one time/ticket link are a single multi-artist Show") to the prompt
- [ ] **[written]** Re-run `eval/run_eval.py` against all four fixtures with the revised schema and prompt, and record whether the added fields made extraction more or less reliable. A richer schema is more for the model to get right — this is worth measuring rather than assuming

### A3. Validation and retry — making the loop real

The most conceptually interesting work in this track, and where the "validation approach for agentic outputs" requirement actually gets answered.

- [ ] **[fill-in]** Wrap `extract_node`'s model call so a raised exception becomes a recorded failed attempt that the retry loop can act on, instead of killing the graph (G2)
- [ ] **[fill-in]** Make `validate_node` read `page_readable` and distinguish three outcomes, not two: valid extraction, confirmed-empty page (a legitimate pass — the venue has no shows listed), and unreadable page (a failure worth retrying). This is the field's entire reason for existing (G3)
- [ ] **[fill-in]** Implement the three named checks — completeness (required fields present), plausibility (dates not in the past, times in a sane range), internal consistency (`free_admission` not true alongside a price) — as functions separate from the node, so they're testable without running a graph (G4)
- [ ] **[fill-in]** Decide how a check failure combines with the model's self-reported confidence into the single routing signal. Worth thinking about: a deterministic consistency failure is a different kind of evidence than a model saying it's 0.6 sure, and collapsing both into one float may be losing information the router needs
- [ ] **[fill-in]** Make each retry attempt escalate the approach rather than repeating the call (G5). `arch-initial.md` is specific about the order: narrow the task or address the specific ambiguity in the prompt first, larger model second
- [ ] **[fill-in]** Fix the routing function's `None` comparison and the two-enums-one-string collision (G6)
- [ ] **[written]** Move the confidence threshold and retry cap out of the routing function into named configuration, so the eval work in A8 can vary them

### A4. Auditability — the part that makes the rest inspectable

Do this *before* reconcile and commit, not after. Building the audit trail first means the hard parts of A5 are debuggable from the database while you write them, rather than from `print()` statements.

- [ ] **[written]** `structlog` configured once, with a processor chain that renders human-readable output locally and JSON otherwise (G12)
- [ ] **[fill-in]** An `agent_run` row created at the start of each venue's processing cycle and closed at the end, with its id carried in the graph state — this is `arch-initial.md`'s `parent_run_id`, and every audit row for the run points at it
- [ ] **[fill-in]** An `audit_log` write from each of the six nodes, carrying `step_type`, `attempt_number`, `source='agent'`, and — on the agentic steps — `model_used` and `confidence`. Because it's append-only, a retry adds a row rather than replacing one, which is what preserves the retry history
- [ ] **[fill-in]** The MongoDB raw-staging write in `extract_node` (`arch-initial.md` Section 6). Already provisioned, never used; this phase gives it its consumer. `pymongo`'s `AsyncMongoClient`, not `motor` — the arch doc is specific about this and the reason is that Motor is deprecated
- [ ] **[written]** Two or three SQL queries saved under `docs/dev/` that answer the questions a human actually asks of an audit trail — "show me everything that happened in run N," "which runs escalated and why," "what changed about this show and when." Being able to run these is the real test of whether point 3 in §2 is met
- [ ] **Deferred, on purpose:** the R2 snapshot write. It needs an account this phase doesn't provision, and `audit_log.snapshot_key` can stay null. Everything else in the audit trail works without it

### A5. Reconcile — the decision logic

- [ ] **[fill-in]** Show matching on the composite key (venue, date, time) producing insert / update / no-op, per `data-model-initial.md`'s outcome table. Deterministic, no model involved
- [ ] **[fill-in]** The set-diff soft delete: shows stored for this venue but absent from this fetch, *within the date range the fetch actually covered*, get `status='removed'`. That date-range qualifier is the subtle part — pagination depth varies run to run, so the graph state needs to carry how far this run actually reached, which it currently doesn't
- [ ] **[fill-in]** Artist matching by name: exact match, no match, and the ambiguous middle. Exact and no-match resolve deterministically (no-match creates a name-only artist record per the requirements)
- [ ] **[fill-in]** The ambiguous-artist branch — an LLM call inside `reconcile_node`, not its own node — with its decision written to `audit_log` carrying `model_used` and `confidence`, exactly like extract and validate. This is the one place in the pipeline where a model makes a database decision, which is precisely why it's the one that most needs auditing

### A6. Commit — the writes

- [ ] **[fill-in]** `commit_node` executing reconcile's decision against Postgres: `show`, `show_artist`, and new `artist` rows, in one transaction per decision, with the resulting `audit_log` row carrying `previous_value` / `new_value` JSONB snapshots (those are what a future revert restores)
- [ ] **[fill-in]** `escalate_node` writing a real `audit_log` row with `outcome='escalated'` rather than printing
- [ ] **[fill-in]** Async vs. sync: the nodes are currently synchronous functions calling a synchronous `OpenAI` client, while `app/db/` and FastAPI are async. LangGraph supports both. Deciding whether to make the nodes async — and what that buys a job that processes venues one at a time — is a real call worth making explicitly rather than by accident

### A7. Testing

- [ ] **[written]** Fix `testpaths` so `agent_worker/` tests are collected, without re-collecting `local_test.py` (G14). The current setting was a workaround for a filename collision; a `tests/` directory and a narrower `python_files` setting is the cleaner fix
- [ ] **[fill-in]** Unit tests for the validation check functions from A3 — the highest-value tests in the codebase, because they're pure functions encoding real business rules with no model or database involved
- [ ] **[fill-in]** Unit tests for the routing function: each of the three branches, plus the `None` confidence case
- [ ] **[fill-in]** Unit tests for reconcile's decision logic against a seeded database, covering insert, update, no-op, and the set-diff delete. This is where `polyfactory` (a dependency since Phase 3, still unused) earns its place
- [ ] **[written]** A fake model client so the graph can be tested end to end without Ollama running. Deterministic, fast, and it makes the pipeline testable in CI — which the real client never will be
- [ ] **[written]** Widen mypy to `agent_worker/` in CI and clear the errors (G15). Do this last in the track, once the code has stopped moving

### A8. Evaluating the pipeline, not just the model

Phase 5 evaluated whether a *model* could extract. This evaluates whether the *pipeline* produces correct calendar data — a different question, and the one the "validation approach for agentic outputs" requirement is really about.

- [ ] **[fill-in]** Hand-label the four fixtures with their correct extraction — what a perfect run would produce. Tedious, and it's the thing that makes every measurement below possible
- [ ] **[fill-in]** Promote `eval/run_eval.py` from throwaway to a real harness that scores a full graph run against those labels: precision and recall on shows found, field-level accuracy, and how often the retry loop fires
- [ ] **[fill-in]** Use it to answer the questions A3 left open — is 0.8 the right threshold, is 3 the right retry cap, does the escalating-prompt retry actually recover failures or just cost tokens
- [ ] **[fill-in]** Check whether the model's self-reported confidence correlates with actual correctness against the labels. Phase 5 judged calibration by eye on a handful of pages; with labels you can check it properly. If it doesn't correlate, routing on it is a design problem worth knowing about

---

## 6. Track B — Next.js and React from scratch

The stated goal is a primer on starting a React/Next.js app from scratch. `apps/calendar` isn't from scratch — it's `create-turbo`'s template with a health check bolted on. B1 fixes that by stripping it back to nothing and building up, which teaches more than editing a template down.

### B1. Strip to bare, then rebuild the shell

- [ ] **[written]** Delete the template: the Turborepo logo and CTAs, `page.module.css`, the `ThemeImage` component, the demo SVGs in `public/` (G18)
- [ ] **[fill-in]** Resolve the three-buttons problem (G19). Concretely: `packages/ui/src/button.tsx` (template) and `apps/calendar/components/ui/button.tsx` (stray copy) both go; `packages/ui/src/components/button.tsx` (shadcn) stays, and `layout.tsx`'s import updates. Also worth understanding while you're in there: `packages/ui/package.json`'s `"exports": {"./*": "./src/*.tsx"}` is what makes `@repo/ui/components/button` resolve to a file path, and why there's no build step
- [ ] **[fill-in]** Commit to Tailwind and drop CSS Modules (G20). Both are currently active
- [ ] **[fill-in]** Real `metadata` in `layout.tsx` (G21), and a root layout with actual application chrome
- [ ] **[fill-in]** Keep the health check, but move it to `/health` as a diagnostics page rather than the home page. It's useful and it shouldn't be what visitors see

**The primer this produces.** Worth writing down as you go, because these are the questions that are genuinely confusing coming to Next.js fresh, and the answers are load-bearing for everything after: what the App Router does with the filesystem; why `page.tsx`, `layout.tsx`, and `loading.tsx` are special names; what "Server Component by default" actually means for where your code runs and what it can touch; what `'use client'` costs; and why `page.tsx` already has `export const dynamic = "force-dynamic"` on it.

### B2. Routes and data loading

- [ ] **[fill-in]** The route structure from `requirements-initial.md`: `/` (four-week calendar), `/day/[date]`, `/venue/[id]`, `/venues`, `/artist/[id]`, `/artists`. Create them as static placeholders first — seeing the URLs resolve before any of them render real data makes the filesystem-routing model concrete
- [ ] **[written]** A typed API client in `apps/calendar/lib/` wrapping `fetch` against FastAPI, using the Track 0 types, reading from the JSON fixtures until Track A's endpoints exist (G23)
- [ ] **[fill-in]** Load data in a Server Component and render it. Specifically worth noticing: this is a `fetch` with no `useEffect`, no loading state, and no client-side data library — and understanding *why* that works is most of understanding RSC
- [ ] **[fill-in]** Filters as URL search params, not component state, per `arch-initial.md` Section 4. This is the decision with the most downstream consequences in the whole frontend: it's what makes a filtered calendar shareable, bookmarkable, and server-rendered from the URL alone

### B3. The calendar

The hard part, and deliberately not a solved problem you can install — `arch-initial.md` is explicit that this isn't a month/week/day grid, it's "closer to a feed."

- [ ] **[fill-in]** The layout: a vertically scrolling list of dates, each date a horizontally scrolling row of venue columns, each venue column holding one or two show blocks. Build it with static data first — the layout is the hard part and data makes it harder to debug
- [ ] **[fill-in]** Responsive behavior across phone, tablet, and desktop, per the global requirement. Nested scroll regions are where this gets genuinely tricky on touch devices
- [ ] **[fill-in]** The show block component in `packages/ui`, since the day view and venue page reuse it
- [ ] **[fill-in]** The filter header: venue and artist multi-selects with type-to-filter, and the future-only month dropdown populated from months that actually have shows
- [ ] **[fill-in]** The empty state — "No matches found" with a reset link — which the requirements call out specifically
- [ ] **[fill-in]** Dates via Temporal (`@js-temporal/polyfill` is already installed). A calendar that renders dates in the metro's timezone rather than the browser's is a correctness requirement here, not a detail, since `metro.timezone` exists precisely for this

### B4. Detail pages

- [ ] **[fill-in]** Venue page: metadata plus the calendar filtered to that venue
- [ ] **[fill-in]** Artist page: metadata plus upcoming shows as a list
- [ ] **[fill-in]** `/venues` and `/artists` — flat alphabetical lists, deliberately simple per the requirements
- [ ] **[fill-in]** `/day/[date]` with its three sort modes (venue-alpha, venue-time, artist-alpha), also in URL params
- [ ] **[written]** `schema.org` Event JSON-LD on show and venue pages, per `arch-initial.md` Section 4's SEO reasoning

### B5. Frontend testing

- [ ] **[written]** `vitest` + `@testing-library/react` set up in `apps/calendar` (specified in the arch doc, not yet installed)
- [ ] **[fill-in]** Component tests for the pieces with real logic — the filter header, the empty state, the date grouping
- [ ] **Deferred:** Playwright end-to-end tests. Worth doing, but after the UI stops changing shape every session

---

## 7. Learning deliverables

Three short documents, written as the corresponding work lands rather than at the end. These are the "solid overview" goal made concrete — if they can't be written clearly, the thing they describe probably isn't clear yet either.

- [ ] **Agent orchestration** (after A6) — why a graph rather than a script, what the state object is actually for, where the conditional edge earns its complexity, and the honest counterfactual: which parts of this would be simpler as a plain function with a `for` loop, and what LangGraph is genuinely buying in exchange
- [ ] **Validating agentic output** (after A8) — the layered picture this phase builds: schema constraints via `instructor`, deterministic rule checks, model self-reported confidence, bounded retry with escalation, and human escalation as the floor. Which layer catches which kind of failure, and what each one misses
- [ ] **Auditability** (after A4) — what "auditable by construction" means in practice, why append-only matters, why reconcile and commit are separate nodes, and a worked example tracing one show from fetch to row

---

## 8. Still deferred after this phase

Unchanged from `arch-initial.md` Section 11 unless noted:

- Everything hosted — Railway agent worker, DeepInfra, R2, Resend, Turnstile, Neon–Vercel integration, branch protection
- Public edit and flag endpoints, and with them the `contributor`, `flag`, and `venue_submission` tables
- The genre / instrument / member vocabulary tables and their join tables — no UI edits them yet
- Playwright fetching, and with it whichever venue needs click-driven pagination. `venue.fetch_strategy` exists as a column from A1 with only the `http` path implemented
- The image-embedded-show case (Terminal Bar). Phase 5 proved the model can read it from a local image file; detecting and downloading images out of a live page is separate work
- The MCP admin server. `arch-initial.md` positions it as the operational interface that removes the need for an admin frontend — genuinely useful, but it's an interface onto a pipeline that should be finished first
- `apps/admin`'s purpose (G22). It has no v1 job. Leaving an untouched template in the repo is a small cost; deciding what it's for prematurely is a larger one
- Chat search, vector storage, multi-metro, revert as a user-facing action, donations

---

## 9. Suggested starting point

Track 0 first — it's short and it unblocks both tracks. Then A1, because everything in Track A needs the models, and because B2's API client is more satisfying to write against a contract that's already real on both ends.

After that the tracks are genuinely independent. A reasonable rhythm is one Track A milestone, then one Track B milestone, alternating — A1 → B1 → A2/A3 → B2 → A4 → B3, and so on. The one real ordering constraint inside Track A is that **A4 comes before A5 and A6**: building the audit trail before the logic it audits means you debug reconcile and commit by querying the database instead of by reading `print()` output.
