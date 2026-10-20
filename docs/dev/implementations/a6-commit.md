# A6 — commit

**Status:** Done (Ari sign off) - Oct 20, 2026
**Date:** October 19, 2026 (plan); October 20, 2026 (decisions, implementation)
**Author model:** Claude Sonnet 5.5 (plan and plan-review resolution, October 19 to 20, 2026; implementation, October 20, 2026)
**Reviewer model:** Claude Opus 5.5 (plan review round 1, October 19, 2026; round 2, targeted at D2 and K2, October 20, 2026; code review round 1, October 20, 2026); Claude Opus 5.5 (plan review round 2, targeted at D2 / K2, October 20, 2026); Claude Opus 5.5 (code review round 1, October 20, 2026)
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
| D1 | Does a show that didn't change get an audit row? | ★ | A: no, count it in the summary | **Decided A** (Ari, Oct 20) |
| D2 | If one show's write fails, do the other shows still get written? | ★ | A: yes, past a data error; stop on a connection error | **Decided A** (Ari, Oct 20) |
| D3 | What does a snapshot hold? | technical | A: the whole `show` row (minus timestamps) plus its lineup | **Decided A** (Ari, Oct 20) |

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
  non-zero afterwards, so a person sees it. This applies to **what the database says is wrong with that one row**,
  decided by the error's SQLSTATE class: class `22` (a data exception, such as the overflow above) or class `23` (an
  integrity violation: the CHECK, a foreign key), or the show having vanished. It is **not** decided by Python exception
  class: on this driver (SQLAlchemy 2.0 with asyncpg) only integrity violations arrive as `IntegrityError`; an overflow
  arrives as a plain `DBAPIError`, and `DataError` never occurs (A6-PR1-1). A lost connection (an `InterfaceError`, whose
  SQLSTATE is `None`, or a class `08` / `57` error) still stops the run, because it is not about one show.
  **What the rule separates, stated carefully (A6-PR2-2):** the database *refusing a row* from *losing the database*. It does
  **not** separate a bad listing from a bug of ours: a commit bug that sends a malformed row (a column left out of the insert,
  an enum written as the wrong string, a stale artist id) is refused with class 22 / 23 too, and is recorded as one show's
  failure. Only a bug that raises a Python exception, or a database error outside classes 22 / 23, stops the run.
  Technically: `calendar_writer.is_decision_error` (**K2**).
- **Option B — stop at the first failure.** The shows already written stay written (each was its own transaction); the rest
  wait for tomorrow. Simpler (no `try`), and a failure can't be missed. But one poisoned listing blocks every show after
  it on that venue's page, every night, until a person fixes it.
- **Cost of A:** a deterministic bug in reconcile that produces a bad decision fails that one show quietly every night
  (loudly in the logs and the exit code, but the calendar looks mostly fine). The `failed_commits` saved query is how you
  find it. **A second cost, which "removals last" below does not cure:** if the failed write is the *insert* half of a time
  change (8 PM removed, 9 PM inserted) and the failure is deterministic, the 8 PM show is removed and the 9 PM show never
  appears, so the calendar has a **gap** on that date every night until a person fixes it (the stale-too-long direction
  `A5-D1` calls safe is the other one). Withholding the removal when the insert on that date failed would avoid it, but
  that is a judgement made in commit, and commit adds none; so the plan states the cost instead of building around it.
  **A third cost (A6-PR2-2):** a commit bug of the malformed-row kind fails *every* write, and option A carries on past each:
  N failure rows, a summary, exit 1, and nothing written. It looks like N bad listings; only the repeated SQLSTATE says
  otherwise. So the failure rows carry `sqlstate`, `failed_commits` can group by it, and the summary flags `all_failed` (below,
  Settled details) so the all-fail case reads as what it probably is.
  **Cost of B:** the calendar for that venue goes stale behind one bad row.
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

- **Removals are applied last.** Inserts and updates first (in calendar order), then removals. This helps a run that
  **stops** (a lost connection, or option B of D2): a time change (remove 8 PM, insert 9 PM) is then left as a duplicate
  rather than a gap, the safe direction (`A5-D1`: "a stale show up too long is the safe direction"). It does **not** help a
  run that carries on past a failed insert (D2 option A, whose cost says so). The audit rows are ordered by id anyway, so
  reading them is unaffected.
- **A new artist's audit row is written in the same transaction as the show that first needs it,** `entity_type = artist`,
  `outcome = inserted`, `new_value = {id, name}`. The artist is created by the first decision that needs it and reused by
  the later ones; if that first decision rolls back, the artist rolls back with it, and because the writer hands created ids
  back only in its return value (nothing outlives the transaction), the next decision that needs the artist creates it
  again (**K1**).
- **A lineup is replaced wholesale when reconcile says it changed** (`"lineup" in decision.changes`): the show's
  `show_artist` rows are deleted and re-inserted from the decision's lineup. When the lineup didn't change they are not
  touched. `show_artist` has no timestamps and a pure-join key, so a diff buys nothing.
