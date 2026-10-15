# A4 — auditability

**Status:** Done (Ari sign off) - Oct 15, 2026
**Date:** October 14, 2026
**Author model:** Claude Opus 5.5 (plan, plan-review resolution, October 14, 2026); Claude Sonnet 5.5 (implementation, from October 14, 2026)
**Reviewer model:** Claude Sonnet 5.5 (plan review round 1); Claude Opus 5.5 (code review round 1, October 14, 2026)
**Spec:** `docs/dev/alpha-build-plan.md` §5 A4 (and gap v0.1-G12, A2.1-E17), §2 point 3; `docs/arch/arch-initial.md` §6
(MongoDB raw staging, `AsyncMongoClient`) and §7 (the audit trail, `parent_run_id`, append-only);
`docs/arch/data-model-initial.md` §3 (`agent_run`, `audit_log`); `docs/references/fastapi-style-guide.md`;
`apps/api/AGENTS.md`

**Designations.** Inside this plan the decisions are `D1`–`D8` and the fill-in key points `K1` (the run's
lifecycle, `main.run_venue`), `K2` (`audit_confidence`, re-marked [written] at approval) and `K3` (the extract
staging write, `trace.audited`); elsewhere they are written `A4-D1`, `A4-K1` and so on
(`docs/dev/conventions.md`). Review items are `A4-PR<round>-<n>` for the plan review (`A4-PR1-4` is item 4
of plan review round 1) and `A4-CR<round>-<n>` for the code review (`A4-CR1-4` is item 4 of code review
round 1). Other plans' IDs carry their scope (`A3-D9`, `A2.1-E17`, `v0.1-G12`).

## Context

A3 made fetch, extract and validate real: the graph retries with a changed request, falls back from the
JSON-LD route to the model route, and escalates with a plain-English reason. Everything it decides stays in
the in-memory state (`attempt_history`, `validation`, `extraction_notes`, `escalation_reason`). When the process
exits, it's gone. The only lasting output is `local_test_output.json` and some `print()` lines.

A4 makes the run inspectable from the database. That's the build plan's definition of done, point 3: "what was
fetched, what the model returned, what validation decided, why reconcile chose what it chose, and what got
written". The build plan puts A4 *before* A5 and A6 on purpose: once the trail exists, reconcile and commit get
debugged by querying it, not by reading `print()` output.

### What A4 delivers

| Item (build plan A4) | Marking | Where it lands |
|---|---|---|
| `structlog` configured once: readable locally, JSON otherwise (v0.1-G12) | [written] | `app/log_config.py`; the worker's `print()`s become log lines |
| An `agent_run` per venue cycle, its id carried in the graph state | [fill-in] | `agent_worker/main.py` (`run_venue`), `state.run_id` — **K1** |
| An `audit_log` row from each of the six nodes | [written] *(re-marked by Ari, see Approval)* | `agent_worker/audit.py` (what each step records), wired in `graph.py` |
| The MongoDB raw-staging write on extract | [fill-in] | `agent_worker/staging.py`, called from the extract step — **K3** |
| Two or three saved SQL queries | [written] | `docs/dev/audit-queries.sql`, executed by a test |
| Persist each extraction's record (A2.1 A2.1-E17) | [written] | The Mongo staging document *is* that record (D4) |
| The R2 snapshot write | Deferred, on purpose | `audit_log.snapshot_key` stays null (build plan A4) |

### Decisions already made (earlier in this project)

- **Append-only.** A retry adds a row; nothing is updated or deleted (`arch-initial.md` §7,
  `data-model-initial.md` §3, `app/db/models/audit.py`).
- **`agent_run` is the `parent_run_id`.** Every row for one venue's cycle, retries included, points at it.
- **MongoDB holds the raw, pre-validation extraction; Postgres holds canonical data and the audit trail.**
  This is a bronze/silver split. Use `pymongo`'s `AsyncMongoClient`, not Motor, because Motor is deprecated
  (`arch-initial.md` §6).
- **The verdict is not a float, and "no confidence" is no evidence, not zero** (A3-D9;
  `arch-initial.md` §7). The audit trail must not turn a `None` into `0`.
- **The sync/async question is A4's to decide**, not A6's (build plan A4, "Known dependency from A1").
  It's settled as D1 below.

### Departures from the build plan (to apply to `alpha-build-plan.md` when implementing)

1. **A6's "`escalate_node` writing a real `audit_log` row with `outcome='escalated'`" lands here** (D5).
   A4 writes a row from every node, and an escalation is already a real decision since A3. A6 keeps
   reconcile's and commit's per-show rows.
2. **The worker reads its venues from Postgres in A4**, a small piece pulled forward from A5 (D6).
   `agent_run.venue_id` is a foreign key, so a run can't be opened for a venue the database doesn't have.
   The venue facts the state carries (`venue_name`, `metro_timezone`, `calendar_url`) should then come from
   that row, not from the caller.
3. **The Mongo write sits in the extract step's audit wrapper, not inside the body of `extract_node`**
   (D1). The build plan says "in `extract_node`". The effect is the same: one staging document per extract
   attempt, written before validation.
4. **`audit_log` gets one more column, `detail` (JSONB)** (D2). That's a departure from
   `data-model-initial.md` §3, to be recorded there.

## Decisions for Ari

Each decision has a recommendation, and the plan below is written to that recommendation. **Bold** marks
the ones that change what gets built if you choose differently.

- **D1 — Sync or async nodes: async graph, sync node bodies.** Each node becomes `async` from LangGraph's
  point of view, wrapped by `trace.audited(step, node)`. The existing node bodies stay plain, synchronous
  `state -> state` functions and run in a worker thread (`asyncio.to_thread`). The wrapper then awaits the
  audit write (and, on extract, the staging write) on the one event loop. The worker runs one
  `asyncio.run(main())` per process and calls `await compiled_graph.ainvoke(...)`. The shared pooled
  engine in `app/db/session.py` and one `AsyncMongoClient` are created inside that loop and used by every
  node.
  - *Why not the build plan's other option* (sync nodes, each write a fresh `NullPool` engine under its own
    `asyncio.run`):
    1. `AsyncMongoClient` is bound to its loop too, so every write would also open a new Mongo client. On
       Atlas (H3) that's a TLS handshake per row.
    2. `asyncio.run` raises inside a running loop, so the DB-backed tests, which run on pytest-asyncio's
       session loop, couldn't drive the graph at all (the same trap `notes.md` records for Alembic's
       `env.py`).
    3. A5 and A6 need an `AsyncSession` inside reconcile and commit. With one loop they simply `await`.
  - *Why not rewrite every node as `async def`:* the wrapper keeps "do the step" and "record the step"
    apart. What each step records is a pure function of the state (testable without a database), and the
    existing tests that call a node directly (`test_extraction.py`, `test_prompts.py`,
    `test_retry_plumbing.py`) keep calling sync functions unchanged. Only `test_graph.py`'s helper
    moves to `ainvoke`.
  - *Cost, accepted:* the model call and `fetch_html` (sync `openai` and `httpx` clients) run in a thread,
    not natively async. Converting them is a change to the code A2.1's eval shares, with nothing to gain for a
    job that processes venues one at a time. Dependencies reach the wrapper through LangGraph's runtime
    context (`StateGraph(..., context_schema=WorkerContext)`, `ainvoke(..., context=...)`), which keeps
    non-serializable clients out of the state. Probed against the pinned langgraph 1.2.11 while planning:
    an async node taking `runtime: Runtime[Ctx]` receives the context, a sync node in the same graph still
    runs, and `invoke()` on a graph with an async node raises `TypeError` (so nothing can call it the old way
    by accident).
  - *Alternative:* convert every node body to `async def` now.
- **D2 — Add `audit_log.detail` (JSONB, nullable).** §3's columns hold *who* and *what kind*
  (step, attempt, model, confidence, outcome, entity, before/after snapshots). They have no place for *why*:
  validate's verdict and failure reasons, fetch's error, extract's route and tier, escalate's reason, the
  staging document's id. Without one, point 3 of the definition of done ("what validation decided") can't
  be answered from Postgres. `previous_value`/`new_value` are the wrong home, because they're what a future
  revert restores, and mixing evidence into them would make revert guess which is which.
  - *Alternative:* keep §3 as is and put the evidence only in Mongo. Then a "why did run N escalate" query
    needs both stores.
- **D3 — MongoDB runs locally in `docker-compose.yml` (`mongo:8`); Atlas waits for H3.** The alpha's
  definition of done is "no network access to any hosted service". Atlas is hosted. H3 (alpha deployment
  plan) is already "audit storage in production", so the hosted cluster is pointed at there by changing
  `MONGODB_URI`.
  - **Departure (October 15, 2026): local Mongo is `mongo:7.0`, not `mongo:8`.** MongoDB 8.x refuses to start
    on Linux kernel 6.19+ (SERVER-121912), and Docker Desktop's VM runs 7.0.12, so `mongo:8.0` exits at
    startup. `make db-wait` reports that as a timeout. `mongo:7.0` (v7.0.45 tested) starts and answers ping.
    `GLIBC_TUNABLES=glibc.pthread.rseq=1` also gets 8.0 past the guard, but it bypasses a check MongoDB added
    for a real incompatibility, so it was not used. Reason and reversal conditions are in `docs/dev/notes.md`.
  - `make db-up` starts both containers.
  - CI's Python job gets a `mongo` service so the one real-Mongo test runs there. October 15, 2026: its image
    is `mongo:7.0` in `.github/workflows/ci.yml`, matching local compose.
  - The cloud sandbox has no Docker and no Mongo, so that test skips there, the same way the eval-fixture
    tests do. `cloud-setup.sh` is left alone.
  - A worker run with no `MONGODB_URI` refuses to start (fail fast). An audit trail that silently skips its
    raw record isn't auditable.
  - *Alternative:* point local runs at Atlas now, which drops the "no hosted service" property.
