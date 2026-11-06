"""Turn a graph-level results file into a readable Markdown report: the questions that used to need a throwaway script each time.

What this is: `run_labeled_pages` writes everything a run produced to `model_eval/results/graph-<label>.json`. Reading it meant writing a small
Python script per question (per-page counts, validation by error kind, what each retry attempt did, what a scenario left in the
database). This is that script, written once: `render(data, labels)` returns Markdown, and `run_labeled_pages --report <label>` prints it
(or writes it with `--out`, so a long report reaches a file or the plan's log without a terminal's line wrapping in between). The
same report reads a local run today and a hosted-model run in C6, which is what makes them comparable (`--compare` lines labels up).

Two shorter console views live here too, so every reading of the aggregate is in one module: `compare_table` (saved runs side by
side) and `summary` (the lines a run prints when it finishes).

How to read it, in the order it prints: header (what produced the numbers); headline (raw, validated, committed); the retry loop;
validation recall by error kind; one row per page; the attempts of every retried page; scenarios; the gate's failures; C7's three
policy sections (confidence and correctness, the threshold sweep, what each retry changed: `policy_sections`); and, with
`errors=True`, every error string in full. `policy_report` prints the policy sections alone, pooled over several saved runs
(`make eval-policy`). It reads the stored aggregate and runs only and never re-scores anything, so it needs no
model, database or fixtures; `--rescore` is the tool that recomputes scores.

docs/dev/evaluating-model-performance.md says where this fits in the sequence of checks.
"""

from collections.abc import Mapping
from typing import Any

from agent_worker.model_eval import scoring
from agent_worker.model_eval.labels import PageLabel
from agent_worker.model_eval.saved_run_reports import policy_questions as pq
from agent_worker.model_eval.saved_run_reports.aggregate_scores import COLUMNS

# The fields the standard judges besides date and acts, in the order the labels and the schema list them (A2.1-D1): missing is
# tolerated up to a tenth of the values the page states, a wrong value never.
FIELD_ORDER = ("time", "end_time", "admission_advance", "admission_day", "free_admission", "status", "image_url")
MISSING_LIMIT = scoring.MISSING_TOLERANCE  # one decision, made in scoring.py


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


def _policy_words(policy: Mapping[str, Any]) -> str:
    """A run's retry policy in words; a forced run says so, since its threshold is not one anybody would ship (C7-D3)."""
    threshold = policy.get("confidence_threshold")
    forced = " (forced retries)" if threshold == pq.FORCED_THRESHOLD else ""
    return (
        f"threshold {threshold}{forced}, cap {policy.get('max_attempts')}, "
        f"escalation model {policy.get('escalation_model') or 'none'}"
    )


def _header(data: Mapping[str, Any]) -> list[str]:
    options = data.get("request_options") or {}
    provenance = data.get("provenance") or {}
    first_provenance = next(iter(provenance.values()), None) or {}
    policy = data.get("policy") or {}
    request = data.get("request") or {}
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
            f"policy: {_policy_words(policy)}"
        ),
        *(
            [
                f"- prompt sha: {str(request.get('instruction_sha'))[:10]}; response schema sha: {str(request.get('response_schema_sha'))[:10]}"
            ]
            if request
            else []
        ),
        "",
    ]


