"""The validation, replayed over real extractions — local only, skipped when the data is absent.

Milestone A3 (docs/dev/implementations/a3-validation-and-retry.md, test approach §5; plan review round 1 #10).
The eval harness calls `extract_page`, not the graph, so nothing else would notice a check that
misfires on a real page (an error that escalates White Squirrel every day, or a repair that drops a
correct value) until `local_test` or production did. The stored extractions in
`eval/results/a21-confirm.json` plus the fixtures make the replay cheap, and no model is called.

**This file does not run in CI.** `eval/fixtures/` and `eval/results/` are gitignored
(apps/api/.gitignore), so CI and a fresh clone have neither and every test here skips (visibly,
`-rs`). It runs on a machine that has them. The committed tests in `test_validation.py` are the
CI layer.

Where the expected values come from: they are literals read from the stored results during the
A3 build (run 0 of each page in `a21-confirm`, replayed with the page's labelled capture date and the
source the run recorded), not recomputed by the code under test. One rule is NOT exercised on real
data here, so a green run isn't evidence for it (plan round 2 #9): the title-scoped end-time repair
(no model-route show in run 0 has an `end_time`); it is covered by the synthetic tests only.
`act_not_in_title` IS exercised, but only by `a3-confirm` (below): `a21-confirm`'s 7th St Entry titles
don't line up with its shows (29 titles, 30 shows), while the current pipeline's do, and there the rule
catches a real wrong act (code review round 1, #9)
"""

import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from agent_worker import validation
from agent_worker.eval.labels import PAGE_LABELS
from agent_worker.extraction import clean_text
from agent_worker.policy import DEFAULT_POLICY, combine
from agent_worker.schemas import VenuePageExtraction
from agent_worker.sources import jsonld
from agent_worker.tests.test_retry_plumbing import PINNED
from agent_worker.validation import CheckCode, Verdict

EVAL = Path(__file__).resolve().parent.parent / "eval"
FIXTURES = EVAL / "fixtures"
CONFIRM = EVAL / "results" / "a21-confirm.json"
REVIEW2 = EVAL / "results" / "a21-review2.json"

A3_CONFIRM = EVAL / "results" / "a3-confirm.json"

needs_data = pytest.mark.skipif(
    not (CONFIRM.exists() and FIXTURES.exists()),
    reason="eval fixtures/results are gitignored; this layer runs only where they exist (see the module docstring)",
)

# fixture file -> (shows returned, shows kept, repairs as (field, reason-fragment)); the pages in "gated
# plus Terminal": the gated pages and the Terminal Bar captures (labels.py marks both Terminal ones
# gated=False), plus Zhora and the posters, which are informational.
EXPECTED: dict[str, tuple[int, int, list[tuple[str, str]]]] = {
    "Archives_ Events - The White Squirrel Bar.html": (12, 12, []),
    "white_squirrel-2026-10-10.html": (12, 11, []),  # one non-music event the splitter left empty
    "seventh_st_entry-2026-10-10.html": (30, 30, []),
    "mortimers-2026-10-10.html": (18, 5, []),  # 13 listings name no act; two of them are real shows (the gate's `missed: 2`)
    "terminal-2026-10-10.html": (14, 14, []),
    "Terminal Bar – The Terminal Bar.html": (8, 6, []),
    "Events — Zhora Darling.html": (24, 23, []),
    "terminal_bar_show_1.png": (1, 1, []),
    # The poster route put a start time in `end_time` with `time` null on every seed (A2's eval).
    "terminal_bar_show_2.webp": (1, 1, [("end_time", "no start time")]),
}


def run_zero_per_fixture() -> dict[str, dict[str, Any]]:
    """Run 0 of every page in `a21-confirm`, keyed by fixture file name (one deterministic run each)."""
    runs: dict[str, dict[str, Any]] = {}
    for run in json.loads(CONFIRM.read_text())["runs"]:
        if run["run"] == 0:
            runs[run["fixture"]] = run
    return runs


def replay(run: dict[str, Any]) -> tuple[validation.ValidationResult, list[Any]]:
    """Validate a stored run's extraction as the pipeline would have: its labelled capture date, its recorded source, its page's HTML and cleaned text; returns the combined result and the kept shows."""
    fixture = run["fixture"]
    label = PAGE_LABELS[fixture]
    is_image = run["source"] == "image"
    html = "" if is_image else (FIXTURES / fixture).read_text()
    notes = dict(run["notes"]) if isinstance(run["notes"], dict) else {}
    if run["source"] == "jsonld" and "titles" not in notes:
        # The stored JSON-LD runs predate `notes["titles"]`; the numbered titles that were sent are the same list.
        notes["titles"] = [line.split(": ", 1)[1] for line in run["sent_text"].split("\n")]
    result, kept = validation.validate_extraction(
        VenuePageExtraction.model_validate(run["extraction"]), source=run["source"], notes=notes,
        fetched_on=label.captured_on, page_html=html, page_text="" if is_image else clean_text(html, False),
    )
    return combine(result, DEFAULT_POLICY), kept


