"""The audit trail: what each of the six steps records, and the writer that appends it to Postgres.

HOW TO READ THIS
  Every time a graph node runs, one `audit_log` row is appended for it (data-model-initial.md §3; build plan
  A4). Three pieces, from pure to impure:

  * `entry_for(step, state)` is a **pure function** from the state after a node ran to an `AuditEntry`, the
    row-to-be. All the rules about what a step records (which attempt number, whether a model is named,
    what goes in `detail`) are here, so they are tested without a database (test_audit_entries.py).
  * `AuditWriter` is the interface the graph writes through: open a run, record an entry, close a run.
    `PostgresAuditWriter` is the real one; tests use `fakes.RecordingAudit`.
  * `trace.audited(step, node)` (trace.py) is the wrapper that calls the node, then `entry_for`, then the writer.

  Commit (A6) adds a fourth kind of row: one per show it writes, one per artist it creates, and one per show whose
  write failed (the builders `show_write_entry`, `artist_created_entry`, `show_failure_entry`). Those rows are not
  written through `AuditWriter.record`: the calendar writer adds them to the SAME transaction as the change they
  record (`calendar_writer.py`), so a rolled-back write leaves no row. They use `audit_row` to become ORM rows, the
  one place that knows the columns. The run's `commit` summary row (`entry_for`) is written afterwards, as every
  step's row is.

WHY IT'S SHAPED THIS WAY
  * **Append-only.** `record` only ever INSERTs. A retry is another row, never an edit of the first, which is
    what preserves the retry history (arch-initial.md §7). The writer has no method that changes an audit row.
  * **One short session per call, committed.** Each row is durable the moment it is written, so a crash later
    in the run cannot roll back the record of what led up to it. A long transaction spanning the run would
    lose exactly the rows that explain the crash.
  * **`detail` carries the why.** The typed columns say who/what kind; `detail` (JSONB, plan A4-D2) carries the
    evidence: validate's verdict and reasons, fetch's error, extract's route and staging id, escalate's
    reason. The keys are what `docs/dev/audit-queries.sql` reads; change one in both places.

docs/dev/implementations/a4-auditability.md.
"""

import dataclasses
import decimal
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic_core import to_jsonable_python
from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_worker.commit import CommitResult, ShowFailure, ShowOp, summary_counts
from agent_worker.state import VenueGraphState
from app.config import AppEnv
from app.db.models import AgentRun, AuditLog
from app.enums import AuditOutcome, AuditSource, EntityType, RunTrigger, StepType

# ---------------------------------------------------------------------------
# The row-to-be
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuditEntry:
    """One `audit_log` row before it is written: the columns A4 fills, and (A6) the snapshots.

    `previous_value` / `new_value` are the row snapshots a future revert restores (`commit.snapshot_of`); only
    commit's per-show and per-artist rows carry them. `snapshot_key` is absent (R2 is deferred; the column stays
    NULL). `created_at` is the database's.
    """

    run_id: int | None
    attempt_number: int
    step_type: StepType
    source: AuditSource
    entity_type: EntityType | None = None
    entity_id: int | None = None
    outcome: AuditOutcome | None = None
    model_used: str | None = None
    confidence: decimal.Decimal | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    previous_value: dict[str, Any] | None = None
    new_value: dict[str, Any] | None = None


def audit_row(entry: AuditEntry) -> AuditLog:
    """The ORM row for an entry: the one place that maps an `AuditEntry` onto `audit_log`'s columns.

    Both writers use it: `PostgresAuditWriter.record` (its own session) and the calendar writer (the write's own
    transaction), so a column added to the table is added in one place.
    """
    return AuditLog(
        run_id=entry.run_id, attempt_number=entry.attempt_number, step_type=entry.step_type, source=entry.source,
        entity_type=entry.entity_type, entity_id=entry.entity_id, outcome=entry.outcome, model_used=entry.model_used,
        confidence=entry.confidence, previous_value=entry.previous_value, new_value=entry.new_value, detail=entry.detail,
    )


