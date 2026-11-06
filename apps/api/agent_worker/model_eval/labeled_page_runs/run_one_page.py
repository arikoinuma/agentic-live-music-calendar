"""Run one labelled page through the real graph and record what came out, at three points (the C5 harness's unit of work).

What this is: `run_page` hands a fixture to `main.run_venue`, the same cycle the scheduled worker runs (open a run, run the
compiled graph, close the run), then reads the final state and scores it three ways against the page's hand-written label:

    raw        the model's answer, as `state.extraction` holds it
    validated  what reconcile receives (repairs applied, excluded shows removed); None when the run escalated, because the
               graph only reaches reconcile on a pass
    committed  the rows the database holds afterwards (a `committed_rows` callable, so the tests need no database)

The differences between the columns say which layer helped and which hurt. It also scores EVERY attempt, not only the last
(C5-D7): the in-memory stager keeps each attempt's staging document, whose `raw_extraction` is what that attempt extracted, so
"did attempt 2 fix attempt 1's errors, or only cost tokens" can be asked (C7 needs it). Each attempt's findings, warnings
included, are recomputed from its document (`validation_recall.recompute_findings`), and the recorded errors are kept beside
them as a self-check.

How to read it: `InMemoryStager`, then the two record types (`AttemptResult`, `PageRun`, both plain data so they go into a
results file as they are), then `run_page`. Scores are `dataclasses.asdict(PageScore)`, so they are JSON and `--rescore` can
rebuild them.

docs/dev/implementations/c5-pipeline-eval-harness.md, Step 2 (C5-D2, C5-D5, C5-D7).
"""

import dataclasses
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_worker.context import WorkerContext
from agent_worker.main import VenueFacts, run_venue
from agent_worker.model_eval import scoring
from agent_worker.model_eval.labels import PageLabel
from agent_worker.model_eval.validation_recall import finding_dict, recompute_findings
from agent_worker.nodes import IMAGE_SUFFIXES
from agent_worker.policy import AttemptRecord, RetryPolicy
from agent_worker.state import VenueGraphState
from agent_worker.validation import Severity
from app.enums import RunTrigger

# What a scored column holds when nothing was produced: no shows. Scoring it against a label counts every labelled show missed,
# which is the truth for an escalated run (it commits nothing) and for a model call that failed outright.
NOTHING: dict[str, Any] = {"page_readable": False, "shows": []}


class InMemoryStager:
    """A `Stager` that keeps each attempt's staging document in a list instead of writing it to MongoDB.

    MongoDB is not what the harness evaluates, and requiring it would make every baseline need a second service (C5-D2). The
    documents are the same ones `staging.document_for` builds, with `staged_at` turned into text so a run record stays JSON.
    """

    def __init__(self) -> None:
        self.documents: list[dict[str, Any]] = []

    async def stage(self, document: dict[str, Any]) -> str:
        stored = {**document, "staged_at": document["staged_at"].isoformat()}
        self.documents.append(stored)
        return f"eval-{len(self.documents)}"


@dataclass
class AttemptResult:
    """One extract-validate attempt, scored on its own."""

    attempt: int
    tier: str | None
    route: str | None
    model: str | None
    larger_model_used: bool
    error: str | None  # the model call's failure, if it raised
    verdict: str  # failed / passed / confirmed_empty; "none" if the graph never recorded one
    reasons: list[str]
    score: dict[str, Any] | None  # asdict(PageScore) of THIS attempt's extraction; None when the call produced nothing
    errors: list[dict[str, Any]] = field(default_factory=list)  # recomputed error findings
    warnings: list[dict[str, Any]] = field(default_factory=list)  # recomputed warnings (stored nowhere else)
    recorded_errors: list[dict[str, Any]] = field(
        default_factory=list
    )  # what AttemptRecord.findings held, for the self-check


@dataclass
class PageRun:
    """Everything one page's run produced, as plain data."""

    fixture: str
    venue_id: int
    run_id: int | None
    seconds: float
    source: str | None  # the route that produced the final extraction
    attempt_count: int
    retried: bool
    recovered: bool  # retried, and the final verdict is not a failure
    escalated: bool
    escalation_reason: str | None
    final_verdict: str | None
    policy: dict[str, Any]
    reconcile_counts: dict[str, int] | None
    commit_written: dict[str, int] | None
    raw: dict[str, Any] | None
    validated: dict[str, Any] | None
    committed: dict[str, Any]
    raw_score: dict[str, Any]
    validated_score: dict[str, Any]
    committed_score: dict[str, Any]
    attempts: list[AttemptResult]
    staged_documents: list[dict[str, Any]]
    # True when the final attempt's staged route differs from the `extraction_source` validation received: findings are recomputed
    # under the staged route, so a mismatch means they may not be the ones the pipeline saw (C5-CR1-6).
    route_mismatch: bool = False


def score_dict(label: PageLabel, extraction: dict[str, Any] | None, page_html: str, fixture: str) -> dict[str, Any]:
    """`score_page` as a plain dict; a missing extraction is scored as nothing returned (every labelled show missed).

    Public because `--rescore` (`run_labeled_pages`) rebuilds a saved run's scores with the very same function: a rule for how a column
    is scored then lives in one place, and a rescore cannot disagree with a fresh run (C5-CR2-3)."""
    return dataclasses.asdict(scoring.score_page(label, extraction or NOTHING, page_html, fixture))


