# Alpha Deployment Plan — from a working local app to a hosted alpha

**Status:** Draft — sequence and milestones (C1–C11) agreed in outline with Ari on October 21, 2026. Decisions marked **[Ari]** in §3.2 are still open. No milestone has an implementation plan yet.

**Date:** Revised October 21, 2026 (first drafted October 12, 2026).

**Purpose:** The plan for the phase after `alpha-build-plan.md`. That plan builds a working app on the local machine and deliberately leaves everything hosted alone. This one moves it onto hosted services in three environments (hosted dev, staging, production) under one domain with a subdomain per metro, and **validates the extraction on hosted inference**: the accuracy work the development laptop can't finish. It also takes over two items from the build plan that only make sense next to the hosted work: A1b (the API reading from the database) and A8 (evaluating the pipeline).

Read `alpha-build-plan.md` first (what the alpha is and what it deliberately left out), and `env-setup.md` phases 7–9 (which hosted services were deployed and which skipped, with reasons; §1 below says what has drifted since). The specification is the same: `docs/arch/arch-initial.md`, `data-model-initial.md` and `requirements-initial.md`.

**Starts when:** now. A7 is done (October 21, 2026), and B6 is the only item left in the build plan; B6 merges first, because C2 waits on it. C1 and the cloud-side planning of C2–C6 can start immediately. The alpha's definition of done (`alpha-build-plan.md` §2) is closed by C2's own verification step, not by a separate gate.

**Designations in this file.** Plan-level decisions are written `Dep-D<n>` (scope `Dep`, `docs/dev/conventions.md`), because this file sits outside `docs/dev/implementations/` and `make designation-check` flags bare IDs here. Each milestone gets its own plan file and its own scope (`C2-D1`, …) when it is planned.

---

## 1. Where things stand

### 1.1 Re-validated October 20–21, 2026

Checked from a cloud session: Vercel through its connector (read-only), the repo by reading it. Railway, Neon, Atlas and GitHub settings can't be reached from there (§1.2).

| Item | Finding | Status |
|---|---|---|
| Vercel production | Project `agentic-live-music-calendar-calendar` exists (Next.js, Node 24.x). Every recent merge to `main` deployed to production and reached `READY`; the latest checked was the A6 merge (October 20). | Verified |
| Vercel previews | The 5 preview deployments on record all ended `ERROR`, the newest around October 15 (branch `a4-auditability`). The one build log read fails at `/artists`: the page is prerendered at build and its API call throws `API_BASE_URL is not set`. So the Preview environment lacks that variable, and the build depends on a reachable API despite B2's intent (`b2-routes-and-data-loading.md`, B2-D1). The other four were not read. No preview deployment exists since, despite PRs through #26; the reason is unknown. | Verified (one log); cause of the gap unknown |
| Vercel plan limits | The API reports a limit of **0 custom environments**, so only Production, Preview and Development exist. Dev and staging have to be branch-scoped Preview configurations (§4). | Verified |
| Vercel protection | `ssoProtection: all_except_custom_domains`: the `*.vercel.app` URLs need a Vercel login, **a custom domain does not**. Attaching a domain to a project makes that host public. | Verified |
| Vercel variables | The connector couldn't list them (HTTP 403). Production builds pass, so `API_BASE_URL` is set for Production. | Unverified |
| Repo visibility | A commit message on a branch says the repo is **public** now, with CodeQL, Dependabot and a PR template added. The "branch protection needs Pro or a public repo" blocker in `env-setup.md` Phase 8 no longer applies. Whether protection is switched on is not known. | Unverified |
| Config as code | The repo has no `Dockerfile`, `railway.*` or `vercel.json`; all Railway and Vercel configuration lives in the dashboards. | Verified |
| API data source | Every router in `apps/api/app/routers/` still imports `app.sample_data`. A1b is open, so the hosted calendar cannot show anything a worker wrote. | Verified |
| Sample window | The sample data's last show falls on October 25 (`alpha-build-plan.md` §6, "Known date cliff"), so the hosted calendar thins out from October 26. | Verified (from the plan) |
| Schema on Neon | Three Alembic migrations exist. `env-setup.md` left Neon with the first (metro and venue) only, the Railway start command runs no migration, and `/health/db` only runs `SELECT 1`, so drift would not show. | Unverified |
| Model endpoint | `agent_worker/llm.py` hard-codes `localhost:11434` (C6). | Verified |
| Worker and Mongo | `Settings` documents that the worker's entry point refuses to start without `MONGODB_URI`, so a hosted worker needs Atlas before its first run. | Verified |
| Metro slug | Neither the models, `schemas.py` nor the data model has a slug on `metro`. | Verified |

