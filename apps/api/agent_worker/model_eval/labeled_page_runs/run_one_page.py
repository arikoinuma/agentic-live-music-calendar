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
included, are recomputed from its document (`validation_recall.recompute_validation`), and the recorded errors are kept beside
them as a self-check. C7 adds what the policy questions read from each attempt: its confidence and the per-show confidences
behind it, which shows that confidence covers, and what the attempt cost in seconds and tokens (C7-D6).

How to read it: the token hooks, `InMemoryStager`, then the two record types (`AttemptResult`, `PageRun`, both plain data so they
go into a results file as they are), then the helpers that fill an attempt and `run_page`. Scores are
`dataclasses.asdict(PageScore)`, so they are JSON and `--rescore` can rebuild them.

docs/dev/implementations/c5-pipeline-eval-harness.md, Step 2 (C5-D2, C5-D5, C5-D7); docs/dev/implementations/c7-pipeline-eval.md,
Step 2 (C7-D6, C7-PR1-1, C7-PR1-6).
"""

import dataclasses
import datetime
import itertools
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_worker import nodes
from agent_worker.context import WorkerContext
from agent_worker.main import VenueFacts, run_venue
from agent_worker.model_eval import run_eval, scoring
from agent_worker.model_eval.labels import PageLabel
from agent_worker.model_eval.validation_recall import finding_dict, recompute_validation
from agent_worker.nodes import IMAGE_SUFFIXES
from agent_worker.policy import AttemptRecord, RetryPolicy
from agent_worker.state import VenueGraphState
from agent_worker.validation import Severity
from app.enums import RunTrigger

# What a scored column holds when nothing was produced: no shows. Scoring it against a label counts every labelled show missed,
# which is the truth for an escalated run (it commits nothing) and for a model call that failed outright.
NOTHING: dict[str, Any] = {"page_readable": False, "shows": []}

# The clients whose calls are being counted. `run_eval.register_hooks` attaches its token and parse-error hooks to a client, and
# `run_eval` attaches them to its OWN client at import; the graph's nodes call a different one (`nodes.instructor_client`, built by
# `llm.build_clients`), so the plan's assumption that the hooks were already on the pipeline's client was wrong (C7, Implementation
# log). `run_page` attaches them to whichever client the nodes use, once per client: attaching twice would count every call twice.
# A scripted test client without `on` is left alone. Strong references, so a client's id cannot be reused by a later one.
_counted_clients: list[Any] = []


def _count_calls_on(client: Any) -> None:
    """Attach `run_eval`'s counting hooks to `client`, unless they already are (or it cannot take hooks)."""
    if any(c is client for c in _counted_clients) or not callable(getattr(client, "on", None)):
        return
    run_eval.register_hooks(client)
    _counted_clients.append(client)


def _tokens_now(counters: run_eval.RunCounters | None) -> tuple[int, int, bool]:
    """The run's token totals so far, and whether any response has carried `usage` yet."""
    if counters is None:
        return 0, 0, False
    return counters.prompt_tokens, counters.completion_tokens, counters.usage_seen


class InMemoryStager:
    """A `Stager` that keeps each attempt's staging document in a list instead of writing it to MongoDB.

    MongoDB is not what the harness evaluates, and requiring it would make every baseline need a second service (C5-D2). The
    documents are the same ones `staging.document_for` builds, with `staged_at` turned into text so a run record stays JSON.

    Each attempt stages exactly one document, right after its extraction calls (page, splitter, status) return, so the stager is
    where an attempt ends. Beside each document it notes the clock and the run's token totals (`marks`); the difference between two
    marks is one attempt's seconds and tokens (C7-D6, C7-PR1-6). `run_page` sets `counters` for the run in progress.
    """

    def __init__(self) -> None:
        self.documents: list[dict[str, Any]] = []
        self.marks: list[tuple[float, tuple[int, int, bool]]] = []
        self.counters: run_eval.RunCounters | None = None

    async def stage(self, document: dict[str, Any]) -> str:
        stored = {**document, "staged_at": document["staged_at"].isoformat()}
        self.documents.append(stored)
        self.marks.append((time.perf_counter(), _tokens_now(self.counters)))
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
    # C7 (Step 2). Every field has a default, so a results file written before C7 still loads.
    confidence: float | None = (
        None  # the record's confidence as validation computed it: the minimum over the judged shows
    )
    show_confidences: list[float | None] = field(
        default_factory=list
    )  # each raw show's confidence as the model gave it, by index
    judged_indices: list[int] = field(default_factory=list)  # the raw indexes that confidence covers (C7-PR1-1)
    excluded_indices: list[int] = field(
        default_factory=list
    )  # the raw indexes validation excluded (`ValidationResult.excluded`)
    recorded_confidence: float | None = None  # AttemptRecord.confidence, for the self-check; None when not recorded
    seconds: float | None = None  # from the previous attempt's staging (or the run's start) to this one's
    tokens: dict[str, int] | None = None  # this attempt's extraction calls; None when no response carried `usage`


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
    # Tokens after the last attempt's staging: reconcile's artist-match calls (C7-D6). With each attempt's tokens it sums to the run's.
    tokens_after_last_attempt: dict[str, int] | None = None


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


