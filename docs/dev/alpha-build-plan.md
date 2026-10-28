# Alpha Build Plan — from scaffolding to a working local app

**Status:** Plan approved, build in-progress

**Date:** September 28, 2026

**Version:** v0.1 (the alpha). The known-gap catalogue in §1.3 is cited as `G<n>`. They are `v0.1-G<n>` outside of this file.

**Purpose:** The plan for the phase after `env-setup.md`. That runbook's job was proving every layer can talk to every other layer. This one's job is turning that into an application that actually does something, running entirely on the local machine.

Read `env-setup.md` first for what exists and why. This document assumes `docs/arch/arch-initial.md` (design), `docs/arch/data-model-initial.md` (schema), and `docs/arch/requirements-initial.md` (screen-by-screen behavior) as the specification — it plans work against them rather than restating them.

**Explicitly out of scope this phase:** anything hosted. Vercel, Railway, Neon, and the deployed services stay as they are — working, and left alone. Nothing below requires a deploy to verify. The three hosted-service items still open in `env-setup.md` (the Railway agent worker service, DeepInfra, branch protection) stay open.

**Renamed October 12, 2026** from `v1-build-plan.md`: this phase was never going to be a real v1. The phase after it, which takes the app onto the hosted services and finishes the extraction accuracy work on hosted inference, is `alpha-deployment-plan.md`.

**Scope migrated October 21, 2026 (Ari):** **A1b** (the read routes on the database) and **A8** (evaluating the pipeline) moved to `alpha-deployment-plan.md`, as C2 and as C5 plus C7. Both depend on hosted work: A1b has to merge only after the hosted database is migrated, and A8's tuning questions can only be answered on the model that ships. Their headings stay below as pointers, so references to "A1b" and "A8" in other documents still resolve. What was left in this plan was B6, signed off October 22, 2026.

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
| G24 | The metro name is hard-coded in the root layout (footer text and the `description` metadata). It should come from the metro record. The contract has no metro endpoint — `MetroSummary` appears only nested inside `VenueDetail` — so this needs a small contract addition first. Single live metro for v1, so no `metro_id` parameter (`api-contract.md`: metro scoping) | `apps/calendar/app/layout.tsx` | B2 |
| G25 | `html_clean` keeps only visible text, so `<img src>` / `<a href>` URLs never reach the model, and `ShowExtraction.image_url` (added in A2) can't be populated from a text page — it is null in practice. Found while planning A2 (the fixtures contain 11–29 `<img>` tags each) | `agent_worker/nodes.py` (`html_clean`) | A3 (fetch) |

---

## 2. Definition of done

This phase is finished when, on a laptop with no network access to any hosted service:

1. `docker compose up -d` and two dev commands bring up the whole stack.
2. The agent worker runs against a real venue calendar URL and writes real `show` and `artist` rows to local Postgres — insert, update, and soft-delete all exercised across two consecutive runs.
3. Every step of that run is queryable afterward from `agent_run` and `audit_log`: what was fetched, what the model returned, what validation decided, why reconcile chose what it chose, and what got written.
4. The Next.js calendar renders those rows — the real four-week vertically-scrolling, horizontally-venue-scrolling layout from `requirements-initial.md`, not a list — with venue and artist detail pages behind working links.
5. `uv run pytest` covers the agent pipeline's decision logic, not just `/health`, and CI stays green with mypy widened to `agent_worker/`.

Point 3 is the one worth being strict about. "Auditable" is a stated requirement of this project, and the only way to know it's real is to be able to answer "why does this row look like this?" entirely from the database.

**Amended October 21, 2026:** point 4 cannot be met while the API serves `app/sample_data.py` instead of the database, and A1b, which changes that, moved to `alpha-deployment-plan.md` as C2. So this phase's definition of done is closed by C2's local verification (run the worker twice, check that the calendar renders the rows), alongside B6. Points 1, 2, 3 and 5 are covered by the milestones above.

---

## 3. How the two tracks work

Two tracks, alternating rather than strictly ordered:

- **Track A — Python, the agent, the data layer.** Depth on orchestration, validation, and auditability.
- **Track B — Next.js and React.** The calendar UI, built up from a minimal shell rather than edited down from a template.

They meet at one place: **the API contract**. Track 0 below defines it once, up front, and is the only genuinely blocking work — after it, either track can move without waiting on the other. Track B can build against a static fixture of that contract's JSON long before Track A produces real rows, which is exactly what makes the parallelism work rather than just being context-switching.

**Notation for who writes what** (per the split-by-area decision):

- **[fill-in]** — I write the file around its key points of interest and leave the 1–3 critical spots as `TODO(Ari)` blocks: what each key point is, the near-exact code to copy in, and the test that proves it. You inspect each one, copy the code in by hand, and run its check; everything else is done. Full protocol: `AGENTS.md`, "[fill-in] tasks". [UPDATE OCT 8, revised] Speed still matters, so the code in each gap is spelled out and should take minutes. But a gap stays open until you fill it or ask for that specific gap to be filled — "go ahead with the plan" produces the scaffold, not the filled-in file. (B1 got this wrong: its fill-in items were implemented outright.) [UPDATE OCT 15] Once a gap is filled, its `TODO(Ari)` block is rewritten as an ordinary why-comment and the scaffold language comes out of the code and its tests; the key point stays in the milestone's implementation plan, which is the paper trail (`AGENTS.md`, "[fill-in] tasks", step 4).
- **[written]** — I write it complete and note the non-obvious parts. Reserved for mechanical work where typing it out adds little: model definitions, migrations, seed data, test fixtures, config.

ALWAYS write tests first.  Discuss how you plan to approach unit tests.

[UPDATE OCT 8] Each milestone gets its implementation plan written to `docs/dev/implementations/<milestone>-<slug>.md` and reviewed by a *different model* before any code is written. See `AGENTS.md`, "Implementation plans".

---

## 4. Track 0 — the contract (blocking, do first)

**Status: complete**, except the one decision it deliberately leaves open. Full write-up in `docs/dev/api-contract.md`.

- [x] **[written]** `.env.example` in `apps/api/` listing every variable `Settings` requires, plus the not-yet-required ones (Mongo, R2, the shared secret) commented out so their shape is known before they're needed (G17)
- [x] **[written]** The read API's response shapes, as Pydantic models in `apps/api/app/schemas.py` — seven endpoints covering the calendar, day view, show/venue/artist details, the two list pages, and the month dropdown. The enums they share with the ORM models (A1) and the audit writes (A4) live in `apps/api/app/enums.py`, so neither layer owns the definition
- [x] **[written]** JSON fixtures under `apps/calendar/lib/fixtures/` — **generated** from those models by `apps/api/scripts/generate_fixtures.py` (`make fixtures`) rather than hand-written, so they can't drift from the contract. 21 shows over four weeks across the same four venues the Phase 5 extraction fixtures came from, deliberately including the untidy cases: no listed start time, multi-act bills, a free show, an empty day, one artist at two venues (21 shows when written, 25 since B3)
- [x] **[fill-in]** How TypeScript types stay in sync with the Pydantic models. **Decided: generated from FastAPI's OpenAPI schema** (`openapi-typescript`). `make types` regenerates; `make contract-check` fails on stale output and runs as its own CI job. `lib/types.ts` is now ~30 lines of friendly aliases over the generated `lib/api-types.ts`. Zod was considered and deferred rather than rejected — it solves runtime shape checking, a different problem from build-time sync, and arrives with the edit forms
- [x] **[written]** Nine read routes serving `app/sample_data.py` over real HTTP (`app/routers/`), so the frontend calls the actual API rather than importing JSON. A1b swaps the function bodies for queries without touching the signatures. 23 route tests
- [x] **[written]** A root `Makefile` so "run the app" is one command. `make setup` for a cold start, `make dev` for Postgres + FastAPI + Next.js together, plus targets for migrations, fixtures, psql, and a `make check` that mirrors CI exactly

**Verified working:** `make dev` brings up all three, `/health` and `/health/db` both answer against local Postgres, Ctrl-C leaves no orphaned listeners, and `make check` is green.

**Three decisions Track 0 made that are worth knowing before building on it** (reasoning in `api-contract.md`):

