"""The aggregate: everything the C5 report says about a set of run records, computed from the stored data alone.

What this is: `aggregate(records, labels)` turns the run records of one results file (`run_one_page.PageRun` as plain dicts, each
scored three ways against its label) into the numbers the milestone reports: the three columns' counts, rates and field accuracy,
the gate per column, the retry loop, validation recall, repeatability per page, and the cost. It is pure (no database, no model,
no file), so it is what `--rescore` recomputes after a label or the scorer changes, and what `markdown_report` reads back. A metric
added for a later milestone (C6's cost, C7's `stopped` and `confidence_disagree`) is added here, and only here.

How to read it: `aggregate` at the bottom shows the shape; the helpers above it are one block each (`_column`, `_gate`, `_retry`,
`_validation`, `_per_fixture`). Page arithmetic (`scoring.summed`, `scoring.headline_rates`) stays in `scoring.py`.

docs/dev/implementations/c5-pipeline-eval-harness.md, Step 3 (C5-D1, C5-D7); moved out of `run_labeled_pages.py` in code review round 2
(C5-CR2-1).
"""

from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from agent_worker import policy
from agent_worker.model_eval import scoring, validation_recall
from agent_worker.model_eval.labels import PageLabel

# The three places a run is scored (see `run_one_page`): the model's answer, what reconcile receives, the rows left in the database.
COLUMNS = ("raw", "validated", "committed")


def _column(scores: list[scoring.PageScore]) -> dict[str, Any]:
    """The counts, headline rates and field accuracy of one column (raw, validated or committed) over all runs."""
    total = scoring.summed(scores)
    rates = scoring.headline_rates(total)
    return {
        **{k: getattr(total, k) for k in ("labelled", "returned", "dropped_empty", "missed", "acts_wrong", "fabricated", "leaks")},
        "found": rates.found,
        "rates": asdict(rates),
        "fields": {
            name: {**asdict(t), "missing_rate": round(t.missing / t.stated, 3) if t.stated else None}
            for name, t in total.fields.items()
        },
    }


def _scored_in(records: list[dict[str, Any]], column: str) -> list[dict[str, Any]]:
    """The runs a column is scored over. The committed column leaves out a run flagged `committed_scored: False`: the second run
    of a SEQUENCE or OVERLAP scenario, whose rows include an earlier page's shows (correctly), which scored against the second
    page's label alone would all be invented shows. The scenario's own `database_score` is the right measure for those (C5-CR1-1)."""
    if column != "committed":
        return records
    return [r for r in records if r.get("committed_scored", True)]


def _gate(records: list[dict[str, Any]], labels: Mapping[str, PageLabel], column: str) -> dict[str, Any]:
    """Ari's standard (`scoring.gate`) over the GATED pages of one column, every run counted (A2.1-D1: every run must pass)."""
    by_run: dict[int, list[scoring.PageScore | scoring.PageFailure]] = {}
    for r in _scored_in(records, column):
        label = labels.get(r["fixture"])
        if label is None or not label.gated:
            continue
        score = scoring.PageScore.from_dict(r[f"{column}_score"])
        score.route = policy.stored_route(r.get("source")) or "model"
        by_run.setdefault(r["run"], []).append(score)
    result = scoring.gate(by_run)
    return {"passed": result.passed, "failures": result.failures, "pages": result.pages}


def _errors_of(score: dict[str, Any] | None) -> int:
    """The errors in one attempt's score that retrying could fix: missed, wrong acts and invented shows."""
    return 0 if score is None else score["missed"] + score["acts_wrong"] + score["fabricated"]


def _retry(records: list[dict[str, Any]]) -> dict[str, Any]:
    """The retry loop over all runs: how often it fired, what it did, and (for runs that retried) what it changed."""
    n = len(records)
    retried = [r for r in records if r["retried"]]
    return {
        "runs": n,
        "retried": len(retried),
        "retry_rate": len(retried) / n if n else 0.0,
        "mean_attempts": sum(r["attempt_count"] for r in records) / n if n else 0.0,
        "escalated": sum(r["escalated"] for r in records),
        "recovered": sum(r["recovered"] for r in records),
        "attempts_by_tier": dict(Counter(a["tier"] for r in records for a in r["attempts"])),
        "reasons": dict(Counter(reason for r in records for a in r["attempts"] for reason in a["reasons"])),
        # C5-D7: for the runs that retried, the errors of attempt 1 against the errors of the last attempt.
        "errors_first_attempt": sum(_errors_of(r["attempts"][0]["score"]) for r in retried if r["attempts"]),
        "errors_final_attempt": sum(_errors_of(r["attempts"][-1]["score"]) for r in retried if r["attempts"]),
    }