- **D4 — A2.1-E17 extraction record lives in the Mongo staging document, not in Postgres.** That
  document is exactly what A2.1-E17 lists: the route, the text actually sent, the route's notes, the raw model
  output, and the request configuration. It's what `arch-initial.md` §6 puts in Mongo. One document per
  extract attempt, failures included. The extract `audit_log` row carries its id in `detail.staging_id`, so
  the two stores join.
  - *Alternative:* a JSONB copy in `audit_log.detail` as well. That duplicates up to tens of KB of page
    text per attempt in Postgres.
- **D5 — Placeholder rows for the stubs; a real row for escalate.** `reconcile_node` and `commit_node` are
  still stubs (A5, A6). They write a row now, with `detail = {"stub": true, ...}` and no `outcome`, so the
  trail's shape (six steps) is complete and A5/A6 only change what the row says. `escalate_node`'s row is
  real: `outcome = 'escalated'`, entity = the venue, `detail.reason` = `state.escalation_reason`. A6's
  escalate bullet is then done (departure 1).
- **D6 — A worker entry point that reads venues from Postgres:** `python -m agent_worker.main [--venue ID]`
  (`make worker`). This is the name H2's Railway cron already expects. It loads each venue with its metro,
  then for each one, one after another: opens a run, invokes the graph, closes the run. `local_test.py`
  goes through the same `run_venue` with a fixture path in place of the URL.
- **D7 — Log format: console on a terminal, JSON otherwise, with `LOG_FORMAT` to force either.** This is
  structlog's own recommended switch (`sys.stderr.isatty()`). Railway's cron isn't a TTY, so it gets JSON
  without configuration. Every line in a run carries `run_id` and `venue_id` (bound with
  `structlog.contextvars`), so a log line joins to its audit rows.
  - `configure_logging()` is called by the worker only. The API logs nothing yet, and the module lives in
    `app/` so the API can call it once it does ("don't build what has nothing to consume it").
- **D8 — A run that crashes is still closed.** `finished_at` is set in a `finally`, and the exception is
  logged and re-raised. A crashed run is then one that has a `finished_at` but no `commit` or `escalate` row,
  which the fourth saved query finds. Leaving `finished_at` null would make "crashed" look the same as "still
  running".
  - *Alternative:* add `agent_run.outcome`, a schema change for something the rows already say.

## Test approach (written first, watched fail, then made green)

Every test below is written before its code and watched fail, as build plan §3 requires. Tests follow
`AGENTS.md`: each opens with `Proves:`, tests are grouped under section comments, and the source of every
expected value is stated. Three layers:

### 1. Pure: what each step records (`agent_worker/tests/test_audit_entries.py`)

`audit.entry_for(step, state, staging_id=None) -> AuditEntry` is a pure function, tested with hand-built
states. Expected values come from `data-model-initial.md` §3, the build plan's A4 bullet, and the literal
inputs, never from the code under test.

- **Every step:** `source = agent`, `run_id = state.run_id`, `entity = (venue, venue_id)` for the four
  venue-level steps.
- **`attempt_number`:**
  - fetch is always 1 (its own transient retries happen inside one step, `nodes.fetch_html`);
  - extract and validate use `state.attempt_count`;
  - reconcile, commit and escalate use the last attempt's number, floored at 1, so an escalation straight
    after a failed fetch is attempt 1, not 0.
- **Agentic fields:**
  - extract records `model_used = state.last_plan.options.model` (the larger model on a tier-3 attempt that
    ran one) and no confidence: the confidence is computed by validation, so it isn't known yet. **This is
    right on all three routes:** the JSON-LD route also calls the model, for the act split and the status
    question, with the same `RequestOptions` (`llm.request_kwargs`), so a model did make that attempt's
    judgement calls. What differs is *which* judgement, so both rows carry `detail.route`, and A8 separates
    "the model read the page" from "the model split titles" by it (A4-PR1-2);
  - validate records the same `model_used` and `confidence = state.confidence`. On the JSON-LD route that
    is a model name with a NULL confidence, which is accurate: the model ran, and gave no confidence that
    validation could weigh (A3-D9);
  - fetch, reconcile (stub), commit (stub) and escalate record neither.
  - Source: build plan A4, "on the agentic steps".
- **K2:**
  - `0.8567` is stored as `Decimal("0.857")`;
  - `0.1` is stored as `Decimal("0.100")`, not `Decimal(0.1)`'s binary tail;
  - **a JSON-LD validate row has `confidence` None, not 0** (A3-D9).
- **`detail` per step:**
  - fetch: url, fetched_on, error, characters of text;
  - extract: tier, route, error, staging_id, show count;
  - validate: route, verdict, reasons, error messages, counts of warnings, repairs and exclusions;
  - reconcile/commit: `{"stub": true, "decision": ...}`;
  - escalate: reason, with `outcome = escalated`.
- **Staging document is plain data:** `staging.document_for` on a state whose `extraction_notes` holds a
  `date`, a `StrEnum` and a tuple returns a document that `bson.encode` accepts (A4-PR1-1).
- **JSON-serializable:** `json.dumps(entry.detail)` succeeds for each step, including a validate state
  carrying enum reasons and dated findings. Guards against a `date` or `StrEnum` reaching JSONB unconverted.

### 2. The graph writes the trail (`agent_worker/tests/test_graph_audit.py`, in-memory fakes)

The real compiled graph, with `fakes.ScriptedClient` for the model and two new recording fakes,
`RecordingAudit` and `RecordingStager`, in `tests/fakes.py`. No database and no Mongo.

- A clean JSON-LD page passes on attempt 1. The rows are fetch, extract, validate, reconcile and commit, in
  that order, all attempt 1, all carrying `run_id`.
- A model call that raises once:
  - extract and validate rows for attempts 1 and 2, then reconcile and commit (a retry *adds* rows);
  - **two staging documents, the failed attempt's included** (K3), each carrying its `error` and request
    configuration;
  - each extract row's `detail.staging_id` names its own document.
- A model call that always raises: three extract/validate pairs, then one escalate row with
  `outcome = escalated` and the same reason text as `state.escalation_reason`.
- An unreadable page: a fetch row with the error, then escalate. No extract row, and no staging document.
- A staging write that raises (fake set to fail): the error propagates out of `ainvoke`. A run whose raw
  record can't be kept stops; it doesn't continue unaudited.

### 3. Real stores (DB tests: `REQUIRE_DB` rules; Mongo test: skips when unreachable)

- **`agent_worker/tests/test_audit_writer.py`** (Postgres, the `db_conn` fixture, with a session factory
  bound to it in savepoint mode):
  - `start_run` inserts an `agent_run` with `started_at` set and `finished_at` null;
  - `record` inserts one `audit_log` row per call and never updates (two calls give two rows);
  - `finish_run` sets `finished_at`;
  - `detail` round-trips as JSONB;
  - a `Decimal("0.857")` lands in `Numeric(4, 3)` unchanged.
- **`agent_worker/tests/test_run_venue.py`** (Postgres, plus the recording stager):
  - `run_venue` loads the seeded venue and its metro's timezone, and every row's `run_id` is the run it
    opened;
  - **K1:** with the graph patched to raise, `finished_at` is still set and the exception still reaches
    the caller;
  - a venue id that doesn't exist raises before any run is opened.
- **`agent_worker/tests/test_audit_queries.py`** (Postgres): runs a scripted retry-then-pass and a scripted
  escalation through `run_venue` against the test database, then executes **each query in
  `docs/dev/audit-queries.sql`** with `:run_id` / `:show_id` bound. Expected rows come from the scripts (for
  example, "which runs escalated" returns the escalated run and not the other). This makes the build plan's
  "being able to run these is the real test" an actual test. The show-history query is checked against one
  hand-inserted `commit` row, since nothing writes per-show rows until A6.
- **`agent_worker/tests/test_staging_mongo.py`** (real Mongo, `MONGODB_TEST_URI`, default
  `mongodb://localhost:27017`). It skips when the server doesn't answer within one second, and fails instead
  of skipping under `CI`. `MongoStager.stage` returns an id that finds the document; a `notes` value holding a
  `date` comes back as its ISO string (converted by `document_for`, since BSON can't encode a `date`), and
  `staged_at` comes back as a `datetime`. The test drops its own test database afterwards.
- **`app/tests/test_log_config.py`:** `LOG_FORMAT=json` renders one JSON object per line carrying bound
  `run_id`. `console` renders the event text. Calling `configure_logging()` twice is harmless.
- **Existing tests:**
  - `test_db_schema.py`'s migration round-trip and `test_db_metadata.py` cover the new column for free (the
    migration must match the model);
  - `test_graph.py`'s 19 tests change only in their helper (`await compiled_graph.ainvoke(..., context=...)`)
    and gain `async`;
  - every direct node test is unchanged (D1).

### What is not covered, stated plainly

- A live worker run against a real venue URL with Ollama. The cloud sandbox can't run one (`AGENTS.md`,
  "Cloud sessions"). It's in Verification for Ari to run locally.
