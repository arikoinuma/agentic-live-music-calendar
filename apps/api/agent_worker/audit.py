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

WHY IT'S SHAPED THIS WAY
  * **Append-only.** `record` only ever INSERTs. A retry is another row, never an edit of the first, which is
    what preserves the retry history (arch-initial.md §7). The writer has no method that changes an audit row.
  * **One short session per call, committed.** Each row is durable the moment it is written, so a crash later
    in the run cannot roll back the record of what led up to it. A long transaction spanning the run would
    lose exactly the rows that explain the crash.
  * **`detail` carries the why.** The typed columns say who/what kind; `detail` (JSONB, plan D2) carries the
    evidence: validate's verdict and reasons, fetch's error, extract's route and staging id, escalate's
    reason. The keys are what `docs/dev/audit-queries.sql` reads; change one in both places.

docs/dev/implementations/a4-auditability.md.
"""

import datetime
import decimal
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic_core import to_jsonable_python
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_worker.state import VenueGraphState
from app.db.models import AgentRun, AuditLog
from app.enums import AuditOutcome, AuditSource, EntityType, RunTrigger, StepType

# ---------------------------------------------------------------------------
# The row-to-be
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuditEntry:
    """One `audit_log` row before it is written: the columns A4 fills.

    `previous_value` / `new_value` are absent on purpose: they are the row snapshots a future revert
    restores, and nothing writes a per-show row until A6. `snapshot_key` is absent too (R2 is deferred; the
    column stays NULL). `created_at` is the database's.
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


def audit_confidence(value: float | None) -> decimal.Decimal | None:
    """The model's confidence as the `Numeric(4, 3)` column wants it, with "no confidence" kept as None.

    Two rules, both from earlier decisions:

    * **None stays None.** A3 decided (D9) that "no confidence" is no evidence, not zero: the JSON-LD
      route's 1.0 is a placeholder, and a page with nothing kept has nothing to be confident about. The
      audit trail is where A8 will measure calibration, so a 0.000 would read as "the model was certain it
      was wrong" and corrupt that check.
    * **Through `str`, then quantize.** `Decimal(0.1)` is the float's binary value
      (0.1000000000000000055511151231257827...), not the number the model said; `Decimal("0.1")` is. Then
      `quantize` fits it to three places, the column's scale (`app/db/models/audit.py`).

    (Gap B in the plan; re-marked [written] by Ari at approval, so written complete here.)
    """
    if value is None:
        return None
    return decimal.Decimal(str(value)).quantize(decimal.Decimal("0.001"))


# ---------------------------------------------------------------------------
# What each step records
# ---------------------------------------------------------------------------

# The four steps that act on the venue itself. Reconcile and commit act on no entity until A5/A6 write
# per-show rows, so their A4 placeholder rows name none.
_VENUE_LEVEL = {StepType.FETCH, StepType.EXTRACT, StepType.VALIDATE, StepType.ESCALATE}
# The two steps where a language model made the judgement being recorded: extract (reads the page or
# splits titles) and validate (the verdict weighs the model's own confidence).
_MODEL_STEPS = {StepType.EXTRACT, StepType.VALIDATE}


def _attempt_number(step: StepType, state: VenueGraphState) -> int:
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
        case StepType.RECONCILE | StepType.COMMIT:
            # A5 / A6 replace these stubs; until then the row says so, so nobody reads it as a decision.
            detail = {"stub": True, "decision": state.reconcile_decision}
        case StepType.ESCALATE:
            detail = {"reason": state.escalation_reason}
    # `to_jsonable_python` turns dates, StrEnums and dataclasses into JSON types: a `date` reaching JSONB
    # unconverted raises at insert time, mid-run.
    converted: dict[str, Any] = to_jsonable_python(detail)
    return converted


def entry_for(step: StepType, state: VenueGraphState, staging_id: str | None = None) -> AuditEntry:
    """The audit row for `step`, given the state after that node ran. Pure: no I/O.

    `staging_id` is the MongoDB document id for an extract step (trace.audited stages first, then calls
    this); it is recorded in `detail` and is how the two stores join (plan D4).
    """
    plan = state.last_plan
    on_venue = step in _VENUE_LEVEL
    return AuditEntry(
        run_id=state.run_id,
        attempt_number=_attempt_number(step, state),
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

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def start_run(self, venue_id: int, trigger: RunTrigger) -> int:
        async with self._session_factory() as session:
            run = AgentRun(venue_id=venue_id, trigger=trigger)
            session.add(run)
            await session.commit()
            return run.id

    async def record(self, entry: AuditEntry) -> int:
        async with self._session_factory() as session:
            row = AuditLog(
                run_id=entry.run_id, attempt_number=entry.attempt_number, step_type=entry.step_type,
                source=entry.source, entity_type=entry.entity_type, entity_id=entry.entity_id,
                outcome=entry.outcome, model_used=entry.model_used, confidence=entry.confidence,
                detail=entry.detail,
            )
            session.add(row)
            await session.commit()
            return row.id

    async def finish_run(self, run_id: int) -> None:
        # The one UPDATE in this class, and it is on `agent_run` (its lifecycle timestamp), not on the
        # append-only `audit_log`.
        async with self._session_factory() as session:
            now = datetime.datetime.now(datetime.UTC)
            await session.execute(update(AgentRun).where(AgentRun.id == run_id).values(finished_at=now))
            await session.commit()