- Inherited show fields — age restriction, alcohol, setting, seating — are **resolved server-side**. The read API returns the effective value and doesn't say whether it came from the show or the venue. The write API will have to, which is the clearest case in this project for read and write shapes being different models rather than one reused out of habit.
- `Decimal` crosses the wire as a **string** (`"15.00"`), not a number, to avoid float rounding on money. And all-null admission means *not stated*, never free — `free_admission` is true only when the listing says so explicitly.
- Fields backed by deferred tables (venue/artist socials, genres, members, instrumentation) are **absent rather than always-empty**. A consumer can't tell "no Instagram" from "feature doesn't exist yet," and a permanently-`[]` field teaches the UI to render an empty state that isn't real.

## 5. Track A — Python, the agent, the data layer

### A1. The data layer — models, migrations, seed

Foundation for everything else in this track. Scope per the decision above: core calendar plus audit; the contributor/flag/submission and genre/instrument/member vocabulary tables wait for the features that read them.

- [x] **[written]** Create `app/db/` as the shared model package `arch-initial.md` Section 5 calls for — importable by both FastAPI and `agent_worker`, with the declarative base, session factory, and an async engine that `app/main.py` switches over to using (G11)
- [x] **[written]** SQLAlchemy models: `metro`, `venue` (filled out to the full column list), `show`, `artist`, `show_artist`, `event`, plus the enum types those need, per `data-model-initial.md` Section 2
- [x] **[written]** SQLAlchemy models: `agent_run` and `audit_log`, per `data-model-initial.md` Section 3
- [x] **[fill-in]** Point Alembic's `env.py` at the models' metadata so autogenerate works, then generate the migration and read what it produced before applying it. Autogenerate is reliable for tables and columns and unreliable for enum types and constraint changes — knowing which parts to check by hand is the actual skill here, and the hand-written first migration is a good comparison point
- [x] **[written]** A seed script creating the Minneapolis/St. Paul metro row and the four venues the Phase 5 fixtures came from, with their real calendar URLs and `fetch_strategy` set appropriately (G13)
- [x] **[fill-in]** Delete the dead `FIXTURES_DIR = ...` (G1)

Implemented per `docs/dev/implementations/a1-data-layer.md`, which records the two review rounds and every departure from `data-model-initial.md` (omitted `contributor` FK columns, `Numeric` precisions, extra indexes, no timestamps on `agent_run`). The DB tests run against a real `calendar_test` database; `make check` requires one (`REQUIRE_DB=1`).

### A1b. Move the read routes onto the database

**Migrated to `alpha-deployment-plan.md` as C2 (October 21, 2026), built in `docs/dev/implementations/c2-api-reads-database.md`.** The scope is unchanged: replace the bodies in `app/routers/` with queries, put the routes on an async session dependency, migrate `test_routers.py`, and delete `app/sample_data.py` once nothing reads it (deciding first where the frontend fixtures come from). The items and their markings moved with it, plus two additions: migrate and seed the hosted database before the merge, since merging deploys the production API, and verify locally that two worker runs leave a calendar that renders. *(Update, October 27, 2026: built in C2; the routes read Postgres on its branch, and the sample world now lives in `app/testing/sample_data.py`.)*

### A2. The extraction schema, against the real requirements

Plan and review: `docs/dev/implementations/a2-extraction-schema.md`. **Done — signed off by Ari October 12, 2026, together with A2.1**; the extraction-quality debt it left is carried to `alpha-deployment-plan.md` C6 (formerly H1). Built, verified and closed October 10, 2026. The four fill-in items were filled by Ari, all of A2's decisions are resolved (including: a time with no AM/PM is read as PM; `metro.timezone` is the zone extracted wall-clock times are in), `make check` is green and `local_test` runs end to end. The eval ran under a working 32768-token window (derived model `gemma4-e4b-32k`; Ollama's `/v1` ignores a request's `num_ctx`, see `notes.md`). **Verdict, amended October 10: mixed** — completions 16 → 18 of 18, failed parses 14 → 1, invented start times 8 → 2 (G8 fixed), non-music leaks 26 → 0 (G9 fixed); but **act splitting regressed badly** (multi-act listings came back as one act named with the whole title — Zhora ~17 of 23 split → 0), and the model writes `free_admission: false` instead of null, merged separately-timed listings on one White Squirrel seed, and invented one end time and one image URL. **Ari judged the resulting quality unacceptable (Oct 10)**; the refinement is A2.1, below. Details in the plan's Eval results (and its Addendum) and "Refinement strategies".

- [x] **[fill-in]** Bring `ShowExtraction` in line with `requirements-initial.md`'s "Agent Extraction: Fields" — replace `ticket_info` with `admission_advance` / `admission_day` / `free_admission`, add the poster `image_url`, and add per-artist start time and sequence number. That last one changes `acts: list[str]` into a list of structured objects, which is a schema shape change, not just a field addition (G7)
- [x] **[fill-in]** Make `time` optional, and say so in its `description` — the description text is part of what `instructor` sends the model, so "leave null if the page doesn't state a start time" is an instruction, not a comment (G8)
- [x] **[fill-in]** Add the non-music-entry exclusion rule to the extraction prompt (G9)
- [x] **[fill-in]** Add the one-show-vs-several rule from the requirements ("listings under one time/ticket link are a single multi-artist Show") to the prompt
- [x] **[written]** Re-run `eval/run_eval.py` against all four fixtures with the revised schema and prompt, and record whether the added fields made extraction more or less reliable. A richer schema is more for the model to get right — this is worth measuring rather than assuming

### A2.1. Extraction reliability — meeting the accuracy standard

Plan: `docs/dev/implementations/a2.1-extraction-reliability.md` (approved by Ari October 10, 2026, after two plan-review rounds and a code review; decisions A2.1-D1–A2.1-D13 recorded there). **The bar is Ari's tiered accuracy standard** (`requirements-initial.md`, "Agent Extraction: Accuracy Standards"): date and acts 100% on the sample venues, no invented shows, other fields may be missing about 1 time in 10 but never wrong, about one non-music leak per month per venue at most, every run — and, Ari added, "when in doubt, include it". Gated on the venues production can fetch: White Squirrel (two captures), 7th St Entry, Mortimer's — 60 shows; Terminal Bar moved to informational on October 11 as an outlier layout; Zhora (needs a browser) and Midway (a bot challenge) are out of reach.

**Done — signed off by Ari October 12, 2026, with the gate unmet.** The pipeline's adopted configuration (temperature 0, the year rule, the JSON-LD route, the separate status question, the act conventions, line-break cleaning, title split on the model route) scores **56 of 60** on the gated pages. That holds both in the 5-run confirmation (`a21-confirm`, deterministic) and in `a21-review2`, re-run after code review round 2 took every labelled answer out of the prompt. No show is invented and no stated field is wrong; the gate fails on four act names. Accepted for the alpha: the title-split route doesn't return per-act start times (A2.1-CR2-9). **The remaining work — a larger hosted model for the act splitter, a held-out test set, per-act start times — is milestone C6 (formerly H1) of `alpha-deployment-plan.md`.**