def audit_confidence(value: float | None) -> decimal.Decimal | None:
    """The model's confidence as the `Numeric(4, 3)` column wants it, with "no confidence" kept as None.

    Two rules, both from earlier decisions:

    * **None stays None.** A3 decided (A3-D9) that "no confidence" is no evidence, not zero: the JSON-LD
      route's 1.0 is a placeholder, and a page with nothing kept has nothing to be confident about. The
      audit trail is where A8 will measure calibration, so a 0.000 would read as "the model was certain it
      was wrong" and corrupt that check.
    * **Through `str`, then quantize.** `Decimal(0.1)` is the float's binary value
      (0.1000000000000000055511151231257827...), not the number the model said; `Decimal("0.1")` is. Then
      `quantize` fits it to three places, the column's scale (`app/db/models/audit.py`).

    (A4-K2 in the plan; re-marked [written] by Ari at approval, so written complete here.)
    """
    if value is None:
        return None
    return decimal.Decimal(str(value)).quantize(decimal.Decimal("0.001"))


# ---------------------------------------------------------------------------
# What each step records
# ---------------------------------------------------------------------------

# The steps that act on the venue itself. Reconcile's summary row (A5) and commit's (A6) are venue-level; reconcile's
# model decisions about artists are separate rows (`model_decision_entries`), and commit's rows about a show or an
# artist are built below, written by the calendar writer.
_VENUE_LEVEL = {
    StepType.FETCH, StepType.EXTRACT, StepType.VALIDATE, StepType.RECONCILE, StepType.COMMIT, StepType.ESCALATE,
}
# The two steps where a language model made the judgement being recorded: extract (reads the page or
# splits titles) and validate (the verdict weighs the model's own confidence).
_MODEL_STEPS = {StepType.EXTRACT, StepType.VALIDATE}


def attempt_number(step: StepType, state: VenueGraphState) -> int:
    """Fetch is one row per run (its transient retries happen inside the step), so always 1. Every later
    step takes the attempt it belongs to, floored at 1: an escalation straight after a failed fetch has an
    attempt count of 0, and the column's default (1) means "first"."""
    if step is StepType.FETCH:
        return 1
    return max(1, state.attempt_count)


def _detail(step: StepType, state: VenueGraphState, staging_id: str | None) -> dict[str, Any]:
    """The step's evidence, as plain data that goes into the JSONB `detail` column."""
    plan = state.last_plan
    match step:
        case StepType.FETCH:
            detail: dict[str, Any] = {
                "url": state.calendar_url,
                "fetched_on": state.fetched_on,
                "error": state.fetch_error,
                "text_chars": len(state.page_content or ""),
            }
        case StepType.EXTRACT:
            detail = {
                "tier": plan.tier if plan else None,
                "route": state.route_attempted,
                "error": state.extract_error,
                "staging_id": staging_id,
                "shows": len(state.extraction.shows) if state.extraction else None,
                "larger_model_used": plan.larger_model_used if plan else False,
            }
        case StepType.VALIDATE:
            result = state.validation
            detail = {
                "route": state.route_attempted,
                "verdict": result.verdict if result else None,
                "reasons": result.reasons if result else [],
                "errors": [f.message for f in result.errors] if result else [],
                "warnings": len(result.warnings) if result else 0,
                "repairs": len(result.repairs) if result else 0,
                "excluded": len(result.excluded) if result else 0,
            }
        case StepType.RECONCILE:
            detail = _reconcile_detail(state)
        case StepType.COMMIT:
            detail = _commit_detail(state)
        case StepType.ESCALATE:
            detail = {"reason": state.escalation_reason}
    # `to_jsonable_python` turns dates, StrEnums and dataclasses into JSON types: a `date` reaching JSONB
    # unconverted raises at insert time, mid-run.
    converted: dict[str, Any] = to_jsonable_python(detail)
    return converted


def _reconcile_detail(state: VenueGraphState) -> dict[str, Any]:
    """Reconcile's summary row (A5-D11): what it decided, over what range, and what a person should look at.

    Keys (also listed in docs/dev/audit-queries.sql): `counts` (decisions per action), `coverage` (the window
    removals were judged inside, or null for a page with no dates), `needs_review` (decisions where a guess
    was involved), `withheld` (removals the guard held back, A5-D10), `artists` (resolutions per outcome) and
    `model_decisions` (how many the model made; each has its own row).
    """
    plan = state.reconcile_plan
    if plan is None:
        return {"plan": None}

    def where(decision: Any) -> dict[str, Any]:
        acts = [a.name for a in decision.listing.acts] if decision.listing else None
        return {
            "action": decision.action, "date": decision.date, "time": decision.start_time,
            "stored_id": decision.stored_id, "acts": acts, "reason": decision.reason,
        }

    outcomes = {"exact": 0, "new": 0, "matched_by_model": 0, "new_after_model": 0}
    for resolution in plan.artists:
        outcomes[resolution.outcome] += 1
    return {
        "counts": plan.counts(),
        "coverage": {"start": plan.coverage.start, "end": plan.coverage.end} if plan.coverage else None,
        "needs_review": [where(d) for d in plan.shows if d.needs_review],
        "withheld": [where(d) for d in plan.withheld],
        "artists": outcomes,
        "model_decisions": sum(1 for r in plan.artists if r.decided_by == "model"),
    }