- The Mongo test in the cloud sandbox, which skips there. CI runs it.
- `configure_logging`'s TTY auto-detection, beyond one test with stderr forced to a non-TTY.

### Known gotchas to handle up front

- **LangGraph injects `runtime` by inspecting the node's signature.** The audit wrapper must declare
  `runtime: Runtime[WorkerContext]` itself and must **not** use `functools.wraps`. That would make the wrapper report the
  inner node's signature (no `runtime` parameter), so no context is injected and the call fails with
  `TypeError: … missing 1 required positional argument: 'runtime'` (verified while building; the first
  draft of this plan said "silently", which was wrong). `test_the_context_reaches_the_audited_nodes` guards it.
- **SQL in `audit-queries.sql` avoids `::` casts** (it uses `CAST(... AS ...)`). SQLAlchemy's `text()` reads
  `:name` as a bind parameter, which is also psql's variable syntax. That's why the same file runs in both
  `psql` (`\set run_id 3`) and the test.
- **`fileConfig()` in Alembic's `env.py` disables stdlib loggers** (`notes.md`). structlog here uses its own
  `PrintLoggerFactory`, not stdlib logging, so it's unaffected. Don't switch it to the stdlib integration
  without re-reading that note.
- **The state crosses a thread** (`to_thread`) and comes back. The node mutates the same object it returns,
  which LangGraph accepts (`graph.py`'s probe notes). No node keeps a reference to it after returning.

## Implementation steps

### Working protocol for [fill-in] steps

The scaffold is complete except for two `TODO(Ari)` blocks (K1 and K3; K2 was re-marked [written] at approval). Each fails loudly with
`raise NotImplementedError("TODO(Ari)")`, so its tests are red, not accidentally green. Everything else,
including the tests for the gaps, is written and green where it doesn't depend on a gap. "Go ahead" or
`/build-milestone` produces the scaffold. A gap is filled only when Ari asks for it by name.

### TODO(Ari) gaps

**Fill order:** K3, then K1. K3's graph test needs only K3 (the recording fakes stand in for Postgres). K1's DB
tests need both. **Until K3 is filled, no test that runs the graph is green** (`test_graph.py` included, which
is green today): the placeholder sits on the path every run takes (A4-PR1-4). K1's placeholder
turns `test_run_venue.py` and `test_audit_queries.py` red as well.

- **K1 — the run's lifecycle, in `agent_worker/main.py` (`run_venue`)** (the `agent_run` bullet).
  - *Lesson:* the run is the parent of every row (`arch-initial.md` §7, `parent_run_id`). Its id travels
    **in the state**, not in a module global, so every node's row points at the run that produced it, and
    two runs could never cross. It is closed in a `finally`, because a run that crashes must still end
    (D8). Otherwise it looks "in progress" forever.
  - *Code:*

    Written just above the gap, so the snippet pastes as is (A4-PR1-8):
    `initial = VenueGraphState(venue_id=venue.id, calendar_url=calendar_url or venue.calendar_url,
    venue_name=venue.name, metro_timezone=venue.metro_timezone, fetched_on=fetched_on)`.

    ```python
    run_id = await ctx.audit.start_run(venue.id, trigger)
    structlog.contextvars.bind_contextvars(run_id=run_id, venue_id=venue.id)
    try:
        result = await compiled_graph.ainvoke(initial.model_copy(update={"run_id": run_id}), context=ctx)
        return VenueGraphState(**result)
    finally:
        await ctx.audit.finish_run(run_id)
        structlog.contextvars.unbind_contextvars("run_id", "venue_id")
    ```

  - *Then:* delete the two `# noqa` markers in `main.py` (`compiled_graph` in the imports, and `initial =`); same reason (A4-CR1-1).
  - *Check:* `uv run pytest agent_worker/tests/test_run_venue.py`. The likeliest mistake is calling
    `finish_run` after `ainvoke` with no `finally`: the crash test then finds `finished_at` null.
- ~~**K2 — `audit_confidence`**~~ **Re-marked [written] by Ari at approval (October 14, 2026).** Written
  complete in `agent_worker/audit.py`. The lesson survives as a comment there: "no confidence" is no
  evidence, not zero (A3-D9), so a `None` stays `NULL`; and the float goes through `str` before `Decimal`
  (`Decimal(0.1)` carries the binary tail), then `quantize(Decimal("0.001"))` to fit `Numeric(4, 3)`. Its
  tests (`test_audit_entries.py -k confidence`) are written and green.

- **K3 — stage every extract attempt, in `agent_worker/trace.py` (`audited`)** (the MongoDB bullet).
  - *Lesson:* raw staging is the record of what the model was asked and what it said, **before anyone
    judged it** (`arch-initial.md` §6, bronze before silver). So it is written on every attempt,
    unconditionally. A failed call's document (its error, request configuration and route) is exactly the
    record a person debugging an escalation needs. The document's id goes into the extract row, which is
    what joins the two stores (D4).
  - *Code:*

    ```python
    staging_id = None
    if step is StepType.EXTRACT:
        staging_id = await runtime.context.stager.stage(staging.document_for(state))
    ```

    `state` here is the one the node *returned* from `asyncio.to_thread`, written just above the gap. The
    document needs what the attempt produced (`extract_error`, `extraction_sent_text`, `extraction_notes`).
  - *Then:* delete the `# noqa` on the `staging` import at the top of `trace.py`; it exists only while the gap is open, and ruff flags it (RUF100) once the name is used (A4-CR1-1).
  - *Check:* `uv run pytest agent_worker/tests/test_graph_audit.py -k retry_adds_rows`. The test checks each
    document's `attempt` and `error`, not just the count. The likeliest mistake is guarding with
    `if state.extraction is not None`: the failed attempt's document is then missing, and the test counts one
    document instead of two. The second likeliest is staging before the node runs: the documents then carry
    the previous attempt's fields, which the per-document `attempt`/`error` check catches (A4-PR1-5).

### 1. Schema: `audit_log.detail` (written)

- Add `detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)` to `AuditLog`, with a comment saying
  what goes there and why it isn't `new_value` (D2).
- Generate the migration with `make migration m="audit_log detail"` and read it. It should be one
  `add_column` and one `drop_column`, with no enum types.
- Record the departure under `data-model-initial.md` §3's "Departures" list.
- `app/schemas.py` is untouched, so `make types` / `make fixtures` have nothing to regenerate and there's no
  B-track impact.

### 2. Configuration and local services (written)

- `Settings` gets:
  - `mongodb_uri: str | None = None`;
  - `mongodb_database: str = "calendar"`;
  - `log_format: Literal["auto", "console", "json"] = "auto"`.
- `.env.example` moves Mongo from "not yet required" to required for worker runs, with the local URL.
- `docker-compose.yml` gets a `mongo:8` service on 27017 with a named volume.
- In the `Makefile`:
  - `db-wait` also waits on `mongosh --eval 'db.runCommand({ping:1})'`;
  - `db-reset` drops both volumes;
  - a `worker` target is added (`cd apps/api && uv run python -m agent_worker.main $(if $(VENUE),--venue $(VENUE))`).
- `ci.yml`'s Python job gets a `mongo:8` service and `MONGODB_TEST_URI`.

### 3. `app/log_config.py` (written)

- `configure_logging(fmt=settings.log_format)` sets up the processor chain:
  1. `merge_contextvars`;
  2. `add_log_level`;
  3. `TimeStamper(fmt="iso", utc=True)`;
  4. `StackInfoRenderer`;
  5. `format_exc_info` (JSON only);
  6. then `ConsoleRenderer()` or `JSONRenderer()`.
- It uses `PrintLoggerFactory(sys.stderr)` and `cache_logger_on_first_use=True`.
- The name avoids `app/logging.py`, which reads as if it shadows the stdlib module.
- The worker's `print()` calls in `reconcile_node`, `commit_node` and `escalate_node` become
  `log.info(...)` with key/value fields. `local_test.py` keeps its `print()` summary, because that's
  output for a human, not logging.

### 4. `agent_worker/audit.py` (written, except K2 and K3)

- `AuditEntry`, a frozen dataclass mirroring the writable columns.
- `entry_for(step, state, staging_id=None)`, with one small builder per step (§1's table of what each
  records).
- `audit_confidence`, written complete (K2 was re-marked [written] at approval).
- The `AuditWriter` protocol: `start_run`, `record`, `finish_run`.
- `PostgresAuditWriter(session_factory)`. It opens one short session per call and commits it. The comment
  says why: each row is committed as it happens, so a crash later in the run can't roll back the record of
  what led up to it. It only ever `add`s, never updates `audit_log`.
- `trace.audited(step, node)`, the wrapper from D1 (K3 sits inside it), is in its own module
  `agent_worker/trace.py`, not `audit.py` (build-time departure, see the Implementation log): `WorkerContext`
  holds an `AuditWriter`, so `audit.py` cannot import `context.py`, and the wrapper needs both. It runs the
  sync node with `asyncio.to_thread`, stages on extract, records the entry, and returns the state. Its
  docstring carries the `functools.wraps` warning.
- Imports go `state` ← `audit` / `staging` ← `context` ← `trace` ← `graph`, so the module DAG stays acyclic.
  `nodes.py` imports none of them.

### 5. `agent_worker/staging.py` (written)

- `document_for(state) -> dict` builds the A2.1-E17 record. Everything except `staged_at` passes through
  `pydantic_core.to_jsonable_python` first, so a `date`, a `StrEnum`, a tuple or a dataclass in the untyped
  `notes` becomes plain JSON before it reaches BSON, which can't encode `datetime.date` (A4-PR1-1).
  `staged_at` is a timezone-aware `datetime`, which BSON stores natively. The record holds:
  - run_id, venue_id, attempt, tier, route;
  - model and request options (`asdict(plan.options)`) and configuration (`asdict(plan.config)`);
  - `sent_text`, `notes`, `raw_extraction` (`model_dump(mode="json")`, or None);
  - on a failed call, `sent_text` is None (`extract_page` raised before returning it), so the document stores
    `page_text = state.page_content` instead, labelled as the cleaned page the route started from, not the
    exact request. The exact request is reproducible from that text plus the stored configuration
    (A4-PR1-6);
  - error;
  - `staged_at`.
- The `Stager` protocol and `MongoStager(collection)`. `stage` is `insert_one`, returning
  `str(inserted_id)`. The collection is `extraction_staging`.
- `state.extraction_sent_text: str | None` is added. `extract_node` sets it from
  `PageExtractionResult.sent_text` and resets it on every attempt, like the other per-attempt fields (the
  comment in `state.py` explains why).
- `extraction_notes` is checked for JSON-safety in the tests (§1 and §2).

### 6. Wiring: state, context, graph (written)

- `state.run_id: int | None = None`.
- `agent_worker/context.py`: `WorkerContext(audit: AuditWriter, stager: Stager)`, a frozen dataclass.
- `graph.py`:
  - `StateGraph(VenueGraphState, context_schema=WorkerContext)`;
  - each `add_node` registers `audited(StepType.X, x_node)`;
  - the module comment about `invoke` is updated: the graph is `ainvoke`-only now, and the reason is given.
- `nodes.py`'s module docstring and the "deferred to A4" notes in `extract_node`, `validate_node` and
  `escalate_node` are updated to say where each thing now lives.

### 7. `agent_worker/main.py` (written, except K1)

- `load_venues(session, venue_id=None)`: venue rows joined to their metro.
- `run_venue(venue, ctx, *, trigger=RunTrigger.MANUAL, calendar_url=None, fetched_on=None)` (K1
  inside). The overrides exist for `local_test.py`'s fixture run. (`venue.calendar_url` is non-null in the
  model, so there is no missing-URL branch; A4-PR1-7.)