- [x] **[written]** One extraction entry point (`extraction.py`, `llm.py`) shared by `extract_node` and the eval harness; the experiment switches (`ExtractionConfig`)
- [x] **[written]** Fixtures captured with the pipeline's own fetch (`eval/capture.py`) — the A2 fixtures were browser captures
- [x] **[written]** Labels for the gated and informational pages (`eval/labels.py`), each row with the page text it was read from
- [x] **[fill-in]** Ari labels the Mortimer's page — the ground-truth key point (A2.1-D11; A8's labelling item, pulled forward)
- [x] **[fill-in]** What counts as correct: `scoring.match_shows` (date is identity, time a field) — A2.1-K2
- [x] **[fill-in]** Convert, don't drop: `jsonld.local_wall_clock` — A2.1-K1
- [x] **[fill-in]** Deterministic first: the routing branch in `extract_page` — A2.1-K3
- [x] **[fill-in]** Narrow the task: the act splitter's instruction — A2.1-K4
- [x] **[written]** The experiment ladder, one change per label (results and decisions in the plan's "Experiment results"); beyond it, by Ari's decisions: the separate status question, the inclusive exclusion wording, title split on the model route, hosts-as-acts and the album-release convention
- [x] **[written]** The 5-run confirmation on all pages (`a21-confirm`, October 11–12, 1 h 53 min): **56 of 60 on every run, deterministic; no invented show, no leak, every field right; gate FAIL on the same four act names** (deferred A2.1-E1, A2.1-E2)
- [x] **[written]** Code review round 2 (Claude Fable 5.1) resolved, 12 of 12: the status merge made strict, the prompt's examples made up rather than quoted from the labels, every prompt stored in results files; gated re-run `a21-review2`: 56 of 60
- [x] Sign-off — Ari, October 12, 2026

**Deferred from A2.1** (details, evidence and reasons in the plan's "Deferred explorations", A2.1-E1–A2.1-E17):
- **Moved to `alpha-deployment-plan.md` C6 (formerly H1):** a hosted larger model for the act splitter (A2.1-E1, with A2.1-E2 and A2.1-E3), the fix for the four remaining act errors and not possible on the development laptop (16 GB RAM, 12 GB free disk); a held-out test set; per-act start times on the title-split route; throughput and thinking on/off on hosted inference (A2.1-E15, A2.1-E4)
- A code check that each act appears in its title (A2.1-E3) and thinking on/off (A2.1-E4) — small experiments not yet run
- Terminal Bar's date-then-lines layout (A2.1-E6: group a date's lines before extraction) and shows listed only in images (A2.1-E7) — Ari: watch for other venues before investing
- Sources beyond page text: First Avenue detail pages for times (A2.1-E9), Mortimer's Wix data (A2.1-E10), an iCal reader (A2.1-E11), browser fetching for Zhora (A2.1-E12), a sanctioned route for Midway (A2.1-E13)
- Artist display text vs. associations (A2.1-E14); throughput (A2.1-E15, also in §8); JSON-LD validation guards (A2.1-E16, in A3); persisting each extraction's audit record (A2.1-E17, in A4)

### A3. Validation and retry — making the loop real

The most conceptually interesting work in this track, and where the "validation approach for agentic outputs" requirement actually gets answered.

Plan and review: `docs/dev/implementations/a3-validation-and-retry.md` (approved by Ari October 12, 2026, after two plan-review rounds; decisions A3-D1–A3-D13 recorded there). **Built October 12, 2026; five `TODO(Ari)` gaps (A3-K1–A3-K5) are open**, so the [fill-in] boxes below stay unticked until Ari fills them. The plan re-marked three bullets [written] (A3-D8: the JSON-LD guards, the repairs, the non-empty-`acts` check — no single line in them teaches a concept). Where each landed: the checks in `agent_worker/validation.py`, the verdict, router core and escalation tiers in `agent_worker/policy.py`, the wiring in `nodes.py` and `graph.py`. Gaps G2–G6 are closed once the gaps are filled. G25's mechanism is built but was measured not adoptable (A3-D12), so `image_url` stays null on text pages whatever is filled in.

- [ ] **[fill-in]** Wrap `extract_node`'s model call so a raised exception becomes a recorded failed attempt that the retry loop can act on, instead of killing the graph (G2) *(scaffolded; A3-K1 open in `nodes.py`)*
- [ ] **[fill-in]** Make `validate_node` read `page_readable` and distinguish three outcomes, not two: valid extraction, confirmed-empty page (a legitimate pass — the venue has no shows listed), and unreadable page (a failure worth retrying). This is the field's entire reason for existing (G3) *(scaffolded; A3-K2 open in `validation.py`)*
- [ ] **[fill-in]** Implement the three named checks — completeness (required fields present), plausibility (dates not in the past, times in a sane range), internal consistency (`free_admission` not true alongside a price) — as functions separate from the node, so they're testable without running a graph (G4) *(all written; A3-K3 open in `validation.py`: the date window and the next-morning end time)*
- [ ] **[fill-in]** Decide how a check failure combines with the model's self-reported confidence into the single routing signal. Worth thinking about: a deterministic consistency failure is a different kind of evidence than a model saying it's 0.6 sure, and collapsing both into one float may be losing information the router needs. *(Decided: a verdict, not a float — `policy.combine`, A3-K4 open)*
- [ ] **[fill-in]** Make each retry attempt escalate the approach rather than repeating the call (G5). `arch-initial.md` is specific about the order: narrow the task or address the specific ambiguity in the prompt first, larger model second *(scaffolded; A3-K5 open in `policy.py`; the larger-model tier is built but unusable until C6, formerly H1 — A3-D5)*
- [ ] **[fill-in]** Fix the routing function's `None` comparison and the two-enums-one-string collision (G6) *(re-marked [written] for `graph.py`; the router reads `policy.decide_route`, A3-K4 open)*
- [x] **[written]** Move the confidence threshold and retry cap out of the routing function into named configuration, so the eval work in A8 can vary them *(`RetryPolicy`, on the state)*

- [ ] **[fill-in]** Consistency/plausibility checks must allow an `end_time` earlier than `time` *(A3-K3)*: it means the next day. White Squirrel lists "Nona … 9:00 pm - 12:00 am", which extracts correctly as start 21:00, end 00:00, and a naive "ends before it starts" check (or A6's write) would flag or reject a correct record
- [x] **[written]** *(re-marked, A3-D8; done in `validation.py`)* Handle what A2's eval showed the model gets wrong, as validation rather than prompt tweaks: *(moved to A2.1: `free_admission: false` is now coerced to null in the schema; the single-price rule was reworded by Ari — an unlabelled price is the day price, a "buy" ticket price the advance price, `requirements-initial.md`)*; an image URL must appear verbatim in the page text or be dropped (one invented URL in `after`); and `end_time` equal to a stated start time with `time` null is a misplaced start (one case). Also decide what `is_ambiguous` means now (it fell to 0 in `after`), since validation reads it
- [x] **[written]** *(re-marked, A3-D8; done: such a show is excluded and reported with a warning, not failed, and excluded does not mean confirmed non-music)* The completeness check also requires `acts` to be non-empty. A2 deliberately left `acts` as a plain list that may be `[]` (a schema rule would turn one leaked "Karaoke" entry into a full-page re-ask); a show with no performing artist isn't a show (`requirements-initial.md`: "Artists — one or more"), so this is where it is dropped or flagged
- [x] **[written]** Preserve image links in fetch/cleaning so `image_url` can actually be populated (G25) *(built behind `ExtractionConfig.keep_image_urls`, off by default; adoption is A3-D12's rule. **Measured October 12: not adopted** — URLs came through (Mortimer's 17, none invented) but act splitting got worse on the model route, 55 of 60 against 56; the switch stays off, and image links on text pages stay null until C6 (formerly H1) or a separate image-extraction call)*: keep poster `<img src>` URLs as text the model can copy, and have the eval's "any returned URL appears verbatim in the page" check score it. Until then `image_url` is a mostly-empty field, accepted in A2
- [x] **[written]** Revisit `max_retries` on the `instructor` call *(lowered 3 → 1, A3-D7)* (A2 made the default of 3 — up to 4 attempts per call — explicit at both call sites). The graph's own 3-attempt cap multiplies it, so one venue can cost up to 12 model calls

- [x] **[written]** *(re-marked, A3-D8; done in `validation.py`)* From A2.1: guards on the JSON-LD route — a page whose JSON-LD lists fewer events than its visible text (under-reporting), and a source-aware check on JSON-LD end times (A2.1 takes `endDate` only within 6 hours of the start); a date plausibility check behind A2.1's year rule (more than a month past or a year out is implausible); and replace the JSON-LD route's placeholder `confidence = 1.0` when deciding how checks and confidence combine

### A4. Auditability — the part that makes the rest inspectable

Plan and review: `docs/dev/implementations/a4-auditability.md` (approved by Ari October 14, 2026 with decisions A4-D1 to A4-D8 as recommended; one plan-review round, 8 of 8 resolved). **Done — signed off by Ari October 15, 2026.** Built October 14; the two `TODO(Ari)` gaps (A4-K1 and A4-K3) were filled by Ari and verified locally against Docker and Ollama; one plan review round and one code review round, both fully resolved. A4-K2 (the confidence conversion) was re-marked [written] at approval. The sync/async question below is settled (A4-D1): the graph is `ainvoke`-only, the nodes stay synchronous functions run in a thread, behind one wrapper that writes each node's audit row. A6's `escalate_node` audit row landed here (A4-D5).

Do this *before* reconcile and commit, not after. Building the audit trail first means the hard parts of A5 are debuggable from the database while you write them, rather than from `print()` statements.

**Known dependency from A1 — decide the sync/async question here, not in A6.** `app/db/session.py` provides an async, pooled engine created at import, but the worker's nodes are synchronous `def`s and this milestone writes `agent_run` / `audit_log` from all six. asyncpg connections are bound to the event loop that created them, so calling `asyncio.run()` once per node against that shared engine fails on the second node ("attached to a different loop"). Either make the nodes `async def` (LangGraph supports it; this pulls A6's async decision forward), or bridge with a **separate `NullPool` engine per `asyncio.run`** — never reuse `app.db.session.engine` across loops. No sync engine exists, and none should be added without a consumer.

