# Alpha Deployment Plan — from a working local app to a hosted alpha

**Status:** Draft — not started. Scope to be confirmed by Ari before the first milestone is planned.

**Date:** October 12, 2026

**Purpose:** The plan for the phase after `alpha-build-plan.md`. That plan builds a working app on the local machine
and deliberately leaves everything hosted alone. This one moves it onto the hosted services, and **validates the
extraction on hosted inference**: the accuracy work that the development laptop can't finish.

Read `alpha-build-plan.md` first (what the alpha is and what it deliberately left out), and `env-setup.md` phases 7–9
(which hosted services are already deployed and which were skipped, with reasons). The specification is the same:
`docs/arch/arch-initial.md`, `data-model-initial.md` and `requirements-initial.md`.

**Starts when** the alpha build plan's definition of done (`alpha-build-plan.md` §2) is met. H1 is the exception: it
needs only a DeepInfra key and the extraction code A2.1 left behind, so it can start earlier if Ari wants.

---

## 1. Where things stand at the handoff

**Already hosted** (`env-setup.md` phases 8–9): `apps/calendar` on Vercel, the FastAPI service on Railway, Neon
Postgres, and CI on every PR. All of it was verified end to end with the health checks, and left alone during the alpha build.

**Skipped on purpose, and picked up here** (`env-setup.md` phases 7–8, `arch-initial.md` §11): DeepInfra, the Railway
agent worker service, the Cloudflare R2 page snapshots, the MongoDB raw-staging write, the Neon–Vercel preview-branch
integration, the FastAPI↔Next.js shared secret, and branch protection on `main`.

