# A6 — commit

**Status:** Plan review
**Date:** October 19, 2026 (plan)
**Author model:** Claude Sonnet 5.5 (plan, October 19, 2026)
**Reviewer model:** — (plan review round 1 pending)
**Spec:** `docs/dev/alpha-build-plan.md` §5 A6 (and §2 points 2 and 3); `docs/arch/arch-initial.md` §7 ("Reconcile (insert /
update / delete / no-op)", "Audit trail extensions", "Revert"); `docs/arch/requirements-initial.md` ("Agent
Reconciliation", "Agent Artist Creation & Matching", "Show"); `docs/arch/data-model-initial.md` §2 (`show`, `show_artist`,
`artist`) and §3 (`audit_log`, `previous_value` / `new_value`); `docs/references/fastapi-style-guide.md`;
`apps/api/AGENTS.md`

**Designations.** Inside this plan the decisions are `D1`–`D3`, the fill-in key points `K1`–`K2` and the mutation
checks `M1`–`M6`; elsewhere they are written `A6-D1`, `A6-K1`, `A6-M1` and so on (`docs/dev/conventions.md`). Code, tests
and code comments write the scoped form even while implementing this plan: `A6-D2` in `calendar_writer.py`, never `D2`
(`make designation-check` fails a bare one). Review items are `A6-PR<round>-<n>` (plan review) and `A6-CR<round>-<n>`
(code review). Other plans' IDs carry their scope (`A5-D4`, `A4-D1`, `A3-D9`, `A2.1-D12`, `v0.1-G10`).

**Branch.** `AGENTS.md` names the branch `a6-commit`. This session was assigned `claude/nifty-sagan-gan2i1`, so the plan,
and later the code, land there. Rename on merge if you want the milestone name.

## Context