- [x] **[written]** *(`app/log_config.py`; the nodes' `print()`s are `structlog` calls)* `structlog` configured once, with a processor chain that renders human-readable output locally and JSON otherwise (G12)
- [x] **[fill-in]** *(filled by Ari: A4-K1, `agent_worker/main.py` `run_venue`)* An `agent_run` row created at the start of each venue's processing cycle and closed at the end, with its id carried in the graph state — this is `arch-initial.md`'s `parent_run_id`, and every audit row for the run points at it
- [x] **[written]** *(re-marked at approval, was [fill-in]; `agent_worker/audit.py` `entry_for` and `trace.audited`, plus a new `audit_log.detail` JSONB column for the evidence, A4-D2. Reconcile and commit write placeholder rows until A5/A6)* An `audit_log` write from each of the six nodes, carrying `step_type`, `attempt_number`, `source='agent'`, and — on the agentic steps — `model_used` and `confidence`. Because it's append-only, a retry adds a row rather than replacing one, which is what preserves the retry history
- [x] **[fill-in]** *(filled by Ari: A4-K3, `agent_worker/trace.py`; staged on every extract attempt, failures included; local `mongo:7.0` in docker-compose since October 15, 2026, pinned because MongoDB 8.x won't start on Docker Desktop's kernel, see `notes.md`; Atlas waits for C3 and C8, formerly H3)* The MongoDB raw-staging write in `extract_node` (`arch-initial.md` Section 6). Already provisioned, never used; this phase gives it its consumer. `pymongo`'s `AsyncMongoClient`, not `motor` — the arch doc is specific about this and the reason is that Motor is deprecated
- [x] **[written]** *(`docs/dev/audit-queries.sql`, four queries, executed by `test_audit_queries.py` and checked in `psql`)* Two or three SQL queries saved under `docs/dev/` that answer the questions a human actually asks of an audit trail — "show me everything that happened in run N," "which runs escalated and why," "what changed about this show and when." Being able to run these is the real test of whether point 3 in §2 is met
- [x] **[written]** *(the MongoDB staging document is the record, A4-D4; `agent_worker/staging.py`)* From A2.1: persist each extraction's record — the route taken (JSON-LD or model), the text actually sent, the route's notes (rejected titles, whether the status question ran), the raw model output and the request configuration — the same things A2.1's eval records per page, so a production run can be audited the way the eval runs were (A2.1 plan, A2.1-E17)
- [ ] **Deferred, on purpose:** the R2 snapshot write. It needs an account this phase doesn't provision, and `audit_log.snapshot_key` can stay null. Everything else in the audit trail works without it

### A5. Reconcile — the decision logic

Plan and reviews: `docs/dev/implementations/a5-reconcile.md` (plan approved by Ari October 17, 2026 with decisions A5-D1 to A5-D12 settled as recommended; one plan-review round, 16 of 16 resolved). **Done — signed off by Ari October 19, 2026.** Built October 17, 2026; plan review and code review round 1 resolved. The five `TODO(Ari)` gaps (A5-K1–A5-K5) were filled by Ari on October 19, 2026 (commit `efe95ca`); the scaffold was cleaned up on October 19, and Ari verified it locally. Reconcile decides and writes nothing: the window is derived from the page's own listings (A5-D1), and its effect on the calendar can't be observed until A6.

- [x] **[fill-in]** Show matching on the composite key (venue, date, time) producing insert / update / no-op, per `data-model-initial.md`'s outcome table. Deterministic, no model involved *(scaffolded; A5-K1 open in `reconcile.py` (`_null_time_pairs`), the null-time rule is A5-D3)*
- [x] **[fill-in]** **Also from A2's eval:** a multi-listing day can come back as one show with a null show-level `time` and per-act start times (White Squirrel, seed 2: 6 shows instead of 12, in both new-schema labels). Reconcile must not assume a show has a `time`, and A3 may want to flag a show whose acts carry different start times as a likely merge *(re-marked [written], A5; reconcile never assumes `time`, pinned in `test_reconcile_shows.py`)*
- [x] **[fill-in]** **Open decision, made reachable by A2: what does the composite key do with a null `time`?** A2 made the extraction's `time` optional (G8), so a show can arrive untimed — and in SQL `NULL = NULL` is not true, so a naive (venue, date, time) match never finds an untimed show: every run would insert a duplicate and soft-delete the previous one, and two untimed shows on one date would collide. *Recommendation:* an untimed show matches a stored show on (venue, date) when exactly one candidate exists on either side, otherwise insert and flag for review; a time that appears later (null → 20:00) counts as an **update**, not remove + insert. Ari confirms in A5's plan. Also: the extraction field is `time`; reconcile maps it to `show.start_time`, and derives each act's `sequence_number` from list position when the extraction leaves it null *(decided by Ari October 17, 2026 (A5-D3): pair an untimed show when it is unambiguous, otherwise by shared acts; `sequence_number` is derived from list position in `reconcile.lineup_for`)*
- [x] **[fill-in]** The set-diff soft delete: shows stored for this venue but absent from this fetch, *within the date range the fetch actually covered*, get `status='removed'`. That date-range qualifier is the subtle part — pagination depth varies run to run, so the graph state needs to carry how far this run actually reached, which it currently doesn't *(scaffolded; A5-K2 open in `reconcile.py` (`removed_by_absence`); the window is derived in reconcile, not carried from fetch (A5-D1, A5-D2))*
- [x] **[fill-in]** Artist matching by name: exact match, no match, and the ambiguous middle. Exact and no-match resolve deterministically (no-match creates a name-only artist record per the requirements) *(scaffolded; A5-K4 open in `artist_match.py` (`classify_artist`))*
- [x] **[fill-in]** The ambiguous-artist branch — an LLM call inside `reconcile_node`, not its own node — with its decision written to `audit_log` carrying `model_used` and `confidence`, exactly like extract and validate. This is the one place in the pipeline where a model makes a database decision, which is precisely why it's the one that most needs auditing *(scaffolded; A5-K5 open in `artist_match.py` (`decide_ambiguous`); audit rows by `trace.audited` (A5-D11))*
- [x] **[fill-in]** From A2.1: times after midnight (Ari, October 10) — a show belongs to the night the venue lists it under, and a time before the 5:00 AM cutoff (decided by Ari October 11, `requirements-initial.md`, Show) is after midnight of that night — A2.1's JSON-LD route already applies it; sort and match with that in mind, and have B3/B4 display it as the next day ("1:00 AM Sat") *(re-marked [written], A5; `reconcile.night_sort_key`. The B3/B4 display was already done (`nightSortKey`, `formatShowTime`))*
- [x] **[fill-in]** From A2.1: cancelled and postponed listings arrive as extracted shows with a `status` (decided by Ari, A2.1-D12) — match them to the stored show and update it (soft delete, or a shown status if the requirements add one); and (venue, date, time) collides when one page lists two untimed shows on the same date (7th St Entry, Oct 31) — the match must tie-break on acts *(scaffolded; A5-K3 open in `reconcile.py` (`plan_for_listing`); stored as `removed` (A5-D6), a returning show is reactivated (A5-D7))*

### A6. Commit — the writes

Plan and reviews: `docs/dev/implementations/a6-commit.md` (plan approved by Ari October 20, 2026 with decisions A6-D1 to A6-D3 as recommended; two plan-review rounds, 19 of 19 resolved). **Done — signed off by Ari October 20, 2026.** Built October 20, 2026; the two `TODO(Ari)` gaps (A6-K1 and A6-K2) were filled by Ari (commit `5204c38`) and the scaffold cleaned up the same day; one code review round and two plan review rounds, all resolved; Ari ran the local verification. Commit writes each show in its own transaction with its audit row inside it (previous and new snapshots of the whole row plus its lineup, read from the database); an unchanged show writes no row (A6-D1); a show the database refuses is recorded and the others are still written (A6-D2). `event` rows are not part of A6 (nothing in extraction identifies a festival). The definition of done's point 2 can be checked end to end once the gaps are filled: run the worker twice and the second plan is all no-ops.

- [x] **[fill-in]** `commit_node` executing reconcile's decision against Postgres: `show`, `show_artist`, and new `artist` rows, in one transaction per decision, with the resulting `audit_log` row carrying `previous_value` / `new_value` JSONB snapshots (those are what a future revert restores) *(filled by Ari: A6-K1 and A6-K2 in `calendar_writer.py`. The writer is `PostgresCalendarWriter.write_show` (one transaction per show, its audit rows inside it, snapshots read from the database) and the loop `write_plan`; what to write is `commit.py`. The node prepares the operations and `trace.audited` awaits the writes, A4-D1)*
- [x] **[written]** Convert extracted prices at the write: A2's extraction schema carries `admission_advance` / `admission_day` as `float | None` (not `Decimal`, to keep the JSON schema the model sees simple), so commit converts with `Decimal(str(value))` and quantizes to `Numeric(10, 2)` *(done: `commit.insert_values` calls `reconcile.to_price`, the one conversion A5 defined; pinned in `test_commit_ops.py`)*
- [x] **[written]** *(done in A4-D5: `trace.audited` writes the escalate row with `outcome='escalated'` and the reason)* `escalate_node` writing a real `audit_log` row with `outcome='escalated'` rather than printing
- [x] **[written]** *(decided and built in A4-D1: the graph is `ainvoke`-only; the node bodies stay synchronous functions run in a thread behind `trace.audited`, on one event loop per process. A5/A6 `await` their database work in the wrapper's context; they don't reopen this)* Async vs. sync: the nodes are currently synchronous functions calling a synchronous `OpenAI` client, while `app/db/` and FastAPI are async. LangGraph supports both. Deciding whether to make the nodes async — and what that buys a job that processes venues one at a time — is a real call worth making explicitly rather than by accident

### A7. Testing

Plan and review: `docs/dev/implementations/a7-testing.md` (plan approved by Ari October 20, 2026 with decisions A7-D1 to A7-D3 as recommended, A7-D2 as revised in review; one plan-review round, 11 of 11 resolved). **Done — signed off by Ari October 21, 2026.** Built October 20, 2026; code review round 1 (5 nits) resolved. Most of A7 had been done by A3 and A5 as a side effect of building them tests-first, so the plan measured before it built: 883 tests collected (868 passed, 15 skipped), 583 test functions, 98% branch coverage, and mypy on `agent_worker/` at **75 errors, not "~11"** (57 of them one wrong annotation in `eval/run_eval.py`). What was left was small: make test collection safe to widen (G14), put the worker under the mypy gate (G15), pin six unpinned rules (eight tests), and tick the rest with evidence. There are no `TODO(Ari)` gaps: every remaining item was [written]. The suite is now 881 passed and 15 skipped (896 items, 13 new); mypy is clean on 104 files; `make coverage` reports 99% (17 missed statements, from 27).

- [x] **[written]** *(done: `testpaths = ["app", "agent_worker"]`, `python_files = ["test_*.py"]`; guard `app/tests/test_pytest_config.py`)* Fix `testpaths` so `agent_worker/` tests are collected, without re-collecting `local_test.py` (G14). *A2 had already added `agent_worker/tests`; what was left was that widening `testpaths` alone makes pytest import `local_test.py` on every run (pytest's default `*_test.py` glob matches it; measured with an import probe, see `notes.md`), so `python_files` is narrowed in the same change, and the guard fails if either setting regresses (A7-M8)*
- [x] **[fill-in]** *(done in A3, tests first: `tests/test_validation.py`)* Unit tests for the validation check functions from A3 — the highest-value tests in the codebase, because they're pure functions encoding real business rules with no model or database involved
- [x] **[fill-in]** *(done in A3: `tests/test_policy.py`, `tests/test_graph.py`)* Unit tests for the routing function: each of the three branches, plus the `None` confidence case
- [x] **[fill-in]** *(done in A5: `tests/test_reconcile_*.py`, `test_calendar_reader.py`; see `a5-reconcile.md`, Departures 3)* Unit tests for reconcile's decision logic against a seeded database, covering insert, update, no-op, and the set-diff delete. This is where `polyfactory` (a dependency since Phase 3, still unused) earns its place
- [x] **[written]** *(done in A3 and A5: `tests/fakes.py`'s `ScriptedCompletions` / `scripted_client()`, used by eleven test modules; the build plan's old name `ScriptedClient` never existed. `test_extraction.py` and `test_prompts.py` keep their own fakes on purpose: they answer every call the same way, a different contract (A7))* A fake model client so the graph can be tested end to end without Ollama running. Deterministic, fast, and it makes the pipeline testable in CI — which the real client never will be
- [x] **[written]** *(done: `[tool.mypy] files = ["app", "agent_worker"]`, tests and eval included, `make typecheck` and CI run a bare `uv run mypy`; 75 errors cleared; the one new `# type: ignore` is `run_eval.py`'s `--legacy` path)* Widen mypy to `agent_worker/` in CI and clear the errors (G15). Do this last in the track, once the code has stopped moving. *Departure: built before A1b and A8 instead of last, because the gate in CI is what keeps later changes to `eval/` and `extraction.py` typed*
- [x] **[written]** *(added in A7)* Eight tests for six rules nobody had pinned (the act splitter's duplicate and out-of-range ids, three JSON-LD edge cases, the status question's short-name fallback, the time normalizer's non-string refusal, reconcile's `None` guards, the fetch node's image route), each proved able to fail by mutation (A7-M1 to A7-M10)
- [x] **[written]** *(added in A7, A7-D1)* `make coverage`: a report-only branch-coverage run of `app/` and `agent_worker/`. No threshold and not in `make check` or CI, on purpose: a percentage gate invites tests that touch lines instead of proving behavior
- [x] **[written]** *(added in A7, A7-D2)* A `Proves:` comment on the 14 older tests that predated the convention (`test_health.py` and 13 router tests); a scan of all 594 test functions now finds none without one
- [x] Sign-off — Ari, October 21, 2026

### A8. Evaluating the pipeline, not just the model

**Migrated to `alpha-deployment-plan.md` and split in two (October 21, 2026).** Phase 5 evaluated whether a *model* could extract. A8 evaluates whether the *pipeline* produces correct calendar data, the question the "validation approach for agentic outputs" requirement is really about. The harness doesn't depend on a model, but half of what it answers does:

- **C5** has the labelling and the full-graph harness (the first two items), built now on the local model, plus two additions: scoring the database after two consecutive runs, and a validation-recall measure (which extraction errors validation catches and which it lets through).
- **C7** has the 0.8 threshold, the retry cap, whether the escalating retry recovers failures, and the confidence calibration check (the last two items). The larger-model retry tier can only run on a hosted model (A3-D5), and the numbers belong to the model that ships, so they follow C6.

The four items kept their `[fill-in]` marking.

---

## 6. Track B — Next.js and React

The goal is to understand each part of a React/Next.js app by building it up step by step. `apps/calendar` started as `create-turbo`'s template with a health check added. B1 strips it back to a minimal shell and builds up from there, so each piece is understood before it is used.

### B1. Strip to bare, then rebuild the shell

- [x] **[written]** Delete the template: the Turborepo logo and CTAs, `page.module.css`, the `ThemeImage` component, the demo SVGs in `public/` (G18)
- [x] **[fill-in]** Resolve the three-buttons problem (G19). *Done, with two corrections: the template button was imported by `page.tsx` (not `layout.tsx`) and also by `apps/admin`, so admin's page now uses the shadcn button (minimal edit); and the shadcn button exposed a latent `exports` bug — see `notes.md`. The template `card.tsx` and `code.tsx` went too.* Concretely: `packages/ui/src/button.tsx` (template) and `apps/calendar/components/ui/button.tsx` (stray copy) both go; `packages/ui/src/components/button.tsx` (shadcn) stays, and `layout.tsx`'s import updates. Also worth understanding while you're in there: `packages/ui/package.json`'s `"exports": {"./*": "./src/*.tsx"}` is what makes `@repo/ui/components/button` resolve to a file path, and why there's no build step
- [x] **[fill-in]** Commit to Tailwind and drop CSS Modules (G20). Both are currently active
- [x] **[fill-in]** Real `metadata` in `layout.tsx` (G21), and a root layout with actual application chrome
- [x] **[fill-in]** Keep the health check, but move it to `/health` as a diagnostics page rather than the home page. It's useful and it shouldn't be what visitors see

**B1 was done before the implementation-plan rule existed** (root `AGENTS.md`: written plan, different-model review, user approval). It has no file under `docs/dev/implementations/`; its review happened afterwards, and the findings were resolved in place. B2 onward follows the rule.

**Notes on the App Router.** Worth writing down as you go, because these are the questions the calendar's structure depends on, and the answers are load-bearing for everything after: what the App Router does with the filesystem; why `page.tsx`, `layout.tsx`, and `loading.tsx` are special names; what "Server Component by default" actually means for where your code runs and what it can touch; what `'use client'` costs; and why `page.tsx` already has `export const dynamic = "force-dynamic"` on it.

### B2. Routes and data loading

Plan and review: `docs/dev/implementations/b2-routes-and-data-loading.md`. **Done** (October 12, 2026; commit `e1eecd4`). The five `TODO(Ari)` gaps (B2-K1–B2-K5) were filled by Ari.

- [x] **[fill-in]** The route structure from `requirements-initial.md`: `/` (four-week calendar), `/day/[date]`, `/venue/[id]`, `/venues`, `/artist/[id]`, `/artists`. Create them as static placeholders first — seeing the URLs resolve before any of them render real data makes the filesystem-routing model concrete
- [x] **[written]** A typed API client in `apps/calendar/lib/` wrapping `fetch` against FastAPI, using the Track 0 types (G23). *Departure from the original wording ("reading from the JSON fixtures until Track A's endpoints exist"): that was stale — Track 0 shipped the routes, and `app/routers/` serves `sample_data.py` over real HTTP. The client calls the API; the fixtures are used only in tests.*
- [x] **[written]** Add `GET /metro` to the contract: a route returning `MetroSummary` for the single live metro, served from `app/sample_data.py` until A1b swaps in a query. Then `make types` and `make fixtures`. Prerequisite for the next item (G24)
- [x] **[fill-in]** Replace the hard-coded metro name in `layout.tsx` (footer and `description` metadata; both carry `TODO(G24)`) with the API's metro. Metadata goes through `generateMetadata`, and the footer uses a small async child inside `<Suspense>` rather than an `await` in the layout body — for streaming, not prerendering. *Departure from the original wording ("cache the fetch with `force-cache` and a long `revalidate`"): any `force-cache` fetch in the root layout prerenders every route at build time and makes every build depend on the API being reachable. B2 uses `no-store` and accepts that every route is dynamic (decision B2-D1; the caching question is recorded in `arch-initial.md` §11).*
- [x] **[fill-in]** Load data in a Server Component and render it. Specifically worth noticing: this is a `fetch` with no `useEffect`, no loading state, and no client-side data library — and understanding *why* that works is most of understanding RSC *(scaffolded; B2-K5, the fetch-and-`notFound()` flow, is open in `app/venue/[id]/page.tsx`)*
- [x] **[fill-in]** Filters as URL search params, not component state, per `arch-initial.md` Section 4. This is the decision with the most downstream consequences in the whole frontend: it's what makes a filtered calendar shareable, bookmarkable, and server-rendered from the URL alone

### B3. The calendar

The hard part, and deliberately not a solved problem you can install — `arch-initial.md` is explicit that this isn't a month/week/day grid, it's "closer to a feed."

Plan and reviews: `docs/dev/implementations/b3-the-calendar.md` (decisions B3-D1–B3-D8 settled by Ari October 12, 2026). **Built and committed as `973f04b` (October 14, 2026); signed off by Ari October 14, 2026.** The five `TODO(Ari)` gaps (B3-K1–B3-K5) were filled by Ari, code review round 1 (6 findings) is resolved — the last, #4, with a small follow-up after Ari's keyboard check — and Ari has checked it in a browser. `make check` is green (580 Python tests, 187 Vitest). Departures from the original wording below are marked *Departure*.

- [x] **[fill-in]** The layout: a vertically scrolling list of dates, each date a horizontally scrolling row of venue columns, each venue column holding that venue's shows that day. *Built (`app/_components/calendar-grid.tsx`, `lib/calendar.ts`); B3-K3 (the date loop) and B3-K5 (the scroller's classes) filled by Ari.* *Departure:* a row lists only the venues with a show that date, and every date in the served range gets a row, thin when empty (B3-D1, B3-D2); there is no cap of two shows per column (B3-D7); data came from the live sample API rather than static data, after four rows were added for the hard cases (B3-D5)
- [x] **[fill-in]** Responsive behavior across phone, tablet, and desktop, per the global requirement. Nested scroll regions are where this gets genuinely tricky on touch devices. *B3-K5 filled by Ari. Measured in headless Chrome at 375/500/768/1280px (no page-level sideways scroll; the 2026-10-07 row scrolls on its own), and checked in a browser by Ari. His keyboard check found the per-row tab stops and landmarks the plan had specified to be noise, so they were removed (code review #4): each venue column starts with a link, so Tab lands inside the row anyway. A scroll container must be the grid item itself or it widens the page — recorded in `notes.md`*
- [x] **[written]** The show block component. *Departure (B3-D3, B3-D6):* `apps/calendar/app/_components/show-block.tsx`, not `packages/ui` — both consumers are in `apps/calendar`, and a design-system package that imports `next/link` and the app's API types would be coupled to one app. Re-marked [written]: its one real rule (after-midnight display) is `lib/dates.ts` B3-K2
- [x] **[fill-in]** The filter header: venue and artist multi-selects with type-to-filter, and the future-only month dropdown populated from months that actually have shows. *Built (`app/_components/filter-header.tsx`, the shadcn combobox and select in `packages/ui`); B3-K4 (navigating from the Client Component) filled by Ari. The filter state lives entirely in the URL; the header holds no results*
- [x] **[written]** The empty state — "No matches found" with a reset link — which the requirements call out specifically (in `app/page.tsx`). *Re-marked [written] (B3-D6)*
- [x] **[fill-in]** Dates via Temporal (`@js-temporal/polyfill` is already installed). *Built in `lib/dates.ts`; B3-K1 (`metroToday`) and B3-K2 (`isAfterMidnight`) filled by Ari.* The metro's timezone matters for exactly one thing — which date is "today" — because a show's own date and time are wall-clock values with no zone; the plan's section "What 'dates in the metro's timezone' actually means here" has the detail
- [x] **[written]** `<Suspense>` streaming on `/` with a skeleton (B2-D4 deferred `loading.tsx` to B3): a boundary inside the home page rather than a root `loading.tsx`, so `notFound()` keeps returning 404 on the detail routes (B3-D4)
- [x] **[written]** *Added during B3 (Ari, October 14, 2026):* every API call is logged by `lib/api.ts` to the Next.js server's terminal, because the browser's Network tab cannot see server-to-server requests — a status line (`[api] GET /shows?venue_id=3 -> 200 in 41ms`) and a one-line summary of the response (counts, the gaps that usually mean extraction missed something, null fields; `lib/api-log.ts`). `LOG_API_BODIES=1` in `apps/calendar/.env.local` adds the full JSON on one line; it is ignored in production, so hosted logs get summaries only
- [x] **[written]** *Added during B3:* VS Code debug configs for the API, the Next.js server and the browser (`.vscode/launch.json`), and run/troubleshoot/debug sections in the root `README.md`
- [x] Sign-off — Ari, October 14, 2026

### B4. Detail pages

Plan and reviews: `docs/dev/implementations/b4-detail-pages.md` (decisions B4-D1–B4-D8 settled by Ari October 14, 2026; B4-D2 and B4-D4 took the alternative). **Built October 14, 2026; Ari filled the four gaps (B4-K1–B4-K4), the scaffold was cleaned out, and Ari signed off October 16, 2026.** Departures from the original wording are marked *Departure*.

- [x] **[fill-in]** Venue page: metadata plus the calendar filtered to that venue. *Built (`app/venue/[id]/page.tsx`): readable metadata, a Google Maps link, B3's `CalendarGrid` over the venue's shows, Earlier/Later paging through `?from=` (the server picks the window; `lib/calendar-window.ts`), and Event JSON-LD. B4-K2 (`windowLinks`) filled by Ari.*
- [x] **[written]** Artist page: metadata plus upcoming shows as a list. *Departure (B4-D2, B4-D5): re-marked [written] (no new line carries a key point), and "upcoming" is literal: a new `GET /shows?upcoming=true` (from the server's today, no upper limit; 422 with `start`/`end` and without a venue or artist) feeds an unpaged list. The API change is its own early commit (step 0), with one sample show added outside the default window so the parameter is observable.*
- [x] **[written]** `/venues` and `/artists` — flat alphabetical lists, deliberately simple per the requirements. *Departure (B4-D5): re-marked [written]; B2 had already built exactly this and B4 changed no code there.*
- [x] **[fill-in]** `/day/[date]` with its three sort modes (venue-alpha, venue-time, artist-alpha), also in URL params. *Built: `?sort=time|artist`, the default is the bare URL, switched with plain links (`lib/show-order.ts`). B4-K3 (`artistRows`) and B4-K4 (the two venue-mode comparators) filled by Ari.*
- [x] **[written]** `schema.org` Event JSON-LD on show and venue pages, per `arch-initial.md` Section 4's SEO reasoning. *Departure (B4-D3): `/show/[id]` did not exist, so B4 builds it (and `getShow()`, and the link to it from every show block's time line). Departure (B4-D8): one line of this item, `withOffset` in `lib/json-ld.ts`, is B4-K1 (filled by Ari): a wall-clock time becomes an instant only with the metro's zone.*
- [x] **[written]** *Added during B4:* posters and photos render as plain `<img>` through one `RemoteImage` component, the app's only `@next/next/no-img-element` exception (B4-D4); every URL scraped from a page goes through `httpUrlOrNull` (http(s) only); real page titles through `generateMetadata`, with `getVenue`/`getArtist`/`getShow` wrapped in `cache()` (B4-D7).
- [x] Sign-off — Ari, October 16, 2026

### B5. Frontend testing

Plan and review: `docs/dev/implementations/b5-frontend-testing.md` (decisions B5-D1–B5-D4 accepted as recommended by Ari, October 16, 2026). **Built October 16, 2026; Ari filled the three gaps (B5-K1–B5-K3, all in test code), the scaffold was cleaned out, and Ari signed off October 17, 2026.** Code review round 1 (7 findings) is resolved. Departures from the original wording are marked *Departure*.

- [x] **[written]** `vitest` + `@testing-library/react` set up in `apps/calendar`. *Departure:* five dev dependencies, not two (`jsdom@^29`, `@testing-library/{react,dom,user-event,jest-dom}`; `dom` is a peer of `react`, and `jsdom` stays on 29 because 30 needs Node `^22.22.2 || ^24.15.0 || >=26.0.0`, see `docs/dev/notes.md`), plus Oxc's automatic JSX runtime (the app's `"jsx": "preserve"` otherwise leaves a `.test.tsx` unparseable) and two Vitest projects where **the file extension picks the environment** (`*.test.ts` node, `*.test.tsx` jsdom).
- [x] **[fill-in]** Component tests for the pieces with real logic — the filter header, the empty state, the date grouping. *Built (`app/_components/*.test.tsx`); B5-K1 (the router mock), B5-K2 (driving the combobox and asserting the whole URL) and B5-K3 (asserting the empty state's absences) filled by Ari.* *Departures:* the empty state was inline in an async Server Component, so it is extracted as the synchronous `CalendarResults` (B5-D1, with a shared `hasActiveFilters`; the rendered page is byte-identical before and after, checked in headless Chromium); "date grouping" was already a unit-tested pure function (`groupCalendar`), so the tests cover what `CalendarGrid` does with rows and one integration through the fixture. *Added (B5-D2):* `ShowBlock` and three pins (`ErrorPage` never prints `error.message`, `RemoteImage` renders only http(s), `JsonLd` can't be closed early by `</script>`). *Added (B5-D3):* the filter chips' remove buttons had no accessible name (found while planning), now `Remove <venue>`
- [x] **Deferred to B6:** Playwright end-to-end tests. Moved to B6 on October 17, 2026, when the UI reached the stopping point this line named
- [x] Sign-off — Ari, October 17, 2026

### B6. Accessibility and end-to-end tests

Scope agreed with Ari on October 17, 2026. Two things come out of it: the accessibility requirement (WCAG 2.2 AA, `requirements-initial.md` Global Requirements; `arch-initial.md` Section 4), and the Playwright suite that B5 deferred, which also runs the automated accessibility checks. Built in its own thread. Its implementation plan, `docs/dev/implementations/b6-accessibility-and-e2e.md`, is written first under the usual cycle (`AGENTS.md`, "Implementation plans"). **Done — signed off by Ari October 22, 2026.** Built October 19–20, 2026 (decisions B6-D1–B6-D11 settled by Ari October 19; the plan file has the findings, the measurements and the departures). The three `TODO(Ari)` gaps (B6-K1–B6-K3) were filled by Ari. Departures from the original wording are marked *Departure*.

- [x] **[written]** WCAG 2.2 AA recorded as the accessibility requirement. *Done October 17, 2026.*
- [x] **[written]** Scope and implementation strategy (below) approved by Ari, October 17, 2026.
- [x] **[written]** Playwright and `@axe-core/playwright` added to `apps/calendar` (Step 1). *Dependencies approved October 17, 2026; installed in the plan's Steps 1 and 3 (`@playwright/test` 1.64.1, `@axe-core/playwright` 4.14.0). Departure: a real FastAPI app on the sample data is the stack (B6-D1), neither of the two options the strategy listed.*
- [x] **[written]** The harness, 11 journeys, the axe scan of every screen and of the open popups against a ratchet baseline, and the reflow, keyboard and painted-focus checks (the plan's Steps 1–7). *Departures: dark mode is not scanned because the app has none (B6-D7); "report-only" became a ratchet baseline that fails on anything new from the first commit (B6-D5); the scan covers every screen at two widths, not one page.*
- [x] **[fill-in]** B6-K1: the clock pin, `Date.now = () => FROZEN` in `e2e/support/fake-now.mjs` *(filled by Ari October 20, 2026; the scaffold then taken out by a Claude pass, verified comment-only)*
- [x] **[fill-in]** B6-K2: the focus-not-obscured predicate in `e2e/support/focus.ts` *(filled by Ari October 20, 2026; the scaffold then taken out by a Claude pass, verified comment-only)*
- [x] **[fill-in]** B6-K3: the page-reflow predicate in `e2e/support/reflow.ts` *(filled by Ari October 20, 2026; the scaffold then taken out by a Claude pass, verified comment-only)*
- [x] **[written]** Findings marked by Ari and the fix round done (the plan's Step 8, October 20, 2026): B6-F1 (lineup link target size), B6-F3 (focus ring contrast) and B6-F7 (a half-visible focused link in a venue row; `ScrollRow`) fixed, each in its own commit; B6-F2 (Base UI popup hides the page) accepted as upstream behaviour; B6-F4 not reproduced; B6-F6 a nit, kept; B6-F5 fixed in round 1 (B6-D8).
- [x] Second-model code review of the Step 8 changes (code review round 2, nine findings, all fixed; Ari marked B6-F8 a nit), then sign-off — Ari, October 22, 2026. *(Ari did his manual checks October 20, 2026, and ran `make e2e` on his laptop; the CI `e2e` job passed on its first run.)*

**Implementation strategy.** One test first, green, then the rest. Each step ends with its own green result before the next starts.

1. **One end-to-end test, green first.** A single Chromium project at the desktop viewport. One test: the home page loads and shows at least one show. The test config starts the stack. Done when it passes three runs in a row locally and in CI. Nothing else is added until it does. Two notes for the plan: browser-side mocking (`page.route`) can't stand in for the API, because Server Components fetch from the Next.js server, not the browser; and how the stack is started (real API with a seeded database, or a stub serving `lib/fixtures`) is the largest decision in this step.
2. **Add the accessibility scan to that test.** Run `@axe-core/playwright` on the same page with tags `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, `wcag22aa`. Report-only at first. Record the baseline, and measure the two colour values that were hand-calculated and not rendered: the focus ring on white, and muted text on muted backgrounds. Once the baseline is clean, the build fails on a new violation (decided October 17). Fixes go in their own commits.
3. **Add the remaining journeys, one test each, green before the next.** These are the B5 Playwright backlog plus the rest of the user flows:

   | # | Journey | Why it needs a browser |
   |---|---|---|
   | 2 | Filter by venue through the combobox; the URL updates | Real router, `aria-busy`, the optimistic chip (B5 backlog) |
   | 3 | A filter with no matches shows the empty state; the reset link restores the calendar | The empty branch, which B5 found unreachable from sample data |
   | 4 | The day view switches sort modes | `/day/[date]`, links-driven sorting |
   | 5 | Venue, artist and show pages are reached through links | Routes and `notFound()` across navigations |
   | 6 | An unknown URL shows the 404 page | `not-found.tsx` through a real request |
   | 7 | The Suspense skeleton is replaced by content | Streaming, which jsdom can't show (B5 backlog) |

4. **Layout and modes.** Reflow at 320px and 375px: no page-level horizontal scroll. Axe in dark mode. A keyboard-only journey through the filter header and a show block.
5. **Run, review, resolve.** Run the full suite, axe scan included, at the end of each step, and review the results with Ari. Every finding Ari marks should-fix or must-fix is fixed in B6 before the step closes, in its own commit, with a test that fails before the fix and passes after. Findings Ari marks nit, or leaves unmarked, are logged in the B6 implementation log and don't block the step.
6. **Manual passes.** A keyboard and screen-reader pass (VoiceOver or NVDA), recorded in the B6 implementation log, done by Ari. The automated suite doesn't replace it.

**Not in B6:** visual snapshots (until the UI settles), a browser matrix beyond Chromium, and API or agent tests (those stay in pytest). The CI job is a separate `e2e` job in `ci.yml` (B6-D4), and `make e2e` is part of `make check`.

**Standing rule: the test clock.** *(Rewritten October 19, 2026: the original paragraph said the home window rolls with the clock and the page would thin out after October 25. That was wrong for the code as written.)* Only one thing in the app reads the real clock: the Next server's `metroToday` (`lib/dates.ts`), which decides which row says "Today". The API's window does not follow the clock: `shows.py` starts it at `data.START`, a pinned constant in `apps/api/app/sample_data.py` (September 28 – October 25, 2026), whatever the date is. The suite pins the Next server's `Date.now` to one instant, `E2E_NOW` in `apps/calendar/e2e/support/clock.ts`, with a preload (`fake-now.mjs`; Playwright's `page.clock` fakes only the browser's clock and cannot reach a Server Component). `e2e/support/clock.test.ts` fails in `pnpm test` if the pin falls outside the window the fixtures echo, or on a day with no show, so "whenever `START` moves, the pin moves in the same change" is a red test and not a memo. *(Superseded in part by C2, October 27, 2026: the API's window now follows the metro's real clock, and the end-to-end job pins two clocks, not one; see `docs/dev/notes.md`, "Two clocks in the end-to-end job".)*

**Known date cliff (not yet real).** Against the sample API there is none: the window stays September 28 – October 25 on any date, and only the Today row changes (it disappears once today leaves the window). The real cliff arrives with A1b: once the routers read Postgres, the API reads the metro's real clock, the sample data must be re-based or reloaded, and the pin must reach the API too (B6 plan, "Follow-ups").

---

## 7. Write-ups

Three short documents, written as the corresponding work lands rather than at the end. These are the "solid overview" goal made concrete — if they can't be written clearly, the thing they describe probably isn't clear yet either.

- [ ] **Agent orchestration** (after A6) — why a graph rather than a script, what the state object is actually for, where the conditional edge earns its complexity, and the honest counterfactual: which parts of this would be simpler as a plain function with a `for` loop, and what LangGraph is genuinely buying in exchange
- [ ] **Validating agentic output** (after A8, which is now C7 in `alpha-deployment-plan.md`) — the layered picture this phase builds: schema constraints via `instructor`, deterministic rule checks, model self-reported confidence, bounded retry with escalation, and human escalation as the floor. Which layer catches which kind of failure, and what each one misses
- [ ] **Auditability** (after A4) — what "auditable by construction" means in practice, why append-only matters, why reconcile and commit are separate nodes, and a worked example tracing one show from fetch to row

---

## 8. Still deferred after this phase

Unchanged from `arch-initial.md` Section 11 unless noted:

- Everything hosted — Railway agent worker, DeepInfra, R2, Neon–Vercel integration, branch protection, the dev and staging environments and the production domain: **planned in `alpha-deployment-plan.md`** as milestones C1–C11, replacing its earlier H1 (now C6)–H4 (Resend and Turnstile stay deferred beyond it)
- Public edit and flag endpoints, and with them the `contributor`, `flag`, and `venue_submission` tables
- The genre / instrument / member vocabulary tables and their join tables — no UI edits them yet
- Playwright fetching, and with it whichever venue needs click-driven pagination. `venue.fetch_strategy` exists as a column from A1 with only the `http` path implemented. *A2.1 found (October 10) that Zhora's listings, and its schema.org data, are drawn client-side by the DICE widget, so a plain fetch gets none of them; and that Midway answers the plain fetch with a Cloudflare bot challenge, which this project will not try to get past (a sanctioned route — asking the venue, or a public feed — is the way back)*
- **Extraction throughput** (Ari's concern, October 10, 2026; **measured in `alpha-deployment-plan.md` C6**). On the development laptop one venue page takes 1.5–5
  minutes (A2.1's rebaseline: 45 extractions in 1 h 35 min), so a metro of a few hundred venues would take hours
  run sequentially. Not an alpha blocker — production inference is DeepInfra (`arch-initial.md` §5/§7), a hosted GPU
  running the same model that can also take requests in parallel — but worth measuring before the scheduled run is
  built. Levers already identified: structured sources (JSON-LD, iCal, platform data) replace a full-page
  extraction with one short splitter call; skipping extraction when a page's content hasn't changed since the last
  run (most calendars change little day to day); turning the model's "thinking" off (A2-S7 — much of each call is
  reasoning, effect on accuracy unmeasured); and shorter output (fewer fields per show)
- **A hosted larger model for A2.1's act splitter** (its A2.1-E1): **now `alpha-deployment-plan.md` C6.** The remaining act-naming errors at 56 of 60 look like the small local model's limit, and a larger model doesn't fit the development laptop
- **Venues that list shows in images, and date-then-lines layouts like Terminal Bar's** (A2.1-E6–A2.1-E7): Ari's call — look for more such venues before investing. The image approach is outlined in `arch-initial.md` §11, "Image-based show listings"
- Deeper and platform-specific sources found in A2.1: following First Avenue's detail pages for show times (one reader would cover 7th St Entry, First Ave, Turf Club, Fine Line and the Palace); Mortimer's Wix event data (it carries the times its text lacks); an iCal reader for public calendar feeds (the Uptown Art House's Google Calendar feed is captured as a fixture)
- The image-embedded-show case (Terminal Bar). Phase 5 proved the model can read it from a local image file, and A2.1's image route reads saved posters correctly. Finding, fetching and merging posters from a live page is the missing work, now outlined as a deferred extraction route in `arch-initial.md` §11, "Image-based show listings"
- The MCP admin server. `arch-initial.md` positions it as the operational interface that removes the need for an admin frontend — genuinely useful, but it's an interface onto a pipeline that should be finished first
- `apps/admin`'s purpose (G22). It has no v1 job. Leaving an untouched template in the repo is a small cost; deciding what it's for prematurely is a larger one
- Chat search, vector storage, multi-metro, revert as a user-facing action, donations

---

## 9. Suggested starting point

Track 0 first — it's short and it unblocks both tracks. Then A1, because everything in Track A needs the models, and because B2's API client is more satisfying to write against a contract that's already real on both ends.

After that the tracks are genuinely independent. A reasonable rhythm is one Track A milestone, then one Track B milestone, alternating — A1 → B1 → A2/A3 → B2 → A4 → B3, and so on. The one real ordering constraint inside Track A is that **A4 comes before A5 and A6**: building the audit trail before the logic it audits means you debug reconcile and commit by querying the database instead of by reading `print()` output.
