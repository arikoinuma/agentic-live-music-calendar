"""Tests for `audit.entry_for`: what each of the six steps records, as a pure function of the state.

Milestone A4 (docs/dev/implementations/a4-auditability.md, Test approach §1). `entry_for(step, state)` turns
the graph state after a node ran into the row that node's audit write will insert. Because it touches no
database, every rule the build plan states about the trail ("`step_type`, `attempt_number`,
`source='agent'`, and on the agentic steps `model_used` and `confidence`") is tested here directly.

How to read it: helpers build the states a node would leave behind (fetched, extracted, validated,
escalated), then each test names one rule and asserts the entry. Expected values come from the plan and
`data-model-initial.md` §3 and from the literal inputs, never from the code under test. The Numeric(4, 3)
column (`app/db/models/audit.py`) is the oracle for the confidence conversion.
"""

import dataclasses
import datetime
import json
from decimal import Decimal

import pytest

from agent_worker import extraction
from agent_worker.audit import AuditEntry, audit_confidence, entry_for
from agent_worker.policy import AttemptPlan, AttemptRecord
from agent_worker.state import VenueGraphState
from agent_worker.validation import (
    CheckCode,
    FailureReason,
    Finding,
    Repair,
    Severity,
    ValidationResult,
    Verdict,
)
from app.enums import AuditOutcome, AuditSource, EntityType, StepType

PLAN = AttemptPlan(tier="initial", config=extraction.PIPELINE_CONFIG, options=extraction.PIPELINE_OPTIONS)


def base_state(**changes: object) -> VenueGraphState:
    """A state as fetch would leave it, for venue 4, run 9."""
    fields: dict[str, object] = {
        "venue_id": 4, "calendar_url": "https://venue.example/events", "venue_name": "The Venue",
        "metro_timezone": "America/Chicago", "fetched_on": datetime.date(2026, 10, 12), "run_id": 9,
        "page_content": "x" * 120,
    }
    fields.update(changes)
    return VenueGraphState(**fields)  # type: ignore[arg-type]