def _validation(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Validation recall over EVERY attempt (C5-D7): each attempt's errors joined to that attempt's own findings."""
    pairs = []
    fired: Counter[str] = Counter()
    disagree = confidence_disagree = stopped = 0
    for r in records:
        for a in r["attempts"]:
            findings = validation_recall.findings_from_dicts([*a["errors"], *a["warnings"]])
            fired.update(validation_recall.findings_fired(findings))
            if a["errors"] != a["recorded_errors"]:
                disagree += 1
            # C7-PR1-4, C7-CR1-7: compared wherever the attempt carries `recorded_confidence`. A fresh C7 run always does (None on
            # the structured route is a recorded None, and a recompute that gives a number there is a drift). A file recorded before
            # C7 has no such key, and a rescore cannot add one (the staging document does not hold it), so it is skipped rather than
            # read as a drift in validate_node that is not there.
            if "recorded_confidence" in a and a.get("confidence") != a["recorded_confidence"]:
                confidence_disagree += 1
            if a["score"] is not None:
                items = a["score"].get("items", [])
                pairs += [(scoring.ErrorItem(**item), findings) for item in items]
                if a["verdict"] == "failed":
                    stopped += len(items)
    tally = validation_recall.tally(pairs)
    return {
        "total": tally.total, "caught": tally.caught, "flagged": tally.flagged, "silent": tally.silent,
        "recall": tally.recall, "by_kind": tally.by_kind, "findings_fired": dict(fired),
        # C5-F14, adopted by C7-D8: errors on an attempt that failed for ANY reason, a finding or not. A forced run fails every
        # model-judged attempt for low confidence, which is no finding, so without this column "silent" swallows everything.
        "stopped": stopped,
        # C5-PR1-6: the recomputed error findings should equal the recorded ones; any attempt where they don't is counted.
        "findings_disagree": disagree,
        # C7-PR1-4: the recomputed confidence should equal `AttemptRecord.confidence` wherever that was recorded.
        "confidence_disagree": confidence_disagree,
        # C5-CR1-6: runs where the staged route was not the source validation received (findings may not be the pipeline's).
        "route_mismatches": sum(1 for r in records if r.get("route_mismatch", False)),
    }


def _per_fixture(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Per page: how many runs, how long they took, and whether the runs agreed (None unless there were two or more)."""
    out: dict[str, Any] = {}
    for name in sorted({r["fixture"] for r in records}):
        mine = [r for r in records if r["fixture"] == name]
        out[name] = {
            "runs": len(mine), "seconds": [r["seconds"] for r in mine],
            "runs_identical": all(r["raw"] == mine[0]["raw"] for r in mine) if len(mine) >= 2 else None,
        }
    return out


def aggregate(records: list[dict[str, Any]], labels: Mapping[str, PageLabel]) -> dict[str, Any]:
    """Everything the milestone reports, from the run records and the labels they were scored against."""
    seconds_by_source: dict[str, list[float]] = {}
    for r in records:
        seconds_by_source.setdefault(policy.stored_route(r.get("source")) or "none", []).append(r["seconds"])
    return {
        "runs": len(records),
        "columns": {c: _column([scoring.PageScore.from_dict(r[f"{c}_score"]) for r in _scored_in(records, c)]) for c in COLUMNS},
        "gate": {c: _gate(records, labels, c) for c in COLUMNS},
        "retry": _retry(records),
        "validation": _validation(records),
        "per_fixture": _per_fixture(records),
        "cost": {
            "mean_seconds": round(sum(r["seconds"] for r in records) / len(records), 1) if records else 0.0,
            "mean_seconds_by_route": {k: round(sum(v) / len(v), 1) for k, v in seconds_by_source.items()},
        },
    }
