"""Agent runs and the append-only audit trail.

HOW THIS FITS TOGETHER
  Every time the agent processes one venue, it opens an `AgentRun`. Every
  step it takes during that run (fetch, extract, validate, reconcile,
  commit, escalate), including each retry, appends one `AuditLog` row that
  points back at the run. Rows are only ever added, never edited or removed,
  so "what happened in run N, and why does this show look the way it does?"
  can be answered entirely from these two tables. That is the project's
  "auditable by construction" requirement (v1-build-plan.md, section 2).

docs/arch/data-model-initial.md section 3; the design (why append-only, why
`parent_run_id`) is arch-initial.md section 7.

Departures from section 3, recorded in
docs/dev/implementations/a1-data-layer.md:

* `agent_run.triggered_by` and `audit_log.contributor_id` are omitted. Their
  FK target, `contributor`, is deferred (v1-build-plan.md section 8), so they
  can't be created as specified; a plain unconstrained integer would be a
  column that is always NULL.
* `audit_log.session_hash` is omitted for the same always-empty reason: it
  is populated only for `source = 'user'` rows, and user edits are deferred.
  Adding any of these later is a nullable-column migration with no backfill.
* `audit_log.snapshot_key` is the one always-NULL column that is kept. The
  build plan (A4) expects it to exist and stay null until the R2 snapshot
  write lands, so it's the documented hook rather than a speculative field.
* `agent_run` has no `created_at` / `updated_at`: `started_at` and
  `finished_at` are its lifecycle timestamps.
* `audit_log.confidence` is `Numeric(4, 3)` (0.000–1.000). The worker holds a
  float; A4 converts at the write.
"""

import datetime
import decimal
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Numeric, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import types
from app.db.base import Base
from app.enums import AuditOutcome, AuditSource, EntityType, RunTrigger, StepType


class AgentRun(Base):
    """One venue-processing cycle: the `parent_run_id` of arch-initial.md.

    Every fetch/extract/validate/reconcile attempt for the cycle, retries
    included, points back at one row here.
    """

    __tablename__ = "agent_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Which venue this run processed.
    venue_id: Mapped[int] = mapped_column(ForeignKey("venue.id"))
    # Why the run started: scheduled / manual / submission / flag_threshold.
    trigger: Mapped[RunTrigger] = mapped_column(types.RUN_TRIGGER)
    started_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # NULL while the run is in progress.
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    """Append-only: a retry adds a row, it never replaces one."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Indexed because Postgres doesn't index FK columns, and the first
    # question anyone asks of this table is "everything that happened in
    # run N" (A4's saved queries). NULL for a human edit not tied to a run.
    run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_run.id"), index=True)
    # Distinguishes retries within one run_id.
    attempt_number: Mapped[int] = mapped_column(server_default=text("1"))
    # Which pipeline stage wrote this row (the six graph nodes).
    step_type: Mapped[StepType] = mapped_column(types.STEP_TYPE)
    # Whether an agent or a human caused it. Humans only appear once public
    # editing exists (deferred), but the column makes the log uniform.
    source: Mapped[AuditSource] = mapped_column(types.AUDIT_SOURCE)
    # What kind of record this row acted on (pairs with entity_id below).
    entity_type: Mapped[EntityType | None] = mapped_column(types.ENTITY_TYPE)
    # Deliberately NOT a foreign key: the referenced row may live in any of
    # several tables, and may later be genuinely deleted. The audit trail
    # must survive that (data-model-initial.md section 3).
    entity_id: Mapped[int | None]
    # What happened to that record: inserted / updated / removed / no_op /
    # escalated. Filled on reconcile and commit rows.
    outcome: Mapped[AuditOutcome | None] = mapped_column(types.AUDIT_OUTCOME)
    # For rows where a language model made a decision: which model, and how
    # sure it said it was. NULL on purely deterministic steps.
    model_used: Mapped[str | None]
    confidence: Mapped[decimal.Decimal | None] = mapped_column(Numeric(4, 3))
    # Snapshots of the affected row before/after this action — what a
    # future revert restores.
    previous_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # R2 object key for the page snapshot, on `fetch` rows. R2 is deferred,
    # so this stays NULL until it lands.
    snapshot_key: Mapped[str | None]
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