def passed_validation(**changes: object) -> ValidationResult:
    """A `ValidationResult` that passed at 0.9 confidence, with one warning, one repair and one excluded show,
    so the validate row's counts have something to count. A test overrides what it needs."""
    fields: dict[str, object] = {
        "outcome": None, "verdict": Verdict.PASSED, "confidence": 0.9,
        "findings": [Finding(CheckCode.AMBIGUOUS, Severity.WARNING, "maybe two shows", 0)],
        "repairs": [Repair(0, "image_url", "http://x/y.png", "not on the page")], "excluded": [3],
    }
    fields.update(changes)
    return ValidationResult(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Every step
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("step", list(StepType))
def test_every_step_is_an_agent_row_for_the_run_in_the_state(step: StepType) -> None:
    # Proves: `source='agent'` (build plan A4) and `run_id` is the run carried in the state (the
    # `parent_run_id`, arch-initial.md §7) for all six steps, so every audit row points at its run.
    entry = entry_for(step, base_state(attempt_count=1))
    assert entry.step_type is step and entry.source is AuditSource.AGENT and entry.run_id == 9


@pytest.mark.parametrize("step", [StepType.FETCH, StepType.EXTRACT, StepType.VALIDATE, StepType.ESCALATE])
def test_the_four_venue_level_steps_act_on_the_venue(step: StepType) -> None:
    # Proves: fetch, extract, validate and escalate name the venue as the entity they acted on
    # (`entity_type=venue`, `entity_id=venue_id`; data-model-initial.md §3).
    entry = entry_for(step, base_state(attempt_count=1))
    assert (entry.entity_type, entry.entity_id) == (EntityType.VENUE, 4)


@pytest.mark.parametrize("step", [StepType.RECONCILE, StepType.COMMIT])
def test_the_stub_steps_name_no_entity_yet(step: StepType) -> None:
    # Proves: reconcile and commit act on no row until A5/A6 write per-show rows, so their A4 placeholder
    # rows carry no entity rather than a venue they did not change.
    entry = entry_for(step, base_state(attempt_count=1, reconcile_decision="insert"))
    assert entry.entity_type is None and entry.entity_id is None and entry.outcome is None


# ---------------------------------------------------------------------------
# attempt_number
# ---------------------------------------------------------------------------


def test_fetch_is_always_attempt_one() -> None:
    # Proves: fetch has one row per run (its transient retries happen inside the step, in
    # `nodes.fetch_html`), so it is attempt 1 whatever the extract count is.
    assert entry_for(StepType.FETCH, base_state()).attempt_number == 1


@pytest.mark.parametrize("step", [StepType.EXTRACT, StepType.VALIDATE])
def test_extract_and_validate_use_the_attempt_count(step: StepType) -> None:
    # Proves: a retry's rows are distinguishable (`attempt_number` "distinguishes retries within one
    # run_id", data-model-initial.md §3): the third attempt's rows say 3.
    assert entry_for(step, base_state(attempt_count=3)).attempt_number == 3


@pytest.mark.parametrize("step", [StepType.RECONCILE, StepType.COMMIT, StepType.ESCALATE])
def test_later_steps_use_the_last_attempt_floored_at_one(step: StepType) -> None:
    # Proves: an escalation straight after a failed fetch has attempt_count 0, and the column's default
    # is 1 and means "first", so the row says 1, not 0; after three attempts it says 3.
    assert entry_for(step, base_state(attempt_count=0)).attempt_number == 1
    assert entry_for(step, base_state(attempt_count=3)).attempt_number == 3


# ---------------------------------------------------------------------------
# model_used and confidence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("step", [StepType.EXTRACT, StepType.VALIDATE])
def test_agentic_steps_record_the_model_the_attempt_used(step: StepType) -> None:
    # Proves: build plan A4, "on the agentic steps `model_used`": the model name is the attempt's own
    # (`last_plan.options.model`), which on a tier-3 attempt is the larger model when one ran.
    larger = AttemptPlan(
        tier="larger_model", config=extraction.PIPELINE_CONFIG,
        options=dataclasses.replace(PLAN.options, model="the-larger-model"), larger_model_used=True,
    )
    assert entry_for(step, base_state(attempt_count=1, last_plan=PLAN)).model_used == PLAN.options.model
    assert entry_for(step, base_state(attempt_count=3, last_plan=larger)).model_used == "the-larger-model"


@pytest.mark.parametrize("step", [StepType.FETCH, StepType.RECONCILE, StepType.COMMIT, StepType.ESCALATE])
def test_deterministic_steps_record_no_model_or_confidence(step: StepType) -> None:
    # Proves: fetch, the stubs and escalate are not model decisions, so both columns stay NULL even when
    # the state carries a plan and a confidence from earlier steps.
    entry = entry_for(step, base_state(attempt_count=1, last_plan=PLAN, confidence=0.9))
    assert entry.model_used is None and entry.confidence is None


def test_extract_records_no_confidence() -> None:
    # Proves: the confidence is computed by validation, after extract, so the extract row leaves it NULL
    # rather than recording a stale value from a previous attempt.
    entry = entry_for(StepType.EXTRACT, base_state(attempt_count=2, last_plan=PLAN, confidence=0.5))
    assert entry.confidence is None


def test_validate_records_the_states_confidence_as_a_decimal() -> None:
    # Proves: the validate row carries the confidence the verdict was built from, converted for the
    # Numeric(4, 3) column. 0.8567 -> 0.857 (three places, rounded), not the float's binary expansion.
    state = base_state(attempt_count=1, last_plan=PLAN, confidence=0.8567, validation=passed_validation())
    assert entry_for(StepType.VALIDATE, state).confidence == Decimal("0.857")


def test_a_json_ld_validate_row_has_confidence_none_not_zero() -> None:
    # Proves (A3-D9): "no confidence" is no evidence, not zero. The JSON-LD route has no model judgement of
    # the record, so the row's confidence is NULL; a 0.000 would read as "the model was certain it was
    # wrong" and corrupt A8's calibration check. The model name is still recorded: the act splitter ran.
    state = base_state(
        attempt_count=1, last_plan=PLAN, confidence=None, route_attempted="jsonld",
        validation=passed_validation(confidence=None),
    )
    entry = entry_for(StepType.VALIDATE, state)
    assert entry.confidence is None and entry.model_used == PLAN.options.model


# ---------------------------------------------------------------------------
# audit_confidence (written complete: A4-K2 was re-marked [written] at approval)
# ---------------------------------------------------------------------------


def test_audit_confidence_none_stays_none() -> None:
    # Proves: the None-stays-NULL rule on its own (see the JSON-LD test above for why it matters).
    assert audit_confidence(None) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.8567, "0.857"), (0.1, "0.100"), (1.0, "1.000"), (0.0, "0.000"), (0.9995, "1.000")],
)
def test_audit_confidence_goes_through_str_and_fits_three_places(value: float, expected: str) -> None:
    # Proves: `Decimal(str(x))` then quantize to 0.001. 0.1 must be exactly Decimal("0.100"), which
    # `Decimal(0.1)` is not (it carries the binary tail 0.1000000000000000055…), and the value fits
    # Numeric(4, 3) (max 9.999): 0.0 stays 0.000 (a real zero is a real answer, unlike None).
    result = audit_confidence(value)
    assert result == Decimal(expected)
    assert result is not None and result.as_tuple().exponent == -3