- `main()`:
  - parse `--venue` and `--trigger`;
  - call `configure_logging()`;
  - fail fast if `MONGODB_URI` is unset (D3);
  - create the `AsyncMongoClient` and the context;
  - loop over the venues **one after another** (`arch-initial.md` §7: one process, every venue);
  - close the Mongo client and dispose of the engine in `finally`.
- `asyncio.run(main())` runs under `if __name__ == "__main__"`.
- One venue's crash is logged and the loop continues to the next venue. The run is already closed by
  K1's `finally`. The catch is a named exception tuple, not `Exception`, per `apps/api/AGENTS.md`; the
  tuple is decided while writing it and listed in the Implementation log.

### 8. `local_test.py` (written)

- Goes through `run_venue` for venue 1 with the White Squirrel fixture path and `fetched_on=2026-08-17`.
- It now needs Postgres (seeded) and Mongo up, and says so in its docstring.
- It prints the `run_id` and the psql line that runs the saved queries for it.

### 9. Tests updated (written)

- `test_graph.py`'s `run_graph` becomes `async` and uses
  `ainvoke(..., context=WorkerContext(RecordingAudit(), RecordingStager()))` with `run_id=1` in the state.
  Its 19 tests gain `async`.
- `fakes.py` gets the two recording fakes. The new test files are as in Test approach.

### 10. `docs/dev/audit-queries.sql` (written)

Each query sits under a `-- name:` header and a one-line comment saying the question it answers:

1. **`run_history`**: everything that happened in run `:run_id`, in order. Columns: step, attempt, model,
   confidence, outcome, the `detail` fields that matter (verdict, reasons, error, route, reason), and
   `staging_id` for the Mongo lookup.
2. **`escalated_runs`**: which runs escalated and why. Venue name, started, attempts used, and the escalate
   row's reason, newest first.
3. **`show_history`**: what changed about show `:show_id` and when. Its `audit_log` rows, with
   `previous_value` and `new_value`. Empty until A6 writes per-show rows; the file says so.
4. **`unfinished_runs`**: runs that ended without reaching commit or escalate, which means they crashed
   (D8), plus runs with no `finished_at` at all.

The file's header shows how to run it: `make db-shell`, then `\set run_id 3`, then `\i docs/dev/audit-queries.sql`
(or paste one query).

### 11. Docs and bookkeeping (written)

- `alpha-build-plan.md` A4: link to this plan and record the departures. A6's escalate bullet is marked
  done-by-A4.
- `arch-initial.md` §7: one paragraph on what A4 built (async graph and sync bodies, `detail`, the staging
  link).
- `data-model-initial.md` §3 departures: `detail`.
- `app/db/session.py`'s docstring: the "known consequence for A4" becomes what was done.
- `apps/api/AGENTS.md`, "Agent worker": the graph is `ainvoke`-only, how a node reaches the database (the
  runtime context), and the `functools.wraps` trap.
- `apps/api/.env.example`.
- `notes.md` if anything non-obvious turns up while building.
- `alpha-deployment-plan.md` H3: point at D3 and D4.

## Critical files

| File | Change |
|---|---|
| `apps/api/app/db/models/audit.py`, `migrations/versions/<new>.py` | `detail` JSONB (D2) |
| `apps/api/app/config.py`, `apps/api/.env.example` | Mongo URL and database, log format |
| `apps/api/app/log_config.py` (new) | structlog (v0.1-G12) |
| `apps/api/agent_worker/audit.py` (new) | Entries, writer, wrapper — K2, K3 |
| `apps/api/agent_worker/staging.py` (new) | A2.1-E17 document, Mongo stager |
| `apps/api/agent_worker/context.py` (new) | `WorkerContext` |
| `apps/api/agent_worker/main.py` (new) | Entry point, `run_venue` — K1 |
| `apps/api/agent_worker/state.py` | `run_id`, `extraction_sent_text` |
| `apps/api/agent_worker/graph.py` | Context schema, audited nodes, `ainvoke`-only |
| `apps/api/agent_worker/nodes.py` | `sent_text`, `print` → structlog, docstrings |
| `apps/api/agent_worker/local_test.py` | Through `run_venue` |
| `apps/api/agent_worker/tests/` | `test_audit_entries`, `test_graph_audit`, `test_audit_writer`, `test_run_venue`, `test_audit_queries`, `test_staging_mongo`; `fakes.py`; `test_graph.py` helper |
| `apps/api/app/tests/test_log_config.py` (new) | Log rendering |
| `docker-compose.yml`, `Makefile`, `.github/workflows/ci.yml` | Mongo service, `make worker` |
| `docs/dev/audit-queries.sql` (new) | The saved queries |
| Docs listed in step 11 | Bookkeeping |

## Verification

