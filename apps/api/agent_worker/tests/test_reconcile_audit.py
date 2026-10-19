"""Tests for what reconcile's audit rows contain: the summary row and one row per model decision about an artist.

Milestone A5 (docs/dev/implementations/a5-reconcile.md, A5-D11 and Test approach §4). `audit.entry_for` and
`audit.model_decision_entries` are pure functions of the state, so the rules about what is recorded are tested here
without a graph or a database, as test_audit_entries.py does for the other steps. The keys of the summary row's
`detail` are read by `docs/dev/audit-queries.sql`; changing one means changing both.

Expected values come from A5-D11 (what each row carries), data-model-initial.md §3 (`audit_log` columns) and A3-D9
("no confidence" is no evidence, not zero), and the literal inputs.
"""

import datetime
import json
from decimal import Decimal

from agent_worker.artist_match import ArtistResolution, KnownArtist
from agent_worker.audit import entry_for, model_decision_entries
from agent_worker.reconcile import (
    Action,
    Coverage,
    ReconcilePlan,
    ShowDecision,
    StoredShow,
)
from agent_worker.state import VenueGraphState
from agent_worker.tests.reconcile_support import at, day, listed
from app.enums import AuditOutcome, AuditSource, EntityType, StepType


def state_with(plan: ReconcilePlan | None) -> VenueGraphState:
    return VenueGraphState(
        venue_id=4, calendar_url="https://venue.example/events", venue_name="The Venue",
        metro_timezone="America/Chicago", fetched_on=datetime.date(2026, 10, 12), run_id=9, attempt_count=2,
        reconcile_plan=plan,
    )


def decision(action: Action, **fields: object) -> ShowDecision:
    fields.setdefault("reason", "because")
    return ShowDecision(action, day(20), at(20), **fields)  # type: ignore[arg-type]


def matched(confidence: float | None = 0.9) -> ArtistResolution:
    return ArtistResolution(
        name="Zhora Band", key="zhora band", outcome="matched_by_model", artist_id=8, decided_by="model",
        model_used="test-model", confidence=confidence, candidates=(KnownArtist(8, "Zhora"),), reason="same band",
    )


def test_the_summary_row_counts_every_action_and_names_the_window() -> None:
    # Proves (A5-D11): the reconcile row is venue-level and carries the counts (every action present, so the row's
    # shape doesn't depend on the run), the window it judged removals inside (A5-D1), and the number of model
    # decisions. It takes the attempt number of the attempt that passed, like validate's.
    plan = ReconcilePlan(
        Coverage(day(12), day(31)),
        (decision(Action.INSERT), decision(Action.INSERT), decision(Action.NO_OP)),
        artists=(matched(),),
    )
    entry = entry_for(StepType.RECONCILE, state_with(plan))
    assert (entry.entity_type, entry.entity_id, entry.attempt_number) == (EntityType.VENUE, 4, 2)
    assert entry.model_used is None and entry.confidence is None and entry.outcome is None
    assert entry.detail["counts"] == {"insert": 2, "update": 0, "no_op": 1, "remove": 0, "skip": 0}
    assert entry.detail["coverage"] == {"start": "2026-10-12", "end": "2026-10-31"}
    assert entry.detail["model_decisions"] == 1 and entry.detail["artists"]["matched_by_model"] == 1


def test_a_page_with_no_dates_records_a_null_window() -> None:
    # Proves (A5-D2): a confirmed-empty page has no window, and the row says so (`coverage: null`) rather than
    # inventing a range, which is how a person reading the trail learns nothing was removed and why.
    detail = entry_for(StepType.RECONCILE, state_with(ReconcilePlan(None, ()))).detail
    assert detail["coverage"] is None and detail["counts"]["remove"] == 0


