"""The retry policy's questions, answered from saved run records: does confidence track correctness, what would another threshold
have done, and what did each retry change (C7).

What this is: A3 built the retry policy with three numbers nobody had measured (a confidence threshold of 0.8, a cap of 3 attempts,
and a third tier that swaps in a larger model). C7 measures them on the shipped model, and this module turns a results file's run
records into the tables that answer the four questions the plan names:

    C7-Q4  does the model's confidence track correctness?      `confidence_rows` (C7-K1), `buckets`, `r1_verdict`        -> C7-R1
    C7-Q1  is 0.8 the right threshold?                          `would_fail`, `sweep_cell` (C7-K2), `sweep`              -> C7-R2
    C7-Q3  does a retry recover errors, or only cost?           `transition` (C7-K3), `retry_effect`, `page_effects`      -> C7-R3
    C7-Q2  is 3 the right cap?                                  `page_effects` on attempt 3, `r4_verdict`                 -> C7-R4

The readings (C7-R1 to C7-R4) were fixed before any C7 run, so the numbers cannot choose their own interpretation
(docs/dev/implementations/c7-pipeline-eval.md, "The readings"). Three definitions are used everywhere below, and C7-K1 and C7-K2
decide the first two: a WRONG SHOW (a kept, model-judged show carrying an error that should not be in the calendar as written), a page-run
that SHOULD RETRY (its attempt 1 fails the A2.1-D1 standard as `scoring.gate` judges it), and an ERROR COUNT (every error item but
`field_missing`).

How to read it: the constants, then one section per question in the order above. It is pure: it reads run records (`asdict(PageRun)`,
as `run_labeled_pages` stores them) and the labels, and never imports `labeled_page_runs` (`test_layering.py`), so a committed snapshot
can be read on a machine with no model or database. `markdown_report` prints the tables.
"""

import itertools
import statistics
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from agent_worker import policy
from agent_worker.model_eval import scoring
from agent_worker.model_eval.labels import PageLabel
from agent_worker.model_eval.scoring import ErrorItem

# The threshold `--force-retries` sets (C7-D3). The schema caps a show's confidence at 1 (`ge=0, le=1`), so a threshold above 1 makes
# every model-judged attempt fail for low confidence, with no change to the pipeline: the retry's effect is then measured on every
# model-route page instead of the few whose confidence happens to dip (on the hosted model, none: C7-F1). It lives here, not beside
# `build_policy`, because the report reads it to label a forced run and this folder may not import the runner.
FORCED_THRESHOLD = 1.01

# The thresholds the sweep tries (C7-R2): the coarse values the hosted model actually returns (C7-F2) and the ones between them.
DEFAULT_THRESHOLDS = (0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 1.0)

# C7-R1's sample rules. The 10 and the 20 are judgement, not statistics: below them a rate turns on one or two shows. No p-values,
# because the instances are not independent (the same show in five runs, one page's layout).
MIN_BUCKET = 10
MIN_WRONG_OUTSIDE_LARGEST = 20

# The least a page's mean error count must move for C7-R3 to call it a change, whatever its noise band (C7-CR1-1, amended before
# any C7 run). A page whose attempt 1 gives the same count in every run has a band of exactly 0, and a forced run is a resample,
# so without a floor one run differing by one error (a mean move of 0.2 over five runs) would read as "helps" or "hurts", and one
# such flip on a quiet page would disqualify a tier ("hurts on none"). Half an error a run is judgement: over five runs it takes
# three errors' net movement, more than the one flip in five C6 saw on Turf Club (C6 Round 10).
MIN_EFFECT = 0.5

# The routes whose confidence is the model's own. The structured route's 1.0 is a placeholder (C7-F5).
MODEL_JUDGED_ROUTES = ("model", "image")

# The four cells of the threshold sweep: would retry / should retry.
CELLS = ("caught", "false_alarm", "missed", "quiet")