def _headline(aggregate: Mapping[str, Any]) -> list[str]:
    rows = []
    for column in COLUMNS:
        c, gate = aggregate["columns"][column], aggregate["gate"][column]
        rates = c["rates"]
        rows.append(
            [
                column,
                f"{rates['recall']:.3f}",
                f"{rates['precision']:.3f}",
                f"{rates['precision_lenient']:.3f}",
                f"{c['found']}/{c['labelled']}",
                f"{c['missed']}/{c['acts_wrong']}/{c['fabricated']}/{c['leaks']}",
                "PASS" if gate["passed"] else "FAIL",
            ]
        )
    return [
        "## Headline",
        "",
        *_table(
            [
                "column",
                "recall",
                "precision",
                "precision (lenient)",
                "found/labelled",
                "missed/wrong/invented/leaks",
                "gate (gated pages)",
            ],
            rows,
        ),
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
        "## The retry loop",
        "",
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
        "## Validation recall",
        "",
        f"- {v['total']} errors over every attempt: caught {v['caught']}, flagged {v['flagged']}, silent {v['silent']}",
        f"- errors on an attempt that failed for any reason (stopped, C7-D8): {v.get('stopped', 'n/a')}",
        (
            f"- findings fired: {v['findings_fired']}; self-checks: findings_disagree {v.get('findings_disagree', 'n/a')}, "
            f"confidence_disagree {v.get('confidence_disagree', 'n/a')}, route_mismatches {v.get('route_mismatches', 'n/a')}"
        ),
        "",
        *_table(["error kind", "caught", "flagged", "silent"], rows),
        "",
        "Caught = an error finding covers it (it fails the record); flagged = only a warning does; silent = no finding.",
    ]
    if aggregate["retry"]["retried"]:
        lines.append(
            "Reading note: every attempt of a retried page is counted, and an attempt failed for low confidence is not a finding "
            "(low confidence is a verdict reason, not a finding), so 'silent' can include errors a retry did stop; 'stopped' "
            "counts those."
        )
    return [*lines, ""]


def _fields(data: Mapping[str, Any]) -> list[str]:
    """Field-level accuracy: the standard's rule for every field besides date and acts, applied to the raw column's tallies."""
    columns = data["aggregate"]["columns"]
    tallies: Mapping[str, Mapping[str, int]] = columns["raw"]["fields"]
    rows = []
    for name in [*FIELD_ORDER, *sorted(set(tallies) - set(FIELD_ORDER))]:
        if name not in tallies:
            continue
        stated, correct, missing, wrong = (tallies[name][k] for k in ("stated", "correct", "missing", "wrong"))
        rate = missing / stated if stated else None
        if wrong:
            verdict = "WRONG"
        elif rate is not None and rate > MISSING_LIMIT:
            verdict = f"over {MISSING_LIMIT:.0%} missing"
        elif not stated and not correct:
            verdict = "n/a"
        else:
            verdict = "ok"
        rows.append(
            [name, str(stated), str(correct), str(missing), str(wrong), "-" if rate is None else f"{rate:.1%}", verdict]
        )
    runs = len(data["runs"])
    by_column = ", ".join(f"{c} {sum(t['wrong'] for t in columns[c]['fields'].values())}" for c in COLUMNS)
    return [
        "## Field accuracy",
        "",
        (
            "The standard (A2.1-D1): a value the page states may be missing at most 10% of the time, and a wrong value never. "
            f"Raw column, summed over all {runs} {'run' if runs == 1 else 'runs'} in the file; image links are checked against the "
            "page, so they have no 'stated' count."
        ),
        "",
        *_table(["field", "stated", "correct", "missing", "wrong", "missing rate", "verdict"], rows),
        "",
        f"Wrong values by column: {by_column}.",
        "",
    ]