**Known extraction debt** (A2 and A2.1 were signed off by Ari on October 12, 2026 with this open): the extraction
pipeline scores **56 of 60** shows correct on the gated venues (White Squirrel ×2, 7th St Entry, Mortimer's). The
standard is 100% for dates and acts (`requirements-initial.md`, "Agent Extraction: Accuracy Standards"). The run was
deterministic and clean on the "never" tiers: no invented shows, no wrong field values. The four misses are act-naming
slips on ambiguous titles, and they look like the limit of the small local model (`gemma4-e4b`, about 4B
parameters). A larger model doesn't fit the development laptop. Evidence and the full list of deferred ideas are in
`implementations/a2.1-extraction-reliability.md`: "Experiment results" (`a21-confirm`, `a21-review2`) and "Deferred
explorations" (A2.1-E1–A2.1-E17).

---

## 2. Definition of done (draft)

1. The agent worker runs on Railway on its daily schedule against the live venue URLs, using DeepInfra for
   inference, and writes to Neon.
2. The extraction meets Ari's accuracy standard **on every run**, on the gated pages and on a fresh held-out
   capture (H1).
3. The Vercel calendar renders what that run wrote, and every row is traceable through the audit trail, as in
   `alpha-build-plan.md` §2 point 3, but in the hosted database.
4. The cost and duration of a daily run are measured and recorded against `arch-initial.md` §10's estimate.

---

## 3. Milestones

H1 is specified here because A2.1 has already defined its problem. H2–H4 are outlines drawn from the existing deferred
lists. Each one gets an implementation plan (`docs/dev/implementations/`) through the usual cycle (`AGENTS.md`) before
it is built.

### H1. Hosted inference and the extraction accuracy gate

**Why:** A2.1 ended at 56 of 60 with the A2.1-D1 gate unmet, and named a larger model for the act splitter as the next fix
(A2.1-E1). That model can only run hosted. This milestone moves inference to DeepInfra, the production provider
`arch-initial.md` §5/§7 already chose, and closes the gate there.

- [ ] **Make the model endpoint configurable.** `agent_worker/llm.py` hard-codes Ollama's `localhost:11434/v1`
  (`arch-initial.md` §11). Add a base URL, API key and model name per call site (page model, act splitter, status
  question) to `Settings`, with Ollama as the local default.
- [ ] **Hosted parity first.** Run the gated eval on DeepInfra's `gemma-4-e4b-it`, the same model as local, before
  changing models. Then any change in the numbers can be put down to the model, not the provider. Expect small
  differences even at temperature 0, and record them.
- [ ] **A larger model for the act splitter only (A2.1-E1).** The splitter is one short call per page, so a bigger model
  costs little there. Re-try A2.1-E2 ("a title that is just a name is a performer") and add A2.1-E3 (a code check that every
  returned act appears in its title) with it. Target: the four known misses (Mortimer's "Flange August Back to Back";
  7th St Entry's "The Bright Light Social Hour" and the INTERNET KIDS night; White Squirrel's "Cole Diamond’s Whiskey
  Wednesdays").
- [ ] **A held-out test set.** The gated pages aren't held out: A2.1-D5's conventions were drawn from them, and the prompt
  was tuned against them (A2.1 code review round 2, #2). Capture fresh pages, from new venues or a later month, with
  `eval/capture.py`, and have Ari label them (`eval/labels.py`) *before* any run is scored against them. **[fill-in]**
  for the labelling, as in A2.1-D11.
- [ ] **Per-act start times on the title-split route.** That route returns each listing's verbatim title and no act
  objects, so per-act start times are lost. Ari accepted this for the alpha on October 12, 2026 (A2.1 code review round 2,
  #9); it departs from A2 Decision 8. Decide whether a larger page model can return acts directly again (dropping
  title split), or add an optional verbatim set-times text to the listing.
- [ ] **Throughput and cost (A2.1-E15, A2.1-E4).** Measure a page's duration and cost on hosted inference, with parallel
  requests, and with thinking on and off. `alpha-build-plan.md` §8 had the laptop at 1.5–7 minutes a page.

**Done when:** the A2.1-D1 gate passes on every run, on both the gated pages and the held-out capture; the chosen models
and their configuration are recorded in `arch-initial.md` §7; duration and cost per page are recorded.

**Constraints carried over from A2.1:** never try to get past a bot challenge (Midway, A2.1-D3); capture fixtures with the
pipeline's own fetch, one plain GET per URL; results files record every prompt sent (code review round 2, #3).

### H2. The agent worker on Railway (outline)

`env-setup.md` Phase 8, "Railway — agent worker service": its own Dockerfile from Playwright's image, a cron-scheduled
`python -m agent_worker.main`, and environment variables pointing at DeepInfra, not Ollama. Includes the first real
run against Neon, and the per-metro 4 a.m. trigger (`arch-initial.md` §11, metro-aware scheduling, with one metro
live).

### H3. Audit storage in production (outline)

The R2 page snapshot in `fetch_node` and the MongoDB raw-staging write in `extract_node`. Both are stubbed today
(`arch-initial.md` §7 and §11). A4 landed the audit trail locally (`implementations/a4-auditability.md`): the MongoDB staging write already exists
and runs against a local `mongo:7.0` container (A4-D3, pinned to 7.0 from 8 on October 15, 2026, see `notes.md`; the hosted cluster's version is H3's to choose), so H3's Mongo half is only pointing `MONGODB_URI` at Atlas and
checking the connection options. The R2 half is still to build: `audit_log.snapshot_key` stays NULL until it
lands, and without it the JSON-LD route's raw markup is kept nowhere (the staging document holds only what the
model was sent).

### H4. Wiring and guard rails (outline)

The FastAPI↔Next.js shared secret, the Neon–Vercel preview-branch integration (once Railway has a matching per-PR
environment, `arch-initial.md` §9), migrations and seed run against Neon, and branch protection on `main` (needs
GitHub Pro or a public repo, `env-setup.md` Phase 8, "CI").

---

## 4. Still deferred after this phase

Unchanged from `alpha-build-plan.md` §8, except for what moved here (the hosted services, the larger model,
throughput): public edit and flag endpoints with Turnstile and Resend; Playwright fetching beyond what H2's image
makes possible; the deeper venue sources (A2.1-E9–A2.1-E13); image-based show listings (`arch-initial.md` §11, not yet scheduled); the MCP admin server; chat search; multi-metro.