def test_the_summary_lists_what_a_person_should_look_at_and_what_the_guard_held_back() -> None:
    # Proves (A5-D10, "Settled details"): flagged decisions and withheld removals are in the row, each with its
    # date, time, stored id and reason, so "what did reconcile hold back, and what is unsure?" is a query.
    flagged = decision(Action.INSERT, needs_review=True, listing=listed(0, day(20), at(20), acts=["Nona"]))
    held = decision(Action.REMOVE, stored_id=3, reason="absent from the page (withheld by the removal guard)")
    detail = entry_for(StepType.RECONCILE, state_with(ReconcilePlan(None, (flagged,), withheld=(held,)))).detail
    assert [(r["action"], r["acts"]) for r in detail["needs_review"]] == [("insert", ["Nona"])]
    assert [(r["stored_id"], r["time"]) for r in detail["withheld"]] == [(3, "20:00:00")]


def test_a_model_decision_has_its_own_row_with_model_and_confidence() -> None:
    # Proves (A5-D11): an artist the MODEL decided gets a `reconcile` row: entity = the artist it linked, `model_used`,
    # the confidence in the column's Decimal form, and the name, answer, reason and candidates in `detail`. A
    # rule-decided artist gets none (the summary counts it).
    rule = ArtistResolution("Nona", "nona", "exact", 7, "rule")
    plan = ReconcilePlan(None, (), artists=(rule, matched(0.9)))
    [entry] = model_decision_entries(state_with(plan))
    assert (entry.step_type, entry.source, entry.entity_type, entry.entity_id) == (
        StepType.RECONCILE, AuditSource.AGENT, EntityType.ARTIST, 8,
    )
    assert entry.model_used == "test-model" and entry.confidence == Decimal("0.900") and entry.outcome is None
    assert entry.detail == {
        "name": "Zhora Band", "outcome": "matched_by_model", "reason": "same band",
        "candidates": [{"id": 8, "name": "Zhora"}],
    }


def test_a_fallback_after_a_failed_call_is_a_row_with_no_confidence_not_zero() -> None:
    # Proves (A3-D9, A5-D9): when the model call failed there is no confidence, and the audit trail must say NULL, not
    # 0.000 (which A8 would read as "the model was certain it was wrong"). The row exists anyway: the fallback is
    # visible, with the failure in the reason, and `entity_id` is None because the artist doesn't exist yet.
    failed = ArtistResolution(
        "Zhora Band", "zhora band", "new_after_model", None, "model", model_used="test-model", confidence=None,
        candidates=(KnownArtist(8, "Zhora"),), reason="model call failed: ValueError: no",
    )
    [entry] = model_decision_entries(state_with(ReconcilePlan(None, (), artists=(failed,))))
    assert entry.confidence is None and entry.entity_id is None and "failed" in entry.detail["reason"]


def test_there_are_no_model_rows_without_a_plan_or_without_model_decisions() -> None:
    # Proves: a state that never reached reconcile, or a plan decided entirely by rules, writes no extra rows.
    assert model_decision_entries(state_with(None)) == []
    assert model_decision_entries(state_with(ReconcilePlan(None, ()))) == []


def test_every_reconcile_row_is_json_serialisable() -> None:
    # Proves: dates, times, enums and tuples reaching JSONB unconverted would raise at insert time, mid-run
    # (the A4 check, extended to the new rows).
    stored_show = StoredShow(id=3, date=day(20))
    plan = ReconcilePlan(
        Coverage(day(12), day(31)),
        (decision(Action.UPDATE, stored_id=stored_show.id, needs_review=True, listing=listed(0, day(20), at(20))),),
        artists=(matched(),), withheld=(decision(Action.REMOVE, stored_id=3),),
    )
    state = state_with(plan)
    json.dumps(entry_for(StepType.RECONCILE, state).detail)
    for entry in model_decision_entries(state):
        json.dumps(entry.detail)


def test_each_action_maps_to_the_audit_outcome_commit_will_write() -> None:
    # Proves: `Action.outcome` is the name A6's per-show audit rows will use (`audit_outcome` in
    # data-model-initial.md §4): insert, update, remove and no-op map one to one, and `skip` writes no row at all.
    assert [a.outcome for a in (Action.INSERT, Action.UPDATE, Action.REMOVE, Action.NO_OP, Action.SKIP)] == [
        AuditOutcome.INSERTED, AuditOutcome.UPDATED, AuditOutcome.REMOVED, AuditOutcome.NO_OP, None,
    ]