**In the cloud session (this author's):**

1. `make check`. Expect red, by design, wherever a run goes through the audit wrapper (A4-PR1-4).
   K3 sits in every extract step, so **all of `test_graph.py` and `test_graph_audit.py` are red until K3
   is filled**, and `test_run_venue.py` and `test_audit_queries.py` also need K1. Everything else (the direct
   node tests, the pure entry tests, the writer, the stager, logging, the migration) must be green. The
   Implementation log lists the red tests by file with that reason. The baseline before A4 was 566 passed and 14 skipped. The Mongo test adds one skip
   here (no Mongo in the sandbox).
2. Gaps verified filled on a scratch copy (a throwaway `git worktree`, removed afterwards): with all three
   filled, the whole suite is green, and the result is recorded in the Implementation log. This is the
   pattern A3 used.
3. `alembic upgrade head` / `downgrade -1` / `upgrade head` against `calendar_dev`, and the new column
   seen in `\d audit_log`.

**Locally (Ari, after filling the gaps; needs Docker and Ollama):**

4. `make db-reset && make seed`, then `make worker VENUE=1`. Expect console log lines carrying
   `run_id=…`, and an exit after one venue.
5. From the repo root, `cat docs/dev/audit-queries.sql | docker compose exec -T postgres psql -U postgres -d calendar_dev -v run_id=<id> -v show_id=0 -f -` runs all four queries. (October 15, 2026: the earlier `\i` recipe fails, because psql runs inside the container and can't see the repo's files.) Expect fetch, extract (one per
   attempt), validate (one per attempt), reconcile and commit stubs, or escalate. Each extract row's
   `staging_id` is set.
6. `docker compose exec mongo mongosh calendar --eval 'db.extraction_staging.findOne()'`. Expect the
   document with `sent_text`, `notes`, `raw_extraction` and the request configuration.
7. `LOG_FORMAT=json make worker VENUE=1 2>&1 | head -3`. Expect one JSON object per line.
8. `cd apps/api && uv run python -m agent_worker.local_test`. Same trail, against the fixture. (Run from `apps/api`, not the repo root: the module lives there. October 15, 2026: the root-level command failed with `No module named 'agent_worker'`.)

## Not doing in A4

- The R2 page snapshot (`snapshot_key` stays null; deferred by the build plan). Without it, the JSON-LD
  route's raw markup isn't kept anywhere. The Mongo document keeps only what the model was sent (the
  numbered titles). Noted for H3.
- Per-show `reconcile`/`commit` rows, `previous_value`/`new_value` (A5, A6).
- Validate reading its input back from Mongo, as the arch diagram's `Staging --> Validate` arrow suggests.
  Validate reads the state, which holds the same object; reading it back would add a round trip for no new
  information. Recorded as a deliberate departure in `arch-initial.md` §7's A4 paragraph.
- Logging in the FastAPI app (D7), and the MCP server's "retrieve the full audit trail for a run"
  (`arch-initial.md` §7), which can reuse `run_history` later.
- Widening mypy to `agent_worker/` (A7). The new modules are written to pass it anyway.
- **Resolved (October 15, 2026):** CI's `mongo` service in `.github/workflows/ci.yml` is now `mongo:7.0`,
  matching local compose (D3 departure). The CI runners' kernel was not checked, so the match is a
  consistency choice, not a verified fix.

## Approval

**Ari, October 14, 2026:** approved D1–D8 as recommended. **K2 re-marked [written]:** it is three lines
and the lesson is already in the plan and in the tests, so it is written complete rather than left as a gap
(`AGENTS.md` allows re-marking a gap that does not earn its place). K1 and K3 stay open for Ari. Approval
was recorded by invoking `/build-milestone`. No draft PR yet, at Ari's request.

**Ari, October 15, 2026: signed off. A4 is Done.** K1 (`main.run_venue`) and K3 (`trace.audited`) were filled by
Ari (commit `ec314a2`, "close the intentional gaps"); Ari ran the local verification (Docker Desktop, Ollama) and
committed its findings (`8ba2864`): local MongoDB pinned to 7.0 (see `docs/dev/notes.md`), the `psql` recipe fixed
to pipe the file in from the host, and `local_test` run from `apps/api`. Plan review round 1 (8 findings) and code
review round 1 (12 findings) are both fully resolved. Not verified in the cloud sandbox and covered instead by
Ari's local run: `MongoStager` against a real server, `make worker`, and live extraction.

## Plan review

### Round 1 (Claude Sonnet 5.5, October 14, 2026)

**Scope:** the whole plan, judged cold against `alpha-build-plan.md` §5 A4 / §2, the A1 `audit.py` models,
`app/db/session.py`, and the current `agent_worker/` code (`graph.py`, `nodes.py`, `state.py`, `policy.py`,
`extraction.py`, `local_test.py`, `tests/test_graph.py`), plus `.env.example`, `env-setup.md` and `app/config.py`.
**How:** read the files above; grep for every `.invoke(` caller and every Mongo setting name; ran one
experiment in the repo's venv (`bson.encode` of a `datetime.date`, no worktree needed, nothing changed).
I did not re-run the langgraph `Runtime` probe the plan reports, and did not run `make check` (no code exists yet).
**Counts:** 0 blocker, 4 should-fix, 4 nit. **Verdict: proceed after fixes.** The design (async graph with
sync bodies behind an audit wrapper, Mongo as bronze, `detail` JSONB, stub rows for reconcile/commit) is
sound and consistent with the docs. The gaps are in details that will trip the build.

| # | Sev | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|
| 1 | should-fix | The Mongo test and document design assume a `date` can be stored, but BSON can't encode `datetime.date`. §"Real stores" says "a `date` in the document round-trips"; §5 builds the document from `asdict(plan.options)`, `asdict(plan.config)`, `notes`, and `model_dump(mode="json")`. Only the last is JSON-safe by construction. | CONFIRMED: `bson.encode({"d": datetime.date.today()})` raises `InvalidDocument: cannot encode object: datetime.date(...)`. `PageExtractionResult.notes` is `dict[str, Any]` (extraction.py:117) and `state.extraction_notes` is likewise untyped. The plan checks JSON-safety of notes only via `json.dumps`, which does not prove BSON-safety (a tuple, set or enum passes some and fails others). | As written, the `test_staging_mongo` date test fails by design, or `document_for` raises `InvalidDocument` in production on the first note holding a date, which K3 then propagates as a halted run (the plan's own rule). Stating "a date round-trips" also contradicts the document being JSON-mode. || **Fixed.** §5: `document_for` passes everything but `staged_at` through `pydantic_core.to_jsonable_python`, so a `date`/`StrEnum`/tuple in `notes` becomes plain JSON before BSON sees it; `staged_at` stays a `datetime` (BSON-native). Test approach §1 adds a `bson.encode` check on a state whose notes hold a date, an enum and a tuple; §3's Mongo test now expects the date back as its ISO string. |
| 2 | should-fix | `model_used` on extract/validate rows is "`state.last_plan.options.model`" unconditionally. On the JSON-LD route (and the image route's non-page path) the plan still carries the page model's name, but no model ran. The plan also says validate "records the same `model_used`" while "a JSON-LD validate row has confidence None". So the same row would say "a model was used" and "no model judged this". | `nodes.py` `_route_for` returns `"jsonld"` when `plan.config.route == "auto"` and the page has usable events; `PIPELINE_OPTIONS.model` is always set (extraction.py ~line 95). `policy.AttemptPlan.larger_model_used` exists to stop exactly this kind of misreport (policy.py:94-103, D5). Build plan A4: `model_used` "on the agentic steps". PLAUSIBLE for the JSON-LD title-split step, which does call a model for act splitting (extraction.py:315 region), so the right rule needs a decision, not a guess. | The audit trail, which A8 uses to measure calibration per model, would attribute every JSON-LD page to the LLM. Tests in §1 would pin the wrong behavior, because the expected values are "last_plan.options.model" on every attempt. || **Fixed (clarified, rule kept).** The model *does* run on the JSON-LD route: the act splitter and the status question both go through `llm.request_kwargs(options)` with the same `options.model` (`act_split.py:102`, `status_check.py:76`, `llm.py:61`), so `model_used` is accurate there. What differs is the judgement, so the extract and validate rows both carry `detail.route`, and the JSON-LD validate row's model name with NULL confidence is stated as intended (Test approach §1, agentic fields). |
| 3 | should-fix | Env var name conflict. The plan introduces `MONGODB_URL` (D3, §2, `Settings.mongodb_url`), but the repo already names it `MONGODB_URI` in `apps/api/.env.example:71` and in `env-setup.md:220` (Railway variables). H2/H3 and the already-provisioned Railway service were written against that name. | CONFIRMED by grep: `MONGODB_URI` in `.env.example` and `env-setup.md`; `MONGODB_URL` appears only in this plan; `app/config.py` has no Mongo setting yet. | Two names for one thing: the hosted service's configured variable would not be read by `Settings` (pydantic-settings matches the field name), and the worker would refuse to start in Railway with the "fail fast" message. || **Fixed.** Renamed to `MONGODB_URI` / `Settings.mongodb_uri` throughout the plan (D3, D6's fail-fast, §2, §7), matching `.env.example` and `env-setup.md`. |
| 4 | should-fix | The scaffold turns existing green tests red, which the plan understates. K2's placeholder (`audit_confidence` in `entry_for`) is called for every validate row, and K3's placeholder sits in the wrapper every extract goes through, so all of `test_graph.py`'s 19 tests (which the plan converts to `ainvoke` with `RecordingAudit`) plus every graph audit test go red until the gaps are filled. Verification step 1 says only "the gap tests, listed by name". | `graph.py` wiring in §6 wraps all six nodes; `test_graph.py:70` runs the whole graph in every test. K2's check names only `-k confidence` and K3's names `-k raises_once`. | The author's `make check` baseline (566 green) stops being a meaningful signal of "scaffold broke nothing", and Ari filling K2 alone sees 20+ tests still red because C blocks extract. The fill order (B, C, A) is stated, but not that nothing in the graph is green in between. || **Fixed.** Verification 1 now says every graph-running test (`test_graph.py` included) is red until B *and* C are filled, lists which files, and says what must stay green. The fill-order note under TODO(Ari) gaps says the same. |
| 5 | nit | K3's snippet calls `staging.document_for(state)`, but which `state` is not said. It must be the state returned by the (threaded) node, because the document needs `extraction_sent_text`, `extract_error` and `extraction_notes`, which only exist after the node ran. Placed before `to_thread` it would stage the previous attempt. | The snippet in the K3 block, and the §4 description ("runs the sync node with `asyncio.to_thread`, stages on extract, records the entry"). | A wrong-order paste stages stale data and the failure-attempt test may still count two documents, so the test would not catch it unless it checks each document's `error`/attempt (the plan's §2 does say each carries its `error`; make the Check say that is what catches this). || **Fixed.** K3 says `state` is the one the node returned from `asyncio.to_thread`, written just above the gap, and its Check now asserts each document's `attempt` and `error` (which catches staging before the node runs). |
| 6 | nit | A failed attempt's staging document can't carry `sent_text`. `extract_page` raises before returning `PageExtractionResult`, so `extraction_sent_text` stays None on failure. The plan says the failed document is "exactly the record a person debugging an escalation needs" and lists request configuration and error, but a debugger most wants the text that was sent. | extraction.py:244/315 return `sent_text` only on success; `nodes.py` `extract_node` sets state fields only after `_run_extraction` returns. PLAUSIBLE (reasoned from the code, not run). | The raw-staging claim "what the model was asked" is only half true for failures. Either say so in D4 or recompute from `page_content`/`page_html` when the call fails. || **Fixed.** §5: on a failed call the document stores `page_text = state.page_content`, labelled as the cleaned page the route started from rather than the exact request (reproducible from it plus the stored configuration). |
| 7 | nit | `run_venue` is specified to raise `ValueError` "when no URL override is given and the venue has no `calendar_url`", but `Venue.calendar_url` is `Mapped[str]` (non-null). That branch can only fire on an empty string. | `app/db/models/calendar.py:97`. | A dead branch with a test, or the check silently gets skipped. Drop it or reword to "empty". || **Fixed.** §7: the missing-URL branch is removed, with a note that `venue.calendar_url` is non-null. |
| 8 | nit | Gap sizing and sanity. K2 is three lines and the lesson (`None` stays NULL, `Decimal(str())`) is real, so it qualifies. K3's code is a two-line `if`; the lesson (stage every attempt, even failed) lives in the guard, which is fine, but the "Code" block uses a name (`runtime`) that exists only if the wrapper follows the `Runtime[WorkerContext]` signature in "Known gotchas". K1's snippet uses `initial`, `trigger`, `ctx`, which `run_venue`'s signature in §7 names `venue`, `ctx`, `trigger`, and `initial` is never defined. | §7 `run_venue` signature versus the K1 block. | Pasting the K1 code does not compile as written; contradicts the "speed matters" rule in AGENTS.md. || **Fixed.** K1 now gives the `initial = VenueGraphState(...)` line written just above it, using `run_venue`'s own parameters (`venue`, `ctx`, `trigger`, `calendar_url`, `fetched_on`), so the snippet pastes as is. |

Also checked and fine: the `Status` cycle and the four departures are recorded; Gap placements are where the concept
lives (the `finally`, the `None`-stays-`None` conversion, stage-unconditionally); tests exist for each gap
and are written first; the sync/async decision against `session.py`'s docstring is consistent; the `invoke`
callers (`test_graph.py:70`, `local_test.py:11`) are the only two and both are in the plan; `testpaths`
already includes `agent_worker/tests`, so the new test files will be collected.

**Rejected:** none. Round 1 resolved by the author (Claude Opus 5.5), October 14, 2026: 8 of 8 fixed in the plan; no design decision changed, so no round 2 was run.

## Implementation log

### Round 1 — Claude Sonnet 5.5, October 14, 2026

**Scope.** The working tree against commit `3e8dd1e` (the plan commit on `a4-auditability`); nothing is committed, as
`/build-milestone` requires, so `git diff 3e8dd1e` plus the untracked files is the whole change. Tests were written first
and watched fail (collection errors for the new modules; the column test red before the model change) and then made green.

Files touched:

| Area | Files |
|---|---|
| Schema | `app/db/models/audit.py` (`detail` JSONB), `migrations/versions/2026-10-14_67609c405218_audit_log_detail.py` (new), `app/tests/test_db_metadata.py` |
| Config and services | `app/config.py` (`mongodb_uri`, `mongodb_database`, `log_format`), `apps/api/.env.example`, `docker-compose.yml` (`mongo:8`), `Makefile` (`db-wait`, `db-reset`, `worker`), `.github/workflows/ci.yml` (Mongo service, `MONGODB_TEST_URI`) |
| Logging | `app/log_config.py` (new), `app/tests/test_log_config.py` (new), `agent_worker/nodes.py` (`print` → `structlog`) |
| Worker, new | `agent_worker/audit.py`, `staging.py`, `context.py`, `trace.py`, `main.py` |
| Worker, changed | `agent_worker/state.py` (`run_id`, `extraction_sent_text`), `graph.py` (context schema, `audited(...)`, `ainvoke`-only), `nodes.py` (`extraction_sent_text`, logging, docstrings), `local_test.py` (through `run_venue`) |
| Tests, new | `test_audit_entries.py`, `test_staging.py`, `test_graph_audit.py`, `test_audit_writer.py`, `test_run_venue.py`, `test_audit_queries.py`, `test_staging_mongo.py`; `fakes.py` (`RecordingAudit`, `RecordingStager`); `test_graph.py` (helper only) |
| SQL and docs | `docs/dev/audit-queries.sql` (new), `alpha-build-plan.md` (A4, A6), `arch-initial.md` §7, `data-model-initial.md` §3, `alpha-deployment-plan.md` H3, `notes.md`, `apps/api/AGENTS.md`, `app/db/session.py` docstring, this plan |

**Departures from the plan**, each with its reason.

1. **`audited` lives in `agent_worker/trace.py`, not `audit.py`** (plan step 4, K3's location). `WorkerContext` holds an
   `AuditWriter` (so `context` imports `audit`), and the wrapper needs `WorkerContext` (so `audit` cannot import `context`
   without a cycle). A fourth module keeps the DAG one-way: `state` ← `audit`/`staging` ← `context` ← `trace` ← `graph`.
   The plan body is updated to say so.
2. **K2 was re-marked [written] by Ari at approval** and written complete (`audit.audit_confidence`); its tests are
   written and green. K1 and K3 stay open, and K3's `Check` command now names the test that exists
   (`-k retry_adds_rows`, not `raises_once`).
3. **`functools.wraps` fails loudly, not silently.** The plan said the context would "silently not arrive". Probed against
   langgraph 1.2.11: the call raises `TypeError: inner() missing 1 required positional argument: 'runtime'`. The plan, `trace.py`,
   `AGENTS.md` and `notes.md` say that.
4. **`audited`'s return type is `Callable[..., Awaitable[...]]`**, not the precise signature, because mypy rejects the
   positional-`runtime` form at LangGraph's `add_node` (its `_NodeWithRuntime` protocol wants `runtime` keyword-only).
   The injection is proved by `test_the_context_reaches_the_audited_nodes`.
5. **Entity on reconcile/commit rows is NULL** (the plan's "four venue-level steps" wording was ambiguous). Fetch,
   extract, validate and escalate name the venue; the two stubs name nothing until A5/A6 write per-show rows.
6. **The staging document stores `page_text` on a failed attempt** (A4-PR1-6) except on the poster route, where
   `page_content` is base64 (megabytes, against Mongo's 16 MB limit). Not in the plan; a guard I added.
7. **`finish_run` stamps `finished_at` with Python's `datetime.now(UTC)`**, not `func.now()`: inside the tests' rolled-back
   transaction `now()` equals the transaction start, which would make "finished" indistinguishable from "started".
8. **Two tests not in the plan:** `MongoStager` against a stub collection (no server in the sandbox) and `main`'s
   fail-fast without `MONGODB_URI`.
9. **`structlog` is configured with `cache_logger_on_first_use=False`.** The plan didn't say; caching would make a
   second `configure_logging()` call (tests do this) keep the old chain.
10. **`RUN_ERRORS = (SQLAlchemyError, PyMongoError, OSError)`** is the named tuple for "one venue's run may fail and the
    next still runs" (the plan left the tuple to build time, step 7). A programming error propagates and stops the process.

**`TODO(Ari)` gaps.** Two open, none filled.

| Gap | Where | Lesson | Tests that go green |
|---|---|---|---|
| A | `agent_worker/main.py`, in `run_venue` | The run's id travels in the state; the run is closed in a `finally` | `uv run pytest agent_worker/tests/test_run_venue.py` |
| C | `agent_worker/trace.py`, in `audited` | Stage every extract attempt, failures included; the id goes on the extract row | `uv run pytest agent_worker/tests/test_graph_audit.py -k retry_adds_rows` |

(K2: re-marked [written], done.) Because both placeholders sit on the path every run takes, the red tests in the scaffold are
exactly: `test_graph.py` 16, `test_graph_audit.py` 9, `test_run_venue.py` 4, `test_audit_queries.py` 5 (setup errors),
**34 in all, every one failing with `NotImplementedError: TODO(Ari)`** (two show "regex did not match" because they expect a
different exception and get the placeholder's). Fill **C first**, then A.

**Verification.**

| Check | Result |
|---|---|
| Baseline before A4 (`pytest`) | 566 passed, 14 skipped |
| `ruff check .` | clean |
| `mypy app/` (CI's scope) | clean, 31 files. The new worker modules are mypy-clean too, apart from `act_split.py:117`, an error that predates A4 |
| `make contract-check` | "Generated contract output is current" (`schemas.py` is untouched, so nothing to regenerate) |
| `pytest` in the scaffold state (this tree) | **620 passed, 15 skipped, 29 failed, 5 errors**; the 34 are the gap tests above and nothing else |
| `make check` | stops at the test step for the same reason (lint, typecheck pass first); not green by design while gaps are open |
| Both gaps filled on a scratch copy (the filled lines are the `Code:` blocks; K1's one `ainvoke(...)` call is on a single line instead of wrapped), then restored | **654 passed, 15 skipped, 0 failed** (corrected from 652, A4-CR1-10; 660 after the review fixes); the diff after restoring is exactly the two gap bodies and their `noqa` markers |
| Migration | `upgrade head` / `downgrade -1` / `upgrade head` on `calendar_dev`; the test fixtures also round-trip it |
| Real `psql` | all four saved queries run via `\set run_id …` + `\i docs/dev/audit-queries.sql` against two scripted runs written to `calendar_dev` (rows then deleted); `run_history` read as the story, the retry visible |
| Terminal log output | a run's lines carry `run_id` and `venue_id` (seen in the console renderer) |

The 15 skips: 14 are `test_validation_on_real_pages.py` (gitignored fixtures), and 1 is `test_staging_mongo.py`: **there is no MongoDB or
Docker daemon in this sandbox, so `MongoStager` has never run against a real server in this session.** It is covered by a
stub-collection test and, in CI, by the Mongo service container; Ari should run it locally (`make db-up`, then `uv run pytest
agent_worker/tests/test_staging_mongo.py`). Live extraction (Ollama), the eval harness, and a real `make worker` run could not run
here either (`AGENTS.md`, "Cloud sessions").

**Where to look hardest.**

- `trace.audited`: the `asyncio.to_thread` hop and the ordering (node, then stage, then record). A node that raises inside the
  thread propagates out of `ainvoke` with no audit row for that step; the graph only turns *expected* failures into state (A3), so
  this should only happen on a bug, but the trail then ends one row early.
- `audit.entry_for` against `docs/dev/audit-queries.sql`: the JSON keys in `detail` are an interface between two files, tested
  together only through `test_audit_queries.py`.
- `PostgresAuditWriter`: a session per call is simple, but each `record` is a transaction. Three rows a step is cheap now; worth
  a look if A5/A6 add per-show rows in bulk.
- `main.run_all`'s `RUN_ERRORS`: is `OSError` too broad or too narrow? And `main()` returns 1 when any venue failed, 0 otherwise,
  with no distinction for an escalation (an escalated run is a successful audit of a failed extraction, so exit 0).
- The decision to leave `validate` reading its input from the state and not from Mongo (the arch diagram's arrow), recorded in
  `arch-initial.md` §7.
- `fakes.RecordingAudit.record` returns a count, not an id the writer would return: nothing reads it.

**Review focus asked of the reviewer:** correctness of the audit rows against the plan's test approach §1; whether any red test is
red for a reason other than a gap; whether the plan's Not-doing list is honoured; the docs claims (each was run or is marked).

## Code review

### Round 1 (Claude Opus 5.5, October 14, 2026)

**Scope:** Implementation log round 1: `git diff 3e8dd1e` plus the untracked files on `a4-auditability`. While this
review was running, that exact change was committed as `75bc287` (not by the reviewer; 37 files, the same list the log
names, and the plan file unchanged at that point), so the scope is `3e8dd1e..75bc287`.
**How:** read `AGENTS.md`, `apps/api/AGENTS.md`, the FastAPI style guide's Anti-patterns table, this plan in full, and
every new or changed file in the diff (code, tests, migration, SQL, CI, Makefile, compose, docs). Commands:
- `make check`: lint and typecheck pass, then pytest gives **620 passed, 15 skipped, 29 failed, 5 errors**, matching
  the log (so the JS test step never ran). `make contract-check` on its own: current.
- `pytest -rfE`: the 34 red tests are exactly the ones the log names (`test_graph.py` 16, `test_graph_audit.py` 9,
  `test_run_venue.py` 4, `test_audit_queries.py` 5 setup errors), and every one fails on `NotImplementedError: TODO(Ari)`.
- In a throwaway `git worktree` (removed afterwards), with the venv symlinked, I filled K1 and K3 with their `Code:`
  blocks verbatim and ran `REQUIRE_DB=1 pytest`: **654 passed, 15 skipped, 0 failed**, so no test is red for any reason
  other than a gap. Then `ruff check .` gave **3 errors (RUF100)** (A4-CR1-1). In the same worktree I ran a probe test of
  `PostgresAuditWriter` with a default (`expire_on_commit=True`) session factory (A4-CR1-4).
- `psql` against `calendar_dev` (at head `67609c405218`): `\set run_id 1` then `\i docs/dev/audit-queries.sql` (A4-CR1-8);
  `now()` vs `clock_timestamp()` inside one transaction (A4-CR1-5); `enum_range(NULL::step_type)` is pipeline order, so
  `max(step_type)` in `unfinished_runs` means "furthest step".
- Probes in the repo venv, nothing written: `compiled_graph.invoke(...)` raises `TypeError: No synchronous function
  provided to "fetch"`, and a `functools.wraps` wrapper raises `inner() missing 1 required positional argument:
  'runtime'`. Both CONFIRM the claims in `AGENTS.md`, `notes.md` and `trace.py`. `AsyncMongoClient` construction is
  lazy, and the first `insert_one` against a closed port waits out `serverSelectionTimeoutMS` (default 30 s) before
  raising `ServerSelectionTimeoutError` (A4-CR1-3).

Not run: anything needing Docker, MongoDB or Ollama (`test_staging_mongo.py` skips here; `make worker`;
Verification 4–8). The JS tests didn't run, because `make check` stops at the red Python step; A4 touches no JS.

**Also checked and fine:**
- Rows against Test approach §1: attempt numbering, `model_used`/`confidence` per step, None stays NULL, the `detail`
  keys, and `json.dumps`/`bson.encode` safety.
- The wrapper's order (node in a thread, then stage, then record) and the state it stages (the one returned).
- Append-only writer, committed per call, with the commit-per-call test actually discriminating.
- `RUN_ERRORS` is a named tuple, never `Exception`.
- Contextvars reach the node threads, because `to_thread` copies the context.
- The migration is a single `add_column`/`drop_column` pair, with no enum types.
- The Not-doing list is honoured: `snapshot_key` stays NULL, no per-show rows, validate reads the state, the API has
  no logging, and mypy's CI scope is unchanged.
- No style-guide anti-pattern: nothing sync-blocking inside `async def` (the sync bodies run via `to_thread`), and no
  bare `Exception`.
- Departures 1–10 in the log are reasoned. They're consistent with the code, except where A4-CR1-6 and A4-CR1-12 below say
  otherwise.

**Counts:** 0 blocker, 3 should-fix, 9 nit. **Verdict: proceed after fixes.** The scaffold is sound: the trail's shape,
the wrapper, the stores, and the queries all work once the gaps are filled. The should-fixes are about what happens the
moment Ari fills them (A4-CR1-1), a hand-off A1 left for A4 (A4-CR1-2), and D3's "fail fast" not covering an unreachable Mongo (A4-CR1-3).

| # | Sev | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|
| 1 | should-fix | Filling both gaps exactly as their `Code:` blocks say leaves three `noqa` markers that ruff then flags as unused, so `make check` fails at lint. The `TODO(Ari)` blocks don't tell Ari to delete them. | CONFIRMED (filled worktree): `ruff check .` reports `RUF100 Unused noqa directive` at `agent_worker/main.py:42` (`compiled_graph,  # noqa: F401`), `main.py:97` (`initial = ...  # noqa: F841`) and `agent_worker/trace.py:34` (`from agent_worker import staging  # noqa: F401`). The Implementation log's Verification row admits the author removed them by hand ("exactly the two gap bodies and their `noqa` markers"). | Ari fills a gap, sees the gap's test go green, and then `make check` fails on lint for a reason the gap never mentioned. This works against AGENTS.md's "a gap should cost minutes, not research". Fix: add "and delete the `noqa` on line N" to each gap's `Code:`, or move the marker onto a line the gap replaces. || **Fixed.** Each gap's `Code:` block now ends with the instruction to delete its `# noqa` marker(s) (`main.py`: `compiled_graph` in the imports and `initial =`; `trace.py`: the `staging` import), with the reason. Verified: gaps filled exactly as written, markers deleted, `ruff check .` clean, 660 passed. |
| 2 | should-fix | A1 handed A4 an explicit job that A4 didn't do. `StepType`'s docstring says "A4 should either import one from the other or assert they agree in a test" (about `NodeNames`). A4 then pairs them by hand in six `add_node(NodeNames.X, audited(StepType.X, x_node))` lines. | CONFIRMED: `app/enums.py:116-124`. `grep -rn NodeNames apps/api` finds only `graph.py` and `test_policy.py`, and no test compares the two enums. The pairing is at `agent_worker/graph.py` (the six `add_node` calls). | A seventh node added to one enum and not the other, or a copy-paste pairing such as `audited(StepType.EXTRACT, validate_node)`, writes rows under the wrong `step_type`. That corrupts the trail every saved query reads. The enum test was cheap and was promised. || **Fixed.** `graph.py` now has one table, `NODE_FUNCTIONS`, and registers each node with `audited(StepType(name.value), fn)`: the step is derived from the name, not paired by hand, and a node without a matching `StepType` fails at import. New `test_graph_wiring.py` (failing first: no `NODE_FUNCTIONS`) pins both enums to the six values and each name to its `<name>_node` function, which catches the `EXTRACT -> validate_node` mis-pairing. |
| 3 | should-fix | D3's "fail fast" covers only an *unset* `MONGODB_URI`, not an unreachable server. `main()` never checks the connection, so with Mongo down every venue still does its fetch and a full model call, then waits 30 s for server selection and fails. `run_all` then moves on to the next venue and does the same. | CONFIRMED (driver behaviour): `AsyncMongoClient(...)` returns in 2 ms against a closed port, `insert_one` raises `ServerSelectionTimeoutError` only after `serverSelectionTimeoutMS` (pymongo default `SERVER_SELECTION_TIMEOUT = 30`), and that error is a `PyMongoError`, so it falls in `main.RUN_ERRORS` (`main.py:59`). PLAUSIBLE (the end-to-end cost, which follows from that plus `trace.py` staging after the node). | Forgetting `make db-up` before `make worker` burns one Ollama extraction plus 30 s per venue. Every venue's run then ends "unfinished", with a model call made and never recorded. Fix: `await mongo.admin.command("ping")` in `main()` before `run_all`, returning 2 like the unset case, with a test beside `test_main_refuses_to_start_without_a_mongodb_uri`. || **Fixed.** `main()` builds the client with `serverSelectionTimeoutMS=5000` and pings it before `run_all`, logging and returning 2 on `PyMongoError`. New test `test_main_refuses_to_start_when_mongodb_does_not_answer` (failing first: the code subscripted the stand-in client) also asserts `run_all` is never reached. |
| 4 | nit | `PostgresAuditWriter.start_run` and `.record` return `run.id`/`row.id` *after* `commit()`. That only works with `expire_on_commit=False`, which the class takes on trust from whatever factory it's given. | CONFIRMED (worktree probe): with `async_sessionmaker(bind=db_conn, join_transaction_mode="create_savepoint")`, the default `expire_on_commit=True`, `start_run` raises `sqlalchemy.exc.MissingGreenlet`. `app/db/session.py:41` and all three test factories set it to False, which is why nothing is red. | A5/A6 or a test that builds its own factory gets `MissingGreenlet`, an error that doesn't point at the cause. Fix: `await session.flush()`, read the id, then commit (or say so in the docstring). || **Fixed.** `start_run` and `record` `flush()`, read the id, then `commit()`. New test `test_the_writer_works_with_a_default_session_factory` failed first with `MissingGreenlet` and passes. |
| 5 | nit | Departure 7 stamps `finished_at` with the worker's clock (`datetime.now(UTC)`), while `started_at` and `created_at` come from Postgres's clock (`now()`). | CONFIRMED (psql): inside one transaction `now() = now()` is true and `clock_timestamp() > now()` is true. So `update(...).values(finished_at=func.clock_timestamp())` avoids the rolled-back-transaction problem the departure describes and keeps one clock. `audit.py:222`. | Hosted (H2/H3), a run's duration mixes Railway's clock with Neon's, so a short run can show `finished_at < started_at` under skew. That's small, but it's an audit timestamp. || **Fixed.** `finish_run` uses `func.clock_timestamp()` (database clock, real time), so both timestamps are the database's; the comment says why. The new test `test_finished_at_is_after_started_at...` passes on the old code too (the worker clock is also later than the transaction start), so it pins the property and not the single-clock point, which is in the comment. |
| 6 | nit | K3's scaffold already writes the `staging_id = None` / `if step is StepType.EXTRACT:` guard that the plan's K3 `Code:` block put in the gap. Only the one `await` line is left for Ari, and this isn't listed among the departures. | CONFIRMED: `trace.py:58-59` against the plan's K3 block (`staging_id = None` / `if step is StepType.EXTRACT:` / `staging_id = await ...`). | The gap's own Check names the "likeliest mistake" as guarding with `if state.extraction is not None`, but that guard line is now pre-written, so the lesson "stage unconditionally" is read rather than typed. Either list it as a departure or hand the guard back to the gap. || **Fixed (as a recorded departure).** Left in the scaffold: `staging_id = None` and the `if step is StepType.EXTRACT:` routing line are written, and Ari types the one `await` line. Reasoning: the guard is routing (which step stages), and the lesson (stage regardless of outcome) is still what the typed line is tested on (`-k retry_adds_rows` checks both documents, failed attempt included). Listed as departure 11 in the Implementation log's next round note below. |
| 7 | nit | Stale or wrong text left behind by the build. | CONFIRMED: `context.py:9` and `test_graph_audit.py:14` say `audit.audited` (it's `trace.audited`, departure 1). `test_graph_audit.py:223` says `functools.wraps` "silently loses the context", contradicting departure 3 (it raises `TypeError`). The `fakes.py` A4 section says the fakes are "Imported lazily inside the classes' methods' annotations only", but nothing is imported. `graph.py:26` still says `compiled_graph.invoke(...)'s return value`. `test_run_venue.py::test_the_step_rows_of_a_run_are_the_six_steps_named_in_the_plan` asserts five. The `unfinished_runs` comment says "open = the process died", but an open run may also be one in progress (the plan says so, §10.4). The plan body still says `MONGODB_TEST_URL` (Test approach §3, step 2), while the code and CI use `MONGODB_TEST_URI`, which isn't listed as a departure. | Each one misleads a reader who has never seen the code, which the comment conventions in `AGENTS.md` exist to prevent. The "silently" comment also teaches the wrong failure mode for the one trap the docs highlight. || **Fixed.** `context.py` and `test_graph_audit.py` now say `trace.audited`; the `functools.wraps` comment says `TypeError`; the `fakes.py` note no longer claims lazy imports; `graph.py`'s comment says `ainvoke`; the test is renamed `test_a_passing_run_leaves_the_five_steps_a_pass_visits`; the `unfinished_runs` comment says an open run is in progress or its process died (check the time); the plan body says `MONGODB_TEST_URI` (the rename from `…_URL` is now a stated departure, 12). |
| 8 | nit | The psql recipe printed by `local_test.py` (and in plan Verification 5 / step 10) sets only `run_id` and then `\i`s the whole file. `show_history` needs `:show_id`, so it errors. | CONFIRMED: `\set run_id 1` + `\i docs/dev/audit-queries.sql` on `calendar_dev` gives `psql:docs/dev/audit-queries.sql:69: ERROR: syntax error at or near ":"`. The file header (`audit-queries.sql:6-7`) does say to set both. `local_test.py:77-78`. | The first thing Ari runs after a local test prints an error, on the one query that's expected to be empty anyway. Fix: print `\set show_id 0` too, or point at pasting `run_history` alone. || **Fixed.** `local_test.py` prints `\set show_id 0` as well as `\set run_id`, and says the `\i` runs all four queries; plan Verification 5 says the same. |
| 9 | nit | Several test helpers and fixtures have no explanation, which AGENTS.md asks for ("explain each helper and fixture in plain terms"). | CONFIRMED: no docstring or comment on `factory`/`ctx`/`count` (`test_run_venue.py:43-65`), `factory`/`queries` (`test_audit_queries.py:58-65`), `entry`/`rows` (`test_audit_writer.py:262-274`), `passed_validation` (`test_audit_entries.py:50`), `state_with` (`test_staging.py:97`), and `lines` (`test_log_config.py:209`). | Small, but these files are the learning material for how the trail is tested. The savepoint-mode `factory` in particular is non-obvious, and only `test_audit_writer.py` explains it. || **Fixed.** Docstrings added to `factory`, `ctx`, `count` (`test_run_venue.py`), `factory`, `queries` (`test_audit_queries.py`), `entry`, `rows` (`test_audit_writer.py`), `passed_validation` (`test_audit_entries.py`), `state_with` (`test_staging.py`) and `lines` (`test_log_config.py`). The savepoint-mode `factory` explanation is repeated where it is defined, in plain terms. |
| 10 | nit | The Implementation log's "both gaps filled" result is off by two. | CONFIRMED: the filled worktree gives **654** passed (620 + 34), and the log says "652 passed". | A wrong number in the verification record makes a reader doubt the rest of it. || **Fixed.** The log's number is corrected to 654 (the reviewer's reproduction, which matches: 652 was before two later tests were added); after this round's fixes the filled-gap result is 660 passed, 15 skipped, 0 failed. |
| 11 | nit | `alpha-build-plan.md` A6 still lists "**[fill-in]** Async vs. sync: … Deciding whether to make the nodes async" as open, though A4's D1 decided it (the build plan's own A4 text says the question is A4's, "not A6's"). | CONFIRMED: `alpha-build-plan.md`, A6 list, the last bullet, unchanged by the diff. The A4 paragraph added above it says "settled (D1)". | Whoever plans A6 finds an open [fill-in] for a decision that's already made, and may reopen it. Annotate it as decided in A4 (D1), the way the escalate bullet was. || **Fixed.** `alpha-build-plan.md` A6's async-vs-sync bullet is ticked and annotated as decided and built in A4 (D1). |
| 12 | nit | CI's `mongo` service has no health check, while the test fails (rather than skips) under `CI` after a one-second server selection. | `ci.yml` (the `mongo:` service has only `image`/`ports`; the Postgres service beside it has `--health-cmd`), and `test_staging_mongo.py:35-41`. PLAUSIBLE: services start before the checkout/`uv sync` steps, so a race is unlikely, but nothing guarantees readiness. | A rare CI-only flake on a slow runner. Fix: add `options: --health-cmd "mongosh --quiet --eval 'db.runCommand({ping:1})'" --health-interval 5s ...` to match Postgres. || **Fixed.** The CI `mongo` service has a `--health-cmd` (`mongosh … ping`) with the same interval, timeout and retries as the Postgres service. |

**Rejected:** none. 12 of 12 fixed (A4-CR1-6 as a recorded departure, not a code change; A4-CR1-5's test pins the property but passes before the fix, as its comment says).

**Resolved by the author (Claude Sonnet 5.5), October 14, 2026.** Testable findings (A4-CR1-2, A4-CR1-3, A4-CR1-4) have a failing test written first and watched fail (A4-CR1-5's passes on the old code, noted above). Departures added by this round: **11.** the K3 guard (`staging_id = None`, `if step is StepType.EXTRACT:`) is written in the scaffold, Ari types the `await` line (A4-CR1-6); **12.** the Mongo test variable is `MONGODB_TEST_URI`, not `…_URL` as the plan first said (the repo's name for the connection string is `MONGODB_URI`, A4-PR1-3).

**Test-suite result after the fixes** (`apps/api`): scaffold state (gaps A and C open): **626 passed, 15 skipped, 29 failed, 5 errors**, the same 34 gap tests as before and nothing else (`test_graph.py` 16, `test_graph_audit.py` 9, `test_run_venue.py` 4, `test_audit_queries.py` 5), every one `NotImplementedError: TODO(Ari)`. With both gaps filled exactly as their `Code:` blocks say, `noqa` markers deleted: **660 passed, 15 skipped, 0 failed**, `ruff check .` clean. `mypy app/` clean. Restored to the scaffold afterwards (the diff against the filled copy is only the two gap bodies and their markers).