def aggregate_per_fixture(data: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
    """The stored per-page run counts and whether the runs agreed (absent in files from before the field existed)."""
    per_fixture: Mapping[str, Mapping[str, Any]] = data["aggregate"].get("per_fixture", {})
    return per_fixture


def _pages(data: Mapping[str, Any], labels: Mapping[str, PageLabel]) -> list[str]:
    rows = []
    for r in data["runs"]:
        label = labels.get(r["fixture"])
        gated = "?" if label is None else ("G" if label.gated else "i")
        rows.append(
            [
                r["fixture"],
                gated,
                r.get("source") or "-",
                str(r["raw_score"]["labelled"]),
                _counts(r["raw_score"]),
                _counts(r["validated_score"]),
                _counts(r["committed_score"]),
                str(r["attempt_count"]),
                "yes" if r["escalated"] else "no",
                str(r["seconds"]),
            ]
        )
    seconds = [r["seconds"] for r in data["runs"]]
    repeated = [
        f"- {name}: {'identical' if p['runs_identical'] else 'DIFFERENT'} across {p['runs']} runs"
        for name, p in aggregate_per_fixture(data).items()
        if p["runs_identical"] is not None
    ]
    return [
        "## Pages",
        "",
        "G = gated, i = informational (never gates), ? = no longer in the labels. Counts are missed/wrong acts/invented/leaks.",
        "",
        *_table(
            ["page", "G/i", "route", "labelled", "raw", "validated", "committed", "attempts", "escalated", "seconds"],
            rows,
        ),
        "",
        f"Total {sum(seconds):.0f} s over {len(seconds)} runs.",
        "",
        *(
            [
                "Repeatability (the same page, run more than once; the model is not repeatable at temperature 0):",
                *repeated,
                "",
            ]
            if repeated
            else []
        ),
    ]


def _attempts(data: Mapping[str, Any]) -> list[str]:
    retried = [r for r in data["runs"] if r["attempt_count"] > 1]
    if not retried:
        return ["## Retried pages", "", "No page needed a second attempt.", ""]
    rows = []
    for r in retried:
        for a in r["attempts"]:
            outcome = ("escalated" if r["escalated"] else "kept") if a["attempt"] == r["attempt_count"] else ""
            rows.append(
                [
                    r["fixture"],
                    str(a["attempt"]),
                    str(a["tier"]),
                    str(a["verdict"]),
                    ",".join(a["reasons"]) or "-",
                    _errors3(a["score"]),
                    outcome,
                ]
            )
    return [
        "## Retried pages",
        "",
        "Errors are missed/wrong acts/invented for that attempt's own extraction.",
        "",
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


# ---------------------------------------------------------------------------
# C7: the policy questions (docs/dev/implementations/c7-pipeline-eval.md, "The readings")
# ---------------------------------------------------------------------------

NOT_RECORDED = (
    "Not recorded in this file (it predates C7): rescore it (`--rescore LABEL`) to fill the per-attempt confidences."
)


def _confidence(records: list[Mapping[str, Any]], labels: Mapping[str, PageLabel]) -> list[str]:
    """C7-Q4: the wrong rate per confidence value over the judged shows of attempt 1, pooled and per venue, and C7-R1's reading."""
    lines = ["## Confidence and correctness (C7-Q4)", ""]
    rows = pq.rows_by_venue(records, labels)
    table = [
        [
            f"{b.confidence:g}",
            str(b.count),
            str(b.wrong),
            f"{b.wrong_rate:.2f}",
            "yes" if b.compared else "no",
            "; ".join(f"{v} {w}/{c}" for v, (c, w) in b.by_venue.items()),
        ]
        for b in pq.buckets(rows)
    ]
    verdict, why = pq.r1_verdict(rows)
    excluded = pq.excluded_confidences(records)
    excluded_words = ", ".join(
        f"{c if c is not None else 'None'}: {t['correct']} correct, {t['missed']} missed"
        for c, t in sorted(excluded.items(), key=lambda kv: (kv[0] is None, kv[0] or 0))
    )
    return [
        *lines,
        (
            "Attempt 1 of each run; one row per show the record's confidence covers (kept, model-judged: not excluded, not a status-merge "
            "placeholder, not the structured route). Wrong = wrong acts, invented, a leak, a wrong field or image (C7-K1). "
            f"A value is compared only with {pq.MIN_BUCKET} or more rows."
        ),
        "",
        *_table(["confidence", "rows", "wrong", "wrong rate", "compared", "per venue (wrong/rows)"], table),
        "",
        f"- C7-R1: **{verdict}** ({why})",
        f"- excluded shows' confidences, never in the buckets: {excluded_words or 'none'}",
        "",
    ]


def _sweep(records: list[Mapping[str, Any]], labels: Mapping[str, PageLabel]) -> list[str]:
    """C7-Q1: what each threshold would have done to attempt 1, gated pages in the table and informational ones below it."""
    lines = ["## Threshold sweep (C7-Q1)", ""]
    out = pq.sweep(records, labels)
    gated = [[f"{t:g}", *(str(cells[c]) for c in pq.CELLS)] for t, cells in out["gated"].items()]
    informational = "; ".join(
        f"{t:g}: " + "/".join(str(cells[c]) for c in pq.CELLS) for t, cells in out["informational"].items()
    )
    structured = "; ".join(
        f"{t:g}: " + "/".join(str(cells[c]) for c in pq.CELLS) for t, cells in out["structured"].items()
    )
    return [
        *lines,
        (
            "Attempt 1 of each model-judged run (model and image routes). Would retry = failed for a reason other than low confidence, "
            "or confidence under the threshold; should retry = attempt 1 fails the A2.1-D1 standard as `scoring.gate` judges it (C7-K2)."
        ),
        "",
        *_table(["threshold", "caught", "false alarm", "missed", "quiet"], gated),
        "",
        f"- informational pages (never gate), caught/false alarm/missed/quiet: {informational}",
        (
            "- structured-route pages (no confidence, so no threshold can catch their errors; C7-CR1-4), "
            f"caught/false alarm/missed/quiet: {structured}"
        ),
        "",
    ]


def _retry_group(records: list[Mapping[str, Any]]) -> list[str]:
    """One policy's retries: C7-K3's transitions, the noise band, and C7-R3 and C7-R4 per page."""
    transitions = [
        [
            r["transition"],
            str(r["runs"]),
            str(r["fixed"]),
            str(r["introduced"]),
            str(r["kept"]),
            "-" if r["mean_seconds"] is None else str(r["mean_seconds"]),
            "not recorded" if r["tokens"] is None else f"{r['tokens']['prompt']}/{r['tokens']['completion']}",
        ]
        for r in pq.retry_effect(records)
    ]
    band, churn = pq.noise_band(records), pq.churn(records)
    second, third = pq.page_effects(records, 1, 2), pq.page_effects(records, 2, 3)
    means = {n: pq.mean_errors(records, n) for n in (1, 2, 3)}
    pages = [
        [
            page,
            f"{band.get(page, 0.0):.2f}",
            f"{churn[page]:.2f}" if page in churn else "-",
            *(f"{means[n][page]:.1f}" if page in means[n] else "-" for n in (1, 2, 3)),
            second.get(page, "-"),
            third.get(page, "-"),
        ]
        for page in sorted(means[1])
    ]
    return [
        *_table(
            ["transition", "runs", "fixed", "introduced", "kept", "mean seconds", "tokens (prompt/completion)"],
            transitions,
        ),
        "",
        *_table(["page", "noise band", "churn", "errors at 1", "at 2", "at 3", "2 vs 1", "3 vs 2"], pages),
        "",
        f"- C7-R3 tier 2: **{pq.tier_verdict(second)}**; tier 3: **{pq.tier_verdict(third)}**",
        f"- C7-R4 (the cap): **{pq.r4_verdict(third)}**",
        "",
    ]


def _retries(records: list[Mapping[str, Any]]) -> list[str]:
    """C7-Q3 and C7-Q2, per retry policy found in the records (so a forced run with and without an escalation model can be pooled
    and compared), then the escalated tier against the unescalated one (C7-R3's last clause)."""
    lines = ["## What each retry changed (C7-Q3, C7-Q2)", ""]
    if not any(len(r.get("attempts") or []) > 1 for r in records):
        return [*lines, "No page made a second attempt.", ""]
    lines += [
        (
            "Errors are every kind but field_missing; an error is the same in two attempts when its kind, date and field match (C7-K3). "
            "Noise band = the population SD of attempt 1's errors across a page's runs; an attempt helps on a page when its mean is lower "
            "by more than the band, and a tier helps when it helps on two pages and hurts on none (C7-R3). On the shipped route a forced "
            "attempt 2 sends the splitter the same request, so this measures a generic hint plus a resample, not the specific-hint path."
        ),
        "",
    ]
    groups: dict[str | None, list[Mapping[str, Any]]] = {}
    for record in records:
        groups.setdefault((record.get("policy") or {}).get("escalation_model"), []).append(record)
    for model, group in groups.items():
        lines += [f"### Escalation model: {model or 'none'}", "", *_retry_group(group)]
    if None in groups and len(groups) > 1:
        for model, group in groups.items():
            if model is not None:
                effects = pq.escalation_effects(groups[None], group)
                lines.append(
                    f"- {model} at attempt 3 against no escalation model: {effects or 'no page reached attempt 3 in both'}; "
                    f"**{pq.tier_verdict(effects)}**"
                )
        lines.append("")
    return lines


def policy_sections(records: list[Mapping[str, Any]], labels: Mapping[str, PageLabel]) -> list[str]:
    """C7's three sections, over any run records (one file's, or several pooled). A file from before C7 carries none of the
    per-attempt fields they read (confidences, seconds, tokens), so it gets one line saying how to fill them instead of three
    sections of zeros."""
    if not pq.confidence_recorded(records):
        return ["## Policy questions (C7)", "", NOT_RECORDED, ""]
    return [*_confidence(records, labels), *_sweep(records, labels), *_retries(records)]


def render(data: Mapping[str, Any], labels: Mapping[str, PageLabel], *, show_errors: bool = False) -> str:
    """The Markdown report for one results file. `labels` says which pages are gated (a page missing from it prints as '?')."""
    aggregate = data["aggregate"]
    lines = [
        *_header(data),
        *_headline(aggregate),
        *_retry(aggregate),
        *_validation(aggregate),
        *_fields(data),
        *_pages(data, labels),
        *_attempts(data),
        *_scenarios(data, show_errors),
        *_gate_failures(aggregate),
        *policy_sections(data["runs"], labels),
    ]
    if show_errors:
        lines += _errors(data)
    return "\n".join(lines).rstrip() + "\n"


def policy_report(files: Mapping[str, Mapping[str, Any]], labels: Mapping[str, PageLabel]) -> str:
    """C7's policy sections pooled over several saved runs (`make eval-policy`), with a line per label saying what produced it.
    The caller refuses files scored against different labels (`run_labeled_pages.policy_report`)."""
    header = ["# Policy questions: " + ", ".join(files), ""]
    for name, data in files.items():
        header.append(
            f"- {name}: labels_sha {str(data.get('labels_sha'))[:10]}; set {data.get('set')}; runs {len(data.get('runs', []))}; "
            f"model {(data.get('request_options') or {}).get('model')}; policy: {_policy_words(data.get('policy') or {})}"
        )
    records = [r for data in files.values() for r in data["runs"]]
    return "\n".join([*header, "", *policy_sections(records, labels)]).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Console views: runs side by side, and the closing summary of a run
# ---------------------------------------------------------------------------


def compare_table(files: Mapping[str, Mapping[str, Any]]) -> str:
    """The headline numbers of saved runs side by side, one column per run, in the order `files` lists them."""
    width = 26
    rows: list[tuple[str, Any]] = [
        ("labels_sha", lambda f: str(f.get("labels_sha"))[:10]),
        ("started_at", lambda f: f.get("started_at")),
    ]
    for column in COLUMNS:
        rows += [
            (f"{column}: recall", lambda f, c=column: round(f["aggregate"]["columns"][c]["rates"]["recall"], 3)),
            (f"{column}: precision", lambda f, c=column: round(f["aggregate"]["columns"][c]["rates"]["precision"], 3)),
            (f"{column}: gate", lambda f, c=column: "PASS" if f["aggregate"]["gate"][c]["passed"] else "FAIL"),
        ]
    rows += [
        ("retry rate", lambda f: round(f["aggregate"]["retry"]["retry_rate"], 3)),
        ("escalated", lambda f: f["aggregate"]["retry"]["escalated"]),
        ("validation recall", lambda f: round(f["aggregate"]["validation"]["recall"], 3)),
    ]
    lines = ["".ljust(width) + "".join(name.ljust(22) for name in files)]
    lines += [name.ljust(width) + "".join(str(getter(f)).ljust(22) for f in files.values()) for name, getter in rows]
    return "\n".join(lines)


def summary(aggregate: Mapping[str, Any]) -> str:
    """The lines printed when a run finishes: recall, precision and the gate per column, then the retry loop and validation recall."""
    lines = []
    for column in COLUMNS:
        rates = aggregate["columns"][column]["rates"]
        gate = aggregate["gate"][column]
        lines.append(
            f"{column:10} recall {rates['recall']:.3f}  precision {rates['precision']:.3f}  gate {'PASS' if gate['passed'] else 'FAIL'}"
        )
    lines.append(
        f"retry rate {aggregate['retry']['retry_rate']:.3f}; escalated {aggregate['retry']['escalated']}; "
        f"validation recall {aggregate['validation']['recall']:.3f} ({aggregate['validation']['silent']} silent)"
    )
    return "\n".join(lines)