# One row of C7-Q4's table: a show's confidence, and whether it was correct.
Row = tuple[float, bool]


def first_attempt(record: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Attempt 1 of a run record: the request production sends first, by the configured model, with no hint. None if it has none."""
    attempts = record.get("attempts") or []
    return attempts[0] if attempts else None


def items_of(attempt: Mapping[str, Any]) -> list[ErrorItem]:
    """The scorer's error items for one attempt's own extraction (none when the call produced nothing)."""
    score = attempt.get("score")
    return [] if score is None else [ErrorItem(**i) for i in score.get("items", [])]


# ---------------------------------------------------------------------------
# C7-Q4: confidence against correctness (C7-K1, C7-R1)
# ---------------------------------------------------------------------------


def confidence_rows(
    route: str | None, show_confidences: Sequence[float | None], judged_indices: Iterable[int], items: Iterable[ErrorItem],
) -> list[Row]:
    """The (confidence, correct) rows of one attempt: one per show the record's confidence covers."""
    # C7-Q4 asks whether the confidence the pipeline ROUTES on tracks correctness, so the rows are the shows that confidence covers:
    # judged shows only (validation's exclusions and the status merge's placeholders never reach `aggregate_confidence`), and no
    # structured-route rows, whose 1.0 is a placeholder (C7-F3, C7-F5; c7-pipeline-eval.md, C7-K1, C7-PR1-1). Scoring an excluded
    # low-confidence show as "correct" would fill the lowest bucket with shows the pipeline discards and invert the answer. Among
    # the judged shows a row is wrong when it should not be in the calendar as written; a missing field is tolerated (A2.1-D1). A
    # leak is wrong here although the gate tolerates one a page: the question is whether this row is right, not whether the page passes.
    if policy.stored_route(route) not in MODEL_JUDGED_ROUTES:
        return []
    WRONG_KINDS = {"acts_wrong", "fabricated", "leak", "field_wrong", "image_wrong"}
    wrong = {i.index for i in items if i.kind in WRONG_KINDS and i.index is not None}
    return [(c, i not in wrong) for i in judged_indices if (c := show_confidences[i]) is not None]


def confidence_recorded(records: Iterable[Mapping[str, Any]]) -> bool:
    """Whether any attempt carries the per-show confidences. A file written before C7 has none: its tables are "not recorded" (rescore
    it to fill them), never zero rows."""
    return any("show_confidences" in a for r in records for a in r.get("attempts") or [])


def rows_by_venue(records: Iterable[Mapping[str, Any]], labels: Mapping[str, PageLabel]) -> dict[str, list[Row]]:
    """C7-K1's rows from attempt 1 of every run, grouped by venue (C7-R1 asks the slope to hold on two venues separately).

    Attempt 1 only: it is what production sends first, by the shipped model. A forced run's later attempts carry a hint and, at tier 3,
    maybe another model, so they would answer a different question. A page no longer in the labels has no venue and is skipped."""
    out: dict[str, list[Row]] = {}
    for record in records:
        label = labels.get(record["fixture"])
        attempt = first_attempt(record)
        if label is None or attempt is None or "show_confidences" not in attempt:
            continue
        rows = confidence_rows(attempt["route"], attempt["show_confidences"], attempt["judged_indices"], items_of(attempt))
        out.setdefault(label.venue, []).extend(rows)
    return out


@dataclass
class Bucket:
    """One confidence value's rows: how many, how many wrong, in total and per venue. `compared` when it holds at least the minimum
    (C7-R1); a smaller bucket is shown and never compared."""

    confidence: float
    count: int
    wrong: int
    compared: bool
    by_venue: dict[str, tuple[int, int]] = field(default_factory=dict)  # venue -> (count, wrong)

    @property
    def wrong_rate(self) -> float:
        return self.wrong / self.count if self.count else 0.0


def buckets(rows_by_venue: Mapping[str, Sequence[Row]], min_size: int = MIN_BUCKET) -> list[Bucket]:
    """The rows bucketed by confidence value, lowest first. The hosted model's confidence is coarse (0.5, 0.8, 0.9, 1.0: C7-F2), so a
    bucket per value is the natural binning and none has to be invented."""
    counts: dict[float, dict[str, list[int]]] = {}
    for venue, rows in rows_by_venue.items():
        for confidence, correct in rows:
            tally = counts.setdefault(confidence, {}).setdefault(venue, [0, 0])
            tally[0] += 1
            tally[1] += not correct
    out = []
    for confidence in sorted(counts):
        per_venue = {v: (c, w) for v, (c, w) in sorted(counts[confidence].items())}
        count = sum(c for c, _ in per_venue.values())
        out.append(Bucket(confidence, count, sum(w for _, w in per_venue.values()), count >= min_size, per_venue))
    return out


def _slope_holds(compared: Sequence[Bucket]) -> bool:
    """C7-R1's test on compared buckets: the lowest bucket wrong at least twice as often as the highest, and wrong at all."""
    low, high = compared[0], compared[-1]
    return low.wrong_rate > 0 and low.wrong_rate >= 2 * high.wrong_rate


def r1_verdict(
    rows_by_venue: Mapping[str, Sequence[Row]], min_size: int = MIN_BUCKET, min_wrong_outside: int = MIN_WRONG_OUTSIDE_LARGEST,
) -> tuple[str, str]:
    """C7-R1, applied: "yes", "no" or "not enough evidence", with the reason in words.

    Not enough evidence comes first: fewer than `min_wrong_outside` wrong rows from venues other than the largest contributor (so one
    page cannot carry it), or fewer than two buckets of `min_size`. Then "yes" only if the slope holds pooled AND on at least two
    venues separately; anything else (flat, inverted, one venue only) is "no"."""
    wrong_by_venue = {v: sum(not ok for _, ok in rows) for v, rows in rows_by_venue.items()}
    largest = max(wrong_by_venue, key=lambda v: wrong_by_venue[v], default=None)
    outside = sum(w for v, w in wrong_by_venue.items() if v != largest)
    if outside < min_wrong_outside:
        return "not enough evidence", (
            f"{outside} wrong rows outside the largest contributor ({largest}); C7-R1 needs {min_wrong_outside}"
        )
    compared = [b for b in buckets(rows_by_venue, min_size) if b.compared]
    if len(compared) < 2:
        return "not enough evidence", f"{len(compared)} confidence value(s) with {min_size} or more rows; C7-R1 needs two"
    venues_holding = [
        v for v, rows in rows_by_venue.items()
        if len(own := [b for b in buckets({v: rows}, min_size) if b.compared]) >= 2 and _slope_holds(own)
    ]
    if _slope_holds(compared) and len(venues_holding) >= 2:
        return "yes", f"the lowest compared bucket is at least twice as wrong as the highest, pooled and on {venues_holding}"
    return "no", f"pooled slope {'holds' if _slope_holds(compared) else 'does not hold'}; venues where it holds: {venues_holding or 'none'}"


def excluded_confidences(records: Iterable[Mapping[str, Any]]) -> dict[float | None, dict[str, int]]:
    """The confidences of the shows validation EXCLUDED on attempt 1, split into correct exclusions and wrong ones (a labeled show
    the scorer reports `missed` at that index). Never part of C7-R1's buckets: they never reach the record's confidence. This is where
    the hosted model's low values actually went (C7-F3), so it is reported on its own line."""
    out: dict[float | None, dict[str, int]] = {}
    for record in records:
        attempt = first_attempt(record)
        if attempt is None or policy.stored_route(attempt.get("route")) not in MODEL_JUDGED_ROUTES:
            continue
        missed_at = {i.index for i in items_of(attempt) if i.kind == "missed" and i.index is not None}
        confidences = attempt.get("show_confidences") or []
        for index in attempt.get("excluded_indices") or []:
            if index < len(confidences):
                tally = out.setdefault(confidences[index], {"correct": 0, "missed": 0})
                tally["missed" if index in missed_at else "correct"] += 1
    return out


# ---------------------------------------------------------------------------
# C7-Q1: the threshold sweep (C7-K2, C7-R2)
# ---------------------------------------------------------------------------


def would_fail(reasons: Sequence[str], confidence: float | None, t: float) -> bool:
    """Whether an attempt with these stored failure reasons and this confidence would have failed at threshold `t`."""
    # The sweep asks what ANOTHER threshold would have done, so the stored low_confidence reason (what 0.8 did) is dropped and
    # recomputed at t, exactly as `policy.combine` would: any other reason fails whatever the confidence, and a None confidence is no
    # evidence, never a failure (A3-K4; c7-pipeline-eval.md, C7-K2). The comparison is strict, as in `combine`. A test runs this
    # against `combine` itself on a table of results, so the mirror cannot drift.
    other = [r for r in reasons if r != "low_confidence"]
    return bool(other) or (confidence is not None and confidence < t)


def sweep_cell(
    reasons: Sequence[str], confidence: float | None, first_attempt_score: scoring.PageScore | scoring.PageFailure, t: float,
) -> str:
    """One page-run's cell at threshold `t`: caught, false_alarm, missed or quiet (`CELLS`)."""
    # "Should retry" is the A2.1-D1 standard on attempt 1, as the scorer's own gate judges it (any missed, wrong-acts or invented
    # show, any wrong field, more than one leak, a field over 10% missing), so the standard is never re-coded here (C7-K2,
    # C7-PR1-2). Would and should together are the confusion table C7-R2 reads.
    would = would_fail(reasons, confidence, t)
    should = not scoring.gate({0: [first_attempt_score]}).passed
    return {(True, True): "caught", (True, False): "false_alarm", (False, True): "missed", (False, False): "quiet"}[(would, should)]


def _first_score(record: Mapping[str, Any], attempt: Mapping[str, Any]) -> scoring.PageScore | scoring.PageFailure:
    """Attempt 1's score for the gate; a call that produced nothing is a page failure (it fails the standard, as a crash does)."""
    if attempt.get("score") is None:
        return scoring.PageFailure(record["fixture"], attempt.get("error") or "no extraction")
    return scoring.PageScore.from_dict(attempt["score"])


def sweep(
    records: Iterable[Mapping[str, Any]], labels: Mapping[str, PageLabel], thresholds: Sequence[float] = DEFAULT_THRESHOLDS,
) -> dict[str, dict[float, dict[str, int]]]:
    """The four cells at each threshold, from attempt 1 of every run, gated and informational pages kept apart (A2.1-D2:
    informational pages never gate), and structured-route pages on a line of their own: they have no confidence, so no threshold can
    catch their errors, and counted beside the model-judged pages they would read as "the threshold missed these" (C7-CR1-4). The
    threshold only decides whether an attempt fails; it does not change what attempt 1 extracts, so one run at the default policy
    answers every threshold at once (the plan's Departure 1)."""
    out: dict[str, dict[float, dict[str, int]]] = {
        group: {t: dict.fromkeys(CELLS, 0) for t in thresholds} for group in ("gated", "informational", "structured")
    }
    for record in records:
        label = labels.get(record["fixture"])
        attempt = first_attempt(record)
        if label is None or attempt is None:
            continue
        if policy.stored_route(attempt.get("route")) == "structured":
            group = "structured"
        else:
            group = "gated" if label.gated else "informational"
        score = _first_score(record, attempt)
        for t in thresholds:
            out[group][t][sweep_cell(attempt.get("reasons") or [], attempt.get("confidence"), score, t)] += 1
    return out


# ---------------------------------------------------------------------------
# C7-Q3 and C7-Q2: what a retry changed (C7-K3, C7-R3, C7-R4)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Transition:
    """Between two attempts (or two runs' first attempts): errors the second no longer has, errors it newly has, errors in both."""

    fixed: int
    introduced: int
    kept: int


def transition(first: Iterable[ErrorItem], second: Iterable[ErrorItem]) -> Transition:
    """What changed between two attempts' error items."""
    # The same error in two attempts is the same kind on the same date and field. The index is not part of it: it is a position in
    # that attempt's list and shifts when a show is added or dropped. It is counted as a multiset, because two shows on one date can
    # both be wrong and one of them fixed (c7-pipeline-eval.md, C7-K3). The same comparison between two runs' first attempts
    # describes how much a resample moves (a hosted retry is also a resample: DeepInfra does not honour `seed`). Every kind but
    # field_missing counts, so a retry that makes a field wrong shows as one that hurt.
    before = Counter((i.kind, i.date, i.field) for i in first if i.kind != "field_missing")
    after = Counter((i.kind, i.date, i.field) for i in second if i.kind != "field_missing")
    return Transition(fixed=sum((before - after).values()), introduced=sum((after - before).values()), kept=sum((before & after).values()))


def error_count(items: Iterable[ErrorItem]) -> int:
    """The plan's error count: every error item but `field_missing` (tolerated up to 1 in 10, so not an error a retry must fix)."""
    return sum(1 for i in items if i.kind != "field_missing")


def _by_page(records: Iterable[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    """Run records grouped by page, in file order."""
    out: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        out.setdefault(record["fixture"], []).append(record)
    return out


def _attempt(record: Mapping[str, Any], n: int) -> Mapping[str, Any] | None:
    """Attempt `n` (1-based) of a run, or None when the run stopped before it."""
    return next((a for a in record.get("attempts") or [] if a["attempt"] == n), None)


def noise_band(records: Iterable[Mapping[str, Any]]) -> dict[str, float]:
    """Per page, the population standard deviation of attempt 1's error count across its runs: what the same request, resampled,
    already moves by (C7-PR1-10). A retry has to beat it to count (C7-R3). One run gives 0.0."""
    out = {}
    for page, runs in _by_page(records).items():
        counts = [error_count(items_of(a)) for r in runs if (a := _attempt(r, 1)) is not None]
        if counts:
            out[page] = statistics.pstdev(counts)
    return out


def churn(records: Iterable[Mapping[str, Any]]) -> dict[str, float]:
    """Per page, the mean of fixed + introduced between every pair of runs' first attempts (C7-K3 between runs). A description of how
    much a resample moves, printed beside the noise band; not itself a test."""
    out = {}
    for page, runs in _by_page(records).items():
        firsts = [items_of(a) for r in runs if (a := _attempt(r, 1)) is not None]
        pairs = list(itertools.combinations(firsts, 2))
        if pairs:
            moved = [(t := transition(a, b)).fixed + t.introduced for a, b in pairs]
            out[page] = sum(moved) / len(pairs)
    return out


def mean_errors(records: Iterable[Mapping[str, Any]], n: int) -> dict[str, float]:
    """Per page, the mean error count of attempt `n` over the runs that reached it."""
    out = {}
    for page, runs in _by_page(records).items():
        counts = [error_count(items_of(a)) for r in runs if (a := _attempt(r, n)) is not None]
        if counts:
            out[page] = sum(counts) / len(counts)
    return out


def _effect(before: float, after: float, band: float) -> str:
    """C7-R3's per-page rule: helps when the mean fell by more than the band (and at least `MIN_EFFECT`), hurts when it rose by more."""
    needed = max(band, MIN_EFFECT)
    if before - after > needed:
        return "helps"
    if after - before > needed:
        return "hurts"
    return "neither"


def page_effects(records: Sequence[Mapping[str, Any]], before: int, after: int) -> dict[str, str]:
    """C7-R3 per page: attempt `after` against attempt `before` over the SAME runs (those that reached `after`), measured against the
    page's noise band (from attempt 1 of all its runs). Comparing with attempt `before` over every run would mix in runs that stopped
    early, which are the better ones when a retry fires for a reason (C7-CR1-2). A page that never reached attempt `after` (a
    structured page in a forced run passes attempt 1, C7-D3) has no effect either way."""
    band = noise_band(records)
    reached = [r for r in records if _attempt(r, after) is not None and _attempt(r, before) is not None]
    first, second = mean_errors(reached, before), mean_errors(reached, after)
    return {page: _effect(first[page], second[page], band.get(page, 0.0)) for page in second if page in first}


def escalation_effects(unescalated: Sequence[Mapping[str, Any]], escalated: Sequence[Mapping[str, Any]], n: int = 3) -> dict[str, str]:
    """C7-R3's last clause: attempt `n` with the escalation model against attempt `n` without it, per page, by the same rule (the
    band from the unescalated runs' attempt 1, and the same `MIN_EFFECT` floor). The two are different runs, so nothing is paired."""
    band = noise_band(unescalated)
    base, other = mean_errors(unescalated, n), mean_errors(escalated, n)
    return {page: _effect(base[page], other[page], band.get(page, 0.0)) for page in other if page in base}


def tier_verdict(effects: Mapping[str, str]) -> str:
    """C7-R3 over pages: a tier helps if it helps on at least two pages and hurts on none (two, so one page cannot carry it)."""
    values = list(effects.values())
    return "helps" if values.count("helps") >= 2 and "hurts" not in values else "does not help"


def r4_verdict(effects: Mapping[str, str]) -> str:
    """C7-R4 from attempt 3's per-page effects: keep 3 unless attempt 3 hurts somewhere and helps nowhere (then 2: the last attempt is
    pure cost); 4 only if attempt 3 helps on at least two pages, and a fourth attempt is not run in C7 unless that happens."""
    values = list(effects.values())
    if "hurts" in values and "helps" not in values:
        return "2 (attempt 3 hurts on a page and helps on none)"
    if values.count("helps") >= 2:
        return "4 (attempt 3 helps on two or more pages; a fourth attempt would need its own run)"
    return "keep 3"


def _summed_tokens(attempts: Sequence[Mapping[str, Any]]) -> dict[str, int] | None:
    """Tokens summed over attempts that recorded them; None when none did (an unknown cost, never 0: C7-D6)."""
    known = [a["tokens"] for a in attempts if a.get("tokens") is not None]
    if not known:
        return None
    return {k: sum(t.get(k, 0) for t in known) for k in ("prompt", "completion")}


def retry_effect(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One row per tier transition (1 to 2; 2 to 3, split by whether the larger model ran): errors fixed, introduced and kept summed
    over the runs that made both attempts, with the later attempt's mean seconds and summed tokens. C7-K3's counts describe WHAT moved;
    whether it helped is `page_effects` against the noise band (C7-R3)."""
    groups: dict[str, list[tuple[Mapping[str, Any], Mapping[str, Any]]]] = {}
    for record in records:
        for n in (2, 3):
            before, after = _attempt(record, n - 1), _attempt(record, n)
            if before is None or after is None:
                continue
            name = "1 to 2" if n == 2 else f"2 to 3 ({'larger model' if after.get('larger_model_used') else 'same model'})"
            groups.setdefault(name, []).append((before, after))
    rows = []
    for name in sorted(groups):
        pairs = groups[name]
        moved = [transition(items_of(a), items_of(b)) for a, b in pairs]
        seconds = [b["seconds"] for _, b in pairs if b.get("seconds") is not None]
        rows.append({
            "transition": name, "runs": len(pairs),
            "fixed": sum(t.fixed for t in moved), "introduced": sum(t.introduced for t in moved), "kept": sum(t.kept for t in moved),
            "mean_seconds": round(sum(seconds) / len(seconds), 1) if seconds else None,
            "tokens": _summed_tokens([b for _, b in pairs]),
        })
    return rows
