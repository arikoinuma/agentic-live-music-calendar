# A4 — auditability

**Status:** Awaiting approval
**Date:** October 14, 2026
**Author model:** Claude Opus 5.5
**Reviewer model:** Claude Sonnet 5.5 (plan review round 1)
**Spec:** `docs/dev/alpha-build-plan.md` §5 A4 (and gap G12, A2.1's E17), §2 point 3; `docs/arch/arch-initial.md` §6
(MongoDB raw staging, `AsyncMongoClient`) and §7 (the audit trail, `parent_run_id`, append-only);
`docs/arch/data-model-initial.md` §3 (`agent_run`, `audit_log`); `docs/references/fastapi-style-guide.md`;
`apps/api/AGENTS.md`

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
| `structlog` configured once: readable locally, JSON otherwise (G12) | [written] | `app/log_config.py`; the worker's `print()`s become log lines |
| An `agent_run` per venue cycle, its id carried in the graph state | [fill-in] | `agent_worker/main.py` (`run_venue`), `state.run_id` — **Gap A** |
| An `audit_log` row from each of the six nodes | [fill-in] | `agent_worker/audit.py` (what each step records), wired in `graph.py` — **Gap B** |
| The MongoDB raw-staging write on extract | [fill-in] | `agent_worker/staging.py`, called from the extract step — **Gap C** |
| Two or three saved SQL queries | [written] | `docs/dev/audit-queries.sql`, executed by a test |
| Persist each extraction's record (A2.1 E17) | [written] | The Mongo staging document *is* that record (D4) |
| The R2 snapshot write | Deferred, on purpose | `audit_log.snapshot_key` stays null (build plan A4) |

### Decisions already made (earlier in this project)

- **Append-only.** A retry adds a row; nothing is updated or deleted (`arch-initial.md` §7,
  `data-model-initial.md` §3, `app/db/models/audit.py`).
- **`agent_run` is the `parent_run_id`.** Every row for one venue's cycle, retries included, points at it.
- **MongoDB holds the raw, pre-validation extraction; Postgres holds canonical data and the audit trail.**
  This is a bronze/silver split. Use `pymongo`'s `AsyncMongoClient`, not Motor, because Motor is deprecated
  (`arch-initial.md` §6).
- **The verdict is not a float, and "no confidence" is no evidence, not zero** (A3, D9;
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
  point of view, wrapped by `audit.audited(step, node)`. The existing node bodies stay plain, synchronous
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
  - `make db-up` starts both containers.
  - CI's Python job gets a `mongo:8` service so the one real-Mongo test runs there.
  - The cloud sandbox has no Docker and no Mongo, so that test skips there, the same way the eval-fixture
    tests do. `cloud-setup.sh` is left alone.
  - A worker run with no `MONGODB_URI` refuses to start (fail fast). An audit trail that silently skips its
    raw record isn't auditable.
  - *Alternative:* point local runs at Atlas now, which drops the "no hosted service" property.
- **D4 — A2.1's E17 extraction record lives in the Mongo staging document, not in Postgres.** That
  document is exactly what E17 lists: the route, the text actually sent, the route's notes, the raw model
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
    "the model read the page" from "the model split titles" by it (plan review #2);
  - validate records the same `model_used` and `confidence = state.confidence`. On the JSON-LD route that
    is a model name with a NULL confidence, which is accurate: the model ran, and gave no confidence that
    validation could weigh (A3, D9);
  - fetch, reconcile (stub), commit (stub) and escalate record neither.
  - Source: build plan A4, "on the agentic steps".
- **Gap B:**
  - `0.8567` is stored as `Decimal("0.857")`;
  - `0.1` is stored as `Decimal("0.100")`, not `Decimal(0.1)`'s binary tail;
  - **a JSON-LD validate row has `confidence` None, not 0** (A3, D9).
- **`detail` per step:**
  - fetch: url, fetched_on, error, characters of text;
  - extract: tier, route, error, staging_id, show count;
  - validate: route, verdict, reasons, error messages, counts of warnings, repairs and exclusions;
  - reconcile/commit: `{"stub": true, "decision": ...}`;
  - escalate: reason, with `outcome = escalated`.
- **Staging document is plain data:** `staging.document_for` on a state whose `extraction_notes` holds a
  `date`, a `StrEnum` and a tuple returns a document that `bson.encode` accepts (plan review #1).
- **JSON-serializable:** `json.dumps(entry.detail)` succeeds for each step, including a validate state
  carrying enum reasons and dated findings. Guards against a `date` or `StrEnum` reaching JSONB unconverted.

### 2. The graph writes the trail (`agent_worker/tests/test_graph_audit.py`, in-memory fakes)

The real compiled graph, with `fakes.ScriptedClient` for the model and two new recording fakes,
`RecordingAudit` and `RecordingStager`, in `tests/fakes.py`. No database and no Mongo.

- A clean JSON-LD page passes on attempt 1. The rows are fetch, extract, validate, reconcile and commit, in
  that order, all attempt 1, all carrying `run_id`.
- A model call that raises once:
  - extract and validate rows for attempts 1 and 2, then reconcile and commit (a retry *adds* rows);
  - **two staging documents, the failed attempt's included** (Gap C), each carrying its `error` and request
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
  - **Gap A:** with the graph patched to raise, `finished_at` is still set and the exception still reaches
    the caller;
  - a venue id that doesn't exist raises before any run is opened.
- **`agent_worker/tests/test_audit_queries.py`** (Postgres): runs a scripted retry-then-pass and a scripted
  escalation through `run_venue` against the test database, then executes **each query in
  `docs/dev/audit-queries.sql`** with `:run_id` / `:show_id` bound. Expected rows come from the scripts (for
  example, "which runs escalated" returns the escalated run and not the other). This makes the build plan's
  "being able to run these is the real test" an actual test. The show-history query is checked against one
  hand-inserted `commit` row, since nothing writes per-show rows until A6.
- **`agent_worker/tests/test_staging_mongo.py`** (real Mongo, `MONGODB_TEST_URL`, default
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
  `runtime: Runtime[WorkerContext]` itself and must **not** use `functools.wraps`. That would copy the inner
  node's signature (no `runtime` parameter), and the context would silently not arrive. A graph test fails
  loudly if it doesn't.
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

The scaffold is complete except for three `TODO(Ari)` blocks. Each fails loudly with
`raise NotImplementedError("TODO(Ari)")`, so its tests are red, not accidentally green. Everything else,
including the tests for the gaps, is written and green where it doesn't depend on a gap. "Go ahead" or
`/build-milestone` produces the scaffold. A gap is filled only when Ari asks for it by name.

### TODO(Ari) gaps

**Fill order:** B, then C, then A. B is pure and unit-tested. C's graph test needs B, because every entry
goes through it. A's DB tests need both. **Until B and C are both filled, no test that runs the graph is
green** (`test_graph.py` included, which is green today): both placeholders sit on the path every run takes
(plan review #4).

- **Gap A — the run's lifecycle, in `agent_worker/main.py` (`run_venue`)** (the `agent_run` bullet).
  - *Lesson:* the run is the parent of every row (`arch-initial.md` §7, `parent_run_id`). Its id travels
    **in the state**, not in a module global, so every node's row points at the run that produced it, and
    two runs could never cross. It is closed in a `finally`, because a run that crashes must still end
    (D8). Otherwise it looks "in progress" forever.
  - *Code:*

    Written just above the gap, so the snippet pastes as is (plan review #8):
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

  - *Check:* `uv run pytest agent_worker/tests/test_run_venue.py`. The likeliest mistake is calling
    `finish_run` after `ainvoke` with no `finally`: the crash test then finds `finished_at` null.
- **Gap B — `audit_confidence` in `agent_worker/audit.py`** (the `audit_log` bullet).
  - *Lesson:* A3 decided that "no confidence" is no evidence, not zero (D9). The JSON-LD route's 1.0 is a
    placeholder, and a page with nothing kept has nothing to be confident about. The audit trail is where
    A8 will measure calibration, so a `None` must stay `NULL`. A 0 would read as "the model was certain it
    was wrong". The conversion also goes through `str`: `Decimal(0.1)` is
    `0.1000000000000000055511151231257827…`, the float's binary value, while `Decimal("0.1")` is the number
    the model said. `quantize` fits it to `Numeric(4, 3)` (`app/db/models/audit.py`).
  - *Code:*

    ```python
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.001"))
    ```

  - *Check:* `uv run pytest agent_worker/tests/test_audit_entries.py -k confidence`. The likeliest mistake is
    `Decimal(value or 0)`: the JSON-LD case then records 0.000.
- **Gap C — stage every extract attempt, in `agent_worker/audit.py` (`audited`)** (the MongoDB bullet).
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
  - *Check:* `uv run pytest agent_worker/tests/test_graph_audit.py -k raises_once`. The test checks each
    document's `attempt` and `error`, not just the count. The likeliest mistake is guarding with
    `if state.extraction is not None`: the failed attempt's document is then missing, and the test counts one
    document instead of two. The second likeliest is staging before the node runs: the documents then carry
    the previous attempt's fields, which the per-document `attempt`/`error` check catches (plan review #5).

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
- `ci.yml`'s Python job gets a `mongo:8` service and `MONGODB_TEST_URL`.

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

### 4. `agent_worker/audit.py` (written, except Gaps B and C)

- `AuditEntry`, a frozen dataclass mirroring the writable columns.
- `entry_for(step, state, staging_id=None)`, with one small builder per step (§1's table of what each
  records).
- `audit_confidence` (Gap B).
- The `AuditWriter` protocol: `start_run`, `record`, `finish_run`.
- `PostgresAuditWriter(session_factory)`. It opens one short session per call and commits it. The comment
  says why: each row is committed as it happens, so a crash later in the run can't roll back the record of
  what led up to it. It only ever `add`s, never updates `audit_log`.
- `audited(step, node)`, the wrapper from D1 (Gap C sits inside it). It runs the sync node with
  `asyncio.to_thread`, stages on extract, records the entry, and returns the state. Its docstring carries the
  `functools.wraps` warning.
- Imports go `state` ← `audit` ← `graph`, so the module DAG stays acyclic. `nodes.py` doesn't import `audit`.

### 5. `agent_worker/staging.py` (written)

- `document_for(state) -> dict` builds the E17 record. Everything except `staged_at` passes through
  `pydantic_core.to_jsonable_python` first, so a `date`, a `StrEnum`, a tuple or a dataclass in the untyped
  `notes` becomes plain JSON before it reaches BSON, which can't encode `datetime.date` (plan review #1).
  `staged_at` is a timezone-aware `datetime`, which BSON stores natively. The record holds:
  - run_id, venue_id, attempt, tier, route;
  - model and request options (`asdict(plan.options)`) and configuration (`asdict(plan.config)`);
  - `sent_text`, `notes`, `raw_extraction` (`model_dump(mode="json")`, or None);
  - on a failed call, `sent_text` is None (`extract_page` raised before returning it), so the document stores
    `page_text = state.page_content` instead, labelled as the cleaned page the route started from, not the
    exact request. The exact request is reproducible from that text plus the stored configuration
    (plan review #6);
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

### 7. `agent_worker/main.py` (written, except Gap A)

- `load_venues(session, venue_id=None)`: venue rows joined to their metro.
- `run_venue(venue, ctx, *, trigger=RunTrigger.MANUAL, calendar_url=None, fetched_on=None)` (Gap A
  inside). The overrides exist for `local_test.py`'s fixture run. (`venue.calendar_url` is non-null in the
  model, so there is no missing-URL branch; plan review #7.)
- `main()`:
  - parse `--venue` and `--trigger`;
  - call `configure_logging()`;
  - fail fast if `MONGODB_URI` is unset (D3);
  - create the `AsyncMongoClient` and the context;
  - loop over the venues **one after another** (`arch-initial.md` §7: one process, every venue);
  - close the Mongo client and dispose of the engine in `finally`.
- `asyncio.run(main())` runs under `if __name__ == "__main__"`.
- One venue's crash is logged and the loop continues to the next venue. The run is already closed by
  Gap A's `finally`. The catch is a named exception tuple, not `Exception`, per `apps/api/AGENTS.md`; the
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
| `apps/api/app/log_config.py` (new) | structlog (G12) |
| `apps/api/agent_worker/audit.py` (new) | Entries, writer, wrapper — Gaps B, C |
| `apps/api/agent_worker/staging.py` (new) | E17 document, Mongo stager |
| `apps/api/agent_worker/context.py` (new) | `WorkerContext` |
| `apps/api/agent_worker/main.py` (new) | Entry point, `run_venue` — Gap A |
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

1. `make check`. Expect red, by design, wherever a run goes through the audit wrapper (plan review #4).
   Gap B sits in every validate entry and Gap C in every extract step, so **all of `test_graph.py`,
   `test_graph_audit.py`, `test_run_venue.py` and `test_audit_queries.py` are red until B and C are both
   filled**, and the last two also need A. Everything else (the direct node tests, the pure entry tests
   other than `-k confidence`, the writer, the stager, logging, the migration) must be green. The
   Implementation log lists the red tests by file with that reason. Filling B alone turns only
   `-k confidence` green; the graph tests need C too. The baseline before A4 was 566 passed and 14 skipped. The Mongo test adds one skip
   here (no Mongo in the sandbox).
2. Gaps verified filled on a scratch copy (a throwaway `git worktree`, removed afterwards): with all three
   filled, the whole suite is green, and the result is recorded in the Implementation log. This is the
   pattern A3 used.
3. `alembic upgrade head` / `downgrade -1` / `upgrade head` against `calendar_dev`, and the new column
   seen in `\d audit_log`.

**Locally (Ari, after filling the gaps; needs Docker and Ollama):**

4. `make db-reset && make seed`, then `make worker VENUE=1`. Expect console log lines carrying
   `run_id=…`, and an exit after one venue.
5. `make db-shell`, `\set run_id <id>`, then the `run_history` query. Expect fetch, extract (one per
   attempt), validate (one per attempt), reconcile and commit stubs, or escalate. Each extract row's
   `staging_id` is set.
6. `docker compose exec mongo mongosh calendar --eval 'db.extraction_staging.findOne()'`. Expect the
   document with `sent_text`, `notes`, `raw_extraction` and the request configuration.
7. `LOG_FORMAT=json make worker VENUE=1 2>&1 | head -3`. Expect one JSON object per line.
8. `uv run python -m agent_worker.local_test`. Same trail, against the fixture.

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
| 1 | should-fix | The Mongo test and document design assume a `date` can be stored, but BSON can't encode `datetime.date`. §"Real stores" says "a `date` in the document round-trips"; §5 builds the document from `asdict(plan.options)`, `asdict(plan.config)`, `notes`, and `model_dump(mode="json")`. Only the last is JSON-safe by construction. | CONFIRMED: `bson.encode({"d": datetime.date.today()})` raises `InvalidDocument: cannot encode object: datetime.date(...)`. `PageExtractionResult.notes` is `dict[str, Any]` (extraction.py:117) and `state.extraction_notes` is likewise untyped. The plan checks JSON-safety of notes only via `json.dumps`, which does not prove BSON-safety (a tuple, set or enum passes some and fails others). | As written, the `test_staging_mongo` date test fails by design, or `document_for` raises `InvalidDocument` in production on the first note holding a date, which Gap C then propagates as a halted run (the plan's own rule). Stating "a date round-trips" also contradicts the document being JSON-mode. || **Fixed.** §5: `document_for` passes everything but `staged_at` through `pydantic_core.to_jsonable_python`, so a `date`/`StrEnum`/tuple in `notes` becomes plain JSON before BSON sees it; `staged_at` stays a `datetime` (BSON-native). Test approach §1 adds a `bson.encode` check on a state whose notes hold a date, an enum and a tuple; §3's Mongo test now expects the date back as its ISO string. |
| 2 | should-fix | `model_used` on extract/validate rows is "`state.last_plan.options.model`" unconditionally. On the JSON-LD route (and the image route's non-page path) the plan still carries the page model's name, but no model ran. The plan also says validate "records the same `model_used`" while "a JSON-LD validate row has confidence None". So the same row would say "a model was used" and "no model judged this". | `nodes.py` `_route_for` returns `"jsonld"` when `plan.config.route == "auto"` and the page has usable events; `PIPELINE_OPTIONS.model` is always set (extraction.py ~line 95). `policy.AttemptPlan.larger_model_used` exists to stop exactly this kind of misreport (policy.py:94-103, D5). Build plan A4: `model_used` "on the agentic steps". PLAUSIBLE for the JSON-LD title-split step, which does call a model for act splitting (extraction.py:315 region), so the right rule needs a decision, not a guess. | The audit trail, which A8 uses to measure calibration per model, would attribute every JSON-LD page to the LLM. Tests in §1 would pin the wrong behavior, because the expected values are "last_plan.options.model" on every attempt. || **Fixed (clarified, rule kept).** The model *does* run on the JSON-LD route: the act splitter and the status question both go through `llm.request_kwargs(options)` with the same `options.model` (`act_split.py:102`, `status_check.py:76`, `llm.py:61`), so `model_used` is accurate there. What differs is the judgement, so the extract and validate rows both carry `detail.route`, and the JSON-LD validate row's model name with NULL confidence is stated as intended (Test approach §1, agentic fields). |
| 3 | should-fix | Env var name conflict. The plan introduces `MONGODB_URL` (D3, §2, `Settings.mongodb_url`), but the repo already names it `MONGODB_URI` in `apps/api/.env.example:71` and in `env-setup.md:220` (Railway variables). H2/H3 and the already-provisioned Railway service were written against that name. | CONFIRMED by grep: `MONGODB_URI` in `.env.example` and `env-setup.md`; `MONGODB_URL` appears only in this plan; `app/config.py` has no Mongo setting yet. | Two names for one thing: the hosted service's configured variable would not be read by `Settings` (pydantic-settings matches the field name), and the worker would refuse to start in Railway with the "fail fast" message. || **Fixed.** Renamed to `MONGODB_URI` / `Settings.mongodb_uri` throughout the plan (D3, D6's fail-fast, §2, §7), matching `.env.example` and `env-setup.md`. |
| 4 | should-fix | The scaffold turns existing green tests red, which the plan understates. Gap B's placeholder (`audit_confidence` in `entry_for`) is called for every validate row, and Gap C's placeholder sits in the wrapper every extract goes through, so all of `test_graph.py`'s 19 tests (which the plan converts to `ainvoke` with `RecordingAudit`) plus every graph audit test go red until the gaps are filled. Verification step 1 says only "the Gap-tests, listed by name". | `graph.py` wiring in §6 wraps all six nodes; `test_graph.py:70` runs the whole graph in every test. Gap B's check names only `-k confidence` and Gap C's names `-k raises_once`. | The author's `make check` baseline (566 green) stops being a meaningful signal of "scaffold broke nothing", and Ari filling Gap B alone sees 20+ tests still red because C blocks extract. The fill order (B, C, A) is stated, but not that nothing in the graph is green in between. || **Fixed.** Verification 1 now says every graph-running test (`test_graph.py` included) is red until B *and* C are filled, lists which files, and says what must stay green. The fill-order note under TODO(Ari) gaps says the same. |
| 5 | nit | Gap C's snippet calls `staging.document_for(state)`, but which `state` is not said. It must be the state returned by the (threaded) node, because the document needs `extraction_sent_text`, `extract_error` and `extraction_notes`, which only exist after the node ran. Placed before `to_thread` it would stage the previous attempt. | The snippet in the Gap C block, and the §4 description ("runs the sync node with `asyncio.to_thread`, stages on extract, records the entry"). | A wrong-order paste stages stale data and the failure-attempt test may still count two documents, so the test would not catch it unless it checks each document's `error`/attempt (the plan's §2 does say each carries its `error`; make the Check say that is what catches this). || **Fixed.** Gap C says `state` is the one the node returned from `asyncio.to_thread`, written just above the gap, and its Check now asserts each document's `attempt` and `error` (which catches staging before the node runs). |
| 6 | nit | A failed attempt's staging document can't carry `sent_text`. `extract_page` raises before returning `PageExtractionResult`, so `extraction_sent_text` stays None on failure. The plan says the failed document is "exactly the record a person debugging an escalation needs" and lists request configuration and error, but a debugger most wants the text that was sent. | extraction.py:244/315 return `sent_text` only on success; `nodes.py` `extract_node` sets state fields only after `_run_extraction` returns. PLAUSIBLE (reasoned from the code, not run). | The raw-staging claim "what the model was asked" is only half true for failures. Either say so in D4 or recompute from `page_content`/`page_html` when the call fails. || **Fixed.** §5: on a failed call the document stores `page_text = state.page_content`, labelled as the cleaned page the route started from rather than the exact request (reproducible from it plus the stored configuration). |
| 7 | nit | `run_venue` is specified to raise `ValueError` "when no URL override is given and the venue has no `calendar_url`", but `Venue.calendar_url` is `Mapped[str]` (non-null). That branch can only fire on an empty string. | `app/db/models/calendar.py:97`. | A dead branch with a test, or the check silently gets skipped. Drop it or reword to "empty". || **Fixed.** §7: the missing-URL branch is removed, with a note that `venue.calendar_url` is non-null. |
| 8 | nit | Gap sizing and sanity. Gap B is three lines and the lesson (`None` stays NULL, `Decimal(str())`) is real, so it qualifies. Gap C's code is a two-line `if`; the lesson (stage every attempt, even failed) lives in the guard, which is fine, but the "Code" block uses a name (`runtime`) that exists only if the wrapper follows the `Runtime[WorkerContext]` signature in "Known gotchas". Gap A's snippet uses `initial`, `trigger`, `ctx`, which `run_venue`'s signature in §7 names `venue`, `ctx`, `trigger`, and `initial` is never defined. | §7 `run_venue` signature versus the Gap A block. | Pasting the Gap A code does not compile as written; contradicts the "speed matters" rule in AGENTS.md. || **Fixed.** Gap A now gives the `initial = VenueGraphState(...)` line written just above it, using `run_venue`'s own parameters (`venue`, `ctx`, `trigger`, `calendar_url`, `fetched_on`), so the snippet pastes as is. |

Also checked and fine: the `Status` cycle and the four departures are recorded; Gap placements are where the concept
lives (the `finally`, the `None`-stays-`None` conversion, stage-unconditionally); tests exist for each gap
and are written first; the sync/async decision against `session.py`'s docstring is consistent; the `invoke`
callers (`test_graph.py:70`, `local_test.py:11`) are the only two and both are in the plan; `testpaths`
already includes `agent_worker/tests`, so the new test files will be collected.

**Rejected:** none. Round 1 resolved by the author (Claude Opus 5.5), October 14, 2026: 8 of 8 fixed in the plan; no design decision changed, so no round 2 was run.

## Implementation log

## Code review