def _failure_dict(failure: ShowFailure) -> dict[str, Any]:
    """A failed show as plain data: the same identity keys in the failure row and in the summary's `failed` list."""
    return dataclasses.asdict(failure)


def _commit_detail(state: VenueGraphState) -> dict[str, Any]:
    """Commit's summary row (A6): what was written, what failed, and what the guard held back.

    Keys (also listed in docs/dev/audit-queries.sql): `counts` (exactly `inserted`, `updated`, `removed`, `no_op`,
    `skip`; the first three are what was written, the last two what reconcile left alone), `artists_created`,
    `failed` (a list of the shows whose write was refused, each with its date, time, stored id, SQLSTATE and error;
    failures are never a key of `counts`), `all_failed` (true when three or more operations all failed, which looks like
    a bug and not bad listings) and `withheld` (how many removals the guard held back; they are never written).
    """
    plan = state.reconcile_plan
    result = state.commit_result or CommitResult()
    return {
        "counts": summary_counts(plan, result) if plan else {
            "inserted": 0, "updated": 0, "removed": 0, "no_op": 0, "skip": 0,
        },
        "artists_created": result.artists_created,
        "failed": [_failure_dict(f) for f in result.failures],
        "all_failed": result.all_failed,
        "withheld": len(plan.withheld) if plan else 0,
    }


def show_write_entry(
    op: ShowOp, *, run_id: int | None, attempt_number: int, show_id: int,
    previous: dict[str, Any] | None, new: dict[str, Any],
) -> AuditEntry:
    """The row for a show commit wrote (A6-D1: only writes get one): the outcome, the two snapshots a revert restores,
    and in `detail` why (the reconcile reason), which columns changed, and whether a guess was involved."""
    changed = sorted(op.values) + (["lineup"] if op.lineup is not None else [])
    return AuditEntry(
        run_id=run_id, attempt_number=attempt_number, step_type=StepType.COMMIT, source=AuditSource.AGENT,
        entity_type=EntityType.SHOW, entity_id=show_id, outcome=op.outcome, previous_value=previous, new_value=new,
        detail=to_jsonable_python({
            "action": op.action, "reconcile_reason": op.reconcile_reason, "changed": changed,
            "needs_review": op.needs_review,
        }),
    )


def artist_created_entry(
    *, run_id: int | None, attempt_number: int, artist_id: int, name: str, key: str,
) -> AuditEntry:
    """The row for an artist commit created, in the same transaction as the show that first needed it. Name only
    (requirements: all other artist fields are left for a human)."""
    return AuditEntry(
        run_id=run_id, attempt_number=attempt_number, step_type=StepType.COMMIT, source=AuditSource.AGENT,
        entity_type=EntityType.ARTIST, entity_id=artist_id, outcome=AuditOutcome.INSERTED,
        new_value={"id": artist_id, "name": name}, detail={"name": name, "key": key},
    )


def show_failure_entry(failure: ShowFailure, *, run_id: int | None, attempt_number: int) -> AuditEntry:
    """The row for a show whose write the database refused. It has no outcome and no snapshots (nothing was written),
    and its `detail` says WHICH show failed (an insert has no id yet) and why. Written outside the rolled-back
    transaction, through `AuditWriter.record`."""
    return AuditEntry(
        run_id=run_id, attempt_number=attempt_number, step_type=StepType.COMMIT, source=AuditSource.AGENT,
        entity_type=EntityType.SHOW, entity_id=failure.stored_id, detail=to_jsonable_python(_failure_dict(failure)),
    )