def column_scores(
    label: PageLabel,
    *,
    raw: dict[str, Any] | None,
    validated: dict[str, Any] | None,
    committed: dict[str, Any],
    page_html: str,
    fixture: str,
) -> dict[str, dict[str, Any]]:
    """The three scored columns of one run, keyed as `PageRun` names them (`raw_score`, `validated_score`, `committed_score`).

    Raw and validated are held to the full label. The database cannot hold a cancelled or postponed show (reconcile skips it), so
    the committed column is held to the scheduled ones only (`scoring.scheduled_only`)."""
    return {
        "raw_score": score_dict(label, raw, page_html, fixture),
        "validated_score": score_dict(label, validated, page_html, fixture),
        "committed_score": score_dict(scoring.scheduled_only(label), committed, page_html, fixture),
    }


def _attempt_result(
    document: dict[str, Any],
    record: AttemptRecord | None,
    label: PageLabel,
    page_html: str,
    fixture: str,
) -> AttemptResult:
    """Score one staged attempt and recompute its findings. A call that produced no extraction has no score and no findings."""
    raw = document["raw_extraction"]
    findings = (
        recompute_findings(document, page_html=page_html, fetched_on=label.captured_on) if raw is not None else []
    )
    return AttemptResult(
        attempt=document["attempt"],
        tier=document["tier"],
        route=document["route"],
        model=document["model"],
        larger_model_used=document["larger_model_used"],
        error=document["error"],
        verdict=record.verdict.value if record else "none",
        reasons=[r.value for r in record.reasons] if record else [],
        score=score_dict(label, raw, page_html, fixture) if raw is not None else None,
        errors=[finding_dict(f) for f in findings if f.severity is Severity.ERROR],
        warnings=[finding_dict(f) for f in findings if f.severity is Severity.WARNING],
        recorded_errors=[finding_dict(f) for f in record.findings] if record else [],
    )


async def run_page(
    *,
    label: PageLabel,
    fixture: Path,
    venue: VenueFacts,
    ctx: WorkerContext,
    committed_rows: Callable[[], Awaitable[dict[str, Any]]],
    policy: RetryPolicy | None = None,
    name: str | None = None,
) -> PageRun:
    """Run `fixture` through the graph as `venue`, and score the raw, validated and committed results against `label`.

    `ctx.stager` must be an `InMemoryStager`: its documents are the per-attempt record. `committed_rows` reads the rows left in
    the database after the run (`scratch_calendar_rows.committed_extraction`); it is injected so the graph-level tests need no database
    (C5-PR1-7). `policy` replaces the default retry policy for this run (C5-D5). `name` is what the record calls the page when
    it differs from the file's name (a scenario feeds every capture of a venue from one fixed path, see `two_run_scenarios.run_scenario`).
    """
    stager = ctx.stager
    assert isinstance(stager, InMemoryStager), (
        "run_page records per-attempt documents; give the context an InMemoryStager"
    )
    first_document = len(stager.documents)
    name = name or fixture.name
    is_image = fixture.suffix in IMAGE_SUFFIXES
    page_html = "" if is_image else fixture.read_text()  # noqa: ASYNC240 - one small local fixture, read once per page

    started = time.perf_counter()
    state: VenueGraphState = await run_venue(
        venue,
        ctx,
        trigger=RunTrigger.MANUAL,
        calendar_url=str(fixture),
        fetched_on=label.captured_on,
        policy=policy,
    )
    seconds = round(time.perf_counter() - started, 1)

    documents = stager.documents[first_document:]
    records = {r.attempt: r for r in state.attempt_history}
    attempts = [_attempt_result(d, records.get(d["attempt"]), label, page_html, name) for d in documents]

    escalated = state.escalation_reason is not None
    raw = state.extraction.model_dump(mode="json") if state.extraction is not None else None
    # Reconcile receives `validated_extraction` only on a pass. `validate_node` fills it on every attempt, a failed one
    # included, so an escalated run must not report it: nothing from it was committed.
    validated = (
        state.validated_extraction.model_dump(mode="json")
        if state.validated_extraction is not None and not escalated
        else None
    )
    committed = await committed_rows()
    final_verdict = state.validation.verdict.value if state.validation and state.validation.verdict else None
    return PageRun(
        fixture=name,
        venue_id=venue.id,
        run_id=state.run_id,
        seconds=seconds,
        source=state.extraction_source,
        attempt_count=state.attempt_count,
        retried=state.attempt_count > 1,
        recovered=state.attempt_count > 1 and not escalated and final_verdict != "failed",
        escalated=escalated,
        escalation_reason=state.escalation_reason,
        final_verdict=final_verdict,
        policy=dataclasses.asdict(state.policy),
        reconcile_counts=state.reconcile_plan.counts() if state.reconcile_plan else None,
        commit_written=dict(state.commit_result.written) if state.commit_result else None,
        raw=raw,
        validated=validated,
        committed=committed,
        **column_scores(label, raw=raw, validated=validated, committed=committed, page_html=page_html, fixture=name),
        attempts=attempts,
        staged_documents=documents,
        route_mismatch=bool(
            documents and state.extraction_source is not None and documents[-1]["route"] != state.extraction_source
        ),
    )