### 1.2 Not checkable from the cloud (C1)

Railway service state and variables; Neon's actual schema and branches; whether the Atlas M0 cluster is still running (I recall that free clusters pause after a period of inactivity, and this one has had no connections since it was provisioned; unconfirmed); the Vercel variable values; GitHub's branch-protection settings; and the DeepInfra and Cloudflare accounts, which were never created (`env-setup.md` Phase 7).

### 1.3 Known extraction debt

A2 and A2.1 were signed off by Ari on October 12, 2026 with this open: the extraction pipeline scores **56 of 60** shows correct on the gated venues (White Squirrel ×2, 7th St Entry, Mortimer's). The standard is 100% for dates and acts (`requirements-initial.md`, "Agent Extraction: Accuracy Standards"). The run was deterministic and clean on the "never" tiers: no invented shows, no wrong field values. The four misses are act-naming slips on ambiguous titles, and they look like the limit of the small local model (`gemma4-e4b`, about 4B parameters). A larger model doesn't fit the development laptop. Evidence and the full list of deferred ideas are in `implementations/a2.1-extraction-reliability.md`: "Experiment results" (`a21-confirm`, `a21-review2`) and "Deferred explorations" (A2.1-E1–A2.1-E17).

**Skipped on purpose earlier, picked up here** (`env-setup.md` phases 7–8, `arch-initial.md` §11): DeepInfra, the Railway agent worker service, Cloudflare R2 page snapshots, Atlas as the raw-staging store (the write itself exists since A4), the Neon–Vercel preview-branch integration, the FastAPI↔Next.js shared secret, and branch protection on `main`.

---

## 2. Definition of done (draft)

1. **Three environments** (hosted dev, staging, production) exist in every layer (Vercel, Railway, Neon, Atlas, R2, DeepInfra keys), each deployed from its own branch with its own database, secrets and keys. Their configuration is in the repo, not only in dashboards (C3).
2. **The API serves the database**, not sample data, and the Vercel calendar renders what a worker run wrote, in every environment (C2, C8).
3. The agent worker runs on Railway on its daily schedule in production (on demand in dev and staging) against the live venue URLs, using DeepInfra, and writes to Neon (C8).
4. The extraction meets Ari's accuracy standard **on every run**, on the gated pages and on a fresh held-out capture (C6).
5. Every row is traceable through the audit trail, as in `alpha-build-plan.md` §2 point 3, but in the hosted database, with the raw page snapshot kept (C9).
6. Production answers at `msp.<domain>`; each metro is its own subdomain, resolved from the host; dev and staging answer at `msp.dev.<domain>` and `msp.staging.<domain>`, gated and not indexed (C4, C11).
7. The cost and duration of a daily run are measured and recorded against `arch-initial.md` §10's estimate (C11).

---

## 3. Decisions

### 3.1 Made

| ID | Decision | Reason and source |
|---|---|---|
| Dep-D1 | Three environments in every layer: **hosted dev**, **staging** (QA) and **production**. | Ari, October 21, 2026. Reverses `arch-initial.md` §9's "favor ephemeral PR environments over a persistent staging environment"; C3 records the change and its cost in §9 and §10. |
| Dep-D2 | One domain for all environments. A host is `<metro>.<environment zone>`: production `msp.<domain>`, staging `msp.staging.<domain>`, dev `msp.dev.<domain>`. | Ari, October 21, 2026 (same domain strongly preferred). The environment is the parent zone because a wildcard certificate covers exactly one DNS label: `*.<domain>`, `*.staging.<domain>` and `*.dev.<domain>` are three wildcards in total however many metros there are, where `staging.msp.<domain>` would need one per metro. |
| Dep-D3 | Metro slugs are short codes: three-letter IATA-style city codes where one exists (`msp`, `chi`, `nyc`, `tyo`). A longer alias (`chicago` for `chi`) may be added later and is optional. Reserved slugs (`www`, `api`, `admin`, `dev`, `staging`, …) can't be metros. | Ari, October 21, 2026. The reserved list is the one place the convention can collide with a real code, so a new slug is checked against it. |
| Dep-D4 | Non-production environments are gated by an app-level password in `proxy.ts`, keyed on `APP_ENV`, and send `noindex`. | Ari accepted the recommendation, October 21, 2026. Custom domains sit outside Vercel's protection scope (§1.1), and an app-level gate works on any plan. |
| Dep-D5 | **A1b and A8 move here.** A1b becomes C2. A8 is split: C5 (labels, harness, local baseline) and C7 (tuning and calibration on the shipped model). | Ari, October 21, 2026. A1b is a prerequisite of the hosted calendar showing real data; A8's tuning questions can only be answered on the model that ships (§5). |
| Dep-D6 | Milestones are numbered C1–C11 and replace H1–H4 (mapping in §7). | Ari, October 21, 2026. The order is dependency-driven (§5), not the order the old names implied. |

### 3.2 Open — **[Ari]** decides

Each row has a default; unless Ari changes it, the milestone plans start from the default.

| ID | **[Ari]** Question | Default and reason |
|---|---|---|
| Dep-D7 | **DNS host for the domain.** Ari's answer was "if there is a need later I'd rather do it now", read here as: after registering at Namecheap, point the nameservers at Vercel straight away (registration stays at Namecheap; a new domain has no records to move). | Do it now. Explicit per-host records work with either DNS host, so nothing breaks if wildcard domains turn out to need another plan; whether Hobby allows wildcard domains, and whether they need Vercel's nameservers, is **unverified** and is checked when the first host is added (C4). **Confirm this reading.** |
| Dep-D8 | **Branch mapping.** (A) `main` deploys to staging, a `production` branch (fast-forwarded by Ari after QA) deploys to production, and a `dev` branch is a lane pointed at whichever milestone branch needs a hosted trial. (B) `main` stays production; dev and staging follow long-lived branches. | (A). It keeps the PR-then-sign-off workflow (`AGENTS.md`) and makes production a deliberate promotion. Vercel's Production Branch setting and Railway's per-environment branch support this. |
| Dep-D9 | **Cost and cron.** Persistent dev and staging on Railway. Only production gets a schedule; the dev and staging workers run on demand. | Accept, with a monthly ceiling set by Ari. By estimate from `arch-initial.md` §9 and §10 (not measured), the always-on API cost roughly triples, and cron workers cost only while running. On-demand workers also stop three environments from fetching the same venue sites daily. |
| Dep-D10 | **Isolation.** One account per provider; Neon branches, Atlas databases (`MONGODB_DATABASE`), R2 buckets and DeepInfra keys per environment, with separate database users. | Accept. Cheaper to run than separate projects; the risk is one pasted connection string reaching production, which `APP_ENV` (C3) makes visible. |
| Dep-D11 | **Audience and go-live.** Attaching `msp.<domain>` to production is the moment the site becomes public. | Make it the last step (C11), after the shared secret (C10) and branch protection. Check Vercel's current Hobby terms before then; I believe the plan is for non-commercial use, and donations are on the deferred list. |
| Dep-D12 | **The October 26 sample cliff.** The sample data runs dry before C2 and a seeded Neon can replace it. | Accept it. Don't edit `sample_data.py` before B6 merges: the B6 test clock is pinned to it (`alpha-build-plan.md` §6, "Standing rule: the test clock"). |
| Dep-D13 | **When production's cron turns on.** | Only after the C6 gate passes, or after Ari explicitly accepts 56 of 60 for production. Definition of done point 4 says "on every run", so enabling it earlier is a conscious departure. |
| Dep-D14 | **Neon–Vercel preview-branch integration.** | Skip for now: it creates a Neon branch per preview, which fights long-lived dev and staging branches. Revisit for ephemeral PR previews (`arch-initial.md` §9, Phase 2). |
| Dep-D15 | **Task markings.** Items carried over from the build plan keep their marking. New items get `[fill-in]` or `[written]` in each milestone's plan, with the `TODO(Ari)` gaps named there (`AGENTS.md`). | Accept. Re-marking is Ari's call. |

---

## 4. Environments and hostnames

The design every milestone refers to.

### 4.1 Topology

| Layer | dev (hosted integration) | staging (QA) | production |
|---|---|---|---|
| Vercel | Preview; variables scoped to the `dev` branch | Preview; variables scoped to `main` | Production; Production Branch `production` |
| Railway API | `dev` environment | `staging` environment | `production` environment |
| Railway worker | `dev`, on demand | `staging`, on demand | `production`, scheduled daily |
| Neon | branch `dev` | branch `staging` | default branch |
| MongoDB Atlas | database `calendar_dev` | `calendar_staging` | `calendar` |
| Cloudflare R2 | bucket `…-dev` | bucket `…-staging` | bucket `…-prod` |
| DeepInfra | own API key | own key, same model as production | own key |
| FastAPI↔Next.js secret | own value | own value | own value |

Branch names assume Dep-D8 (A); Vercel Hobby has no custom environments (§1.1), which is why dev and staging are branch-scoped Preview configurations. The API needs no custom domain: the browser never talks to it (`arch-initial.md` §5), so Railway's default URLs serve.

### 4.2 Hostnames

| Environment | Host | Wildcard that would cover it |
|---|---|---|
| production | `msp.<domain>` | `*.<domain>` |
| staging | `msp.staging.<domain>` | `*.staging.<domain>` |
| dev | `msp.dev.<domain>` | `*.dev.<domain>` |
| production apex | `<domain>` | a metro chooser, in the Craigslist style; with one live metro it redirects to `msp.` |

The Next.js app resolves the metro from the request host: strip the environment's own zone (configured per environment), and the remainder is the slug; an unknown slug redirects to the chooser. The hook is `proxy.ts` (`docs/references/nextjs-style-guide.md`: `middleware.ts` is `proxy.ts` in Next.js 16). Cookies are host-only, never set on the parent domain, so the environments can't read each other's.

---

## 5. The sequence

### 5.1 Milestones, in order of dependency

Every milestone follows the usual cycle (`AGENTS.md`): plan, plan review by a different model, Ari's approval, build, code review, Ari's sign-off. Plan and review rounds are cloud work; where a plan depends on measurements only the local model can produce (C5, C6, C7), it is planned locally or marks those facts as unverified (`AGENTS.md`, "Cloud sessions").

| # | Milestone | Where it runs | Waits on | Gate |
|---|---|---|---|---|
| C1 | Preflight: re-validate, register, accounts | Ari, dashboards | nothing | Facts recorded; Dep-D7–Dep-D14 answered |
| C2 | The API reads from the database (was A1b) | cloud, `[written]` | B6 merged; Neon migrated and seeded | Alpha definition of done met |
| C3 | Environments and deploy-as-code | cloud, plus dashboard steps | C1 | Previews build; three environments deploy from their branches |
| C4 | Metro hosts and the domain | cloud, plus Namecheap and Vercel | C2, C3 | `msp.dev.<domain>` and `msp.staging.<domain>` serve behind the gate |
| C5 | Pipeline evaluation harness (was A8, first half) | local, `[fill-in]` | nothing | Local baseline recorded |
| C6 | Hosted inference and the accuracy gate (was H1) | local, against DeepInfra | DeepInfra key; part 2 waits on C5 | A2.1-D1 gate passes on gated and held-out pages |
| C7 | Pipeline evaluation on the shipped model (was A8, second half) | local, against DeepInfra | C5, C6 | Thresholds changed or confirmed with data |
| C8 | The agent worker on Railway (was H2, with H3's Mongo half) | cloud, plus dashboard steps | C3, C6 part 1 | Worker runs hosted in dev and staging; production cron stays off |
| C9 | Audit storage: R2 snapshots (was H3's R2 half) | cloud, plus Cloudflare account | C8 | `audit_log.snapshot_key` filled |
| C10 | Wiring and guard rails (was H4) | cloud | C3 | The API refuses calls without the shared secret |
| C11 | Go-live and burn-in | Ari | C4, C6, C8, C9, C10 | Production on its domain; cost and duration recorded |

**Critical path:** C1 → C3 → C8 → C9 → C11. C2 runs beside C3 (both wait on little). C5, C6 and C7 run beside the path and gate its end (Dep-D13). C4 needs C2 because the slug lives in the database the API now serves.

**Lanes.** Cloud: C2, C3, C4, C8, C9, C10 and every plan and review round. Local (Ari, laptop and Ollama): C5, C6, C7. Dashboards and accounts (Ari): C1, the manual parts of C3, C4, C9 and C11.

### 5.2 Ordering traps

| Trap | Why it matters | How the order avoids it |
|---|---|---|
| Merging C2 before Neon is migrated | Railway deploys on push, so the production API would query tables that may not exist; every route would answer 500, and `/health/db` would not warn. | C2's gate: Neon migrated and seeded first |
| Starting C8 before Atlas is ready | The worker refuses to start without `MONGODB_URI` | C3 provisions per-environment Atlas databases; C8 connects them |
| Labelling twice | C5's labels and C6's held-out set are the same job | Label once; the held-out pages are captured before C6 scores anything |
| C2 and B6 both touching the sample data | B6's test clock is pinned to `sample_data.py`; C2 may delete it | C2 waits for B6 to merge |
| Three scheduled workers | Three daily hits on each venue site, plus inference spend three times over | Only production is scheduled (Dep-D9) |
| Attaching the production domain early | Custom domains sit outside Vercel's protection scope, so the site goes public | It is C11's last step (Dep-D11) |
| The Atlas M0 cluster paused | A worker's first hosted run would fail on connect | Checked in C1, again in C3 |

---

## 6. Milestones

Each gets an implementation plan under `docs/dev/implementations/` (`c2-…md`, and so on) before it is built. C1 is a checklist with its result in `docs/dev/env-revalidation.md`.

### C1. Preflight: re-validate, register, accounts

**Why:** §1.2 lists what only Ari can check, and the open decisions need answers before C3 and C4 can be planned.

- [ ] **Re-validate the hosted state** and record each result in `docs/dev/env-revalidation.md`, secrets redacted: Railway (`railway status`, `railway variable list --kv`, `/health`, `/health/db`, and the plan's limits on environments); Neon (`alembic current` against it, the existing branches); Atlas (is the cluster running, which database users exist); Vercel (`vercel env ls`, the Production and Preview variables); GitHub (repo visibility, branch-protection settings).
- [ ] **Register the domain** (Namecheap, Ari's usual registrar) and, per Dep-D7, point its nameservers at Vercel. Not blocking: dev and staging can use `*.vercel.app` until it exists.
- [ ] **Open accounts:** DeepInfra now (C6 needs it); Cloudflare (R2) can wait until C9.
- [ ] **Branch protection on `main`** (pulled forward from the old H4), now that the repo is public: require the Python, JS, contract and designations checks; add B6's end-to-end check when it lands.
- [ ] **Answer Dep-D7 to Dep-D14**, or confirm the defaults.

**Done when:** `env-revalidation.md` records every §1.2 item as verified or as a finding; the open decisions are answered.

### C2. The API reads from the database (was A1b)

*Migrated from `alpha-build-plan.md` A1b, October 21, 2026.* Split out of A1 deliberately: A1 is the data layer, and swapping the routers is its own change with its own test migration. The routes still serve `app/sample_data.py` until this lands.

**Waits on:** B6 merged (the test clock and the sample data), and a migrated, seeded Neon before the merge (§5.2).

- [ ] **[written]** Replace the bodies in `app/routers/` with queries, keeping every signature, response model and error code (`api-contract.md` §2). Resolve inherited show fields (age restriction, alcohol, setting, seating) server-side from the venue, per `api-contract.md` §5. Add ORM `relationship()`s here, with the first consumer, choosing cascade settings then
- [ ] **[written]** Make the routes `async def` against a session dependency (`Annotated[AsyncSession, Depends(get_db)]` — `get_db` doesn't exist yet; it's added here, with its first consumer), and migrate `test_routers.py` from `TestClient` to `httpx.AsyncClient` + `ASGITransport` with `dependency_overrides` (the live `StarletteDeprecationWarning` is the nudge). Delete `app/sample_data.py` once nothing reads it — but note `scripts/generate_fixtures.py` builds the frontend fixtures from it, so decide first whether the fixtures keep a sample-data source of their own
- [ ] **[written]** *(added)* Before the merge: run `alembic upgrade head` and the seed against Neon production, then check every route against it. Merging first would put the production API on tables that may not exist (§5.2).
- [ ] *(added)* Verify locally, as `alpha-build-plan.md` §2 points 2 and 4 require: run the worker twice against local Postgres, and check that the calendar renders the rows (insert, update and soft-delete across the two runs).

**Done when:** the routers query the database; `make check` is green; Neon is migrated and seeded; the local verification passes. That closes the alpha's definition of done.

### C3. Environments and deploy-as-code

**Why:** Dep-D1 asks for three environments in every layer, and today none of the hosted configuration is in the repo (§1.1). This milestone builds §4.1, and is where the previews get fixed.

- [ ] Record the environment decisions in `arch-initial.md` §9 and §10 (Dep-D1, the cost note under Dep-D9) and fix the stale `env-setup.md` notes (branch protection, the repo's visibility).
- [ ] **Neon:** branches `dev` and `staging` off the production branch, and a rule for how staging's data is refreshed.
- [ ] **Railway:** `dev`, `staging` and `production` environments, each with its own API service and variables (`DATABASE_URL` without the `sslmode` and `channel_binding` parameters, `notes.md`).
- [ ] **Atlas:** per-environment databases and database users (`MONGODB_DATABASE` already exists in `Settings`); confirm the cluster is running.
- [ ] **Vercel:** Production Branch and branch-scoped Preview variables for dev and staging (`API_BASE_URL`, `APP_ENV`), per Dep-D8.
- [ ] **Configuration in the repo:** a `railway.toml` per service (the worker's Dockerfile arrives in C8), a `vercel.json` only if something needs it.
- [ ] **Migrations on deploy:** the API's pre-deploy step runs `alembic upgrade head`, with expand-contract changes because the API and worker don't redeploy together (`arch-initial.md` §5).
- [ ] **`APP_ENV`** (`dev`, `staging`, `prod`) in `Settings`, shown by `/health`, written on `agent_run`, and checked against the database host so a wrong connection string is visible.
- [ ] **Fix the preview build:** set `API_BASE_URL` for the Preview environment and remove `/artists`' build-time API call (§1.1), checking the other prerendered routes. Then confirm a PR preview deploys.
- [ ] **Secrets inventory:** a table of every variable per environment, no values.
- [ ] Decide the Neon–Vercel integration (Dep-D14).
- [ ] *(optional)* **First real hosted data:** run the worker from the laptop into the dev Neon branch and dev Atlas database, so the hosted dev calendar shows real shows before DeepInfra or the Railway worker exist. Needs C2.

**Done when:** a PR preview builds; dev and staging deploy from their branches; each environment has its own database and secrets; `APP_ENV` is visible; the configuration is in the repo.

### C4. Metro hosts and the domain

**Why:** Each metro is its own subdomain (Dep-D2, Dep-D3). This pulls the minimum of multi-metro forward (a slug, and resolving the metro from the host) and nothing more: scoping every query by metro stays deferred (`arch-initial.md` §11).

**Waits on:** C2 (the slug lives in the database the API now serves) and C3 (the dev and staging environments).

- [ ] **Tests first:** host parsing (`msp.dev.<domain>` and `msp.<domain>` resolve; an unknown or reserved slug doesn't; the environment's own zone is configurable).
- [ ] **`metro.slug`:** a column, its migration and the seed (`msp`), in its own early PR, because the contract regenerates `lib/api-types.ts` and the fixtures (`AGENTS.md`, "Parallel tracks"). `GET /metro` carries the slug.
- [ ] **Host to metro:** one small module plus `proxy.ts`, with the reserved-slug list. `metadataBase`, canonical URLs and the JSON-LD URLs come from the host.
- [ ] **The apex chooser**, which redirects to `msp.` while one metro is live.
- [ ] **The non-production gate and `noindex`**, keyed on `APP_ENV` (Dep-D4).
- [ ] **DNS and hosts:** add `msp.staging.<domain>` and `msp.dev.<domain>` to the Vercel project, bound to their branches, with the DNS records. Confirm what the plan allows (wildcards, branch-bound domains; Dep-D7). **Do not attach `msp.<domain>` to Production yet** (C11).

**Done when:** the dev and staging hosts serve their environments behind the gate, send `noindex`, and resolve `msp`; an unknown slug lands on the chooser.

### C5. Pipeline evaluation harness (was A8, first half)

*Migrated from `alpha-build-plan.md` A8, October 21, 2026.* Phase 5 evaluated whether a *model* could extract. This evaluates whether the *pipeline* produces correct calendar data. The harness is model-independent, so it is built now on the local model. That baseline also has errors to measure: 4 in 60, where a better model leaves fewer.

- [ ] **[fill-in]** Hand-label the four fixtures with their correct extraction — what a perfect run would produce. *A2.1 labelled the pages it gates on (`eval/labels.py`; Ari labels Mortimer's); what remains is labelling further venues. These labels are also C6's held-out set: label once.*
- [ ] **[fill-in]** Promote `eval/run_eval.py` from throwaway to a real harness that scores a full graph run against those labels: precision and recall on shows found, field-level accuracy, and how often the retry loop fires. *A2.1 built the extraction-level scorer and gate (`eval/scoring.py`); what remains is scoring a full graph run and the retry loop. `run_eval.py` reaches `extract_page` only, so no graph-level retry data exists yet.*
- [ ] *(added)* **Score the database, not only the extraction:** run the graph twice over two captures of one venue (White Squirrel has two) and score the rows left behind: inserts, updates and soft deletes.
- [ ] *(added)* **Validation recall:** of the extraction errors the labels reveal, the fraction validation flagged versus let through silently. Act-naming slips look plausible to every check (an inference to confirm here, not measured), and this is what shows which layer catches which failure.
- [ ] *(added)* Record the baseline on `gemma4-e4b`.

**Done when:** the harness reports the four measures and the baseline is recorded. Needs the local model and the gitignored fixtures, so it can't run in the cloud.

### C6. Hosted inference and the extraction accuracy gate (was H1)

**Why:** A2.1 ended at 56 of 60 with the A2.1-D1 gate unmet, and named a larger model for the act splitter as the next fix (A2.1-E1). That model can only run hosted. This milestone moves inference to DeepInfra, the production provider `arch-initial.md` §5/§7 already chose, and closes the gate there. It needs only a DeepInfra key and the code A2.1 left behind, run from the laptop, so part 1 can start before C5 finishes.

- [ ] **Make the model endpoint configurable.** `agent_worker/llm.py` hard-codes Ollama's `localhost:11434/v1` (`arch-initial.md` §11). Add a base URL, API key and model name per call site (page model, act splitter, status question) to `Settings`, with Ollama as the local default. The retry policy's larger-model tier reads its model from the same place (`policy.py`).
- [ ] **Hosted parity first.** Run the gated eval on DeepInfra's `gemma-4-e4b-it`, the same model as local, before changing models. Then any change in the numbers can be put down to the model, not the provider. Expect small differences even at temperature 0, and record them.
- [ ] **A larger model for the act splitter only (A2.1-E1).** The splitter is one short call per page, so a bigger model costs little there. Re-try A2.1-E2 ("a title that is just a name is a performer") and add A2.1-E3 (a code check that every returned act appears in its title) with it. Target: the four known misses (Mortimer's "Flange August Back to Back"; 7th St Entry's "The Bright Light Social Hour" and the INTERNET KIDS night; White Squirrel's "Cole Diamond’s Whiskey Wednesdays").
- [ ] **A held-out test set.** The gated pages aren't held out: A2.1-D5's conventions were drawn from them, and the prompt was tuned against them (A2.1 code review round 2, #2). Capture fresh pages, from new venues or a later month, with `eval/capture.py`, and have Ari label them (`eval/labels.py`) *before* any run is scored against them. **[fill-in]** for the labelling, as in A2.1-D11; shared with C5.
- [ ] **Per-act start times on the title-split route.** That route returns each listing's verbatim title and no act objects, so per-act start times are lost. Ari accepted this for the alpha on October 12, 2026 (A2.1 code review round 2, #9); it departs from A2-D8. Decide whether a larger page model can return acts directly again (dropping title split), or add an optional verbatim set-times text to the listing.
- [ ] **Throughput and cost (A2.1-E15, A2.1-E4).** Measure a page's duration and cost on hosted inference, with parallel requests, and with thinking on and off. `alpha-build-plan.md` §8 had the laptop at 1.5–7 minutes a page.

**Done when:** the A2.1-D1 gate passes on every run, on both the gated pages and the held-out capture; the chosen models and their configuration are recorded in `arch-initial.md` §7; duration and cost per page are recorded.

**Constraints carried over from A2.1:** never try to get past a bot challenge (Midway, A2.1-D3); capture fixtures with the pipeline's own fetch, one plain GET per URL; results files record every prompt sent (code review round 2, #3).

### C7. Pipeline evaluation on the shipped model (was A8, second half)

*Migrated from `alpha-build-plan.md` A8, October 21, 2026.* These two questions have answers that depend on the model, so they wait for C6.

- [ ] **[fill-in]** Use the harness to answer the questions A3 left open: is 0.8 the right threshold, is 3 the right retry cap, and does the escalating-prompt retry actually recover failures or just cost tokens. The larger-model tier can only be tested here: on the laptop it reruns the same model (A3-D5, `a3-validation-and-retry.md`), and the attempt record says so.
- [ ] **[fill-in]** Check whether the model's self-reported confidence correlates with actual correctness against the labels. Phase 5 judged calibration by eye on a handful of pages; with labels you can check it properly. If it doesn't correlate, routing on it is a design problem worth knowing about. Four errors can't support a correlation, so the label set from C5 and C6 has to be broad enough to contain errors.
- [ ] Update the retry policy's defaults if the data says so, and record the numbers.

**Done when:** the threshold, the cap and the tier-3 question are each answered with data, and the policy is changed or confirmed.

### C8. The agent worker on Railway (was H2, with H3's Mongo half)

**Why:** `env-setup.md` Phase 8, "Railway — agent worker service". **Waits on** C3 (the environments) and C6 part 1 (the configurable endpoint).

- [ ] Its own `Dockerfile` from Playwright's image (`mcr.microsoft.com/playwright/python`, which already includes Chromium and its system libraries), and a Railway service per environment with `python -m agent_worker.main`.
- [ ] Environment variables point at DeepInfra, never Ollama (`localhost:11434` doesn't exist on Railway), and `MONGODB_URI` at the Atlas cluster, with the connection options checked. The staging write already exists since A4; the hosted cluster's version is this milestone's to choose (A4-D3 pinned local MongoDB to 7.0, `notes.md`).
- [ ] **Dev and staging run on demand; production is scheduled** (Dep-D9): the per-metro 4 a.m. trigger (`arch-initial.md` §11, metro-aware scheduling, with one metro live), **left off** until C11.
- [ ] The first real run against Neon, in dev, then staging.

**Done when:** the worker runs hosted in dev and staging, and the calendar at those hosts shows what it wrote.

### C9. Audit storage: R2 snapshots (was H3's R2 half)

**Why:** The R2 page snapshot in `fetch_node` is stubbed today (`arch-initial.md` §7 and §11). `audit_log.snapshot_key` stays NULL until it lands, and without it the JSON-LD route's raw markup is kept nowhere (the staging document holds only what the model was sent). Definition of done point 5 needs it.

- [ ] Create the Cloudflare account and a bucket and scoped token per environment (Dep-D10); the variables are in `.env.example` and commented.
- [ ] Write the snapshot in `fetch_node` with `boto3` and store the key on the audit row.
- [ ] *(idea, not scoped)* Saved snapshots would let dev and staging replay extraction without refetching venue sites.

**Done when:** a hosted run's audit rows carry a `snapshot_key` that resolves to the page it fetched.

### C10. Wiring and guard rails (was H4)

**Why:** The remaining pieces of `env-setup.md` Phase 8's skipped items. **Waits on** C3.

- [ ] **The FastAPI↔Next.js shared secret**, per environment, server-only: a FastAPI dependency checks the header and every Next.js call sends it (`arch-initial.md` §5). Until then the Railway API answers anyone who finds its URL.
- [ ] Update the required checks on `main` for jobs added since C1 (B6's end-to-end job, the evaluation harness if it gets one).
- [ ] Migrations and the seed run against Neon: done by C2 and C3; verify here that production, staging and dev all match.

**Done when:** a call to the Railway API without the secret is refused, and the calendar still renders.

### C11. Go-live and burn-in

- [ ] Enable production's cron, once Dep-D13's condition holds.
- [ ] Attach `msp.<domain>` to the Production environment; turn on the apex chooser (Dep-D11). Check Vercel's current plan terms first.
- [ ] **Burn-in:** let several daily runs complete; check each run's audit trail and the accuracy gate on what production fetched.
- [ ] **Measure the cost and duration** of a daily run and record them against `arch-initial.md` §10's estimate.
- [ ] Update `arch-initial.md` §7 (the chosen models), §9 and §10, and the stale notes in `env-setup.md`.

**Done when:** production answers on its domain, every row is traceable, and the cost and duration are on record (§2).

---

## 7. Where the old names went

| Old | Now | Note |
|---|---|---|
| `alpha-build-plan.md` A1b | C2 | The build plan keeps a pointer. |
| `alpha-build-plan.md` A8 | C5 and C7 | Labelling and the harness are C5; the threshold, retry and calibration questions are C7. |
| H1 | C6 | |
| H2 | C8 | |
| H3 | C3 (the per-environment Atlas databases), C8 (connecting the worker) and C9 (R2) | |
| H4 | C1 (branch protection), C3 (migrations, the Neon–Vercel decision) and C10 (the shared secret) | |

**References that still say H1–H4.** `AGENTS.md` ("Current phase"), `docs/arch/arch-initial.md` §11, `docs/dev/env-setup.md`, `docs/dev/conventions.md`, the A2, A2.1, A3, A4 and A5 plans, `apps/api/.env.example`, `docker-compose.yml`, and comments in `app/config.py` and `agent_worker/` (`policy.py`, `nodes.py`, `act_split.py`). They resolve through this table. Converting them is a separate pass: the code comments are a comment-only change (`AGENTS.md`, "Comment-only passes must not change code"), and the plan files record history. It is not done in the change that rewrote this plan.

---

## 8. Still deferred after this phase

Unchanged from `alpha-build-plan.md` §8, except for what moved here (the hosted services, the larger model, throughput, the pipeline evaluation): public edit and flag endpoints with Turnstile and Resend; Playwright fetching beyond what C8's image makes possible; the deeper venue sources (A2.1-E9–A2.1-E13); image-based show listings (`arch-initial.md` §11, not yet scheduled); the MCP admin server; chat search.

Also deferred, from this rewrite: **scoping every query by metro** (`arch-initial.md` §11; C4 resolves a host to a metro and stops there); **metro aliases** (`chicago` for `chi`, Dep-D3); **ephemeral PR environments** on Railway and Neon (Dep-D14); a **custom domain for the API**, which the browser never calls.
