"""Validation recall: of the errors the labels reveal, how many did validation catch, and how many slipped through.

What this is: the instrument behind the deployment plan's "validation recall" item (C5). Validation is one layer of the
pipeline (`validation.py` gathers findings, `policy.combine` turns them into a verdict, and a failed verdict triggers a retry).
This module asks of each extraction error the scorer found (`scoring.ErrorItem`): did a finding cover it, and was that finding
strong enough to stop the record?

How to read it, top to bottom:
1. `Coverage` and `coverage` (C5-K4): the classification of one error against one attempt's findings.
2. `tally`: counting the classes over many errors, per error kind (so "which layer catches which failure" can be read off).
3. `recompute_validation` and `recompute_findings`: an attempt's whole validation result, and its full findings (errors AND
   warnings), rebuilt from its staged document. Nothing stores an earlier attempt's warnings (`AttemptRecord.findings` is errors
   only; the audit row keeps a count), but `validate_extraction` is a pure function of inputs the staged document and the fixture
   still hold, so the harness recomputes them exactly and the production code stays untouched (C5-PR1-6). C7 reads the same
   result's confidence and exclusions, which the staging document does not carry either (C7-PR1-1).

Findings travel in results files as plain dicts (`finding_dict`, `findings_from_dicts`), so a --rescore needs neither a model nor
a fixture to compute coverage.
"""

import datetime
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, cast

from agent_worker.extraction import clean_text
from agent_worker.model_eval.scoring import ErrorItem
from agent_worker.policy import stored_route
from agent_worker.schemas import VenuePageExtraction
from agent_worker.validation import (
    CheckCode,
    Finding,
    Severity,
    Source,
    ValidationResult,
    validate_extraction,
)


class Coverage(StrEnum):
    """How validation treated one extraction error. `caught` and `flagged` are different claims and are never merged."""

    CAUGHT = "caught"  # an error finding covers it: the record fails and the pipeline retries
    FLAGGED = "flagged"  # only a warning covers it: recorded, nothing changes
    SILENT = "silent"  # nothing covers it


def coverage(error: ErrorItem, findings: Sequence[Finding]) -> Coverage:
    """Classify one error against the findings of the attempt that produced it."""
    # Validation "catches" an error only if it would make the pipeline act (C5-K4). An ERROR-severity finding fails the record
    # and triggers a retry (`policy.combine`, A3-K4); a WARNING is recorded and changes nothing. So an error is caught when an
    # error finding sits on that show's index, or a page-level error finding covers a show nothing was returned for; flagged
    # when only a warning covers it; silent when nothing does. Flagged is reported beside caught and never folded into it:
    # "validation noticed" and "validation stopped it" are different claims. (docs/dev/alpha-deployment-plan.md, C5.)
    covering = [f for f in findings if f.show_index == error.index or (f.show_index is None and error.index is None)]
    if any(f.severity is Severity.ERROR for f in covering):
        return Coverage.CAUGHT
    return Coverage.FLAGGED if covering else Coverage.SILENT


@dataclass
class RecallTally:
    """Counts of the three classes over a set of errors, in total and per error kind."""

    total: int = 0
    caught: int = 0
    flagged: int = 0
    silent: int = 0
    by_kind: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def recall(self) -> float:
        """Caught over total; 1.0 when there were no errors (nothing was missed). `flagged` is reported beside it."""
        return self.caught / self.total if self.total else 1.0


def tally(pairs: Iterable[tuple[ErrorItem, Sequence[Finding]]]) -> RecallTally:
    """Count `coverage` over `(error, the findings of its attempt)` pairs."""
    result = RecallTally()
    for error, findings in pairs:
        cls = coverage(error, findings)
        result.total += 1
        setattr(result, cls.value, getattr(result, cls.value) + 1)
        kind = result.by_kind.setdefault(error.kind, {c.value: 0 for c in Coverage})
        kind[cls.value] += 1
    return result


def findings_fired(findings: Iterable[Finding]) -> dict[str, int]:
    """How often each check code fired, as a plain dict: a descriptive companion to the tally (which codes are doing the work)."""
    return dict(Counter(f.code.value for f in findings))


# ---------------------------------------------------------------------------
# Findings as stored data
# ---------------------------------------------------------------------------


def finding_dict(finding: Finding) -> dict[str, Any]:
    """A finding as JSON-friendly data, for the results file."""
    return {
        "code": finding.code.value,
        "severity": finding.severity.value,
        "message": finding.message,
        "show_index": finding.show_index,
    }


def findings_from_dicts(stored: Iterable[dict[str, Any]]) -> list[Finding]:
    """The inverse of `finding_dict`, so coverage can be computed from a stored file."""
    return [Finding(CheckCode(f["code"]), Severity(f["severity"]), f["message"], f.get("show_index")) for f in stored]


def recompute_validation(document: dict[str, Any], *, page_html: str, fetched_on: datetime.date) -> ValidationResult:
    """The validation result for the attempt a staging document records: its findings, its exclusions and its confidence.

    The inputs are what `validate_node` passed: the attempt's raw extraction, its route (`extraction_source`) and notes, the
    fetch date, and the page's HTML and cleaned text (empty for an image). The staged document holds the first three
    (`staging.document_for`); the fixture holds the rest. Tests pin that the recomputed ERRORS equal the recorded
    `AttemptRecord.findings`, and the recomputed confidence the recorded `AttemptRecord.confidence`, which guards this against
    drifting from `validate_node` (C5-PR1-6, C7-PR1-4). The confidence is the minimum over the kept, model-judged shows
    (`validation.aggregate_confidence`), so C7-Q4 reads the number the router actually saw.
    """
    extraction = VenuePageExtraction.model_validate(document["raw_extraction"])
    result, _kept = validate_extraction(
        # A stored route name: "jsonld" (before C6.1) reads as "structured".
        extraction,
        source=cast(Source, stored_route(document["route"])),
        notes=document["notes"],
        fetched_on=fetched_on,
        page_html=page_html,
        page_text=clean_text(page_html, False) if page_html else "",
    )
    return result


def recompute_findings(document: dict[str, Any], *, page_html: str, fetched_on: datetime.date) -> list[Finding]:
    """Every finding (errors and warnings) validation produced for the attempt a staging document records (`recompute_validation`)."""
    return recompute_validation(document, page_html=page_html, fetched_on=fetched_on).findings