@needs_data
@pytest.mark.parametrize("fixture", sorted(EXPECTED))
def test_a_real_extraction_validates_clean(fixture: str) -> None:
    # Proves: the checks raise no error on any real page the pipeline serves, the verdict is a pass, the
    # number of shows kept is what the plan's replay found, and the only repair anywhere is the poster's
    # misplaced start. A check that misfires on White Squirrel would escalate it every day; this is where
    # that would be seen before production.
    returned, kept_count, repairs = EXPECTED[fixture]
    result, kept = replay(run_zero_per_fixture()[fixture])
    assert result.errors == []
    assert result.verdict is Verdict.PASSED
    assert len(kept) == kept_count and len(result.excluded) == returned - kept_count
    assert [r.field for r in result.repairs] == [field for field, _ in repairs]
    assert all(fragment in r.reason for r, (_, fragment) in zip(result.repairs, repairs, strict=True))


@needs_data
def test_every_excluded_show_on_a_real_page_is_reported_with_a_warning() -> None:
    # Proves (round 1 #7): Mortimer's 13 no-act listings are each a warning naming the listing, so the
    # two real shows the splitter misses are findable instead of vanishing.
    result, _ = replay(run_zero_per_fixture()["mortimers-2026-10-10.html"])
    warned = [f for f in result.findings if f.code is CheckCode.EXCLUDED_NO_ACTS]
    assert [f.show_index for f in warned] == result.excluded and len(warned) == 13


@needs_data
@pytest.mark.parametrize("fixture", ["Archives_ Events - The White Squirrel Bar.html", "white_squirrel-2026-10-10.html"])
def test_the_json_ld_under_report_guard_does_not_fire_on_the_real_white_squirrel_pages(fixture: str) -> None:
    # Proves: the evidence the threshold of 3 was chosen from. Built from the page's own JSON-LD, with no
    # model: events -> structured shows -> the guard. Both captures' text names exactly the dates their
    # events fall on (Oct 10-14 and Aug 17-22), so there are no unmatched dates.
    html = (FIXTURES / fixture).read_text()
    events = [e for e in jsonld.find_events(html) if e.get("startDate") and e.get("name")]
    structured = [jsonld.to_structured_show(e, "America/Chicago") for e in events]
    extraction = VenuePageExtraction.model_validate({"page_readable": True, "shows": [
        {"venue": "V", "date": s.date, "acts": [{"name": s.title}], "is_ambiguous": False, "confidence": 1.0}
        for s in structured
    ]})
    findings = validation.check_under_reported(extraction, clean_text(html, False), PAGE_LABELS[fixture].captured_on)
    assert findings == []


@needs_data
def test_act_not_in_title_catches_a_real_wrong_act_in_the_current_pipelines_run() -> None:
    # Proves (code review round 1, #9): A2.1-E3 guard has real evidence. In `a3-confirm` (the gated run
    # after A3, 56 of 60) 7th St Entry's 30 titles line up with its 30 shows, and the model route's act
    # splitter wrote "Devilsoundguy" for a title that says "Evilsoundguy": the one act name it got wrong
    # that is a typo and not a convention call. The warning names it; no error is raised.
    if not A3_CONFIRM.exists():
        pytest.skip("a3-confirm.json is not present (produced by the A3 build's gated eval run)")
    run = next(
        r for r in json.loads(A3_CONFIRM.read_text())["runs"]
        if r["run"] == 0 and r["fixture"] == "seventh_st_entry-2026-10-10.html"
    )
    result, _ = replay(run)
    warned = [f for f in result.findings if f.code is CheckCode.ACT_NOT_IN_TITLE]
    assert [("Devilsoundguy" in f.message, "Evilsoundguy" in f.message) for f in warned] == [(True, True)]
    assert result.errors == []


@needs_data
def test_the_pinned_request_hashes_are_the_ones_that_scored_56_of_60() -> None:
    # Proves: the SHA-256 literals pinned in test_retry_plumbing.py are the hashes of the four request texts
    # stored in a21-review2.json — the gated re-run after code review round 2, 56 of 60. This is what ties
    # the committed byte-identical test to the measured request.
    if not REVIEW2.exists():
        pytest.skip("a21-review2.json is not present")
    stored = json.loads(REVIEW2.read_text())["request"]
    for key, pinned in PINNED.items():
        assert hashlib.sha256(stored[key].encode()).hexdigest() == pinned, key


def test_the_expected_table_covers_the_labelled_capture_dates() -> None:
    # Proves: the replay uses each page's labelled capture date (what the year rule and the plausibility
    # window are relative to), and every page it names has one. Runs in CI too: labels.py is committed.
    for fixture in EXPECTED:
        assert isinstance(PAGE_LABELS[fixture].captured_on, datetime.date), fixture
