"""Turn a graph-level results file into a readable Markdown report: the questions that used to need a throwaway script each time.

What this is: `graph_eval` writes everything a run produced to `eval/results/graph-<label>.json`. Reading it meant writing a small
Python script per question (per-page counts, validation by error kind, what each retry attempt did, what a scenario left in the
database). This is that script, written once: `render(data, labels)` returns Markdown, and `graph_eval --report <label>` prints it
(or writes it with `--out`, so a long report reaches a file or the plan's log without a terminal's line wrapping in between). The
same report reads a local run today and a hosted-model run in C6, which is what makes them comparable (`--compare` lines labels up).

How to read it, in the order it prints: header (what produced the numbers); headline (raw, validated, committed); the retry loop;
validation recall by error kind; one row per page; the attempts of every retried page; scenarios; the gate's failures; and, with
`errors=True`, every error string in full. It reads the stored aggregate and runs only and never re-scores anything, so it needs no
model, database or fixtures; `--rescore` is the tool that recomputes scores.

docs/dev/evaluating-model-performance.md says where this fits in the sequence of checks.
"""

from collections.abc import Mapping
from typing import Any

from agent_worker.eval.labels import PageLabel

COLUMNS = ("raw", "validated", "committed")


def _counts(score: Mapping[str, Any]) -> str:
    """missed / wrong acts / invented / leaks, the four counts the standard tiers on."""
    return f"{score['missed']}/{score['acts_wrong']}/{score['fabricated']}/{score['leaks']}"


def _errors3(score: Mapping[str, Any] | None) -> str:
    """missed / wrong acts / invented for one attempt's score ('-' when the call produced nothing)."""
    return "-" if score is None else f"{score['missed']}/{score['acts_wrong']}/{score['fabricated']}"


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    """A Markdown table as lines."""
    return [
        "| " + " | ".join(header) + " |",
        "|" + "|".join("---" for _ in header) + "|",
        *["| " + " | ".join(row) + " |" for row in rows],
    ]


def _header(data: Mapping[str, Any]) -> list[str]:
    options = data.get("request_options") or {}
    provenance = data.get("provenance") or {}
    first_provenance = next(iter(provenance.values()), None) or {}
    policy = data.get("policy") or {}
    return [
        f"# Report: {data.get('label')}",
        "",
        (
            f"- started: {data.get('started_at')}; set: {data.get('set')}; scenario: {data.get('scenario') or 'none'}; "
            f"runs: {len(data.get('runs', []))}; held-out scored: {'yes' if data.get('held_out_scored') else 'no'}"
        ),
        (
            f"- model: {options.get('model')}; digest: {first_provenance.get('model_digest') or 'not recorded'}; "
            f"runtime: {first_provenance.get('ollama_version') or 'not recorded'}"
        ),
        (
            f"- labels_sha: {str(data.get('labels_sha'))[:10]}; harness commit: {str(data.get('harness_commit'))[:10]}; "
            f"policy: threshold {policy.get('confidence_threshold')}, cap {policy.get('max_attempts')}, "
            f"escalation model {policy.get('escalation_model') or 'none'}"
        ),
        "",
    ]


def _headline(aggregate: Mapping[str, Any]) -> list[str]:
    rows = []
    for column in COLUMNS:
        c, gate = aggregate["columns"][column], aggregate["gate"][column]
        rates = c["rates"]
        rows.append([
            column, f"{rates['recall']:.3f}", f"{rates['precision']:.3f}", f"{rates['precision_lenient']:.3f}",
            f"{c['found']}/{c['labelled']}", f"{c['missed']}/{c['acts_wrong']}/{c['fabricated']}/{c['leaks']}",
            "PASS" if gate["passed"] else "FAIL",
        ])
    return [
        "## Headline", "",
        *_table(["column", "recall", "precision", "precision (lenient)", "found/labelled", "missed/wrong/invented/leaks", "gate (gated pages)"], rows),
        "",
        (
            "Raw is the model's answer, validated is what reconcile receives, committed is the rows left in the database. "
            "An escalated run commits nothing, so its shows count as missed in the last two."
        ),
        "",
    ]


def _retry(aggregate: Mapping[str, Any]) -> list[str]:
    r = aggregate["retry"]
    return [
        "## The retry loop", "",
        (
            f"- runs {r['runs']}; retried {r['retried']} (rate {r['retry_rate']:.2f}); mean attempts {r['mean_attempts']:.1f}; "
            f"escalated {r['escalated']}; recovered {r['recovered']}"
        ),
        f"- attempts by tier: {r['attempts_by_tier']}; failure reasons: {r['reasons']}",
        (
            f"- errors summed over the retried pages: first attempt {r['errors_first_attempt']}, final attempt {r['errors_final_attempt']} "
            "(equal means the retries changed nothing on net)"
        ),
        "",
    ]


def _validation(aggregate: Mapping[str, Any]) -> list[str]:
    v = aggregate["validation"]
    rows = [[kind, str(c["caught"]), str(c["flagged"]), str(c["silent"])] for kind, c in sorted(v["by_kind"].items())]
    lines = [
        "## Validation recall", "",
        f"- {v['total']} errors over every attempt: caught {v['caught']}, flagged {v['flagged']}, silent {v['silent']}",
        f"- findings fired: {v['findings_fired']}; self-checks: findings_disagree {v.get('findings_disagree', 'n/a')}, route_mismatches {v.get('route_mismatches', 'n/a')}",
        "",
        *_table(["error kind", "caught", "flagged", "silent"], rows),
        "",
        "Caught = an error finding covers it (it fails the record); flagged = only a warning does; silent = no finding.",
    ]
    if aggregate["retry"]["retried"]:
        lines.append(
            "Reading note: every attempt of a retried page is counted, and an attempt failed for low confidence is not a finding "
            "(low confidence is a verdict reason, not a finding), so 'silent' can include errors a retry did stop."
        )
    return [*lines, ""]