# ---------------------------------------------------------------------------
# detail: the evidence per step
# ---------------------------------------------------------------------------


def test_fetch_detail_records_url_date_error_and_size() -> None:
    # Proves (A4-D2): the fetch row can answer "what was fetched and did it work" from Postgres alone.
    ok = entry_for(StepType.FETCH, base_state()).detail
    assert ok == {"url": "https://venue.example/events", "fetched_on": "2026-10-12", "error": None, "text_chars": 120}
    failed = entry_for(StepType.FETCH, base_state(fetch_error="HTTPStatusError: 404", page_content=None)).detail
    assert failed["error"] == "HTTPStatusError: 404" and failed["text_chars"] == 0


def test_extract_detail_records_route_tier_error_and_the_staging_id() -> None:
    # Proves (A4-D4): `detail.staging_id` is what joins the extract row to its MongoDB document, and a failed
    # attempt's error is on the row. The expected keys are the plan's, spelled out.
    state = base_state(
        attempt_count=2, last_plan=PLAN, route_attempted="model", extract_error="ValueError: bad json",
    )
    detail = entry_for(StepType.EXTRACT, state, staging_id="doc-7").detail
    assert detail["staging_id"] == "doc-7"
    assert detail["tier"] == "initial" and detail["route"] == "model"
    assert detail["error"] == "ValueError: bad json" and detail["shows"] is None
    assert detail["larger_model_used"] is False


def test_validate_detail_records_verdict_reasons_messages_and_counts() -> None:
    # Proves: "what validation decided" (definition of done, point 3) is on the validate row: the verdict,
    # the failure reasons as their string codes, the error messages, and the counts of warnings, repairs
    # and exclusions.
    result = passed_validation(
        verdict=Verdict.FAILED, confidence=0.4,
        findings=[
            Finding(CheckCode.DATE_IMPLAUSIBLE, Severity.ERROR, "date is two years out", 1),
            Finding(CheckCode.AMBIGUOUS, Severity.WARNING, "maybe two shows", 0),
        ],
    ).with_verdict(Verdict.FAILED, [FailureReason.CHECK_ERRORS, FailureReason.LOW_CONFIDENCE])
    state = base_state(
        attempt_count=1, last_plan=PLAN, route_attempted="model", validation=result, confidence=0.4,
    )
    detail = entry_for(StepType.VALIDATE, state).detail
    assert detail["route"] == "model" and detail["verdict"] == "failed"
    assert detail["reasons"] == ["check_errors", "low_confidence"]
    assert detail["errors"] == ["date is two years out"]
    assert (detail["warnings"], detail["repairs"], detail["excluded"]) == (1, 1, 1)


def test_the_stub_steps_say_they_are_stubs() -> None:
    # Proves (A4-D5): until A5/A6, reconcile and commit rows are explicit placeholders, so nobody reads one as
    # a real decision. The decision string the stub set is carried.
    for step in (StepType.RECONCILE, StepType.COMMIT):
        detail = entry_for(step, base_state(attempt_count=1, reconcile_decision="insert")).detail
        assert detail == {"stub": True, "decision": "insert"}


def test_escalate_is_a_real_row_with_the_reason_and_the_escalated_outcome() -> None:
    # Proves (A4-D5): escalate writes `outcome='escalated'` and the plain-English reason, which is what the
    # "which runs escalated and why" query reads.
    state = base_state(attempt_count=3, escalation_reason="validation failed after 3 attempt(s)")
    entry = entry_for(StepType.ESCALATE, state)
    assert entry.outcome is AuditOutcome.ESCALATED
    assert entry.detail == {"reason": "validation failed after 3 attempt(s)"}


# ---------------------------------------------------------------------------
# The detail goes into JSONB
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("step", list(StepType))
def test_every_entrys_detail_is_json_serializable(step: StepType) -> None:
    # Proves: a `date`, a `StrEnum` or a dataclass reaching JSONB unconverted would raise at insert, in
    # production, mid-run. A fully loaded state (dates, enum reasons, findings, repairs, an attempt
    # record) goes through `json.dumps` for each step.
    record = AttemptRecord(
        attempt=1, tier="initial", model="m", route="model", error=None, verdict=Verdict.PASSED, reasons=[],
        findings=[], confidence=0.9, error_count=0, warning_count=1,
    )
    state = base_state(
        attempt_count=1, last_plan=PLAN, route_attempted="model", validation=passed_validation(),
        attempt_history=[record], escalation_reason="why", reconcile_decision="insert", confidence=0.9,
    )
    entry = entry_for(step, state, staging_id="doc-1")
    assert isinstance(entry, AuditEntry)
    json.dumps(entry.detail)