def model_decision_entries(state: VenueGraphState) -> list[AuditEntry]:
    """One reconcile row for each artist the MODEL decided (A5-D11), with `model_used` and `confidence`.

    A rule-decided artist (exact or new) needs no row of its own: the summary counts it. A model decision does,
    because it is a judgement call that changed what the calendar links to, and "why did the app think
    'Zhora Band' was 'Zhora'?" has to be answerable. `entity_id` is the artist it linked to, or None when the
    answer was "new" (the artist does not exist yet). The fallback (a failed call, low confidence) is a row too,
    with its reason, so it is visible.
    """
    plan = state.reconcile_plan
    if plan is None:
        return []
    return [
        AuditEntry(
            run_id=state.run_id, attempt_number=attempt_number(StepType.RECONCILE, state),
            step_type=StepType.RECONCILE, source=AuditSource.AGENT, entity_type=EntityType.ARTIST,
            entity_id=resolution.artist_id, model_used=resolution.model_used,
            confidence=audit_confidence(resolution.confidence),
            detail=to_jsonable_python({
                "name": resolution.name, "outcome": resolution.outcome, "reason": resolution.reason,
                "candidates": [{"id": c.id, "name": c.name} for c in resolution.candidates],
            }),
        )
        for resolution in plan.artists if resolution.decided_by == "model"
    ]


def entry_for(step: StepType, state: VenueGraphState, staging_id: str | None = None) -> AuditEntry:
    """The audit row for `step`, given the state after that node ran. Pure: no I/O.

    `staging_id` is the MongoDB document id for an extract step (trace.audited stages first, then calls
    this); it is recorded in `detail` and is how the two stores join (plan A4-D4).
    """
    plan = state.last_plan
    on_venue = step in _VENUE_LEVEL
    return AuditEntry(
        run_id=state.run_id,
        attempt_number=attempt_number(step, state),
        step_type=step,
        source=AuditSource.AGENT,
        entity_type=EntityType.VENUE if on_venue else None,
        entity_id=state.venue_id if on_venue else None,
        outcome=AuditOutcome.ESCALATED if step is StepType.ESCALATE else None,
        model_used=plan.options.model if plan and step in _MODEL_STEPS else None,
        # Confidence is computed by validation, so only the validate row has it; extract runs before it exists.
        confidence=audit_confidence(state.confidence) if step is StepType.VALIDATE else None,
        detail=_detail(step, state, staging_id if step is StepType.EXTRACT else None),
    )


# ---------------------------------------------------------------------------
# The writer
# ---------------------------------------------------------------------------


class AuditWriter(Protocol):
    """Where the audit trail is written. The graph depends on this, not on Postgres."""

    async def start_run(self, venue_id: int, trigger: RunTrigger) -> int:
        """Open an `agent_run` and return its id (the `parent_run_id`)."""
        ...

    async def record(self, entry: AuditEntry) -> int:
        """Append one `audit_log` row and return its id."""
        ...

    async def finish_run(self, run_id: int) -> None:
        """Stamp the run finished."""
        ...


class PostgresAuditWriter:
    """Writes the audit trail to Postgres with a short, committed session per call (see the module docstring)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], app_env: AppEnv | None = None) -> None:
        self._session_factory = session_factory
        # The environment written on every run this writer opens (C3-D5). Handed in by the entry point
        # (`settings.app_env`), not read from global settings here, so a test can prove the value is the one
        # injected. `None` writes NULL: "unknown", the same as a run recorded before C3.
        self._app_env = app_env

    async def start_run(self, venue_id: int, trigger: RunTrigger) -> int:
        async with self._session_factory() as session:
            run = AgentRun(venue_id=venue_id, trigger=trigger, app_env=self._app_env)
            session.add(run)
            # flush assigns the id; read it BEFORE commit. After a commit a session built with SQLAlchemy's
            # default `expire_on_commit=True` has expired the attribute, and reading it under asyncio raises
            # `MissingGreenlet`, an error that doesn't point at the cause (A4-CR1-4).
            await session.flush()
            run_id = run.id
            await session.commit()
            return run_id

    async def record(self, entry: AuditEntry) -> int:
        async with self._session_factory() as session:
            row = audit_row(entry)
            session.add(row)
            await session.flush()
            row_id = row.id  # before commit, for the reason in `start_run`
            await session.commit()
            return row_id

    async def finish_run(self, run_id: int) -> None:
        # The one UPDATE in this class, and it is on `agent_run` (its lifecycle timestamp), not on the
        # append-only `audit_log`.
        # `clock_timestamp()`, Postgres's real current time, not `now()` (the transaction's start, which
        # inside one transaction, as in the tests, equals `started_at`) and not the worker's own clock:
        # `started_at` and `created_at` come from the database, so a run's duration should be one clock's
        # difference and not go negative under worker/database skew (A4-CR1-5).
        async with self._session_factory() as session:
            await session.execute(
                update(AgentRun).where(AgentRun.id == run_id).values(finished_at=func.clock_timestamp())
            )
            await session.commit()