def aggregate_per_fixture(data: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
    """The stored per-page run counts and whether the runs agreed (absent in files from before the field existed)."""
    per_fixture: Mapping[str, Mapping[str, Any]] = data["aggregate"].get("per_fixture", {})
    return per_fixture


def _pages(data: Mapping[str, Any], labels: Mapping[str, PageLabel]) -> list[str]:
    rows = []
    for r in data["runs"]:
        label = labels.get(r["fixture"])
        gated = "?" if label is None else ("G" if label.gated else "i")
        rows.append([
            r["fixture"], gated, r.get("source") or "-", str(r["raw_score"]["labelled"]), _counts(r["raw_score"]),
            _counts(r["validated_score"]), _counts(r["committed_score"]), str(r["attempt_count"]),
            "yes" if r["escalated"] else "no", str(r["seconds"]),
        ])
    seconds = [r["seconds"] for r in data["runs"]]
    repeated = [
        f"- {name}: {'identical' if p['runs_identical'] else 'DIFFERENT'} across {p['runs']} runs"
        for name, p in aggregate_per_fixture(data).items() if p["runs_identical"] is not None
    ]
    return [
        "## Pages", "",
        "G = gated, i = informational (never gates), ? = no longer in the labels. Counts are missed/wrong acts/invented/leaks.", "",
        *_table(["page", "G/i", "route", "labelled", "raw", "validated", "committed", "attempts", "escalated", "seconds"], rows),
        "",
        f"Total {sum(seconds):.0f} s over {len(seconds)} runs.",
        "",
        *(["Repeatability (the same page, run more than once; the model is not repeatable at temperature 0):", *repeated, ""] if repeated else []),
    ]


def _attempts(data: Mapping[str, Any]) -> list[str]:
    retried = [r for r in data["runs"] if r["attempt_count"] > 1]
    if not retried:
        return ["## Retried pages", "", "No page needed a second attempt.", ""]
    rows = []
    for r in retried:
        for a in r["attempts"]:
            outcome = ("escalated" if r["escalated"] else "kept") if a["attempt"] == r["attempt_count"] else ""
            rows.append([
                r["fixture"], str(a["attempt"]), str(a["tier"]), str(a["verdict"]), ",".join(a["reasons"]) or "-",
                _errors3(a["score"]), outcome,
            ])
    return [
        "## Retried pages", "",
        "Errors are missed/wrong acts/invented for that attempt's own extraction.", "",
        *_table(["page", "attempt", "tier", "verdict", "reasons", "errors", "end"], rows),
        "",
    ]


def _scenarios(data: Mapping[str, Any], show_errors: bool) -> list[str]:
    scenarios = data.get("scenarios") or []
    if not scenarios:
        return []
    lines = ["## Scenarios", ""]
    for s in scenarios:
        result = s["result"]
        lines.append(f"### {result['scenario']}: {' -> '.join(s['pages'])}")
        for i, run in enumerate(result["runs"], start=1):
            lines.append(f"- run {i} {run['fixture']}: reconcile {run.get('reconcile_counts')}")
        if result.get("not_run"):
            lines.append(f"- NOT RUN: {result['not_run']}")
        for difference in result.get("count_differences", []):
            lines.append(f"- difference: {difference}")
        db = s.get("database_score")
        if db is not None:
            lines.append(
                f"- database vs expected: labelled {db['labelled']}, returned {db['returned']}, missed {db['missed']}, "
                f"wrong acts {db['acts_wrong']}, invented {db['fabricated']}"
            )
            if show_errors:
                lines += [f"  - {e}" for e in db["errors"]]
        lines.append("")
    return lines


def _gate_failures(aggregate: Mapping[str, Any]) -> list[str]:
    lines = ["## Gate failures (gated pages only)", ""]
    any_failure = False
    for column in COLUMNS:
        for failure in aggregate["gate"][column]["failures"]:
            lines.append(f"- {column}: {failure}")
            any_failure = True
    if not any_failure:
        lines.append("None.")
    return [*lines, ""]


def _errors(data: Mapping[str, Any]) -> list[str]:
    lines = ["## Errors, in full (raw column)", ""]
    for r in data["runs"]:
        if r["raw_score"]["errors"]:
            lines.append(f"- {r['fixture']}")
            lines += [f"  - {e}" for e in r["raw_score"]["errors"]]
    return [*lines, ""]


def render(data: Mapping[str, Any], labels: Mapping[str, PageLabel], *, show_errors: bool = False) -> str:
    """The Markdown report for one results file. `labels` says which pages are gated (a page missing from it prints as '?')."""
    aggregate = data["aggregate"]
    lines = [
        *_header(data), *_headline(aggregate), *_retry(aggregate), *_validation(aggregate), *_pages(data, labels),
        *_attempts(data), *_scenarios(data, show_errors), *_gate_failures(aggregate),
    ]
    if show_errors:
        lines += _errors(data)
    return "\n".join(lines).rstrip() + "\n"