A5 made the worker decide. For every venue run it produces a `ReconcilePlan` (per show: insert, update, no-op, remove or
skip, with the fields that changed and the resulting lineup; the artists to create; the removals the guard withheld),
and `commit_node` is still the stub from Phase 6: it logs the plan's counts and returns. **Nothing has ever been written
to `show`, `show_artist` or `artist` by the worker.** A6 makes `commit_node` execute the plan, which closes the loop the
whole alpha is built around (`alpha-build-plan.md` §2 point 2: "writes real `show` and `artist` rows to local Postgres,
insert, update and soft-delete all exercised across two consecutive runs") and gives A5 its first real before-and-after.

What A6 does, per venue run:

1. **For each insert / update / remove decision,** write it to Postgres in **one transaction per show**: the `show` row,
   its `show_artist` lineup, any `artist` row that show is the first to need, and the `audit_log` row that records it with
   `previous_value` / `new_value` snapshots (those are what a future revert restores).
2. **Convert prices at the write** (`Decimal(str(value))` quantized to `Numeric(10, 2)`): A5 already defined the
   conversion once (`reconcile.to_price`) so that comparison and storage agree; A6 imports it.
3. **Write a summary `commit` row** for the run: what was written, what failed, what the guard withheld. It replaces the
   `{"stub": true}` row A4 left behind.

Two things make this milestone different from A5, and most of the design below exists for them. First, **a write is the
first thing the worker does that can be wrong in a way that outlives the run**: a bad snapshot can't be fixed by
re-running, and a half-applied show (the row inserted but the lineup missing, or the artist created and the show not) is
a corrupt calendar. So the unit of work is one show, atomically, with its audit row inside the same transaction. Second,
**the audit row for a write can't come from `AuditWriter.record`** (which opens its own session and commits on its own),
because then a rolled-back write could leave an audit row for something that never happened, or a committed write could
lose its record. So per-show rows are written by the same session that makes the change.

### What A6 delivers

| Item (build plan A6) | Marking | Where it lands |
|---|---|---|
| `commit_node` executing reconcile's decision: `show`, `show_artist`, new `artist` rows, one transaction per decision, audit row with `previous_value` / `new_value` | [fill-in] | `calendar_writer.py` `PostgresCalendarWriter.write_show` — **K1**; the loop that survives a failed show, `write_plan` — **K2** |
| Convert extracted prices at the write | [written] | `commit.insert_values` (uses `reconcile.to_price`) |
| `escalate_node` writing a real `audit_log` row | [x] done in A4-D5 | — |
| Async vs. sync nodes | [x] decided and built in A4-D1 | The writer is awaited in `trace.audited`, like the reader (see "The wiring") |
| (From A5's list of what A6 would do) per-show audit rows with snapshots, `show.original_url` | [written] | `audit.py` builders, `commit.insert_values` |
| (From A5's list) `event` rows | **not done**, see "Departures" 1 | — |
| (A5 deferred) replace `test_reconcile_shows`'s `apply_plan` simulator with a real round trip | [written] | `tests/test_commit_db.py` (parity and idempotency against real Postgres) |
| `unfinished_runs` / `show_history` saved queries meet real commit rows | [written] | `docs/dev/audit-queries.sql`, `test_audit_queries.py` |

### Decisions already made (earlier in this project)

- **One transaction per decision, audit row carrying `previous_value` / `new_value`** (build plan A6, first bullet).
- **Reconcile decides, commit writes** (`arch-initial.md` §7). Commit adds no judgement: it executes the plan it is given.
  A bad decision and a failed write stay different failures in the audit trail.
- **Async database work is awaited in the `trace.audited` wrapper; node bodies are plain functions run in a thread**
  (`A4-D1`, restated in `A5`: "A5/A6 `await` their database work in the wrapper's context; they don't reopen this").
- **`audit_log` is append-only** and `entity_id` is deliberately not a foreign key (`data-model-initial.md` §3).
  `previous_value` / `new_value` are what a revert restores; evidence goes in `detail`, never in them (`A4-D2`).
- **Soft delete only.** A removed show is `status = 'removed'`, never deleted; a cancelled or postponed listing is stored
  as `removed` with the reason in the audit trail (`A5-D6`); a returning show is the same row, back to `active` (`A5-D7`).
- **A field the listing leaves blank never erases a stored value; the three admission fields update as one unit**
  (`A5-D4`, `A5-D5`). Reconcile already encodes both in `ShowDecision.changes`; commit applies `changes` as given and
  does not re-derive them.
- **A new artist is name-only** (`requirements-initial.md`, "Agent Artist Creation & Matching"), created once per
  distinct name however many shows name it (`ArtistResolution.name` is the spelling first seen).
- **Prices:** extraction carries `float | None`, the columns are `Numeric(10, 2)`; convert with `Decimal(str(value))`
  then quantize (build plan A6; `reconcile.to_price` is that conversion).
- **`needs_review` lives in the audit row only; no review queue exists** (`A5`, "Settled details"). Commit writes a
  flagged decision like any other and carries the flag into its audit row.

### What the code already gives commit

- `state.reconcile_plan: ReconcilePlan | None` (set by reconcile; the graph reaches commit only through reconcile).
  Each `ShowDecision` has `action`, `date`, `start_time`, `reason`, `listing`, `stored_id`, `changes`
  (`{field: (old, new)}`, prices already `Decimal`), `lineup: tuple[LineupEntry, ...]` and `needs_review`; `Action.outcome`
  already maps to `AuditOutcome` ("for A6's per-show rows"). `plan.artists` are the resolutions some decision uses.
- `state.venue_id`, `state.calendar_url` (what `show.original_url` holds), `state.run_id`, and `audit.entry_for` /
  `audit.audit_confidence` with its conventions.
- `Show` is a `TimestampMixin` model with `eager_defaults=True`, added in A1 *for this milestone* ("A6 snapshots a row right
  after updating it (for `audit_log.new_value`), which is exactly that read": `app/db/base.py`).
- `AuditLog.previous_value` / `new_value` exist and are JSONB; `AuditEntry` doesn't carry them yet ("absent on purpose until
  A6": `audit.py`).
- `to_jsonable_python` turns `Decimal` into `"20.00"`, `time` into `"20:00:00"` and `date` into `"2026-10-20"` (checked
  October 19, 2026), which is the form a snapshot needs to be restorable without loss.
- The test machinery: `db_conn` / savepoint-mode session factories (`app/testing/db.py`), `PostgresCalendarReader`,
  `tests/reconcile_support.py`'s `apply_plan` simulator, `fakes.RecordingAudit` / `FakeReader`.

## Decisions for Ari

**How to read this section.** Each decision is **one question** with two options. Each opens with a real-life scenario,
then names the fields and functions involved, then says what each option costs. The plan below is written to the
recommended option (A). **★ = it changes how the calendar or the audit trail behaves** and is yours to decide;
**technical** = it changes how the code is built, and I'd settle it myself, but a different answer changes what gets built.

**Words used here.** *A decision* is one `ShowDecision` in the plan. *A write* is an insert, update or remove that goes
to Postgres. *A snapshot* is a copy of a show as a JSON object, stored in `audit_log.previous_value` / `new_value`.

| # | Question | Kind | Recommendation | Status |
|---|---|---|---|---|
| D1 | Does a show that didn't change get an audit row? | ★ | A: no, count it in the summary | Open |
| D2 | If one show's write fails, do the other shows still get written? | ★ | A: yes, past a data error; stop on a connection error | Open |
| D3 | What does a snapshot hold? | technical | A: the whole `show` row (minus timestamps) plus its lineup | Open |

---

### D1 — Does a show that didn't change get an audit row? ★

- **Scenario.** The White Squirrel page lists 12 shows and nothing has changed since last night. Reconcile decided 12
  no-ops. Should the audit trail say so 12 times?
- **Option A — no. Per-show rows record writes only.** Insert, update and remove each get a row (and each new artist);
  the run's summary `commit` row says `no_op: 12`. `show_history` ("what changed about this show, and when") then
  shows only changes, and the audit table grows with change, not with the number of shows times the number of nights.
  Technically: `commit.build_ops` produces no operation for `no_op` or `skip`.
- **Option B — yes. A `no_op` row for every unchanged show,** `outcome = 'no_op'`, no snapshots. A show's history then
  proves "we looked at it on Tuesday and it was fine". Four venues of about 30 shows is about 120 rows a night, 44,000 a
  year, and every "what changed" query has to filter them out. The data model lists `no_op` as an outcome "populated on
  `reconcile`/`commit` rows", which B would use; A5-D11 chose a summary row for reconcile and left the per-show rows here.
- **Cost of A:** you can't tell from the table whether a show was *checked* on a given night, only that it didn't
  change. The summary row carries the count, and the next question this raises (was this venue even processed on Tuesday?)
  is answered by the venue-level rows that already exist (`run_history`).

### D2 — If one show's write fails, do the other shows still get written? ★

- **Scenario.** A venue's page lists a show with a price of `$99999999999` (a typo on their site). Validation lets it
  through (it is a positive number). Postgres refuses it (`Numeric(10, 2)` overflows). The plan has 11 other shows.
- **Option A — carry on.** That one show's transaction rolls back (nothing of it is written, including its artists),
  its failure is recorded in its own audit row and in the summary, and the other 11 are written. The worker exits
  non-zero afterwards, so a person sees it. This applies to **data errors for one show** (`IntegrityError`, `DataError`,
  or the show having vanished); a lost connection or a bug in our code still stops the run, because those are not about
  one show. Technically: `calendar_writer.DECISION_ERRORS` (**K2**).
- **Option B — stop at the first failure.** The shows already written stay written (each was its own transaction); the rest
  wait for tomorrow. Simpler (no `try`), and a failure can't be missed. But one poisoned listing blocks every show after
  it on that venue's page, every night, until a person fixes it.
- **Cost of A:** a deterministic bug in reconcile that produces a bad decision fails that one show quietly every night
  (loudly in the logs and the exit code, but the calendar looks mostly fine). The `failed_commits` saved query is how you
  find it. **Cost of B:** the calendar for that venue goes stale behind one bad row.
- Either way the next run recomputes the plan from the stored calendar, so a half-applied run **converges**: the shows
  that were written are now no-ops and the rest are decided again (the idempotency test is what proves it).

### D3 — What does a snapshot hold? (technical)

- **Scenario.** Months from now a person wants to revert a show to how it was on October 22. Which columns come back?
- **Option A — the whole `show` row (every column except `created_at` / `updated_at`) plus the lineup,** read from the
  database inside the transaction. A revert can restore any column, and restoring only the columns that differ between
  `previous_value` and `new_value` leaves a human's later edits to other columns alone. The lineup (`show_artist`) is
  part of the snapshot because an update that changes the lineup can't be reverted without it.
  Technically: `commit.snapshot_of`, keys listed under "Design".
- **Option B — only the columns the agent writes** (start and end time, prices, free flag, image, original URL, status),
  plus the lineup. Smaller rows, and a snapshot that can't mention a column the agent never touches.
- **Cost of A:** a larger JSONB per row (about 20 keys), including columns that are always `null` today
  (`age_restriction`, `setting`, ...). **Cost of B:** the day a human edit exists, "what did this row look like" needs a
  second source for the columns B left out, and a snapshot that isn't the row isn't what `data-model-initial.md` §3
  says it is ("snapshot of the affected row before this action").
- The snapshots are read **from the database** inside the transaction, not copied from the plan (reconcile's `StoredShow`
  lacks most columns, and may be seconds stale), so `previous_value` is the row as it really was.

---

### Settled details (veto only)

These follow from your requirements or from the decisions above. I'm listing them so nothing is hidden; object to any.

- **Removals are applied last.** Inserts and updates first (in calendar order), then removals. If a run dies half way, or
  one write fails, a time change (remove 8 PM, insert 9 PM) is left as a duplicate rather than a gap, which is the safe
  direction (`A5-D1`: "a stale show up too long is the safe direction"). The audit rows are ordered by id anyway, so
  reading them is unaffected.
- **A new artist's audit row is written in the same transaction as the show that first needs it,** `entity_type = artist`,
  `outcome = inserted`, `new_value = {id, name}`. The artist is created by the first decision that needs it and reused by
  the later ones; if that first decision rolls back, the artist rolls back with it and the next decision that needs the
  artist creates it again (**K2**).
- **A lineup is replaced wholesale when reconcile says it changed** (`"lineup" in decision.changes`): the show's
  `show_artist` rows are deleted and re-inserted from the decision's lineup. When the lineup didn't change they are not
  touched. `show_artist` has no timestamps and a pure-join key, so a diff buys nothing.
- **`show.updated_at` is touched on every update,** including one that changes only the lineup (an ORM update that
  changes no `show` column would otherwise leave it stale).
- **`original_url` is the run's `calendar_url`,** written on insert and (when it differs) on update, as `A5-D4` has it.
  `local_test.py` passes a fixture *path* as the URL (`A5` noted this: "A6 should know"), so rows it writes carry that path.
  They are dev data in a local database that `make db-reset` clears, and the read API doesn't expose the column, so the
  write is not special-cased.
- **A cancelled or postponed removal is an ordinary `removed` write** whose audit row carries `reconcile_reason =
  "cancelled"` (`A5-D6`).
- **Withheld removals (`A5-D10`) are never written;** the summary row repeats their count so one query shows both.
- **The failure rows are written outside the rolled-back transaction,** through `AuditWriter.record` (its own session),
  because the transaction that would have held them is gone.
- **`detail` keys on commit rows avoid `reason`:** `run_history` labels `detail ->> 'reason'` "escalation_reason", so a
  commit row calls the reconcile reason `reconcile_reason`.
- **Exceptions that stop the run are not caught.** `OperationalError`, `InterfaceError` and every non-database exception
  propagate; `main.run_all` already treats `SQLAlchemyError` as "this venue failed, carry on to the next one".

## Design

### The pure core: `agent_worker/commit.py`

No I/O, no clock, no model, and **no import of `state.py` or `audit.py`** (the state imports these types for its new
fields, and `audit.py` imports the state; the dependency runs the other way, as in A5). Everything is a function of its
arguments, so every rule is tested with hand-built plans.

```
ShowOp         decision: ShowDecision; values: dict[str, Any]   # column -> value to set (insert: all; update: changed only)
               lineup: tuple[LineupEntry, ...] | None            # None = leave show_artist untouched
               new_artist_names: dict[str, str]                  # key -> name, for artists with no id yet in this lineup
               (properties: action, stored_id, outcome -> AuditOutcome, reconcile_reason, needs_review)
ShowFailure    action, date, time, stored_id, error              # one failed show
CommitResult   written: dict[str, int]                           # "inserted" / "updated" / "removed" -> how many
               artists_created: int; failures: tuple[ShowFailure, ...]
SNAPSHOT_EXCLUDED = {"created_at", "updated_at"}                 # D3
```

| Function | Job | Marking |
|---|---|---|
| `build_ops(plan, venue_id, original_url)` | One `ShowOp` per insert / update / remove decision; none for `no_op` or `skip` (**A6-D1**); withheld removals never; inserts and updates first in calendar order, then removals | [written] |
| `insert_values(listing, venue_id, original_url)` | The columns of a new show: `venue_id`, `date`, `start_time` (the listing's `time`), `end_time`, the two prices through `reconcile.to_price`, `free_admission`, `image_url`, `original_url`, `status = active` | [written] |
| `changed_values(changes)` | The columns of an update: the new side of each `(old, new)` pair in `changes`, minus `lineup`; `status` arrives as `ShowStatus` | [written] |
| `snapshot_of(columns, lineup)` | A show as restorable JSON: `Decimal` as its decimal string, times and dates ISO, enums by value, no timestamps (**A6-D3**), `lineup` a list of `{artist_id, start_time, sequence_number}` in performance order | [written] |
| `summary_counts(plan, result)` | The summary row's `counts` (`inserted`, `updated`, `removed`, from the result; `no_op`, `skip`, from the plan) | [written] |

The snapshot's keys (so the audit trail's readers and a future revert agree): `id`, `venue_id`, `event_id`, `date`,
`start_time`, `end_time`, `age_restriction`, `serves_alcohol`, `setting`, `seating`, `admission_advance`, `admission_day`,
`free_admission`, `image_url`, `original_url`, `status`, `lineup`. It is built from the model's mapped columns rather than a
hand-written list, so a column added by a later migration appears in snapshots without anyone remembering to, and a test
pins the current set so the change is visible.

**Import order** (a DAG, `apps/api/AGENTS.md`): `reconcile`, `artist_match` ← `commit` ← `state` ← `audit` ←
`calendar_writer` ← `context` ← `trace` ← `graph`. A test imports `agent_worker.commit` in a fresh interpreter and asserts
neither `agent_worker.state` nor `agent_worker.audit` is in `sys.modules` (the A5 test's pattern).

### The writer: `agent_worker/calendar_writer.py`

Mirrors `calendar_reader.py`: a protocol the graph depends on, a Postgres implementation, and the loop that drives it.

```python
class CalendarWriter(Protocol):
    async def write_show(self, op: ShowOp, artist_ids: Mapping[str, int], *, venue_id: int,
                         run_id: int | None, attempt_number: int) -> ShowWritten: ...

ShowWritten(show_id: int, outcome: AuditOutcome, created_artists: dict[str, int])   # key -> new artist id

DECISION_ERRORS = (IntegrityError, DataError, ShowGone)    # failures about ONE show (A6-D2); a named tuple, never `Exception`
```

**`PostgresCalendarWriter(session_factory).write_show`** is one transaction, in this order (the order is the lesson, **K1**):

```
async with session.begin():                                     # nothing below is visible until this block exits cleanly
    created   = create the artists this show is first to need   # flush -> ids; skips keys already in `artist_ids`
    previous  = snapshot the stored row                         # BEFORE anything changes; None for an insert
    show_id   = apply the op                                    # insert / update columns, replace the lineup if told to, flush
    new       = snapshot the row again                          # AFTER the flush, read back from the database
    add audit rows: one per created artist, then the show's     # the SAME session, so they commit or roll back with the write
```

- `_snapshot` runs a `SELECT ... populate_existing` rather than reading the session's identity map, so it reports what the
  database holds (the quantized price, the `updated_at` that `eager_defaults` brought back), and it builds a plain `dict`
  immediately, so a later change to the ORM object can't alter a snapshot already taken.
- An update or remove loads its row with `with_for_update=True` (a row lock for the transaction) and raises `ShowGone`
  if the row isn't there, instead of failing later with an `AttributeError` that would look like a bug.
- Nothing here calls `commit()` itself: leaving the `begin()` block commits, an exception rolls back.

**`write_plan(ops, writer, audit, *, venue_id, run_id, attempt_number) -> CommitResult`** is the loop: for each op, call
`write_show`; on a `DECISION_ERRORS` failure, record that show's failure row through `audit.record` and carry on; after a
show has been written, remember the artists it created for the shows after it (**K2**). Anything else propagates.

### Audit rows: `agent_worker/audit.py` (extended)

`AuditEntry` gains `previous_value` and `new_value` (JSON-safe dicts or `None`). A module-level `audit_row(entry) ->
AuditLog` maps an entry onto the ORM row; both `PostgresAuditWriter.record` and the calendar writer use it, so there is
one place that knows the columns. New pure builders, tested without a database:

| Row | `step_type` | `entity` | `outcome` | `previous_value` / `new_value` | `detail` |
|---|---|---|---|---|---|
| A show written | `commit` | `show`, the show's id | `inserted` / `updated` / `removed` | the two snapshots (previous is `null` for an insert) | `action`, `reconcile_reason`, `changed` (the column names, plus `"lineup"`), `needs_review` |
| An artist created | `commit` | `artist`, the new id | `inserted` | `null` / `{id, name}` | `name`, `key` |
| A show that failed | `commit` | `show`, the stored id (`null` for an insert) | none | none | `action`, `reconcile_reason`, `error` (the exception type and first line of the database's message; never the SQL with its parameters) |
| The run's summary | `commit` | `venue` | none | none | `counts`, `artists_created`, `failed` (a list of `{action, date, time, stored_id, error}`), `withheld` |

`COMMIT` joins `_VENUE_LEVEL` (the summary row names the venue, as reconcile's does). `attempt_number` for every commit row is
the existing rule (the last attempt, floored at 1); the private helper becomes public as `audit.attempt_number`, because
`trace` and the builders both need it. The summary `counts` shape is `{inserted, updated, removed, no_op, skip}` plus the
failures, so its shape doesn't depend on the run (as reconcile's does).

### The wiring

- `context.py`: `WorkerContext` gains `writer: CalendarWriter`.
- `state.py`: `commit_ops: tuple[ShowOp, ...]` (set by the node) and `commit_result: CommitResult | None` (set by the wrapper).
- `nodes.commit_node`: a plain function, as before. It turns `state.reconcile_plan` into `state.commit_ops` with
  `commit.build_ops`, and logs. It touches no database (A4-D1).
- `trace.audited`: for `StepType.COMMIT`, after the thread returns and before the summary row, `await write_plan(...)` with
  `runtime.context.writer` and `runtime.context.audit`, and put the result on the state. The per-show rows are written inside
  `write_plan` (each in its own transaction), so the audit table reads, in id order: the earlier steps, then each commit row,
  then the commit summary. **A connection failure raises out of `write_plan`, so no summary row is written**, and the run
  is closed by `run_venue`'s `finally`.
- `main.run_all`: after a venue's run, `if state.commit_result and state.commit_result.failures`, count the venue as failed and
  log it, so the process exits 1 (`A6-D2`). `main` and `local_test` build `PostgresCalendarWriter(SessionFactory)`.
- `audit-queries.sql`: `unfinished_runs` currently treats *any* `commit` row as "the run finished". With per-show rows, a run that
  crashed after writing one show has a `commit` row but no summary. The query changes to count only the summary
  (`step_type = 'commit' AND entity_type = 'venue'`), with a test. A sixth query, `failed_commits`, lists the failure rows.
  `show_history` loses its "EMPTY until A6" note.

## Test approach (written first, watched fail, then made green)

Every test is written before its code and watched fail (build plan §3). Tests follow `AGENTS.md`: each opens with `Proves:`,
tests sit under labelled section comments, and the source of every expected value is stated. **Expected values come from the
requirements, the data model and the literal inputs, never from the code under test.** Five layers. Because the writer's two
`TODO(Ari)` gaps (K1, K2) sit on every path that writes, every test that writes is red until they are filled; the pure tests
(layer 1) and the rows' shapes (layer 2) are green from the start.

### 1. Pure: what to write (`agent_worker/tests/test_commit_ops.py`)

Hand-built `ReconcilePlan`s; no database. Sources: `data-model-initial.md` §2 and §3, `A5-D4`–`A5-D7`, D1 and D3 above.

- **Section: which decisions become operations**
  - insert, update and remove each produce one op; `no_op` and `skip` produce none (D1);
  - a withheld removal never appears; a cancelled-listing removal and an absent-from-the-page removal are both `status =
    removed` writes, with `reconcile_reason` `cancelled` and `absent from the page`;
  - inserts and updates come before removals, each group in the plan's (calendar) order.
- **Section: values of an insert**
  - `19.99` (a float) becomes `Decimal("19.99")`, `20.0` becomes `Decimal("20.00")`, `None` stays `None`: the price
    conversion, **never** `Decimal(19.99)`'s binary tail (build plan A6; the expected strings are literals);
  - `free_admission = True` with no prices is written as given; `venue_id`, `original_url` and `status = active` are set;
  - a listing with no `time` writes `start_time = None` (reconcile never assumes a time, `A5`).
- **Section: values of an update**
  - only the fields in `changes` are in `values`; `lineup` never is; a reactivation sets `status = active`;
  - `op.lineup` is the decision's lineup when `"lineup" in changes`, otherwise `None` (the lineup is not touched);
  - a blank field in the listing is absent from `values` (`A5-D4` already put it that way in `changes`; this pins that commit
    doesn't re-add it).
- **Section: new artists**: `new_artist_names` has exactly the keys of lineup entries with no id, each named by the first-seen
  spelling in `plan.artists`; an op whose lineup is all existing artists has none.
- **Section: the snapshot (D3)**
  - a literal show with `Decimal("20.00")`, `time(20, 0)`, `date(2026, 10, 20)` and a two-act lineup gives exactly the JSON
    in the test: `"20.00"` (a string, not `20.0`), `"20:00:00"`, `"2026-10-20"`, `status` `"active"`;
  - `created_at` / `updated_at` are absent; the lineup is in `sequence_number` order;
  - `json.dumps(snapshot)` succeeds; the key set equals the list above (so a new column is a visible change).
- **Section: the module's place in the DAG**: a fresh interpreter importing `agent_worker.commit` has neither `agent_worker.state`
  nor `agent_worker.audit` in `sys.modules`.

### 2. Pure: the rows (`agent_worker/tests/test_audit_entries.py`, extended)

`entry_for(COMMIT, state)` is the summary: entity = the venue, no outcome, `detail` keys as listed under "Audit rows"
(`counts` always has `inserted, updated, removed, no_op, skip`). The show, artist and failure builders: the outcome follows the
action (`insert` → `inserted`, `update` → `updated`, `remove` → `removed`); an insert's `previous_value` is `None`; the
artist row names `entity_type = artist`; a failure row has no outcome and no snapshots and its `error` is the type and one line;
`json.dumps` succeeds on every row's `detail`, `previous_value` and `new_value`. The A4 tests that call the commit row "a stub"
(`test_the_commit_stub_names_no_entity_yet`, `test_the_commit_stub_says_it_is_a_stub`) are replaced, not edited around.

### 3. The writer against Postgres (`agent_worker/tests/test_calendar_writer.py`)

`db_conn` and a savepoint-mode factory, as `test_audit_writer.py` does (the writer's `begin()` becomes a savepoint, so a
rolled-back write is really rolled back while the outer test transaction still undoes everything). Seeded with
`polyfactory` for filler columns only; names, dates and times are set explicitly (as `A5-PR1-15` fixed for A5), because
random ones would make the expected values depend on the code under test.

- **Section: the writes (K1)**
  - insert: one `show` row with the listing's values, the lineup in `show_artist` with sequence numbers and per-act times, a
    new `artist` row for a new name (name only; all other columns null), and **three audit rows**: the artist's, the show's
    (`previous_value` null, `new_value` the snapshot, equal to what a fresh read of the row gives) in that order;
  - update: only the changed columns change; the lineup is replaced only when told to; `updated_at` moves even for a
    lineup-only change;
  - remove: `status = removed`, the row and its lineup stay; reactivation sets it back;
  - **`previous_value` is the row before the change** (a changed end time shows the old value in `previous_value` and the new
    one in `new_value`): the test that catches reading the snapshot after the write (**A6-M1**);
  - **atomic:** an op whose lineup names an artist id that doesn't exist fails at the foreign key *after* the show was
    inserted; afterwards there is no `show` row, no `show_artist`, no new `artist` and **no `audit_log` row**
    (**A6-M2**: the audit row written through a separate session);
  - a price that overflows `Numeric(10, 2)` and a `free_admission` + price row (the table's CHECK) each fail as
    `DataError` / `IntegrityError` and leave nothing behind;
  - **revert is possible:** a test-only `restore(session, snapshot)` puts a row back from `previous_value`, and the row then
    equals its pre-update snapshot (columns and lineup). This proves the snapshot is *sufficient*, which is its whole purpose
    (build plan A6: "those are what a future revert restores"); the revert action itself stays deferred.
- **Section: `write_plan` and failures (K2)**
  - two shows naming the same new artist create it **once**; the second show links to the first's artist;
  - a show whose transaction fails *after* creating a new artist does not leave that artist in the map: the next show that
    names the same artist creates it again and succeeds (**A6-M3**: the map updated before the write returned);
  - a failing show is recorded (failure row, `ShowFailure`) and the others are written (D2); a connection-class error
    (`OperationalError`, injected by a stub writer) propagates and writes nothing further; a bare `RuntimeError` from the
    writer propagates (it's a bug, not a data error);
  - with D2 answered B the "others are written" test becomes "the run stops at the failure" (the plan notes this so the
    build can follow Ari's answer).

### 4. The graph with fakes (`agent_worker/tests/test_graph_commit.py`)

The real compiled graph, `fakes.ScriptedClient`, `RecordingAudit`, `FakeReader`, and a new `fakes.FakeWriter` that records
the ops it is given, can be scripted to fail a given op, and appends the rows a real write would to the `RecordingAudit`
(so the order is observable).

- a first run (empty calendar): `FakeWriter` receives one op per show, inserts first; the audit steps end `..., reconcile,
  commit (per show), commit (summary)`;
- a second run returned by `FakeReader` as the first run's result: **no ops**, summary `counts` all zero except `no_op`, one
  row only;
- a cancelled listing for a stored show: one remove op, reason `cancelled`; a withheld removal: no op, `withheld` in the summary;
- one failing op: the other ops are written, the failure row and a summary with one `failed` entry exist, and
  `run_venue` returns normally with `commit_result.failures`; `run_all` counts the venue failed (`test_run_venue.py`);
- an `OperationalError` from the writer propagates out of `ainvoke` and **no summary row** is written;
- an escalated run (no reconcile) never reaches commit: no ops, no writer call (the A4 tests that assert this stay green).

### 5. The whole loop against Postgres (`agent_worker/tests/test_commit_db.py`)

The seeded calendar from `test_reconcile_db.py` (its seeding moves into `reconcile_support.py` so both files share it) run
through the **real graph with the real reader and the real writer**; only the model is scripted. This is the test A5 could
not write ("a real database round trip is A6's test").

- **parity with the simulator:** after the commit, `PostgresCalendarReader` over the plan's range returns what
  `reconcile_support.apply_plan` predicted for the same plan (compared on date, time, status, prices, lineup names, with ids
  mapped). This proves the A5 simulator mirrors the real write, so A5's idempotency test is evidence about the real thing;
- **idempotency:** run the same page again: the second plan is **all `no_op`**, no row in `show`, `show_artist` or `artist`
  changed (counts and `updated_at`), and no per-show `commit` row was added (**A6-M4**: skipping the price conversion makes
  `20.0` compare unequal to the stored `Decimal("20.00")` and the second run updates);
- **the changes run:** a third run on an edited page (a lineup change, a vanished show, a returning show) writes exactly
  those, and `show_history` for the changed show returns the insert row, then the update row, with the snapshots;
- **the artists table** now holds exactly the old artists plus the new ones, once each;
- **a run that fails mid-commit** (an op that violates the CHECK, injected by seeding a conflicting row) leaves the other
  shows written and `unfinished_runs` does *not* list it (the summary was written), while a run whose writer raises a
  connection error *is* listed (**A6-M5**: the query counting per-show rows as "reached commit").

### Mutation checks (the proof the tests can fail)

Run by the build step on a scratch copy (a throwaway `git worktree`, removed afterwards), each recorded in the Implementation log.

| # | Break | The test that must go red |
|---|---|---|
| A6-M1 | read `previous` after the write instead of before | `test_previous_value_is_the_row_before_the_change` |
| A6-M2 | write the show's audit row through `AuditWriter.record` (its own session) | `test_a_failed_write_leaves_no_audit_row` |
| A6-M3 | update the artist map before `write_show` returns | `test_a_rolled_back_artist_is_not_remembered` |
| A6-M4 | write prices with `Decimal(float)` instead of `to_price` | `test_the_second_run_is_all_no_ops` |
| A6-M5 | count every `commit` row as "reached commit" in `unfinished_runs` | `test_a_run_that_crashed_mid_commit_is_unfinished` |
| A6-M6 | catch `Exception` (or `SQLAlchemyError`) around `write_show` | `test_a_connection_error_stops_the_run` |

### Existing tests that change

`WorkerContext(...)` gains `writer=` at ten call sites: `main.py`, `local_test.py`, `test_graph.py`, `test_graph_audit.py` (2),
`test_graph_reconcile.py` (2), `test_audit_queries.py` (2), `test_run_venue.py`, `test_reconcile_db.py`. Tests that don't
care about the calendar get `fakes.FakeWriter()`; `test_audit_queries.py` uses the real `PostgresCalendarWriter` so its
`show_history` check runs against a real commit row (it hand-inserts one today); `test_reconcile_db.py` keeps a `FakeWriter`
so it continues to prove what its docstring says, that reconcile writes nothing (its "artists table is unchanged" test would
otherwise be asserting the wrong thing now that commit exists). `test_graph_audit.py`'s step lists gain the per-show commit
rows where the page has shows (the fake appends them), and `entry_for(COMMIT)` assertions change from the stub shape.

### What is not covered, stated plainly

- **A live worker run against a real venue URL with Ollama.** The cloud sandbox has neither Ollama nor Docker's MongoDB
  (`AGENTS.md`, "Cloud sessions"), so the Verification steps marked *local* are Ari's.
- **Concurrency.** Two workers writing one venue at once would race on the same rows (the row lock only protects one
  transaction at a time against another); the alpha runs venues one after another in one process.
- **A write against a stale plan.** The snapshot is read from the database, so it is honest, but a change a human makes
  between reconcile's read and commit's write is overwritten for the fields the plan names (last write wins). There are no
  human edits yet; when they exist (deferred), the writer should compare the row to what the plan expected. Not built,
  not claimed.
- **Revert itself.** Only that a snapshot is enough to revert (the test-only `restore`).
- **Mongo.** Commit stages nothing in MongoDB.

### Known gotchas to handle up front

- **The ORM identity map is the trap in K1.** Within a session, `session.get(Show, id)` returns the *same Python object*
  every time, so a `previous` taken from it after `setattr` is the new value. The snapshot is a `dict` built before the
  change.
- **`Decimal` in JSONB.** `json.dumps(Decimal("20.00"))` raises; `to_jsonable_python` returns `"20.00"`. A snapshot with a
  `float` price would round-trip as `19.989999999999998`. Snapshots are built with `to_jsonable_python`, as `audit.py` does.
- **`updated_at` and a lineup-only change** (Settled details): an ORM update that changes no `show` column issues no UPDATE.
- **`session.begin()` inside the test's savepoint mode** nests as a savepoint, so a rollback in a test is real but does not
  end the outer transaction; an assertion that "nothing persisted" reads through the same connection.
- **A failed asyncpg transaction can't be reused.** The loop opens a fresh session per show (`write_show` owns its session),
  so a failure in show 3 can't poison show 4.
- **`state.run_id` is `None` in some tests;** the rows then have a NULL `run_id`, as for every other step.
- **mypy.** `agent_worker/` is outside CI's mypy scope until A7, but the three new modules must pass `mypy` run on them
  (the standard A5 kept).

## Implementation steps

### Working protocol for [fill-in] steps

The scaffold is complete except for two `TODO(Ari)` blocks (K1, K2). Each fails loudly with
`raise NotImplementedError("TODO(Ari)")`, so its tests are red, not accidentally green. Everything else, including the tests
for the gaps, is written. "Go ahead" or `/build-milestone` produces the scaffold. A gap is filled only when Ari asks for it by
name; the cleanup pass (`AGENTS.md`, step 4) follows.

### TODO(Ari) gaps

**Fill order:** K1, then K2 (K2 needs a writer that works). Until K1 is filled **every test that writes is red**: layers 3, 4
(the writer is called) and 5, and every graph test that reaches commit with a non-empty plan and the real `calendar_writer`
(the fakes keep the graph tests green). The Implementation log lists the red tests by file.

- **K1 — one show, one transaction, in `calendar_writer.py` (`PostgresCalendarWriter.write_show`).** *(Build plan A6, first
  item; D3; `arch-initial.md` §7.)*
  - *Lesson:* a write and its record are **one unit**. The `audit_log` row goes in the *same* session and transaction as
    the change, so they commit or roll back together: a rolled-back show leaves no audit row, and a committed one can't lose
    its record. And the snapshots are taken in a deliberate order: `previous` **before** the change (the ORM hands back the
    same object after it, mutated), `new` **after** the flush (so it holds what the database holds, `updated_at` included).
    Those two snapshots are what a future revert restores (`data-model-initial.md` §3).
  - *Code:* the helpers (`_create_artists`, `_snapshot`, `_apply`, `_audit_rows`) are written; the gap is the block that orders them:
    ```python
    async with session.begin():
        created = await self._create_artists(session, op, artist_ids)
        previous = await self._snapshot(session, op.stored_id) if op.stored_id is not None else None
        show_id = await self._apply(session, op, {**artist_ids, **created}, venue_id)
        new = await self._snapshot(session, show_id)
        session.add_all(audit_row(e) for e in self._audit_rows(op, created, show_id, previous, new, run_id, attempt_number))
    return ShowWritten(show_id, op.outcome, created)
    ```
  - *Check:* `uv run pytest agent_worker/tests/test_calendar_writer.py -k "writes or previous or atomic or revert"`. The likeliest mistake is
    taking `previous` after `_apply` (the identity map returns the mutated object, so `previous_value` equals `new_value`: the
    "previous is the row before the change" test goes red); the second is writing the audit row with `AuditWriter.record`
    or calling `session.commit()` before the audit row is added (the "failed write leaves no audit row" test goes red).

- **K2 — what survives a failed show, in `calendar_writer.py` (`write_plan`).** *(Build plan A6; D2.)*
  - *Lesson:* a failure about **one show** is not a reason to stop, and a failure about the **run** is. The first is a data
    error from the database for that show (`DECISION_ERRORS`, a named tuple, never `Exception`: `apps/api/AGENTS.md`); the second
    (a lost connection, a bug) must propagate. And state that outlives a transaction is updated only *after* the transaction
    commits: the map of artists created so far is extended once `write_show` has returned, never before, because a rolled-back
    artist's id is a lie that the next show would link to.
  - *Code:*
    ```python
    try:
        written = await writer.write_show(op, artist_ids, venue_id=venue_id, run_id=run_id, attempt_number=attempt_number)
    except DECISION_ERRORS as err:
        failures.append(await record_failure(audit, op, err, run_id, attempt_number))
        continue
    artist_ids.update(written.created_artists)
    tally[written.outcome.value] += 1
    ```
  - *Check:* `uv run pytest agent_worker/tests/test_calendar_writer.py -k "write_plan or failure or created_once"` and
    `test_graph_commit.py -k failed`. The likeliest mistake is catching `SQLAlchemyError` or `Exception` (the "connection error
    stops the run" test goes red); the second is extending `artist_ids` before the write returns (the "rolled-back artist
    is not remembered" test goes red).
  - *If you answer D2 with B,* the `try` goes and the block is two lines; the lesson becomes only the second half.

### 1. Tests first (written)

`test_commit_ops.py`, the `test_audit_entries.py` changes, `test_calendar_writer.py`, `test_graph_commit.py`,
`test_commit_db.py`, and the helpers they need (`fakes.FakeWriter`, `reconcile_support`'s shared seeded calendar, the test-only
`restore`). Watched fail before any code exists.

### 2. `agent_worker/commit.py` (written)

The types, `build_ops`, `insert_values`, `changed_values`, `snapshot_of`, `summary_counts`. A module docstring says what commit
is and the order to read it in, as `reconcile.py`'s does; each function says what it is for.

### 3. `agent_worker/audit.py` (written)

`AuditEntry.previous_value` / `new_value`, `audit_row`, the show / artist / failure builders, `COMMIT` in `_VENUE_LEVEL`, the
summary `_detail`, `attempt_number` public. The A4 stub comments are updated, not left saying "until A6".

### 4. `agent_worker/calendar_writer.py` (written, except K1, K2)

`CalendarWriter`, `ShowWritten`, `DECISION_ERRORS`, `ShowGone`, `PostgresCalendarWriter` with its helpers, `write_plan`,
`record_failure`.

### 5. Wiring (written)

`context.py`, `state.py`, `nodes.py` (`commit_node`), `trace.py` (the commit branch, with a comment block saying why the write
is awaited there and why the summary row comes last), `main.py` (the writer; `run_all` counts commit failures), `local_test.py`
(builds the writer; prints what was written and what failed), and `tests/fakes.py`.

### 6. `docs/dev/audit-queries.sql` (written)

Header keys for the commit rows; `unfinished_runs` counts the summary only; `show_history` without its "EMPTY until A6"
note; the sixth query `failed_commits` ("which shows failed to write, and why"): the failure rows joined to the run's venue. It
uses `CAST(... AS ...)`, not `::`, like the others. `test_audit_queries.py` executes each against real rows.

### 7. Docs and bookkeeping (written)

- `alpha-build-plan.md`: tick A6's items, record the departures below, a paragraph like A5's ("Plan and reviews: ...").
- `arch-initial.md` §7: a "Built in A6" paragraph after A5's: the unit of work (one show, one transaction, the audit row inside
  it), the snapshot (whole row plus lineup, read from the database), the failure policy, removals last, the summary row, and
  the departure that commit's write is awaited in the wrapper.
- `data-model-initial.md`: under `audit_log`'s departures, the `previous_value` / `new_value` shape (the keys above) and that
  an unchanged show writes no row (D1).
- `conventions.md`: add `A6` to the scope table (`Future milestones use their own IDs`).
- `apps/api/AGENTS.md`: the worker paragraph gets commit's module map, the "per-show audit rows are written in the write's own
  transaction, never through `AuditWriter.record`" rule, and that a failed show is recorded and the run carries on.
- `notes.md`: append what the build turns up (the identity-map trap if it bites; the `unfinished_runs` change).

### Departures from the build plan (to apply to `alpha-build-plan.md` when implementing)

1. **No `event` rows.** `A5`'s "Not doing" listed "the `event` rows" under A6. An `Event` is a festival that groups several shows
   and "isn't a v1 UI surface" (`data-model-initial.md`); nothing in the extraction schema identifies one, so there is nothing
   to write and `show.event_id` stays `NULL`. Proposed: strike it from A6's scope and leave festivals to the feature that
   introduces them.
2. **An unchanged show writes no audit row** (D1). The data model lists `no_op` as an outcome for commit rows; if you pick
   option B this reverses and `AuditOutcome.NO_OP` rows are added.
3. **The price conversion already exists.** The [written] item is satisfied by `commit.insert_values` calling `reconcile.to_price`
   (A5 defined it once so comparison and storage agree); there is no second conversion.
4. **`commit_node` prepares, the wrapper writes** (A4-D1). The build plan's "`commit_node` executing reconcile's decision" is true of
   the graph step, not of the function body: the node turns the plan into operations, `trace.audited` awaits the writes.
5. **Per-show audit rows are written by the calendar writer, in the write's transaction,** not through `AuditWriter.record`.
   `AuditWriter` stays the append-only writer for the steps that have no data write to be atomic with.
6. **A7's "unit tests for reconcile's decision logic against a seeded database" is unaffected;** A6 adds the round trip and the
   simulator parity test, which A5 deferred to it.

## Critical files

| File | Change |
|---|---|
| `apps/api/agent_worker/commit.py` (new) | The pure core: `ShowOp`, `build_ops`, `insert_values`, `changed_values`, `snapshot_of` |
| `apps/api/agent_worker/calendar_writer.py` (new) | `CalendarWriter`, `PostgresCalendarWriter` (K1), `write_plan` (K2), `DECISION_ERRORS` |
| `apps/api/agent_worker/audit.py` | `previous_value` / `new_value`, `audit_row`, commit builders, the summary `detail` |
| `apps/api/agent_worker/state.py`, `context.py` | `commit_ops`, `commit_result`; `writer` |
| `apps/api/agent_worker/nodes.py`, `trace.py` | `commit_node` builds operations; the wrapper awaits `write_plan` |
| `apps/api/agent_worker/main.py`, `local_test.py` | Build the writer; `run_all` counts commit failures |
| `apps/api/agent_worker/tests/` | `test_commit_ops`, `test_calendar_writer`, `test_graph_commit`, `test_commit_db` (new); `fakes.py` (`FakeWriter`), `reconcile_support.py` (shared seeding), `test_audit_entries`, `test_audit_queries`, `test_graph`, `test_graph_audit`, `test_graph_reconcile`, `test_reconcile_db`, `test_run_venue` (updated: the new `WorkerContext` field, the commit row) |
| `docs/dev/audit-queries.sql` | Commit keys; `unfinished_runs`; `failed_commits` |
| Docs listed in step 7 | Bookkeeping |

No migration (`show`, `show_artist`, `artist`, `audit_log.previous_value` / `new_value` all exist), and `app/schemas.py` is
untouched, so `make types` / `make fixtures` have nothing to regenerate and there is no B-track impact. Stated because the
build plan's gate for schema changes is "their own early PR".

## Verification

**In the cloud session (this author's):**

1. `make check`. Baseline measured October 19, 2026 on this branch before any A6 change: **790 passed, 15 skipped** for the API
   suite, ruff clean. Expect red, by design, wherever a test writes (K1, K2): the log lists them by file. Everything else
   must be green. The JS suite is untouched.
2. Gaps verified filled on a scratch copy (a throwaway `git worktree`, removed afterwards): with both filled the whole suite is
   green; the result is recorded in the Implementation log (the A3/A4/A5 pattern).
3. The six mutation checks (A6-M1 to A6-M6) run on a scratch copy and recorded.
4. `uv run mypy` on `commit.py` and `calendar_writer.py` is clean; `make designation-check BASE=<the diff base>` exits 0.
5. No migration, so no `alembic` round trip; `make contract-check` stays green.

**Locally (Ari, after filling the gaps; needs Docker and Ollama):**

6. `make db-reset && make seed`, then `cd apps/api && uv run python -m agent_worker.local_test`. Expect, for the White Squirrel
   fixture (A5's local run: 12 shows, 27 artists): 12 inserts **written**, 27 artists created, three rows per new-artist show
   in `audit_log` (artists, then the show), one `commit` summary row with `counts.inserted = 12`.
7. Run it again. Expect the plan all `no_op`, nothing written, no new `show`, `show_artist` or `artist` row, `updated_at`
   unchanged, one new `commit` summary row with `counts.no_op = 12`. This is the check A5 could not do.
8. Edit the database by hand to simulate a page change (`make db-shell`): change a show's `end_time`, delete one of its
   `show_artist` rows, and set one show's `start_time` to a time the page doesn't list. Run again: one `updated` (with
   `previous_value` / `new_value` differing in `end_time` and `lineup`), and the changed-time show is removed and re-inserted.
   Run the `show_history` query for the updated show.
9. The failure path (D2): `ALTER TABLE show ADD CONSTRAINT tmp_no_end_time CHECK (end_time IS NULL) NOT VALID;`, delete one show,
   run. Expect the insert of that show (it has an end time) to fail, a `failed_commits` row, the others unaffected, and exit
   status 1; then drop the constraint and run once more to see it converge.
10. Eyeball the snapshots: take one `previous_value` and confirm it has the whole row and a `lineup` array you could restore from.

## Not doing in A6

- **A revert action.** Only the proof that snapshots suffice (`arch-initial.md` §7, "Revert", is a first-class feature, later).
- **`event` rows** (Departures 1) and any festival logic.
- **A review queue for `needs_review` decisions.** They are written and flagged in the audit row (`A5`).
- **Comparing the row to the plan at write time** (stale-plan detection), until human edits exist.
- **Artist merge / de-duplication** (`data-model-initial.md` §5). A duplicate artist the model declined to merge stays a duplicate.
- **Concurrency control** between workers on one venue.
- **Reading from the new rows.** The read routes are still on `sample_data.py` (A1b); the calendar rendering real rows is
  A1b plus the B track, and the definition of done's point 4 waits for it.
- **Mongo writes from commit.** Raw staging is the extract step's.

## Approval

*(Awaiting plan review and Ari's decisions on D1–D3. Ari moves the status to `Approved`.)*

## Plan review

*(Round 1 pending: the reviewer appends it here.)*