def confidence_fields(document: dict[str, Any], result: Any) -> dict[str, Any]:
    """What C7-Q4 reads from one attempt: the record's confidence, each raw show's confidence, and which shows that confidence covers.

    `judged_indices` is every raw index minus validation's exclusions and the status merge's added shows, the set
    `validation.aggregate_confidence` takes its minimum over (C7-PR1-1). The per-show values are stored as the model gave them,
    the structured route's placeholder 1.0s included: deciding which routes count is C7-K1's job, not the recorder's (C7-PR1-3).
    Public because `--rescore` fills the same fields from a stored file with this very function."""
    raw = document["raw_extraction"]
    if raw is None:
        return {"confidence": None, "show_confidences": [], "judged_indices": [], "excluded_indices": []}
    shows = raw.get("shows") or []
    excluded = sorted(result.excluded)
    added = set((document.get("notes") or {}).get("added_indices") or [])
    return {
        "confidence": result.confidence,
        "show_confidences": [s.get("confidence") for s in shows],
        "judged_indices": [i for i in range(len(shows)) if i not in excluded and i not in added],
        "excluded_indices": excluded,
    }


def staged_seconds(documents: list[dict[str, Any]]) -> list[float | None]:
    """Per-attempt seconds from the stored `staged_at` values alone, for a file recorded before C7: attempt n is staging n-1 to
    staging n, and attempt 1 is None (the run's start is not on the record, C7-PR1-6)."""
    times = [datetime.datetime.fromisoformat(d["staged_at"]) for d in documents]
    if not times:
        return []
    return [None, *[round((b - a).total_seconds(), 2) for a, b in itertools.pairwise(times)]]


def _spans(
    started: float,
    marks: list[tuple[float, tuple[int, int, bool]]],
    end: tuple[int, int, bool],
) -> tuple[list[float], list[dict[str, int] | None], dict[str, int] | None]:
    """Each attempt's seconds and tokens from the stager's marks, and the tokens spent after the last one.

    Each span runs from the previous mark (the run's start for attempt 1) to this one, so it holds the previous attempt's
    validation too; that is milliseconds beside a model call. Tokens are None throughout when no response in the run carried
    `usage`: a provider that reports nothing is an unknown cost, never 0 (C7-D6)."""
    seen = end[2]
    previous_time, previous = started, (0, 0)
    seconds, tokens = [], []
    for at, (prompt, completion, _seen) in marks:
        seconds.append(round(at - previous_time, 2))
        tokens.append({"prompt": prompt - previous[0], "completion": completion - previous[1]} if seen else None)
        previous_time, previous = at, (prompt, completion)
    after = {"prompt": end[0] - previous[0], "completion": end[1] - previous[1]} if seen else None
    return seconds, tokens, after


def _attempt_result(
    document: dict[str, Any],
    record: AttemptRecord | None,
    label: PageLabel,
    page_html: str,
    fixture: str,
    *,
    seconds: float | None,
    tokens: dict[str, int] | None,
) -> AttemptResult:
    """Score one staged attempt and recompute its validation. A call that produced no extraction has no score and no findings."""
    raw = document["raw_extraction"]
    result = (
        recompute_validation(document, page_html=page_html, fetched_on=label.captured_on) if raw is not None else None
    )
    findings = result.findings if result is not None else []
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
        **confidence_fields(document, result),
        recorded_confidence=record.confidence if record else None,
        seconds=seconds,
        tokens=tokens,
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

    # Count this run's calls (C7-D6): the hooks write to the counters found through `run_eval`'s ContextVar, which the graph's
    # node threads inherit from this task, and the stager notes the totals at each staging.
    _count_calls_on(nodes.instructor_client)
    stager.counters = run_eval.new_counters()
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
    attempt_seconds, attempt_tokens, tokens_after = _spans(
        started, stager.marks[first_document:], _tokens_now(stager.counters)
    )
    records = {r.attempt: r for r in state.attempt_history}
    attempts = [
        _attempt_result(d, records.get(d["attempt"]), label, page_html, name, seconds=s, tokens=t)
        for d, s, t in zip(documents, attempt_seconds, attempt_tokens, strict=True)
    ]

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
        tokens_after_last_attempt=tokens_after,
    )