- **`show.updated_at` is touched on every update,** including one that changes only the lineup (an ORM update that
  changes no `show` column would otherwise leave it stale). It is set to `func.now()` explicitly. Its tests seed rows with a
  literal past `updated_at` and compare against that literal, because inside the test transaction `now()` is the
  transaction's start and never moves (A6-PR1-3).
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
- **Exceptions that stop the run are not caught.** An `InterfaceError` (a real lost connection, `connection_invalidated`,
  SQLSTATE `None`), a `DBAPIError` whose SQLSTATE is not class `22` or `23` (`08006`, `57P01`, ...) and every non-database
  exception propagate; `main.run_all` already treats `SQLAlchemyError` as "this venue failed, carry on to the next one". A
  commit bug that makes the database refuse a row is *not* in this list (see D2's wording and third cost).
- **An all-fail run is flagged, not raised.** When a run had at least 3 operations and every one failed with a decision error,
  the summary row carries `all_failed: true` and the worker logs an error saying the failures look like a bug and not bad
  listings. It does not raise: the exit code is already 1 and nothing is written either way. (3 mirrors
  `ReconcilePolicy.min_removals_to_guard`; a named constant in `calendar_writer.py`.)

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
ShowFailure    action, date, time, stored_id, sqlstate, error    # one failed show; sqlstate None for ShowGone
CommitResult   written: dict[str, int]                           # "inserted" / "updated" / "removed" -> how many
               artists_created: int; failures: tuple[ShowFailure, ...]
SNAPSHOT_EXCLUDED = {"created_at", "updated_at"}                 # D3
SNAPSHOT_COLUMNS = tuple(c.key for c in Show.__table__.columns if c.key not in SNAPSHOT_EXCLUDED)   # derived, not typed
```

| Function | Job | Marking |
|---|---|---|
| `build_ops(plan, venue_id, original_url)` | One `ShowOp` per insert / update / remove decision; none for `no_op` or `skip` (**A6-D1**); withheld removals never; inserts and updates first in calendar order, then removals | [written] |
| `insert_values(listing, venue_id, original_url)` | The columns of a new show: `venue_id`, `date`, `start_time` (the listing's `time`), `end_time`, the two prices through `reconcile.to_price`, `free_admission`, `image_url`, `original_url`, `status = active` | [written] |
| `changed_values(changes)` | The columns of an update: the new side of each `(old, new)` pair in `changes`, minus `lineup`; `status` arrives as `ShowStatus` | [written] |
| `snapshot_of(columns, lineup)` | A show as restorable JSON: takes exactly the keys in `SNAPSHOT_COLUMNS` from `columns` (a missing one is an error, an extra one is dropped), `Decimal` as its decimal string, times and dates ISO, enums by value, no timestamps (**A6-D3**), `lineup` a list of `{artist_id, start_time, sequence_number}` in performance order | [written] |
| `summary_counts(plan, result)` | The summary row's `counts` (`inserted`, `updated`, `removed`, from the result; `no_op`, `skip`, from the plan) | [written] |

The snapshot's keys (so the audit trail's readers and a future revert agree): `id`, `venue_id`, `event_id`, `date`,
`start_time`, `end_time`, `age_restriction`, `serves_alcohol`, `setting`, `seating`, `admission_advance`, `admission_day`,
`free_admission`, `image_url`, `original_url`, `status`, `lineup`. The column keys come from `commit.SNAPSHOT_COLUMNS`,
derived from `Show.__table__.columns` minus `SNAPSHOT_EXCLUDED`, not a hand-written list, so a column added by a later
migration appears in snapshots without anyone remembering to. Because `snapshot_of` takes exactly those keys, a test that
pins `SNAPSHOT_COLUMNS` against the literal list above **can fail**: a migration that adds a column changes the derived
tuple, the test goes red, and the change is a deliberate edit to the list (and to the snapshot's documentation).

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

DECISION_SQLSTATE_CLASSES = ("22", "23")   # data exception, integrity violation: what the DATABASE says is wrong with this row

def is_decision_error(err: BaseException) -> bool:
    """A failure about ONE show (A6-D2): the show vanished, or the database rejected its row by SQLSTATE class 22 / 23.
    Decided by SQLSTATE, not by Python class: asyncpg maps only integrity violations to `IntegrityError`, and an overflow is
    a plain `DBAPIError` (A6-PR1-1). The expression is `sqlstate = getattr(err.orig, "sqlstate", None) or ""`, **not** a
    `getattr(..., "")` default: the dialect always SETS `sqlstate`, to `None` for an error asyncpg gives none (a real lost
    connection is an `InterfaceError` with `orig.sqlstate = None`), so a default is never used and `None[:2]` would raise a
    `TypeError` inside K2's `except`, an exception outside `RUN_ERRORS` that crashes the whole worker (A6-PR2-1). An error
    with `connection_invalidated` set is False before the SQLSTATE is looked at. Everything else (a lost connection, an
    error outside classes 22 / 23, a bug that raises) is False."""
```

**`PostgresCalendarWriter(session_factory).write_show`** is one transaction, in this order (the order is the lesson, **K1**):

```
async with self._session_factory() as session:                  # a fresh session per show: a failure can't poison the next one
    async with session.begin():                                 # nothing below is visible until this block exits cleanly
        created   = create the artists this show is first to need   # flush -> ids; skips keys already in `artist_ids`
        previous  = snapshot the stored row (locked)                # BEFORE anything changes; None for an insert
        show_id   = apply the op                                    # insert / update columns, replace the lineup if told to, flush
        new       = snapshot the row again                          # AFTER the flush, read back from the database
        add audit rows: one per created artist, then the show's     # the SAME session, so they commit or roll back with the write
```

- `_snapshot(session, show_id, *, lock=False)` runs a `SELECT ... populate_existing` rather than reading the session's
  identity map, so it reports what the database holds (the quantized price, the server's values), and it builds a plain
  `dict` immediately, so a later change to the ORM object can't alter a snapshot already taken. (Timestamps are not in it, D3.)
- **The lock is taken, and `ShowGone` raised, by the first read.** For an update or remove the `previous` snapshot is
  `_snapshot(session, stored_id, lock=True)`: it selects `FOR UPDATE` and raises `ShowGone` if the row isn't there, so the
  `previous_value` is read from the row that stays locked for the transaction, and a vanished row is a per-show failure
  rather than a `NoResultFound` that would look like a bug (A6-PR1-7). `_apply` then finds the row in the session already.
- Nothing here calls `commit()` itself: leaving the `begin()` block commits, an exception rolls back.
- **Created artist ids leave the writer only in the returned `ShowWritten`.** The writer keeps no state of its own between
  shows (no cache of created ids), because anything it remembered from a transaction that later rolled back would be a
  lie the next show links to (**K1**).

**`write_plan(ops, writer, audit, *, venue_id, run_id, attempt_number) -> CommitResult`** is the loop: for each op, call
`write_show`; on a failure for which `is_decision_error` is true, record that show's failure row through `audit.record` and
carry on; after a show has been written, extend the artist map for the shows after it from what `write_show` returned
(**K2**). Any other failure propagates.

### Audit rows: `agent_worker/audit.py` (extended)

`AuditEntry` gains `previous_value` and `new_value` (JSON-safe dicts or `None`). A module-level `audit_row(entry) ->
AuditLog` maps an entry onto the ORM row; both `PostgresAuditWriter.record` and the calendar writer use it, so there is
one place that knows the columns. New pure builders, tested without a database:

| Row | `step_type` | `entity` | `outcome` | `previous_value` / `new_value` | `detail` |
|---|---|---|---|---|---|
| A show written | `commit` | `show`, the show's id | `inserted` / `updated` / `removed` | the two snapshots (previous is `null` for an insert) | `action`, `reconcile_reason`, `changed` (the column names, plus `"lineup"`), `needs_review` |
| An artist created | `commit` | `artist`, the new id | `inserted` | `null` / `{id, name}` | `name`, `key` |
| A show that failed | `commit` | `show`, the stored id (`null` for an insert) | none | none | `action`, `reconcile_reason`, `date`, `time`, `stored_id`, `sqlstate`, `error` (the exception type and first line of the database's message; never the SQL with its parameters). The identity keys are the same as the summary's `failed` entries, so an insert's failure row says which show failed (A6-PR2-3) |
| The run's summary | `commit` | `venue` | none | none | `counts` (exactly five keys), `artists_created`, `failed` (a list of `{action, date, time, stored_id, sqlstate, error}`), `all_failed` (bool), `withheld` |

`COMMIT` joins `_VENUE_LEVEL` (the summary row names the venue, as reconcile's does). `attempt_number` for every commit row is
the existing rule (the last attempt, floored at 1); the private helper becomes public as `audit.attempt_number`, because
`trace` and the builders both need it. The summary `counts` has **exactly** the five keys `{inserted, updated, removed, no_op,
skip}` (what was written, and what reconcile decided to leave alone), so its shape doesn't depend on the run (as reconcile's
does); failures are **only** in the `failed` list, never a sixth key (A6-PR2-8).

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
  (`step_type = 'commit' AND entity_type = 'venue'`), with a test. The A4 / A5 stub `commit` row has no entity, so **every run
  that finished before A6 in an un-reset dev database reads as unfinished**; the query's comment says so and relies on
  `make db-reset` (as Verification 6 already does) rather than also accepting the stub (A6-PR2-6). A sixth query,
  `failed_commits`, lists the failure rows: `WHERE step_type = 'commit' AND entity_type = 'show' AND detail ->> 'error' IS NOT
  NULL`, with a `LEFT JOIN agent_run` and `LEFT JOIN venue` so a row with a NULL `run_id` doesn't drop out; it selects `date`,
  `time`, `stored_id`, `action`, `sqlstate`, `error` from the row's own `detail`, and a `GROUP BY sqlstate` variant in its comment
  for a recurring failure (A6-PR2-3). `show_history` loses its "EMPTY until A6" note.

## Test approach (written first, watched fail, then made green)

Every test is written before its code and watched fail (build plan §3). Tests follow `AGENTS.md`: each opens with `Proves:`,
tests sit under labelled section comments, and the source of every expected value is stated. **Expected values come from the
requirements, the data model and the literal inputs, never from the code under test.** Five layers. Because the writer's two
`TODO(Ari)` gaps (K1, K2) sit on every path that writes, every test that writes is red until they are filled; the pure tests
(layer 1) and the rows' shapes (layer 2) are green from the start. **K2's placeholder sits in `write_plan`'s loop, which every
run with at least one insert, update or remove goes through even with a fake writer, so existing tests that run the whole
graph on a page with shows are red too while K2 is open** (A6-PR1-4; measured at 21 failed and 10 errors by the reviewer's
probe, to be re-measured at build): "Existing tests that change" lists them.

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
  - `json.dumps(snapshot)` succeeds; `commit.SNAPSHOT_COLUMNS` equals the literal list above, which is the test that goes red
    when a migration adds a column to `show` (A6-PR1-10); a column missing from the input is an error.
- **Section: the module's place in the DAG**: a fresh interpreter importing `agent_worker.commit` has neither `agent_worker.state`
  nor `agent_worker.audit` in `sys.modules`.

### 2. Pure: the rows (`agent_worker/tests/test_audit_entries.py`, extended)

`entry_for(COMMIT, state)` is the summary: entity = the venue, no outcome, `detail` keys as listed under "Audit rows"
(`counts` has exactly `inserted, updated, removed, no_op, skip`, pinned as a set; failures appear only in `failed`, and
`all_failed` is true only for 3 or more operations that all failed). The show, artist and failure builders: the outcome follows the
action (`insert` → `inserted`, `update` → `updated`, `remove` → `removed`); an insert's `previous_value` is `None`; the
artist row names `entity_type = artist`; a failure row has no outcome and no snapshots, its `error` is the type and one line,
and its `detail` keys are pinned (`action`, `reconcile_reason`, `date`, `time`, `stored_id`, `sqlstate`, `error`), so an insert's
failure says which show failed;
`json.dumps` succeeds on every row's `detail`, `previous_value` and `new_value`. The A4 tests that call the commit row "a stub"
(`test_the_commit_stub_names_no_entity_yet`, `test_the_commit_stub_says_it_is_a_stub`) are replaced, not edited around.

### 3. The writer against Postgres (`agent_worker/tests/test_calendar_writer.py`)

`db_conn` and a savepoint-mode factory, as `test_audit_writer.py` does (the writer's `begin()` becomes a savepoint, so a
rolled-back write is really rolled back while the outer test transaction still undoes everything). Seeded with
`polyfactory` for filler columns only; names, dates and times are set explicitly (as `A5-PR1-15` fixed for A5), because
random ones would make the expected values depend on the code under test.

- **Section: the writes (K1)**
  - insert: one `show` row with the listing's values, the lineup in `show_artist` with sequence numbers and per-act times, a
    new `artist` row for a new name (name only; all other columns null), and **two audit rows for a show with one new artist**
    (one per new artist, then the show's), the show's with `previous_value` null and `new_value` the snapshot, equal to what a
    fresh read of the row gives;
  - update: only the changed columns change; the lineup is replaced only when told to; **`updated_at` moves even for a
    lineup-only change**, asserted against a literal past value the row was seeded with (`2026-01-01T00:00Z`), because
    `now()` is fixed for the whole test transaction and a before/after comparison of two `now()`s proves nothing (A6-PR1-3);
  - remove: `status = removed`, the row and its lineup stay; reactivation sets it back;
  - **`previous_value` is the row before the change** (a changed end time shows the old value in `previous_value` and the new
    one in `new_value`): the test that catches reading the snapshot after the write (**A6-M1**);
  - **atomic, two ways.** (a) An op whose lineup names an artist id that doesn't exist fails at the foreign key *after* the
    show was inserted; afterwards there is no `show` row, no `show_artist`, no new `artist` and no `audit_log` row. That
    proves the *data* rolls back, but the failure comes before the audit rows are added, so it cannot tell a correct K1
    from one that writes the audit row separately. (b) `test_audit_rows_roll_back_with_the_write`: a test subclass of
    `PostgresCalendarWriter` whose `_audit_rows` yields the real entries and **then raises an `IntegrityError`**; afterwards
    there is no `show` row **and no `audit_log` row**. With the correct K1 the rows were only added to the transaction;
    under **A6-M2** (the rows written through `AuditWriter.record`'s own session, or a `commit()` before they are added)
    they were already committed (A6-PR1-2). A comparison of `xmin` was considered and not used: that savepoint behaviour
    was not verified;
  - the table's CHECK (a `free_admission` row with a price) and a foreign key each raise `IntegrityError`, and a price that
    overflows `Numeric(10, 2)` raises a plain `DBAPIError` with SQLSTATE `22003` (not `DataError`: A6-PR1-1); each leaves
    nothing behind and each is `is_decision_error`;
  - a unit test of `is_decision_error` on the real shapes from the shared `fakes` helper (A6-PR2-1): `check_violation()`
    (`IntegrityError`, `23514`) and `overflow()` (`DBAPIError`, `22003`) are True; **`lost_connection()` (an `InterfaceError`
    with `orig.sqlstate = None` and `connection_invalidated = True`) is False and does not raise** (the case a
    `getattr(..., "")[:2]` implementation fails with a `TypeError`); a `DBAPIError` with `08006` and with `57P01`, a
    `RuntimeError` and a `NoResultFound` are False; a `ShowGone` is True;
  - **revert is possible:** a test-only `restore(session, snapshot)` puts a row back from `previous_value`, and the row then
    equals its pre-update snapshot (columns and lineup). This proves the snapshot is *sufficient*, which is its whole purpose
    (build plan A6: "those are what a future revert restores"); the revert action itself stays deferred.
- **Section: `write_plan` and failures (K2)**
  - two shows naming the same new artist create it **once**; the second show links to the first's artist;
  - a show whose transaction fails *after* creating a new artist does not leave that artist anywhere: the next show that
    names the same artist creates it again and succeeds (**A6-M3**: the writer remembers created ids in a cache that
    outlives the transaction);
  - a failing show is recorded (failure row, `ShowFailure`) and the others are written (D2), including a show whose price
    overflows `Numeric(10, 2)` (the D2 scenario, named `test_an_overflowing_price_fails_only_its_show`); a connection-class
    failure (a stub writer raising `fakes.lost_connection()`, and another a `DBAPIError` with `08006`) propagates and writes
    nothing further (`test_a_connection_error_stops_the_run`); a bare `RuntimeError` from the writer propagates (it's a bug,
    not a data error) (**A6-M6**); and a run of 3 operations that all fail sets `all_failed` in the summary while a run of 2
    does not (`test_an_all_failed_run_is_flagged`);
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
- a connection-class failure from the writer (`InterfaceError`) propagates out of `ainvoke` and **no summary row** is written;
- an escalated run (no reconcile) never reaches commit: no ops, no writer call (the A4 tests that assert this stay green).

### 5. The whole loop against Postgres (`agent_worker/tests/test_commit_db.py`)

The seeded calendar from `test_reconcile_db.py` (its seeding moves into `reconcile_support.py` so both files share it) run
through the **real graph with the real reader and the real writer**; only the model is scripted. This is the test A5 could
not write ("a real database round trip is A6's test").

- **parity with the simulator:** after the commit, `PostgresCalendarReader` over the plan's range returns what
  `reconcile_support.apply_plan` predicted for the same plan (compared on date, time, status, prices, lineup names, with ids
  mapped). This proves the A5 simulator mirrors the real write, so A5's idempotency test is evidence about the real thing;
- **idempotency:** run the same page again: the second plan is **all `no_op`**, no row in `show`, `show_artist` or `artist`
  changed (counts, and `updated_at` equal to the literal past value the seeded rows were given: inside the test transaction a
  rewritten row would get the transaction's `now()`, a different value, whereas two `now()`s would be equal and prove nothing:
  A6-PR1-3), and no per-show `commit` row was added (**A6-M4**: skipping the price conversion makes `20.0` compare unequal to
  the stored `Decimal("20.00")` and the second run updates);
- **the changes run:** a third run on an edited page (a lineup change, a vanished show, a returning show) writes exactly
  those, and `show_history` for the changed show returns the insert row, then the update row, with the snapshots;
- **the artists table** now holds exactly the old artists plus the new ones, once each;
- **a run with one failing show** leaves the other shows written, writes the failure row and the summary, and
  `unfinished_runs` does *not* list it (the summary was written), while a run whose writer raises a connection error *is*
  listed (**A6-M5**: the query counting per-show rows as "reached commit"). **The crash must come after at least one show was
  written** (A6-PR2-4): the injected writer delegates to the real `PostgresCalendarWriter` for the first operation, then raises
  `fakes.lost_connection()` on the second, and the test asserts that exactly one per-show `commit` row exists, that **no** summary
  row exists, and that the run is listed. A writer that raises on the first operation leaves no `commit` row, so both the correct
  query and the mutated one list the run and the check proves nothing. The one-failing-show failure is injected by a mechanism that
  exists on the real graph (A6-PR1-6): a **test-only constraint added inside the test transaction**, `ALTER TABLE show ADD
  CONSTRAINT tmp_no_end_time CHECK (end_time IS NULL) NOT VALID`, so that inserting a show with an end time raises
  `IntegrityError` (DDL is transactional in Postgres, so the outer rollback removes it; the build verifies that under the
  savepoint-mode connection), and, as the D2 scenario itself, a scripted page with one overflowing price. Seeding a stored
  row that makes the merged row free-and-priced cannot work: reconcile replaces the admission fields as one unit
  (`A5-D5`), and a listing that is itself free and priced fails validation (`FREE_WITH_PRICE`) and never reaches commit.

### Mutation checks (the proof the tests can fail)

Run by the build step on a scratch copy (a throwaway `git worktree`, removed afterwards), each recorded in the Implementation log.

| # | Break | The test that must go red |
|---|---|---|
| A6-M1 | read `previous` after the write instead of before | `test_previous_value_is_the_row_before_the_change` |
| A6-M2 | write the show's audit row through `AuditWriter.record` (its own session), or `commit()` before the rows are added | `test_audit_rows_roll_back_with_the_write` |
| A6-M3 | make `_create_artists` record created ids in a writer-level cache that outlives the transaction | `test_a_rolled_back_artist_is_not_remembered` |
| A6-M4 | write prices with `Decimal(float)` instead of `to_price` | `test_the_second_run_is_all_no_ops` |
| A6-M5 | count every `commit` row as "reached commit" in `unfinished_runs` | `test_a_run_that_crashed_mid_commit_is_unfinished` |
| A6-M6 | treat a connection-class failure as per-show (catch `Exception`, `SQLAlchemyError` or any `DBAPIError`) | `test_a_connection_error_stops_the_run` (with `08006` and `InterfaceError`) |

### Existing tests that change

`WorkerContext(...)` gains `writer=` at **eleven** call sites: `main.py`, `local_test.py`, `test_graph.py`, `test_graph_audit.py` (2),
`test_graph_reconcile.py` (2), `test_audit_queries.py` (2), `test_run_venue.py`, `test_reconcile_db.py` (a grep finds the same
eleven). Tests that don't care about the calendar get `fakes.FakeWriter()` (which still goes through `write_plan`, so those
tests are red while K2 is open, below); `test_audit_queries.py` uses the real `PostgresCalendarWriter` so its
`show_history` check runs against a real commit row (it hand-inserts one today); `test_reconcile_db.py` keeps a `FakeWriter`
so it continues to prove what its docstring says, that reconcile writes nothing (its "artists table is unchanged" test would
otherwise be asserting the wrong thing now that commit exists). `test_graph_audit.py`'s step lists gain the per-show commit
rows where the page has shows (the fake appends them), and `entry_for(COMMIT)` assertions change from the stub shape.

**Red while K2 is open, and why that is acceptable** (A6-PR1-4). `write_plan` is real code on every path to commit, so a run
with at least one insert, update or remove reaches K2's `NotImplementedError` even with a `FakeWriter`. The reviewer's probe
(the placeholder approximated by raising in `commit_node` on those runs) measured **31** existing tests: `test_graph.py` 10,
`test_graph_audit.py` 6, `test_graph_reconcile.py` 3, `test_run_venue.py` 2, `test_audit_queries.py` 6 (errors),
`test_reconcile_db.py` 4 (errors). Until K2 is filled, a regression in the retry loop, the audit rows or reconcile is hidden among
those reds. A4 (K1 and K3) and A5 (all five gaps) accepted the same trade, and the Implementation log will list the red tests
by file with the reason, as theirs did. **The alternative** is to make `write_plan` skip its loop when handed a fake, or to put
K2's placeholder where only the real writer reaches it; the plan does not, because the gap would then not sit in the loop it
teaches. This is Ari's call at approval: say so if you would rather keep the old tests green.

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
  And in tests `now()` is the outer transaction's start time, so an `updated_at` assertion compares against a literal
  past value the row was seeded with, never two readings of `now()` (A6-PR1-3; the same trap `finished_at` set in A4-CR1-5).
- **The driver's exception classes lie about data errors.** With asyncpg only integrity violations arrive as
  `IntegrityError`; an overflow is a plain `DBAPIError` (`22003`), a CHECK violation an `IntegrityError` (`23514`), and a **real
  lost connection an `InterfaceError` whose `orig.sqlstate` is `None` and whose `connection_invalidated` is `True`** (measured
  both by killing the backend with `pg_terminate_backend` and by closing the raw connection; neither produced an `08006`).
  Classify by `getattr(err.orig, "sqlstate", None) or ""` (A6-PR1-1, A6-PR2-1). The tests' errors come from one shared helper in
  `tests/fakes.py` that builds each real shape (`overflow()`, `check_violation()`, `lost_connection()`), used by the unit test,
  by `FakeWriter` and by the stub writers, so no test invents a shape the driver never produces. A `08006` /`57P01`
  `DBAPIError` is kept as one extra case: the rule must treat any non-22/23 SQLSTATE as run-level.
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

**Fill order:** K1, then K2 (K2 needs a writer that works). Until K1 is filled **every test that uses the real
`PostgresCalendarWriter` is red**: layers 3 and 5, and the `test_audit_queries.py` checks that run a real commit. Until K2
is filled **every test that reaches `write_plan` with a non-empty plan is red, fakes included** (layer 4 and the 31 existing
graph tests listed under "Existing tests that change"): `write_plan` is real code on that path whatever writer it is handed.
The Implementation log lists the red tests by file with the reason, as A4 and A5's did (A6-PR1-4).

- **K1 — one show, one transaction, in `calendar_writer.py` (`PostgresCalendarWriter.write_show`).** *(Build plan A6, first
  item; D3; `arch-initial.md` §7.)*
  - *Lesson:* a write and its record are **one unit**. The `audit_log` row goes in the *same* session and transaction as
    the change, so they commit or roll back together: a rolled-back show leaves no audit row, and a committed one can't lose
    its record. And the snapshots are taken in a deliberate order: `previous` **before** the change (the ORM hands back the
    same object after it, mutated), `new` **after** the flush (so it holds what the database holds). Those two snapshots
    are what a future revert restores (`data-model-initial.md` §3). The last half of the lesson: **nothing outlives the
    transaction except the return value.** The ids of the artists this show created go back only in `ShowWritten`, and the
    ids the lineup uses are a fresh merge, `{**artist_ids, **created}`, never a write into the caller's map or a cache on
    the writer, because an id remembered from a transaction that later rolls back is a lie the next show would link to.
  - *Code:* the helpers (`_create_artists`, `_snapshot`, `_apply`, `_audit_rows`) are written; the gap is the block that orders them:
    ```python
    async with self._session_factory() as session:
        async with session.begin():
            created = await self._create_artists(session, op, artist_ids)
            previous = await self._snapshot(session, op.stored_id, lock=True) if op.stored_id is not None else None
            show_id = await self._apply(session, op, {**artist_ids, **created}, venue_id)
            new = await self._snapshot(session, show_id)
            session.add_all(audit_row(e) for e in self._audit_rows(op, created, show_id, previous, new, run_id, attempt_number))
    return ShowWritten(show_id, op.outcome, created)
    ```
  - *Check:* `uv run pytest agent_worker/tests/test_calendar_writer.py -k "insert or update or removal or previous or roll_back or rolls_back or one_session or check_constraint or overflowing_price_is or vanished or restoring"` (corrected in code review, A6-CR1-4: the first draft named `atomic`, which matches nothing, and left out the update, removal and vanished-show tests). After filling K1, also delete the noqa comment on the `audit_row` import, which `ruff` then rejects as unused.
    The likeliest mistake is taking `previous` after `_apply` (the identity map returns the mutated object, so
    `previous_value` equals `new_value`: the "previous is the row before the change" test goes red); the second is writing
    the audit rows through `AuditWriter.record` or calling `session.commit()` before they are added (only
    `test_audit_rows_roll_back_with_the_write` goes red: the foreign-key test fails earlier, before the audit rows exist, so
    it cannot see this); the third is keeping created ids anywhere but the return value (the "rolled-back artist is not
    remembered" test goes red).

- **K2 — what survives a failed show, in `calendar_writer.py` (`write_plan`).** *(Build plan A6; D2.)*
  - *Lesson:* a failure about **one show** is not a reason to stop, and a failure about the **run** is, and the line between
    them is **what the database says about this row**, not which Python class the driver happened to raise. SQLSTATE class
    `22` (a data exception: the overflow) and `23` (an integrity violation) are about the row; a lost connection, or a bug
    in our code, must propagate. `is_decision_error` (written) holds that rule, so the `except` clause names the broad
    types (`DBAPIError`, `ShowGone`) and re-raises when the rule says no: never `except Exception`
    (`apps/api/AGENTS.md`), and never `except SQLAlchemyError` that swallows a dead connection. The artist map is extended
    only from what `write_show` returned, after the write, so a failed show contributes nothing to it.
  - *Code:*
    ```python
    try:
        written = await writer.write_show(op, artist_ids, venue_id=venue_id, run_id=run_id, attempt_number=attempt_number)
    except (DBAPIError, ShowGone) as err:
        if not is_decision_error(err):
            raise
        failures.append(await record_failure(audit, op, err, run_id, attempt_number))
        continue
    artist_ids.update(written.created_artists)
    tally[written.outcome.value] += 1
    ```
  - *Check:* `uv run pytest agent_worker/tests/test_calendar_writer.py -k "created_once or remembered or overflowing or connection or failing_show or show_gone or all_failed or created_so_far"`
    and `test_graph_commit.py -k failing` (corrected in code review, A6-CR1-4: `-k failed` collected nothing). The likeliest mistake is catching `Exception`, `SQLAlchemyError` or any `DBAPIError`
    without the SQLSTATE test (the "connection error stops the run" test goes red, with `08006` and with the real
    `lost_connection()` shape); the second is forgetting that the overflow is **not** an `IntegrityError` (catching only
    `IntegrityError` makes the overflow test, the D2 scenario, go red). The SQLSTATE rule itself is the written
    `is_decision_error`, whose own unit test (the real `lost_connection()` shape must be False and must not raise) guards it.
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

`CalendarWriter`, `ShowWritten`, `is_decision_error`, `ShowGone`, `PostgresCalendarWriter` with its helpers, `write_plan`,
`record_failure`.

### 5. Wiring (written)

`context.py`, `state.py`, `nodes.py` (`commit_node`), `trace.py` (the commit branch, with a comment block saying why the write
is awaited there and why the summary row comes last), `main.py` (the writer; `run_all` counts commit failures), `local_test.py`
(builds the writer; prints what was written and what failed; **exits 1 when `commit_result.failures` is non-empty**, as `main` does
through `run_all`: A6-PR2-5), and `tests/fakes.py`.

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
| `apps/api/agent_worker/calendar_writer.py` (new) | `CalendarWriter`, `PostgresCalendarWriter` (K1), `write_plan` (K2), `is_decision_error` |
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
   suite, ruff clean. Expect red, by design, wherever a test reaches `write_plan` with a non-empty plan or uses the real
   writer (K1, K2): the new tests, and about **31** existing ones (the reviewer's probe: `test_graph.py` 10,
   `test_graph_audit.py` 6, `test_graph_reconcile.py` 3, `test_run_venue.py` 2, `test_audit_queries.py` 6,
   `test_reconcile_db.py` 4; re-measure at build). The log lists them by file with the reason. Everything else must be
   green. The JS suite is untouched.
2. Gaps verified filled on a scratch copy (a throwaway `git worktree`, removed afterwards): with both filled the whole suite is
   green; the result is recorded in the Implementation log (the A3/A4/A5 pattern).
3. The six mutation checks (A6-M1 to A6-M6) run on a scratch copy and recorded.
4. `uv run mypy` on `commit.py` and `calendar_writer.py` is clean; `make designation-check BASE=<the diff base>` exits 0.
5. No migration, so no `alembic` round trip; `make contract-check` stays green.

**Locally (Ari, after filling the gaps; needs Docker and Ollama):**

6. `make db-reset && make seed`, then `cd apps/api && uv run python -m agent_worker.local_test`. Expect, for the White Squirrel
   fixture (A5's local run: 12 shows, 27 artists): 12 inserts **written**, 27 artists created, in `audit_log` one row per
   new artist (written before the show that first needs it) and one per show, then one `commit` summary row with
   `counts.inserted = 12`.
7. Run it again. Expect the plan all `no_op`, nothing written, no new `show`, `show_artist` or `artist` row, `updated_at`
   unchanged, one new `commit` summary row with `counts.no_op = 12`. This is the check A5 could not do.
8. Edit the database by hand to simulate a page change (`make db-shell`): change a show's `end_time`, delete one of its
   `show_artist` rows, and set one show's `start_time` to a time the page doesn't list. Run again: one `updated` (with
   `previous_value` / `new_value` differing in `end_time` and `lineup`), and the changed-time show is removed and re-inserted.
   Run the `show_history` query for the updated show.
9. The failure path (D2): `ALTER TABLE show ADD CONSTRAINT tmp_no_end_time CHECK (end_time IS NULL) NOT VALID;`, delete one
   show **and its `show_artist` rows first** (`show_artist_show_id_fkey`), run. Expect the insert of that show (it has an end time) to fail, a `failed_commits` row (with the show's date and time), the others unaffected, and exit
   status 1 (`local_test` exits 1 on commit failures); then drop the constraint and run once more to see it converge.
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

**Ari, October 20, 2026:** decided D1, D2 and D3 as recommended (option A): an unchanged show writes no audit row; a data error on one show is recorded and the others are still written; a snapshot is the whole `show` row (minus timestamps) plus its lineup. **Ari, October 20, 2026: approved the plan** ("I am aligned with the recommendations on D1-3. Approved to proceed to implementation. /build-milestone docs/dev/implementations/a6-commit.md"). `/build-milestone` set the status to `Approved` at step 0. Ari did not comment separately on the one non-numbered question (about 31 existing graph tests red while K2 is open); approving the plan as written keeps K2 in `write_plan`'s loop, and that is how it is built. No [written] item was re-marked [fill-in] or the reverse.

**For Ari to decide before approving:** D1, D2 and D3 above, and one more that is not a numbered decision: while K2 is open,
**about 31 existing graph tests are red** (not only the new ones), because `write_plan` is real code on every path to commit
(A6-PR1-4; "Existing tests that change"). A4 and A5 accepted the same trade; say so if you would rather keep them green and
accept a different gap placement. Also veto-or-accept the Settled details, in particular the two the review corrected:
removals-last (it helps a run that stops, not one that carries on) and the SQLSTATE rule for what counts as one show's failure.

**Ari, October 20, 2026: signed off. A6 is Done.** Ari filled the two key points himself (A6-K1 and A6-K2, commit `5204c38`, whose message
says A5 by mistake), looked over the key parts of the code and ran the local verification (Verification steps 6 to 10: Postgres,
MongoDB and Ollama), which found everything in order. Plan review rounds 1 and 2 (19 findings) and code review round 1 (7
findings) are all resolved. The scaffold was cleaned up on October 20 (Implementation log round 3). Not verified, and not claimed:
concurrent workers on one venue, a stale plan overwriting a human edit (there are none yet), and revert itself (only that a snapshot
suffices); the artist-match thresholds still wait for A8.

## Plan review

### Round 1 — Claude Opus 5.5, October 19, 2026

**Scope.** The plan as committed in `81e2579` ("A6: draft the commit implementation plan"). The author committed it while
this review was running; the reviewed text and the committed file are the same 665 lines. This is a plan review, so no
code exists yet.

**What was checked and how.**
- **Docs read:** `AGENTS.md` ([fill-in] tasks; Implementation plans); `apps/api/AGENTS.md`; `docs/references/fastapi-style-guide.md`
  (Anti-patterns); build plan §5 A5–A7; `arch-initial.md` §7 (Reconcile, Audit trail extensions, Revert, the "Built in A5"
  paragraph); `data-model-initial.md` §3 `audit_log` and the A1 departures; `a5-reconcile.md` (Known gotchas, Not doing,
  plan review round 1).
- **Code read:** `reconcile.py`, `artist_match.ArtistResolution`, `audit.py`, `trace.py`, `state.py`, `context.py`,
  `calendar_reader.py`, `main.py`, `nodes.commit_node`, `graph.py`, `app/db/base.py`, `app/db/models/*.py`, `app/db/session.py`,
  `app/enums.py`, `docs/dev/audit-queries.sql`, `tests/reconcile_support.apply_plan`, and the `WorkerContext(` call sites (grep).
- **Run in a throwaway `git worktree` of HEAD (with a copy of `.env`), removed afterwards:**
  - The API suite with `REQUIRE_DB=1`: **790 passed, 15 skipped**, which matches the plan's baseline (CONFIRMED).
  - A probe of what the K2 placeholder will do to existing tests. `commit_node` was patched to raise `NotImplementedError` whenever
    the plan holds an insert, update or remove, which is the set of runs on which `write_plan`'s loop body would run. Result:
    **21 failed and 10 errors** where the baseline had none (finding 4).
  - A probe test on `calendar_test` with the savepoint-mode factory `test_audit_writer.py` uses. It checked three things.
    First, which exception each failure in the plan raises: a `Numeric(10, 2)` overflow raises plain `DBAPIError`, while a
    CHECK violation and an FK violation raise `IntegrityError` (finding 1). Second, that `session.begin()` nests as a
    savepoint and an FK failure after the show was flushed leaves 0 `show` rows (CONFIRMED, as the plan's gotcha says).
    Third, whether `updated_at` moves on an ORM UPDATE in a test transaction: it doesn't (finding 3).
  - `to_jsonable_python` gives `"20.00"`, `"20:00:00"`, `"2026-10-20"` and `"active"`, as the plan says (CONFIRMED). The
    `Show` table's columns are the plan's 16 snapshot keys plus `created_at` and `updated_at` (CONFIRMED).

**What holds up.** The unit of work (one show, its lineup, its new artists and its audit rows in one transaction) is what
the build plan asks for. Reading both snapshots from the database inside the transaction is the right call. The three
decisions are framed as real choices, each with its cost. The `unfinished_runs` change (count only the summary row) is
correct, and A6-M5 pins it. The tests come first, layered from pure to the real graph, and the A5 simulator gets the
real round trip A5 deferred. K1 sits where the concept lives. The "no migration, no schema change" claim is true.

**Counts:** 1 blocker, 5 should-fix, 5 nits.

**Verdict:** *proceed after fixes.* The blocker is in ★ D2's mechanism: the failure Ari is asked to decide about is not
caught by the `DECISION_ERRORS` the plan names, so D2 and K2 need rewording before Ari decides. Of the should-fix rows,
two are tests that cannot fail, or cannot pass, as designed (A6-M2, `updated_at`). One is a red-test list that is wrong
by 31 tests. One is a rationale given to Ari that is false under the recommended D2. The last is a test with no stated
mechanism.

| # | Sev | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|
| 1 | blocker | **`DECISION_ERRORS = (IntegrityError, DataError, ShowGone)` doesn't catch D2's own example.** On this driver a data exception never arrives as `DataError`. SQLAlchemy's asyncpg dialect maps `IntegrityConstraintViolationError` to `IntegrityError` and every other `PostgresError` to the generic `Error`, so a `Numeric(10, 2)` overflow (SQLSTATE `22003`), and any other class-22 error, is a plain `DBAPIError`. `DataError` is a dead entry in the tuple. The dialect has no `OperationalError` mapping either. A dropped connection comes back as `InterfaceError` (`ConnectionDoesNotExistError`) or as a generic `DBAPIError` (e.g. `57P01`), so the stub's `OperationalError` is not what a real lost connection looks like. Fix: classify by SQLSTATE class, not by Python class. Catch `DBAPIError` and keep it as a per-show failure only when `getattr(err.orig, "sqlstate", "")` starts with `22` (data exception) or `23` (integrity violation); re-raise everything else. Update D2's text, the K2 lesson and code ("what the database says about this row", not "which exception class"), and the layer-3 overflow test (expect a per-show failure, not `DataError`). A6-M6 should use the real shapes: a `DBAPIError` whose `orig.sqlstate` is `08006`, and an `InterfaceError`, must both propagate. | CONFIRMED (worktree probe, SQLAlchemy 2.0.52, asyncpg 0.32.0): the overflow raised `sqlalchemy.exc.DBAPIError`, with `orig` = `AsyncAdapt_asyncpg_dbapi.Error`, sqlstate `22003`, and cause `asyncpg.exceptions.NumericValueOutOfRangeError`. The CHECK violation and the FK violation raised `IntegrityError`. The mapping table is in `.venv/…/sqlalchemy/dialects/postgresql/asyncpg.py:1010-1020`. Plan lines 136-142, 250, 376-377, 515-534. | The scenario Ari decides ★ D2 on doesn't happen under either option. The first show with an overflowing price raises out of `write_plan`, `main.RUN_ERRORS` files the whole venue as failed, and the shows after it are never written. No failure row and no summary row are written, so the run reads as a crash in `unfinished_runs`. The layer-3 overflow test fails during the build, and the fix then lands in the K2 lesson after Ari has approved its wording. | **Fixed.** `DECISION_ERRORS` is gone. `calendar_writer.is_decision_error(err)` classifies by SQLSTATE: true for `ShowGone` and for a `DBAPIError` whose `orig.sqlstate` starts with `22` or `23`, false for everything else (`08006`, `57P01`, `InterfaceError`, `NoResultFound`, bugs). I re-checked the dialect mapping (`asyncpg.py`, `_asyncpg_error_translate`): only `IntegrityConstraintViolationError` is mapped to a specific class. Changed: D2 option A's text (the rule, and why it is not by Python class), the Design section (signature and docstring), K2's lesson, code (`except (DBAPIError, ShowGone)` then `if not is_decision_error(err): raise`) and Check, the layer-3 tests (the overflow is a `DBAPIError` `22003`; a unit test of `is_decision_error` on the real shapes; the D2 overflow scenario is a real test), A6-M6 (`08006` and `InterfaceError`), the 'driver lies' gotcha, and the Critical files / writer step names. The build must confirm `err.orig.sqlstate` is present on this driver, as the probe found. |
| 2 | should-fix | **A6-M2 can't go red, and neither can the K1 Check's second "likeliest mistake".** K1 writes the audit rows last (`_apply`, then `_snapshot`, then `session.add_all(...)`). The atomic test's failure (the FK on `show_artist`) is raised by `_apply`'s flush, before the audit line runs. Two mutations both leave that test green: writing the audit rows through `AuditWriter.record` at that same place, and calling `session.commit()` before they are added. In both, the failing op never reaches the audit step. The overflow and CHECK tests fail in `_apply` too. To catch the mutation, the failure has to come *after* the audit rows are handed over. Option: a test subclass of `PostgresCalendarWriter` whose `_audit_rows` yields the real entries and then raises a per-show error (a `DBAPIError` carrying a class-23 sqlstate, per row 1). With the correct K1 nothing survives. Under the mutation, the rows yielded before the raise were committed in their own sessions. Option: on a successful write, assert that the `show` row and its `audit_log` row have equal `xmin`. In savepoint mode each session's savepoint gets its own subtransaction id, so a row written by a separate session differs. | CONFIRMED by reading K1's code (plan lines 502-507) together with the probe: the FK violation was raised at the `show_artist` flush, and the show insert before it was rolled back (0 rows left). | The mutation table (line 433) claims protection the suite doesn't give. The first half of K1's lesson, that the write and its record are one unit, ends up with no test that can fail. | **Fixed.** The reviewer is right: the FK test fails in `_apply`, before the audit rows are added. Added `test_audit_rows_roll_back_with_the_write` (layer 3): a test subclass whose `_audit_rows` yields the real entries and then raises `IntegrityError`; with the correct K1 nothing survives, under A6-M2 the rows were already committed. A6-M2 now names that test, and K1's Check says that only it can see the second mistake. The FK test stays, described as proving the data rolls back. I did not use the `xmin` option: the savepoint behaviour it relies on was not verified. |
| 3 | should-fix | **The `updated_at` assertions are wrong in a test transaction.** `TimestampMixin.updated_at` uses `onupdate=func.now()`. `now()` is the start time of the *outer* test transaction, and the savepoints don't change it. So in savepoint mode an UPDATE leaves `updated_at` equal to the value the insert gave it. Two tests depend on it. Layer 3's "`updated_at` moves even for a lineup-only change" fails even with a correct writer. Layer 5's idempotency assertion that `updated_at` is unchanged passes even if the second run rewrites every row. This is the trap A4-CR1-5 hit with `finished_at`. Fix: seed the stored rows with a literal past `updated_at` (e.g. `2026-01-01T00:00Z`) and assert that it changed, or stayed, against that literal. Or have the writer set `updated_at = func.clock_timestamp()` itself on every update, and say why. | CONFIRMED (worktree probe): a show was inserted in one savepoint and its `end_time` updated through the ORM in another, with `eager_defaults` returning the value. `updated_at` before and after: `2026-10-19 23:21:11.843834+00:00` both times. `app/db/base.py` `TimestampMixin`. | One test is red with no bug behind it, and the obvious "fix" is to drop the assertion. The idempotency check's `updated_at` half is vacuous, so it can't catch a second run that rewrites rows without changing their values (the other halves of A6-M4 still work). | **Fixed.** The `updated_at` tests now seed rows with a literal past value (`2026-01-01T00:00Z`) and compare against it: the layer-3 lineup-only update test (it must move to the transaction's `now()`) and the layer-5 idempotency check (it must stay at the literal). The Settled detail says the writer sets `updated_at = func.now()` explicitly on every update and why the tests use a literal, and a gotcha records the trap next to the `finished_at` one from A4-CR1-5. I kept `func.now()` rather than `clock_timestamp()` (the reviewer's other option) because the column's own `onupdate` is `now()` and an update in production gets the same value either way. |
| 4 | should-fix | **While K2 is open, 31 existing tests go red, but the plan says the fakes keep the graph tests green.** `write_plan` is real code on every path that reaches commit, and `FakeWriter` doesn't bypass it. K2's `NotImplementedError` sits in the loop body, so any run with at least one insert, update or remove raises before a fake is called. That covers most of A3's graph tests (a passing page's shows are inserts against `FakeReader`'s empty calendar). It also covers `test_reconcile_db.py`, which the plan keeps on a `FakeWriter` "so it continues to prove … reconcile writes nothing". Fix: either list these files and counts as expected-red in "TODO(Ari) gaps" and Verification 1, saying that A3–A5's graph tests lose their guard until K2 is filled (A4 and A5 accepted red tests, so Ari can accept this knowingly), or restructure so that the fake path doesn't reach the placeholder. Ari's call. | CONFIRMED (worktree probe, approximating K2 by raising in `commit_node` on the same runs): 21 failed and 10 errors, where the baseline is 710 passed for `agent_worker/tests`. By file: `test_graph.py` 10, `test_graph_audit.py` 6, `test_graph_reconcile.py` 3, `test_run_venue.py` 2, `test_audit_queries.py` 6 (errors), `test_reconcile_db.py` 4 (errors). Plan lines 315-317, 489-491, 622-624. | Verification 1's "everything else must be green" can't be met, and the Implementation log's red list will be wrong. While the gaps are open, a regression in the retry loop, the audit rows or reconcile is hidden among the expected reds. | **Fixed (documented; Ari decides).** Accepted as the reviewer states it: `write_plan` is real on every path to commit, so a fake writer does not avoid K2's placeholder. The test approach intro, 'Existing tests that change' (a new 'Red while K2 is open' paragraph with the by-file counts: 31 = 21 failed + 10 errors), 'TODO(Ari) gaps' (fill order) and Verification 1 now say so. A4 and A5 accepted the same trade, and the paragraph names the alternative (keep the old tests green by having the placeholder reached only by the real writer) and says it is Ari's call at approval. I did not restructure, because K2 would then no longer sit in the loop it teaches. The counts are the reviewer's probe, to be re-measured at build. |
| 5 | should-fix | **The "removals last" rationale given to Ari is false under the recommended D2.** Settled details says that if "one write fails, a time change (remove 8 PM, insert 9 PM) is left as a duplicate rather than a gap". Under D2 option A the loop `continue`s past a failed insert and still applies the 8 PM removal, which leaves a gap. If the failure is deterministic, the show is missing from the calendar every night until a person fixes it. Ordering removals last only helps a run that *stops*: option B, or a connection error. Fix: correct the sentence, and add this to D2's "Cost of A" so Ari decides with it in view. Holding back a removal on the date of a failed insert would be a judgement made in commit, which "commit adds no judgement" argues against, so stating the cost is probably enough. | CONFIRMED by reading plan lines 175-178 against K2's code (lines 523-527) and D2 option A (lines 138-142). | Ari vetoes or accepts a settled detail on a false premise. The calendar then loses a show that has moved time, which is the unsafe direction `A5-D1` names. | **Fixed.** The Settled detail now says removals-last helps a run that stops (a lost connection, or D2 option B) and does **not** help a run that carries on past a failed insert. D2's 'Cost of A' now states the gap case (the insert half of a time change fails deterministically, the 8 PM show is removed, the 9 PM show never appears, nightly), and says why the plan states the cost rather than building a hold-back in commit: that would be a judgement commit does not make. Ari decides D2 with the cost in view. |
| 6 | should-fix | **Layer 5's "run that fails mid-commit … an op that violates the CHECK, injected by seeding a conflicting row" has no route through the real graph.** Reconcile replaces the three admission fields as one unit (`A5-D5`, `show_changes`), so a seeded stored row can't make the merged row free and priced. A listing that is itself free and priced is a validation *error* (`FREE_WITH_PRICE`), which retries or escalates and never reaches commit. Fix: name a mechanism that exists. One is a test-only constraint added inside the test transaction (`ALTER TABLE show ADD CONSTRAINT … CHECK (…) NOT VALID`; DDL is transactional, so the outer rollback removes it). That is the trick Verification 9 uses by hand. Another, once row 1 makes `22003` a per-show error, is a scripted page with one overflowing price. | PLAUSIBLE (reasoned, not run): `reconcile.py:538-546` (the admission unit), `validation.py:223-229` (`FREE_WITH_PRICE` is `Severity.ERROR`), plan line 422. | The build either can't write A6-M5's companion test as described, or invents a path that doesn't exercise the real graph. The "others are still written, and the summary exists" property then goes untested end to end. | **Fixed.** Layer 5 now names two mechanisms that exist on the real graph: a test-only `ALTER TABLE show ADD CONSTRAINT tmp_no_end_time CHECK (end_time IS NULL) NOT VALID` inside the test transaction (DDL is transactional; the build verifies the outer rollback removes it under the savepoint-mode connection), and, as D2's own scenario, a scripted page with one overflowing price. The test description records why a seeded conflicting row cannot work (`A5-D5` replaces the admission fields as a unit; a free-and-priced listing fails validation). |
| 7 | nit | **The `previous` snapshot is read before the row is locked, and a vanished row surfaces in the wrong place.** In K1's order `_snapshot(session, op.stored_id)` runs before `_apply`, and `_apply` is where the row is loaded `with_for_update=True` and `ShowGone` is raised. So `previous` is an unlocked read, and a row that has disappeared fails first in `_snapshot`. That is probably a `NoResultFound`, which `DECISION_ERRORS` doesn't catch and which therefore stops the run. Fix: take the lock and raise `ShowGone` in the first read, and snapshot the locked row. | PLAUSIBLE: plan lines 258, 264-268, 504. | A row deleted by hand between reconcile and commit stops the venue's run instead of being recorded as one failed show. That contradicts D2's "the show having vanished" case. | **Fixed.** `_snapshot(session, show_id, *, lock=False)`: for an update or remove, the first read is `_snapshot(session, stored_id, lock=True)`, which selects `FOR UPDATE` and raises `ShowGone` if the row is missing, so `previous_value` comes from the row that stays locked and a vanished row is a per-show failure (and `is_decision_error` is true for it), not a `NoResultFound`. Design bullets and K1's code updated; `_apply` finds the row already in the session. |
| 8 | nit | **K1's text doesn't match D3, and its code leaves out the line that owns the session.** The K1 lesson and the `_snapshot` note say `new` holds "`updated_at` included", but D3 drops both timestamps from every snapshot (`SNAPSHOT_EXCLUDED`). K1's code starts at `async with session.begin():`, without the `async with self._session_factory() as session:` around it. That line is the "fresh session per show" the gotchas rely on, and it belongs in the code Ari types. | CONFIRMED by reading plan lines 218, 264-266, 497-509, 472-473. | A learner reads a contradiction between the lesson and the decision. A pasted block has no `session`. | **Fixed.** 'updated_at included' is gone from K1's lesson and from the `_snapshot` note (D3 excludes both timestamps; the note now says so). K1's code now starts at `async with self._session_factory() as session:` and nests `async with session.begin():`, matching the Design sketch, and the `return` follows both. |
| 9 | nit | **The second half of K2's lesson, and A6-M3, can't be got wrong inside K2's lines.** `written` exists only after `write_show` has returned, so the K2 loop has no way to remember a rolled-back artist. The mistake can only be made inside the writer: `_create_artists` writing into the caller's map, or K1 merging into `artist_ids` instead of `{**artist_ids, **created}`. Fix: move that clause to K1's lesson, where `{**artist_ids, **created}` is typed, or say that A6-M3 mutates `_create_artists`. | CONFIRMED by reading plan lines 245-246 (`artist_ids: Mapping`), 505, 518-534, 434. | K2's "likeliest mistake #2" points Ari at a mistake his lines can't make. | **Fixed.** The reviewer is right that K2's lines cannot make the 'remember before the write' mistake. The clause moved to K1's lesson as 'nothing outlives the transaction except the return value' (created ids go back only in `ShowWritten`; the lineup uses a fresh `{**artist_ids, **created}`; no writer-level cache), with a third likeliest mistake in K1's Check. A6-M3 now mutates `_create_artists` to cache created ids on the writer, which K1/the writer's code can get wrong. K2's lesson keeps the true half (extend the map from the return value only) without claiming a mistake. |
| 10 | nit | **The snapshot key pin may be tautological.** The plan says the key set is "built from the model's mapped columns", while `snapshot_of(columns, lineup)` is pure and is tested with a literal show. If `snapshot_of` copies whatever keys it is given, layer 1's "the key set equals the list above" only checks the test's own input, and a migration that adds a column changes nothing it can see. Fix: say where the column list lives (e.g. `commit.SNAPSHOT_COLUMNS`, derived from `Show.__table__.columns` minus `SNAPSHOT_EXCLUDED`), have `snapshot_of` take exactly those keys, and pin that list against the literal list in a test. | CONFIRMED: `Show.__table__.columns` is the 16 keys at plan line 230 plus `created_at`, `updated_at` (python probe). Plan lines 226-233, 341-344. | The test that should make a new column a visible change can't fail. | **Fixed.** `commit.SNAPSHOT_COLUMNS` (derived from `Show.__table__.columns` minus `SNAPSHOT_EXCLUDED`) is in the types block; `snapshot_of` takes exactly those keys from its input (a missing one is an error, an extra is dropped). The layer-1 test pins `SNAPSHOT_COLUMNS` against the literal 16-key list, so a migration that adds a column turns it red. `commit.py` may import `app.db.models` (as `reconcile.py` imports `app.enums`). |
| 11 | nit | **Counts that don't add up.** (a) Layer 3's insert expects "**three** audit rows: the artist's, the show's", which names two. With one new artist there are two rows. (b) Verification 6 says "three rows per new-artist show". It is one row per new artist plus one for the show. (c) "`WorkerContext(...)` gains `writer=` at **ten** call sites", but the list adds up to eleven, and grep finds eleven. (d) Verification 9's "delete one show" first needs that show's `show_artist` rows deleted (`show_artist_show_id_fkey`). | CONFIRMED: plan lines 365-367, 634-635, 441-442, 642; `grep -rn "WorkerContext(" apps/api/agent_worker` (11 sites outside `context.py`); `app/db/models/calendar.py` `ShowArtist.show_id`. | The tests or the local check get written to the wrong number, and the manual step fails on the FK. | **Fixed.** (a) Layer 3 insert: two audit rows for a show with one new artist (one per new artist, then the show's). (b) Verification 6: one row per new artist and one per show, then the summary. (c) 'eleven' call sites (the list was right; the count word was wrong). (d) Verification 9 deletes the show's `show_artist` rows first. |

**Rejected:** none. Round 1 resolved by the author (Claude Sonnet 5.5), October 19, 2026: 11 of 11 fixed (row 4 fixed by
documenting the consequence, with the alternative and the decision left to Ari). The blocker (row 1) changed the wording of
★ D2, which Ari is asked to decide, and K2's lesson, code and check; rows 2, 3 and 6 added or changed tests; row 7 moved the row
lock to the first read. No round 2 was run. The change to D2 and K2 is substantial enough that Ari may want one before
approving; I would run it if you want a second look at the SQLSTATE rule.

### Round 2 — Claude Opus 5.5, October 20, 2026 (targeted: D2 and K2)

**Scope.** The plan as committed at `24bf94a`, read cold. The review covers only ★ D2 and the K2 gap (`write_plan`), plus
what they depend on or feed: `is_decision_error` and the SQLSTATE rule, the failure rows and the summary row's `failed`
list, `main.run_all`'s handling of commit failures, the `unfinished_runs` and `failed_commits` queries where they touch
failures, the layer-3, 4 and 5 tests and A6-M3 / A6-M6 on the failure path, and three Settled details: removals last,
failure rows written outside the rolled-back transaction, and what stops the run. Everything else in the plan is out of
scope and was not re-reviewed. This is still a plan review, so no A6 code exists yet.

**What was checked and how.**
- **Read:** round 1 and its resolutions; `agent_worker/main.py` (`RUN_ERRORS`, `run_venue`, `run_all`), `trace.py`,
  `audit.py` (`_VENUE_LEVEL`, `PostgresAuditWriter.record`), `context.py`, `local_test.py`, `docs/dev/audit-queries.sql`
  (`unfinished_runs`), `app/db/models/calendar.py` (no unique constraint on `artist`), `tests/fakes.RecordingAudit` and
  `test_run_venue.py`. I also read SQLAlchemy's asyncpg dialect: `_handle_exception` (`asyncpg.py:781-800`), the
  translation table (`:1010-1020`) and `is_disconnect` (`:1176`).
- **Versions:** SQLAlchemy 2.0.52 and asyncpg 0.32.0, from the repo's `.venv`.
- **Experiments:** run in a throwaway `git worktree` of `24bf94a` (with a copy of `apps/api/.env`), as a scratch pytest
  file on `calendar_test` with `REQUIRE_DB=1`. The worktree was removed afterwards and `git worktree list` shows only
  the main tree. Results, all CONFIRMED:
  - **The failure loop works in savepoint mode** (the `test_audit_writer.py` factory). A write of a `Numeric(10, 2)`
    overflow in its own session and `begin()` raised `DBAPIError`, with `orig.sqlstate = '22003'` and cause
    `NumericValueOutOfRangeError`. After it, a failure row written through `PostgresAuditWriter(factory).record`
    succeeded, and so did a good show write in a fresh session. The final count was 1 `show` and 1 `audit_log`.
  - **Layer 5's test-only constraint works and goes away on rollback.** `ALTER TABLE show ADD CONSTRAINT tmp_no_end_time
    CHECK (end_time IS NULL) NOT VALID` on `db_conn` made an insert with an end time raise `IntegrityError` `23514`. The
    next test found 0 rows for that constraint in `pg_constraint`. Round 1's resolution left this for the build to
    check; it is now checked.
  - **Errors that come from page text are classified per show.** A NUL byte in `image_url` raised `DBAPIError` `22021`.
    A lone surrogate raised `DBAPIError` `22000`. Both have class 22, so the rule treats both as one show's failure.
  - **Bug-shaped errors are also class 22 / 23** (finding 2). A NOT NULL violation raised `IntegrityError` `23502`. An
    invalid enum text raised `DBAPIError` `22P02`.
  - **A real lost connection is an `InterfaceError` whose `orig.sqlstate` is `None`** (finding 1). I tried two ways:
    killing the session's backend with `pg_terminate_backend` from a second connection, and closing the raw asyncpg
    connection under the session. Both raised `sqlalchemy.exc.InterfaceError`, with `orig.sqlstate = None`,
    `connection_invalidated = True` and cause asyncpg `InterfaceError`. Neither raised the `08006` or `57P01` shapes the
    plan's tests use. The plan's literal rule, `getattr(err.orig, "sqlstate", "")[:2]`, raised
    `TypeError: 'NoneType' object is not subscriptable` on both.
  - Aside, out of scope, not counted: a `Decimal("NaN")` price is **written**, not refused, because `numeric(10, 2)`
    accepts NaN. If extraction can ever produce one, that belongs to validation or `to_price`, not to D2.

**What holds up.** Classifying by SQLSTATE class is the right rule on this driver. The dialect maps only
`IntegrityConstraintViolationError` to its own class, and every other server error becomes the generic `Error`, so a
Python-class rule can't work. The rule is also right about data from a venue's page: overflow, bad characters and
constraint violations all land in 22 / 23. K2 sits where the concept lives. Its `except (DBAPIError, ShowGone)` plus
re-raise is the correct shape, and it can't make the artist-cache mistake, which round 1 moved to K1. "Removals last"
is now stated correctly. Failure rows go through `AuditWriter.record` and survive the rollback, as shown above.
`run_all` already treats `SQLAlchemyError` as "venue failed, carry on", and `InterfaceError` is a `SQLAlchemyError`.
Counting a venue with commit failures as failed is a small, correct addition.

**Counts:** 0 blockers, 4 should-fix, 4 nits.

**Verdict:** *proceed after fixes.* None of the findings changes D2's recommendation. Finding 1 is a crash path in the
helper's specified expression, and the planned tests can't see it. Finding 2 corrects a claim Ari is asked to decide ★
D2 on. Findings 3 and 4 are a failure row that can't say which show failed, and a mutation check that can stay green.

| # | Sev | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|
| 1 | should-fix | **`is_decision_error` as specified crashes on a real lost connection, and the planned tests can't see it.** The Design docstring says the rule is "decided by `getattr(err.orig, "sqlstate", "")`". When the dialect translates an asyncpg error, it always *sets* `sqlstate`, to `getattr(error, "sqlstate", None)`. asyncpg's `InterfaceError` has no `sqlstate`, so a real dropped connection reaches K2 as `sqlalchemy.exc.InterfaceError` with `orig.sqlstate = None`. The attribute exists, so `getattr`'s default `""` is never used, and `None[:2]` or `None.startswith(...)` raises `TypeError` / `AttributeError` inside K2's `except` block. The 08006 / 57P01 shapes the plan names did not occur in either experiment. The planned tests build "an `InterfaceError`" and "a `DBAPIError` with `orig.sqlstate = "08006"`". An `orig` without a `sqlstate` attribute, or with `"08006"`, passes under the buggy expression. **Fix:** write the rule as `sqlstate = getattr(err.orig, "sqlstate", None) or ""`, and return False when `err.connection_invalidated` is set. The `is_decision_error` unit test and A6-M6's `InterfaceError` should use the real shape: an `orig` whose `sqlstate` is `None`, plus `connection_invalidated=True`. Name it in the "driver lies" gotcha, ideally as a shared `fakes` helper that builds each real shape (`22003`, `23514`, lost connection), which `FakeWriter` also uses. | CONFIRMED (worktree probe): `pg_terminate_backend` and a closed raw connection each gave `('InterfaceError', orig 'InterfaceError', sqlstate None, connection_invalidated True)`, and the plan's expression raised `TypeError: 'NoneType' object is not subscriptable`. Translation: `.venv/…/sqlalchemy/dialects/postgresql/asyncpg.py:794-796`. Plan lines 269-272, 420-422, 432-434, 492, 538-540. | A database restart or idle-connection kill during a commit raises `TypeError` instead of `InterfaceError`. `TypeError` is not in `main.RUN_ERRORS`, so instead of "this venue failed, carry on to the next one", the **whole worker process crashes** and every venue after it is skipped that night. Layer 3, layer 4 and A6-M6 all stay green under the bug. | **Fixed.** The rule is now `sqlstate = getattr(err.orig, "sqlstate", None) or ""`, and an error with `connection_invalidated` is False before SQLSTATE is looked at (Design docstring for `is_decision_error`). The reviewer's measurement stands (a real lost connection is an `InterfaceError` with `orig.sqlstate = None`); I replaced my invented `08006` shapes. A shared helper in `tests/fakes.py` builds each real shape (`overflow()` 22003, `check_violation()` 23514, `lost_connection()` with `sqlstate=None` and `connection_invalidated=True`) and is used by the `is_decision_error` unit test (which asserts the lost-connection shape is False **and does not raise**), by `FakeWriter`, and by the stub writers in layers 3 to 5. A6-M6 and the 'driver lies' gotcha updated. A `08006` / `57P01` `DBAPIError` stays as one extra case. |
| 2 | should-fix | **D2 tells Ari that "a bug in our code still stops the run". Under the SQLSTATE rule, many commit bugs don't.** A bug that sends the database a malformed row gets a class 22 / 23 SQLSTATE, the same as a bad listing. Examples: a column left out of `insert_values` (`23502`), an enum value written as the wrong string (`22P02`), a wrong or stale artist id (`23503`, which is the very failure layer 3's atomicity test (a) injects). Each one is classified as one show's failure. A commit bug of that kind fails **every** write, and D2-A carries on past each: N failure rows, a summary, exit 1, and nothing written. Only bugs that raise a Python exception, or a SQLSTATE outside 22 / 23, stop the run. **Fix:** in D2 option A and the "Exceptions that stop the run" Settled detail, say that the rule separates the database refusing a row from losing the database, not "the venue's data" from "our bug". Add this case to D2's "Cost of A". Optionally (Ari's call, and it is an operational rule, not a calendar judgement), add a breaker: when every op failed with a decision error, `write_plan` raises after recording them, so an all-fail run reads as a crash and not as N separate bad listings. | CONFIRMED (worktree probe): NOT NULL gave `IntegrityError` `23502`; a bad enum text gave `DBAPIError` `22P02`; both were classified per-show by the rule. Plan lines 140-146, 150-151, 212-214, 408-410. | Ari decides ★ D2 on a false premise. In practice the visible harm is small, because nothing wrong is written and the exit code is 1. But the audit trail then shows a commit bug as N failed listings, each with the same SQLSTATE. A person reading `failed_commits` goes looking at venue pages instead of the code. | **Fixed.** D2 option A now says what the rule really separates (the database refusing a row from losing the database, not a bad listing from a bug of ours), lists the malformed-row bugs (`23502`, `22P02`, `23503`) that are recorded per show, and gets a third cost of A (an all-fail run looks like N bad listings). The Settled detail 'Exceptions that stop the run' is corrected to match. **Optional breaker (Ari's call, per the reviewer):** I did not make `write_plan` raise on an all-fail run. A raise would need its own exception type in `RUN_ERRORS`, and the exit code is already 1 and nothing is written either way. Instead a new Settled detail flags it: the summary carries `all_failed` (3 or more operations, every one a decision error), the worker logs an error that says it looks like a bug, and the failure rows carry `sqlstate` so `failed_commits` groups them. Veto it or ask for the raising version. |
| 3 | should-fix | **The failure row for a failed insert can't say which show failed.** The "Audit rows" table gives the failure row `entity_id` = the stored id (`null` for an insert) and a `detail` of only `action`, `reconcile_reason`, `error`. For an insert, nothing in the row identifies the show. The date and time live only in the summary's `failed` list and in `ShowFailure`. `failed_commits` ("which shows failed to write, and why") reads the failure rows, so for D2's own scenario (an overflowing price on a new show) and for Verification 9 (a failed insert) it returns a row with no date, no time and no id. The table also doesn't say what marks a failure row, so the query's `WHERE` is left to the build. **Fix:** give the failure row's `detail` the same identity the summary's `failed` entry has: `date`, `time`, `stored_id`, plus `sqlstate`, which lets `failed_commits` group a recurring failure (see finding 2). Pin the keys in layer 2. State `failed_commits`'s predicate (`step_type = 'commit' AND entity_type = 'show' AND outcome IS NULL`) and its join. A `LEFT JOIN agent_run`, or a note, keeps rows whose `run_id` is NULL from silently dropping out. | CONFIRMED by reading: plan line 314 (failure row) against line 315 (summary `failed`) and line 229 (`ShowFailure`); line 337 (`failed_commits`); Verification 9 (lines 731-733). | The saved query built for D2 can't answer its own question for inserts, which is the D2 scenario. A person has to correlate the failure row with the summary row of the same run by hand. | **Fixed.** The failure row's `detail` now has `action`, `reconcile_reason`, `date`, `time`, `stored_id`, `sqlstate` and `error` (the same identity as the summary's `failed` entries; `ShowFailure` gains `sqlstate`); layer 2 pins the keys. The `failed_commits` predicate is stated (`step_type = 'commit' AND entity_type = 'show' AND detail ->> 'error' IS NOT NULL`, with `LEFT JOIN agent_run` / `venue`), as are its selected columns and a `GROUP BY sqlstate` variant for a recurring failure. I used `detail ->> 'error'` rather than the reviewer's `outcome IS NULL`, because a no-op or stub row with no outcome would also match the latter. |
| 4 | should-fix | **A6-M5's companion test can stay green under the mutation unless the crash comes after at least one show was written.** Layer 5 says only that "a run whose writer raises a connection error *is* listed". A6-M5 mutates `unfinished_runs` back to "any `commit` row means the run finished". If the injected writer raises on the **first** op, the run has no `commit` row at all, so both the correct and the mutated query list it, and `test_a_run_that_crashed_mid_commit_is_unfinished` stays green. The test proves something only if a per-show `commit` row exists and the summary doesn't. **Fix:** say so in layer 5. The injected writer delegates to the real `PostgresCalendarWriter` for the first op, then raises the real lost-connection shape (finding 1) on the second. The test asserts that one per-show `commit` row exists, that no summary row exists, and that the run is listed. | CONFIRMED by reading the query: `docs/dev/audit-queries.sql:92-95` (`NOT EXISTS … step_type IN ('commit', 'escalate')`); plan lines 335-337, 471-473, 491. | The mutation table claims protection the suite might not give. The one thing the `unfinished_runs` change exists for, a run that crashed between per-show rows and the summary, goes untested. | **Fixed.** Layer 5 now requires the injected writer to delegate to the real `PostgresCalendarWriter` for the first operation and raise `fakes.lost_connection()` on the second, and asserts one per-show `commit` row, no summary row, and that the run is listed. The text says why a first-operation raise proves nothing under A6-M5. |
| 5 | nit | **Verification 9 expects "exit status 1", but it runs through `local_test`, which always exits 0.** `local_test.main()` returns `None` and is run as `asyncio.run(main())`. Step 5 only says `local_test` "prints what was written and what failed". **Fix:** have `local_test` exit 1 when `state.commit_result.failures` is non-empty (as `main` does through `run_all`), or drop the exit-status expectation from Verification 9. | CONFIRMED by reading `agent_worker/local_test.py:35, 98`; plan lines 645-647, 731-733. | Ari's local check of D2 fails on the exit code while the behaviour is correct. | **Fixed.** `local_test` exits 1 when `commit_result.failures` is non-empty (Wiring, step 5), and Verification 9 says so. |
| 6 | nit | **The new `unfinished_runs` predicate lists every pre-A6 run in an existing dev database.** The A4 / A5 stub `commit` row has `entity_type` NULL, because `COMMIT` is not in `_VENUE_LEVEL` today. So `step_type = 'commit' AND entity_type = 'venue'` doesn't match it, and every run that finished before A6 now reads as a crash. **Fix:** say so in the query's comment and rely on `make db-reset`, as Verification 6 already does, or also accept the stub row (`… OR al.detail ? 'stub'`). | CONFIRMED by reading `agent_worker/audit.py:92` and `:142` (the stub's `detail`); plan lines 335-337. | Someone running the query against a dev database that was not reset sees false "unfinished" runs. | **Fixed (documented).** The `unfinished_runs` comment and the Wiring bullet say that runs finished before A6 in an un-reset dev database read as unfinished, and rely on `make db-reset` as Verification 6 does. I did not also accept the stub row: the stub row has no entity to separate it from per-show rows, and a one-time dev-data artefact doesn't earn query logic. |
| 7 | nit | **K2's Check command may not select the test its second "likeliest mistake" depends on.** The Check is `-k "write_plan or failure or created_once or connection"`, and mistake 2 says the overflow test goes red. That test's name isn't given ("a failing show is recorded … including a show whose price overflows"). A natural name such as `test_an_overflowing_price_fails_only_its_show` matches none of the four words. **Fix:** name the K2 tests in the plan, or list their node ids in the Check. | PLAUSIBLE (reasoned): plan lines 431-434, 615-619. | Ari runs the Check after catching only `IntegrityError`, sees green, and moves on. | **Fixed.** The K2 tests are named (`test_an_overflowing_price_fails_only_its_show`, `test_a_connection_error_stops_the_run`, `test_an_all_failed_run_is_flagged`) and K2's Check `-k` now selects them (`write_plan or overflowing or connection or created_once or all_failed or is_decision_error`). |
| 8 | nit | **The summary's `counts` key set is stated two ways.** "Audit rows" says the shape is `{inserted, updated, removed, no_op, skip}` "plus the failures". Layer 2 says `counts` "always has `inserted, updated, removed, no_op, skip`". It is unclear whether `counts` has a `failed` key or whether failures appear only as the `failed` list. **Fix:** pick one, and make layer 2 pin the exact key set. | CONFIRMED by reading plan lines 319-320 against 383-384. | The builder and the test agree by accident or not at all, and `audit-queries.sql`'s header documents whichever one came first. | **Fixed.** `counts` has exactly five keys (`inserted, updated, removed, no_op, skip`), pinned as a set in layer 2; failures appear only in the `failed` list, with `all_failed` as a separate boolean. The Audit rows table, its prose and layer 2 now agree; `audit-queries.sql`'s header documents this one. |

**Rejected:** none. Round 2 resolved by the author (Claude Sonnet 5.5), October 20, 2026: 8 of 8 fixed. Two are judgement calls
worth Ari's eye: the optional all-fail breaker (row 2) is a flag and a log line, not a raised error; and `failed_commits` keys on
`detail ->> 'error'` (row 3), not on a missing outcome. No round 3 was run. D2's recommendation is unchanged, but its wording now
says what its rule does and does not separate, and its cost list has three entries.

## Implementation log

### Round 1 — Claude Sonnet 5.5, October 20, 2026

**Scope.** `git diff e6008cd` (the last plan commit, "A6: plan review round 2 (D2 and K2) and its resolution") plus the new untracked
files: the working tree, uncommitted at the time the reviewer is spawned. Branch `claude/nifty-sagan-gan2i1` (assigned by the
session; `AGENTS.md` names `a6-commit`). No migration, no schema change, `app/schemas.py` untouched.

*New:* `agent_worker/commit.py`, `agent_worker/calendar_writer.py`; tests `test_commit_ops.py`, `test_calendar_writer.py`,
`test_graph_commit.py`, `test_commit_db.py`.
*Changed:* `audit.py` (`previous_value` / `new_value`, `audit_row`, the commit builders and summary `detail`, `attempt_number`
public, `COMMIT` venue-level), `state.py` (`commit_ops`, `commit_result`), `context.py` (`writer`), `nodes.py` (`commit_node`
prepares operations), `trace.py` (the commit branch), `main.py` (the writer; `run_all` counts commit failures), `local_test.py`
(the writer; prints what was written; exits 1 on failures); tests `fakes.py` (`FakeWriter`, the real driver error shapes),
`test_audit_entries.py`, `test_audit_queries.py`, `test_graph.py`, `test_graph_audit.py`, `test_graph_reconcile.py`,
`test_reconcile_db.py` (`seed_calendar` extracted), `test_run_venue.py`; docs `audit-queries.sql` (header keys,
`unfinished_runs`, the sixth query `failed_commits`), `alpha-build-plan.md`, `arch-initial.md` §7, `data-model-initial.md`,
`conventions.md`, `apps/api/AGENTS.md`, `notes.md`.

**Departures from the plan, each with its reason.**

1. **The order of work.** Tests for the pure layer (`test_commit_ops.py`) were written first and watched fail (the module did not
   exist). The writer, loop and graph tests were written with the code, with both gaps filled, to get a known-good version to
   derive the scaffold from; the "watched fail" step for them is the scaffold itself (69 red results, all `TODO(Ari)`), as in A4
   and A5. Expected values were still written from the requirements and decisions, not read from the code.
2. **`venue_id` travels in the operation's `values`**, set by `build_ops(plan, venue_id, original_url)`; `write_show` and
   `write_plan` do not take it (the plan's sketch passed it twice). K1's code block lost its `venue_id` argument.
3. **K1's block uses one combined `async with self._session_factory() as session, session.begin():`** (ruff SIM117 rejects the
   nested form). Same behaviour, one line shorter.
4. **`MIN_OPS_FOR_ALL_FAILED` and the `all_failed` property live in `commit.py`** (`CommitResult.all_failed`), not
   `calendar_writer.py`, so the flag is a pure function of the result and the summary row can be built without the writer.
5. **`ShowFailure` carries `reconcile_reason`** as well as the plan's fields (the failure row's `detail` lists it).
6. **The seeded calendar is shared as `seed_calendar` in `test_reconcile_db.py`**, not in `reconcile_support.py` as the plan said:
   `test_calendar_reader.py` imports `reconcile_support`, and `reconcile_support` importing `make_show` from it would be a cycle.
   `test_commit_db.py` imports it from `test_reconcile_db.py`, the pattern `test_reconcile_db.py` already uses for `test_calendar_reader`.
7. **A6-M4's named test is the unit test**, `test_prices_are_converted_at_the_write_not_carried_as_floats`, not
   `test_the_second_run_is_all_no_ops`. *(Corrected in round 2, A6-CR1-2.)* The reason first given here, that a `Decimal(float)`
   write is invisible to a database-level test, is true only for prices like 19.99 and 20.0, where Python and Postgres round the
   same way. For a HALF cent they differ (`to_price(0.125)` is `0.12`, Postgres stores `Decimal(0.125)` as `0.13`), so the
   mutation would flip a show between updates every night; the end-to-end round-trip test now uses a half-cent price and
   catches it too. The plan file keeps its text (the plan is the plan).
8. **A6-M2 needed an extra test** (`test_a_write_uses_exactly_one_session`). In savepoint mode a second session's "committed"
   work nests inside the first's savepoint and rolls back with it, so the "own session" mutation was NOT caught by the plan's
   test. Recorded in `notes.md`. Also added `fakes.client_side_error()` (an `InterfaceError` with `sqlstate = None` that is not
   invalidated): with the invalidated flag checked first, the lost-connection helper no longer exercised the SQLSTATE expression alone
   (the `getattr(..., "")` mutation survived until this case existed).
9. **Layer 5's refused-show test uses the test-only CHECK constraint only.** The plan also named "a scripted page with one
   overflowing price"; the JSON-LD route carries no prices, and the overflow is covered at layer 3
   (`test_an_overflowing_price_fails_only_its_show`, through the real writer).
10. **`audit.attempt_number`** is public (the plan said so); `_attempt_number` is gone. `local_test.main` returns an exit status.
11. **`test_graph_audit.py`'s step lists did not gain the per-show commit rows** the plan's "Existing tests that change" described:
    those tests build `FakeWriter()` without an audit, so nothing is appended and the lists still end `("commit", n)` once. The
    order of the per-show rows and the summary is proven by `test_graph_commit.py`'s first test and by `test_audit_queries.py`'s
    `run_history` (A6-CR1-6).

**`TODO(Ari)` gaps** (both open; review the code as it stands, they are not findings):

| Key | Where | Lesson |
|---|---|---|
| A6-K1 | `calendar_writer.py` `PostgresCalendarWriter.write_show` | A write and its record are one transaction; `previous` before the change, `new` after the flush; nothing outlives the transaction but the return value |
| A6-K2 | `calendar_writer.py` `write_plan` | One show's problem is what the database says about the row (SQLSTATE 22 / 23), not a Python class; a lost connection or a bug propagates |

Fill order K1, K2. Every test that uses the real writer is red until K1; every test that reaches `write_plan` with a non-empty plan
is red until K2, fakes included.

**Verification.**

- **Baseline** before A6, measured October 19: 790 passed, 15 skipped, ruff clean.
- **As delivered (gaps open):** `REQUIRE_DB=1 uv run pytest`: **798 passed, 51 failed, 18 errors, 15 skipped**. All 69 red results
  are `NotImplementedError: TODO(Ari)` (checked by grepping every failure). Red by file: `test_calendar_writer.py` 22,
  `test_graph.py` 10, `test_commit_db.py` 9 (3 failed + 6 errors), `test_audit_queries.py` 8 (errors), `test_graph_audit.py` 6,
  `test_graph_commit.py` 5, `test_reconcile_db.py` 4 (errors), `test_graph_reconcile.py` 3, `test_run_venue.py` 2. That is
  36 new tests and 33 existing ones (the plan review measured 31; `test_audit_queries.py` has two more tests that use the
  real-commit fixture).
- **Gaps filled on a scratch copy** (a temporary directory outside the repo, with the working tree copied and the filled
  `calendar_writer.py`): **867 passed, 15 skipped**, ruff clean, and the two new modules pass `mypy` (the one reported error is
  `act_split.py:109`, which A7 owns). That is the 790 baseline plus 77 new tests.
- **Mutation checks** (on the scratch copy, each restored afterwards): A6-M1 caught (3 tests). A6-M2: the "own session" variant
  was **not caught** by `test_audit_rows_roll_back_with_the_write` (savepoint nesting, see departure 8) and is caught by
  `test_a_write_uses_exactly_one_session`; the "commit before the audit rows" variant is caught (10 tests). A6-M3 caught
  (`test_a_rolled_back_artist_is_not_remembered`). A6-M4 caught by the unit test only (departure 7). A6-M5 caught (2 tests: the
  query test and the real crash). A6-M6 caught for both `except Exception` (4 tests) and "any `DBAPIError`" (3 tests). The
  `getattr(..., "")` default was not caught until `client_side_error()` was added, then caught.
- `uv run ruff check .` clean. `make lint`, `make typecheck` (mypy `app/` and tsc), `make contract-check` and
  `make designation-check BASE=e6008cd` exit 0; `pnpm turbo run test` passes (the JS suite is untouched).
- `make check` as a whole stops at its Python test stage, red by design; every stage after it was run separately and is green.
- **Not run here:** `make worker` and `local_test` (no Ollama, no Docker, no MongoDB in the cloud sandbox), so Verification 6 to 10
  are Ari's. The real lost-connection error shape and the real-database behaviour of `FOR UPDATE` under concurrency were
  measured by the plan review, not re-measured here.

**Where to look hardest.**

1. **`is_decision_error` and K2's `except (DBAPIError, ShowGone)`** (`calendar_writer.py`): whether the SQLSTATE rule matches what the
   installed driver really does, in particular `err.orig.sqlstate` on errors other than the three the DB tests raise for real
   (check, foreign key, overflow); the lost-connection case rests on the plan review's measurement and on `fakes.lost_connection()`.
2. **`_snapshot` and `_apply`** together: the `populate_existing` select, the `FOR UPDATE` lock taken by the first read, and
   `_apply` finding the row through `session.get`; and whether a lineup replace (a Core `delete` then `add_all` of rows with the same
   primary keys) can collide with the identity map (the lineup is read as columns for that reason).
3. **`build_ops`**: `new_artist_names` for an update whose lineup did not change (empty by construction), and the removals-last
   ordering.
4. **`trace.audited`'s commit branch**: that the summary row is written last, and that a raised connection error leaves no summary.
5. **The test harness's limits**: savepoint mode hides a second session's commit (departure 8); whether any other mutation of K1
   could survive; `test_commit_db.py`'s parity comparison masks `original_url` and artist spelling, by design.
6. Anything in the tests whose expected value I may have taken from the code instead of the requirements.

### Round 2 — Claude Sonnet 5.5, October 20, 2026 (fixes for code review round 1)

**Scope.** The fixes for `A6-CR1-1` to `A6-CR1-7`, on top of `f8c0138`: `calendar_writer.py` (`failure_for`; the comment blocks of the
two open gaps), tests `test_calendar_writer.py` (the `ShowGone` loop test), `test_commit_db.py` (the half-cent price, two comments),
`test_audit_entries.py` (a comment), and docs (`notes.md`, this plan's Check commands and departures). Each testable finding got a
failing-test check first: the `ShowGone` test and the half-cent price were run against the reviewer's mutations in the scratch copy
(both caught) before being relied on.

**Departures.** None from the plan. Departure 7 and a new departure 11 are recorded in round 1.

**`TODO(Ari)` gaps.** Both still open (A6-K1, A6-K2). The gaps' `Check:` commands are corrected and verified (A6-CR1-4).

**Verification.**
- **As delivered (gaps open):** `REQUIRE_DB=1 uv run pytest`: **798 passed, 52 failed, 18 errors, 15 skipped**. All 70 red results are
  `NotImplementedError: TODO(Ari)` (the 69 of round 1 plus the new `ShowGone` loop test). Red by file: `test_calendar_writer.py` 23,
  `test_graph.py` 10, `test_commit_db.py` 9, `test_audit_queries.py` 8, `test_graph_audit.py` 6, `test_graph_commit.py` 5,
  `test_reconcile_db.py` 4, `test_graph_reconcile.py` 3, `test_run_venue.py` 2.
- **Gaps filled on a scratch copy** (outside the repo, the working tree with the filled `calendar_writer.py`): **868 passed, 15
  skipped**, ruff clean, the two new modules clean under `mypy` apart from `act_split.py:109` (A7's). On a copy with only K1 filled,
  K1's corrected `-k` selection gives 12 passed; K2's `-k` is red with only K1 filled (11 failed) and 16 passed with both.
- **Mutation checks, re-run for the two new tests:** K2 catching only `DBAPIError`: caught; A6-M4 (`Decimal(float)`) with the
  half-cent price: caught by `test_a_price_round_trips_exactly_and_a_second_run_does_not_rewrite_it`.
- `uv run ruff check .`, `make lint`, `make typecheck`, `make contract-check` and `make designation-check BASE=e6008cd` exit 0.
  `make check` as a whole still stops at its Python test stage, red by design.

**Where to look hardest.** The corrected `-k` selections (do they select what the gap's lesson names?), and `failure_for`'s single
branch.

### Round 3 — Claude Sonnet 5.5, October 20, 2026 (Ari's fills; cleanup of the closed gaps)

**What arrived.** Ari filled A6-K1 and A6-K2 in `calendar_writer.py` (commit `5204c38`; it also removed the `audit_row` import's
suppression, as K1's block said). His code is the plan's `Code:` block for each, line for line. With it the suite is **868 passed,
15 skipped**, ruff clean, the number the scratch copy gave with the gaps filled.

**Cleanup pass (`AGENTS.md` "[fill-in] tasks" step 4).** The two lesson blocks, which Ari's commit had partly stripped, were rewritten
as plain why-comments in the style of their neighbours: the `Lesson`/`Code`/`Check` labels, the test-command pointers and the "likeliest
mistake" lists are gone, and the reasoning (why the audit rows share the transaction, why `previous` is read before the change, why
nothing outlives the transaction but the return value, why SQLSTATE and not the Python class, why never `except Exception`) is kept as
sentences of rationale with the plan references (`A6-K1`, `A6-K2`, `A6-D2`). **Comment-only, verified as such:** syntax trees (docstrings
stripped) identical before and after. No placeholder helper existed to delete, and no `noqa` remained.

**Verification.** `make check` end to end: **exit 0**. Python 868 passed, 15 skipped; JS 337 passed; ruff, mypy (`app/`), eslint, tsc,
`make contract-check` and `make designation-check` clean. Both gaps are filled (by Ari) and cleaned; no `TODO(Ari)` remains in the A6
files. Verification steps 6 to 10 (local: Docker, Ollama) were run by Ari.

## Code review

### Round 1 — Claude Opus 5.5, October 20, 2026

**Scope.** Implementation log round 1: `git diff e6008cd` plus the untracked files. While this review ran, the author committed
that working tree as `f8c0138` ("A6: commit step (scaffold with two TODO(Ari) gaps), tests, docs"). `git diff e6008cd f8c0138`
has the same 29 files the log lists (23 changed, 6 new), so this round reviews `e6008cd..f8c0138`. The two open gaps (A6-K1,
A6-K2) are not findings.

**What was checked and how.**
- **Read:** the whole plan, including both plan-review rounds and the Implementation log; `AGENTS.md`; `apps/api/AGENTS.md`;
  `docs/references/fastapi-style-guide.md` (Anti-patterns); and the full diff: `commit.py`, `calendar_writer.py`, `audit.py`,
  `trace.py`, `nodes.py`, `state.py`, `context.py`, `main.py`, `local_test.py`, `fakes.py`, the six new or changed test files
  and the updated existing ones, `audit-queries.sql`, and the doc changes (`arch-initial.md`, `data-model-initial.md`,
  `alpha-build-plan.md`, `conventions.md`, `notes.md`). I also read `app/db/models/calendar.py` (`Show` has no
  `relationship()`, so replacing the lineup can't collide with the identity map) and `reconcile.lineup_for` (an artist named
  twice is deduplicated, so the `show_artist` primary key can't be hit twice).
- **`make check` on the tree as delivered:** it stops at the Python test stage, red by design: **51 failed, 18 errors, 798
  passed, 15 skipped**, the log's numbers. By file the reds match the log (writer 22, graph 10, commit_db 9, audit_queries 8,
  graph_audit 6, graph_commit 5, reconcile_db 4, graph_reconcile 3, run_venue 2), and every one is `NotImplementedError:
  TODO(Ari)` (no other failure line). I then ran each stage after it: `ruff check .` clean, `mypy app/` clean, `make
  contract-check` current, `make designation-check BASE=e6008cd` exit 0 (the script covers untracked files),
  `pnpm turbo run lint check-types test` 7/7. `mypy` on `commit.py` and `calendar_writer.py` reports only
  `act_split.py:109` (A7's). All CONFIRMED.
- **The gaps filled from their own `Code:` lines,** in a throwaway `git worktree` at `f8c0138` (with `.env` copied and the
  venv linked; removed afterwards, and `git worktree list` shows only the main tree): **867 passed, 15 skipped**, as the log
  says. `ruff` then reports only RUF100 on the `audit_row` import's `noqa` (see row 4). CONFIRMED.
- **The author's mutation checks, re-run in that worktree:** A6-M1 (`previous` read after `_apply`) is caught by 3 tests.
  For A6-M2, the "own session" variant (the audit rows written through `PostgresAuditWriter(self._session_factory).record`)
  is caught **only** by `test_a_write_uses_exactly_one_session`; `test_audit_rows_roll_back_with_the_write` stays green, so
  departure 8 holds. A6-M6 (the `is_decision_error` re-raise removed) is caught by 5 tests. All CONFIRMED.
- **My own mutations:**
  - K2 catching only `DBAPIError`, without `ShowGone`: **survives**, the whole suite stays green (row 1).
  - K1 writing `created` into the caller's `artist_ids` before `_apply`: caught by
    `test_a_rolled_back_artist_is_not_remembered`.
  - K1 dropping `lock=True`, and `_snapshot` without `populate_existing`: both survive, as expected. Neither is observable on
    one test connection, and the plan lists concurrency as not covered. Not findings.
- **A real lost connection through the real writer:** a scratch test on a real engine (not savepoint mode). A
  `PostgresCalendarWriter` subclass killed its own backend (`pg_terminate_backend`) inside `_apply`, and the filled
  `write_plan` ran over two ops. Result: `sqlalchemy.exc.InterfaceError`, `orig.sqlstate = None`, `connection_invalidated =
  True`, `is_decision_error` False, no failure row recorded, and it propagated. The rollback on leaving `begin()` did not
  replace it. A fresh session worked afterwards (what `run_venue`'s `finally` needs). This answers "look hardest" 1 for the
  real case, not only the `fakes` shape. CONFIRMED.
- **Half-cent price under A6-M4:** see row 2. Python's `quantize` rounds half to even and Postgres `numeric` rounds half away
  from zero, so `to_price(0.125)` is `0.12` but `Decimal(0.125)` is stored as `0.13`. CONFIRMED.

**What holds up.** `commit.py` is pure and stays out of `state` / `audit` (a test enforces it). `build_ops` follows A6-D1 and
removals-last. The snapshot is derived from the model, and its pin test can fail. `is_decision_error` uses the corrected
expression (A6-PR2-1) and is right on the real shape. The per-show rows go through `audit_row` in the write's session. The
summary row is written last in `trace.audited`, and none is written when the run raises. `unfinished_runs` and
`failed_commits` match the plan and run against real rows. `run_all` and `local_test` exit non-zero on refused shows. The
anti-patterns table turned up nothing: no bare `except Exception`, no sync I/O in `async def`, no mocked database, and
`is None` throughout. The test layers are as planned, the `Proves` lines cite their sources, and departures 1 to 10 are
reasoned. Departure 7's reasoning is the exception (row 2).

**Counts:** 0 blockers, 3 should-fix, 4 nits.

**Verdict:** *proceed after fixes.* The scaffold is sound and the gaps fill green from their own `Code:` lines. The
should-fix rows are two test or guard claims that don't hold (one K2 branch with no test, and one `Proves` line that claims
A6-M4 protection it can't give) and one lesson in `notes.md` that names a test which can't catch the mutation it is offered
for.

| # | Sev | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|
| 1 | should-fix | **No test covers half of K2's `except (DBAPIError, ShowGone)`.** A6-D2 says "the show having vanished" is one show's failure, and K2's lesson and code list `ShowGone`. But no test takes a `ShowGone` through `write_plan`. `test_a_vanished_show_is_a_show_gone_failure_not_an_attribute_error` only calls `write_show` and `is_decision_error`, and the loop tests use only `overflow()`, `check_violation()` and the connection shapes. A K2 that catches only `DBAPIError` passes every test. **Fix:** a loop test with `FakeWriter(fail={1: ShowGone("show 3 is not in the calendar")})` that asserts the other two writes, one `ShowFailure` with `sqlstate None` and an `error` beginning `ShowGone:`, and one failure row. Put it in K2's Check `-k` (or parametrize `test_a_failing_show_is_recorded_and_skipped_and_the_loop_goes_on` over `check_violation()` and `ShowGone`). | CONFIRMED (worktree, gaps filled): with K2's `except` reduced to `except DBAPIError as err:` the suite stays at **867 passed**. The probe test above went red under that mutation (868 passed, 1 failed) and green without it. Its failure was `ShowFailure(action='insert', …, sqlstate=None, error='ShowGone: show 3 is not in the calendar')`. `calendar_writer.py:295` (K2 code), `test_calendar_writer.py:350-364, 540-550`. | A row deleted by hand between reconcile and commit (the A6-PR1-7 case) raises out of `write_plan` and stops the venue's run instead of being recorded. Every test stays green while Ari's K2 has that bug, and the lesson's "names the broad types" half is never checked. | **Fixed.** Test first: `test_a_show_gone_error_in_the_loop_is_recorded_and_skipped_like_a_refused_row` (`FakeWriter(fail={1: ShowGone(...)})`; the other two writes happen, one `ShowFailure` with `sqlstate None` and an error starting `ShowGone:`, one failure row). Red before the fix in the sense that matters: with K2's `except` reduced to `except DBAPIError`, it fails (mutation re-run in the scratch copy: caught, 1 failed, 33 passed). It is in K2's Check `-k` (`show_gone`) and in K2's list of likeliest mistakes (the third). The gap itself is unchanged. |
| 2 | should-fix | **`test_the_second_run_is_all_no_ops` says it guards A6-M4, but it can't; and departure 7's reason is wrong.** Its `Proves` comment says "Skipping the price conversion would make `20.0` compare unequal to the stored Decimal("20.00") and fail this test". Its page (`test_reconcile_db.PAGE`, JSON-LD) carries no prices, so it can't see a price conversion at all. Departure 7 moves A6-M4 to the unit test because "a `Decimal(float)` write is invisible to a database-level test". That is true for 19.99 and 20.0, but not in general. `to_price` rounds half to even and Postgres `numeric` rounds half away from zero, so a half-cent price stores differently under the mutation, and the next run updates the show **every night**. That nightly flip is the failure A6-M4 exists to catch. **Fix:** correct the run-2 test's comment (it proves idempotency, not the price conversion). Add a half-cent price (e.g. `admission_advance=0.125`, expected `Decimal("0.12")`) to `test_a_price_round_trips_exactly_and_a_second_run_does_not_rewrite_it`, so the end-to-end test also catches A6-M4. Correct departure 7's reason. | CONFIRMED (worktree): `to_price(0.125)` = `0.12`; `SELECT CAST(0.125 AS numeric(10,2))` = `0.13`. With the round-trip test's advance price changed to `0.125`, the correct code stored `0.12` and passed. Under A6-M4 (`Decimal(listing.admission_advance)` in `insert_values`) it stored `0.13`, and the second run's plan was `[Action.UPDATE]`, so the test failed. `test_commit_db.py:216-221`, `:235-259`, `test_reconcile_db.py:51-57`; Implementation log departure 7. | The suite's only end-to-end idempotency guard for prices is a page with no prices, while its comment says otherwise. The recorded reason ("invisible to a database-level test") tells the next reader that no such test is possible. A price conversion that drifted (e.g. a later `to_price` change to round half up) would make half-cent shows flip nightly, and only a unit test that compares against `to_price`'s own output would notice. | **Fixed.** Reproduced (`to_price(0.125)` is `0.12`, `CAST(0.125 AS numeric(10,2))` is `0.13`) and my departure-7 reason was wrong; it is corrected in Implementation log round 1 (departure 7) and the round-trip test now carries the half cent: a day price of 19.99 and an advance price of 0.125, expected stored `Decimal("19.99")` and `Decimal("0.12")`. Re-ran A6-M4 (`Decimal(float)` in `insert_values`) against `test_commit_db.py`: caught by that test (1 failed). The run-2 test's `Proves` comment no longer claims to guard A6-M4; it says it proves idempotency and points at the round-trip test. The unit test stays too. The mutation table row for A6-M4 still names the unit test in the plan (the plan keeps its text); the log records that the end-to-end test also catches it. |
| 3 | should-fix | **The new `notes.md` entry on savepoint nesting offers, as its second remedy, the test that can't catch the mutation it describes.** The entry says a rolled-back-write test "cannot tell a writer that used one transaction from one that wrote the audit row through a second session (the A6-M2 mutation)". It then offers: "Count the sessions (`test_a_write_uses_exactly_one_session`), **or** end the first with a failure raised AFTER the rows were produced (`test_audit_rows_roll_back_with_the_write`)". That second test is the one the own-session variant passes. It catches only the other variant (`commit()` before the rows are added). **Fix:** say that only counting sessions (or a test on a real engine, not savepoint mode) catches a second session. The raise-after-the-rows test catches an early `commit()`, not a second session. | CONFIRMED (worktree): under the own-session A6-M2 mutation, only `test_a_write_uses_exactly_one_session` failed, and `test_audit_rows_roll_back_with_the_write` passed. The Implementation log's own mutation line says the same. `docs/dev/notes.md:552-558`. | `notes.md` is where the next milestone's author looks for "what bit us". Following its "or" gives a test that can't fail on exactly the bug the note warns about. | **Fixed.** `notes.md` now says only counting sessions (or a test on a real engine, not savepoint mode) catches a second session, and that the raise-after-the-rows test catches a different mistake (`commit()` before the rows are added) and passes a writer that used a second session. |
| 4 | nit | **The gaps' `Check:` lines don't select what they claim, and K1 leaves a lint failure it doesn't mention.** (a) K2's second command, `agent_worker/tests/test_graph_commit.py -k failed`, collects **no tests**. The graph test is `test_one_failing_show_is_recorded_…` ("failing", not "failed"), so pytest exits 5 ("no tests ran"). (b) K1's `-k` names `atomic`, which matches no test. Its selection leaves out the K1 tests for the update, lineup-only, removal and return, rollback, CHECK, overflow and vanished-show paths (6 of the 13 writer tests selected; the rest only by the full file). (c) Filling K1 makes the `audit_row` import's `noqa: F401` unused, so `ruff` (RUF100) fails, and so does `make check`'s first stage, until the noqa goes. The comment on the import says so, but K1's block, which is what Ari reads, does not. **Fix:** `-k failing` (or the node id); drop `atomic` and add `update or removal or lineup or vanished or rolls_back or constraint`, or run the whole file; add "and delete the `noqa` on the `audit_row` import" to K1's Code. | CONFIRMED: `pytest --collect-only -k failed agent_worker/tests/test_graph_commit.py` lists nothing; K1's `-k` collects the 6 tests named above; worktree `ruff check .` after filling gives `RUF100 Unused noqa directive (unused: F401)` at `calendar_writer.py:46`. `calendar_writer.py:180, 302-303`. | Ari runs a Check that tests nothing, or that skips the update and removal paths of the block he just typed, and reads it as done. Then his first `make check` fails on lint for a reason the block didn't tell him about. | **Fixed.** (a) K2's graph command is now `test_graph_commit.py -k failing` (verified: 1 test collected, passes with K2 filled). (b) K1's `-k` is `insert or update or removal or previous or roll_back or rolls_back or one_session or check_constraint or overflowing_price_is or vanished or restoring` (verified on a copy with only K1 filled: 12 passed; the remaining writer tests, which run through `write_plan`, stay red until K2). K2's `-k` is `created_once or remembered or overflowing or connection or failing_show or show_gone or all_failed or created_so_far` (11 red with only K1 filled, 16 passed with both). (c) K1's comment block now says to delete the suppression comment on the `audit_row` import after filling (and the plan body's K1 Check says so). The plan's two `Check:` lines carry the same corrections. |
| 5 | nit | **`failure_for` computes the same condition three ways.** `wrapped = isinstance(err, DBAPIError)`, then `sqlstate = (getattr(err.orig, "sqlstate", None) or None) if isinstance(err, DBAPIError) else None`, then `sqlstate=sqlstate if wrapped else None`. The second `isinstance` and the final conditional repeat `wrapped`, and `or None` only turns `""` into `None`. **Fix:** compute `sqlstate` once from `wrapped` and pass it as is. | CONFIRMED by reading: `calendar_writer.py:97-108`. | No behaviour difference. A learner reading the module that teaches "the SQLSTATE expression" finds three versions of it in one function. | **Fixed.** `failure_for` branches once on `isinstance(err, DBAPIError)` and sets `sqlstate` and `message` together; the `ShowGone` branch says it has no SQLSTATE because it is not a database error. Behaviour unchanged (all failure-path tests green, and the filled copy re-run). |
| 6 | nit | **`test_graph_audit.py`'s step lists did not gain the per-show commit rows, and the log doesn't record this as a departure.** The plan ("Existing tests that change") says those step lists "gain the per-show commit rows where the page has shows (the fake appends them)". The tests construct `FakeWriter()` without an audit, so nothing is appended, and the lists still end `("commit", n)` once. The order is proven elsewhere (`test_graph_commit.py`'s first test and `test_audit_queries`' `run_history`), so the gap is only in the record. **Fix:** list it as a departure, or pass the `RecordingAudit` to the `FakeWriter` and extend the two lists. | CONFIRMED by reading: `test_graph_audit.py:64, 79, 121`; plan "Existing tests that change"; Implementation log departures 1-10. | The Implementation log is meant to name every departure. A reader comparing plan and tests finds one it doesn't mention. | **Fixed (recorded as a departure).** Implementation log round 1, new departure 11: `test_graph_audit.py` constructs `FakeWriter()` without an audit and so its step lists are unchanged; the order of per-show and summary rows is proven by `test_graph_commit.py`'s first test and by `test_audit_queries.py`'s `run_history`. I did not extend those lists: the point of that file is the A4 trail, and a second place that restates commit's row order would be one more place to edit. |
| 7 | nit | **Two comment slips in the new tests.** `test_commit_db.py:174` says run 1 "wrote four shows (an update, a removal, a reactivation, two inserts: five writes)". That is five shows, and the assertions say five. `test_audit_entries.py:298` (`an_insert_op`) says "one new Nona show", but the listing's act is "Sunny Day". **Fix:** "five shows"; "one new Sunny Day show". | CONFIRMED by reading the lines cited. | Comments that disagree with the code next to them, in a project whose tests are read as explanations. | **Fixed.** `test_commit_db.py`: "run 1 wrote five shows"; `test_audit_entries.py`: `an_insert_op` says "one new Sunny Day show". |

**Rejected:** none. Round 1 resolved by the author (Claude Sonnet 5.5), October 20, 2026: 7 of 7 fixed (row 6 by recording the departure,
not by changing the tests). Test-suite result after the fixes: 798 passed, 52 failed, 18 errors, 15 skipped with the two gaps open
(every red result is `NotImplementedError: TODO(Ari)`); 868 passed, 15 skipped with the gaps filled on a scratch copy. No round 2
review was run; nothing in the fixes touched the write path, only a function's shape (`failure_for`), tests and comments.
