"""Tests for the pure parts of the eval harness (`agent_worker/eval/run_eval.py`): how a run
is scored against the hand-written reference, how a label is aggregated, and that the
frozen pre-A2 "legacy" configuration really is the pre-A2 one.

No model is called. The scoring expectations are written by hand from `reference.py`'s
facts (e.g. "Terminal Bar's page states no times"), not read back from the code under test.
The harness is a throwaway-grade measurement tool, but A2's verdict rests on its numbers, so
the arithmetic that produces them is pinned here.

How to read it: scoring -> aggregation -> legacy configuration.
"""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agent_worker import extraction
from agent_worker.eval import run_eval
from agent_worker.eval.reference import REFERENCE, FixtureReference
from agent_worker.schemas import VenuePageExtraction

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def show(acts: list[Any], **fields: Any) -> dict[str, Any]:
    """One show as a dict, shaped like `VenuePageExtraction.model_dump()` output (acts may
    be plain strings, the pre-A2 shape, or objects)."""
    base: dict[str, Any] = {
        "venue": "The Terminal Bar", "date": "2026-08-07", "acts": acts,
        "is_ambiguous": False, "confidence": 0.9,
    }
    base.update(fields)
    return base


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def test_a_leaked_non_music_act_is_counted() -> None:
    # Proves: an act whose name contains a non-music term from the reference is a leak,
    # case-insensitively, for both act shapes (pre-A2 strings, post-A2 objects).
    ref = REFERENCE["terminal_html"]
    result = run_eval.score_extraction(
        {"shows": [show(["OPEN MIC"]), show([{"name": "Open Comedy Night"}]), show(["Envies"])]},
        ref, page_text="",
    )
    assert result["leaks"] == ["OPEN MIC", "Open Comedy Night"]


def test_a_show_with_no_acts_is_counted_as_empty() -> None:
    # Proves: `acts: []` is visible. A leaked "Karaoke" entry the model emits with no
    # artists would otherwise score as zero leaks (no act name to match), a false zero
    # on exactly the rule A2 is measuring. The baseline produced two such shows itself.
    result = run_eval.score_extraction(
        {"shows": [show([]), show(["Envies"]), show([])]}, FixtureReference(), page_text="",
    )
    assert result["empty_acts"] == 2


def test_a_leak_titled_in_the_venue_field_is_counted() -> None:
    # Proves: when a model puts the entry's title in `venue` and returns no acts, the
    # leak is still caught, not only leaks that arrive as act names.
    result = run_eval.score_extraction(
        {"shows": [show([], venue="KARAOKE NIGHT")]}, REFERENCE["zhora"], page_text="",
    )
    assert result["leaks"] == ["KARAOKE NIGHT"]


def test_invented_values_are_judged_against_what_the_page_states() -> None:
    # Proves: "invented" means the reference says the page states no such thing. Terminal
    # Bar's page states no times, so each returned `time` is invented; White Squirrel
    # states end times, so its `end_time` is not; and a price on a page with none is invented.
    shows = {"shows": [show(["A"], time="20:00:00", end_time="22:00:00", admission_day=10.0)]}
    terminal = run_eval.score_extraction(shows, REFERENCE["terminal_html"], page_text="")
    assert (terminal["invented_time"], terminal["invented_end_time"], terminal["invented_price"]) == (1, 1, 1)
    squirrel = run_eval.score_extraction(shows, REFERENCE["white_squirrel"], page_text="")
    assert squirrel["invented_end_time"] == 0
    assert squirrel["invented_time"] == 0


def test_an_image_url_not_in_the_page_text_is_invented() -> None:
    # Proves: a returned poster URL counts as invented unless it appears verbatim in the
    # page text (the cleaned text has no URLs, so in practice any URL is invented).
    result = run_eval.score_extraction(
        {"shows": [show(["A"], image_url="https://x.test/p.jpg"), show(["B"], image_url="seen.jpg")]},
        FixtureReference(), page_text="the page mentions seen.jpg here",
    )
    assert result["invented_image_urls"] == ["https://x.test/p.jpg"]


def test_aggregate_sums_empty_acts_and_leaks_over_ok_runs_only() -> None:
    # Proves: the label-level numbers count only runs that produced an extraction, and
    # carry the empty-acts total alongside leaks, so the comparison reads it.
    ref = REFERENCE["terminal_html"]
    ok = {
        "key": "terminal_html", "outcome": "ok", "attempts_used": 1, "parse_failures": 0,
        "parse_failure_fields": [], "seconds": 10.0, "shows": 2, "page_readable": True,
        "extraction": {"shows": [show([]), show(["OPEN MIC"])]},
        "score": run_eval.score_extraction({"shows": [show([]), show(["OPEN MIC"])]}, ref, ""),
    }
    failed = {
        "key": "terminal_html", "outcome": "IncompleteOutputException", "attempts_used": 0,
        "parse_failures": 0, "parse_failure_fields": [], "seconds": 70.0,
    }
    agg = run_eval.aggregate([ok, failed])
    assert (agg["runs"], agg["ok"]) == (2, 1)
    assert agg["empty_acts"] == 1
    assert agg["leaks"] == 1


# ---------------------------------------------------------------------------
# The frozen pre-A2 configuration (what `baseline` ran)
# ---------------------------------------------------------------------------


def test_the_legacy_configuration_is_the_pre_a2_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Proves: `legacy=True` sends the pre-A2 instruction ("any ticket info") and asks for
    # the pre-A2 schema (required `time`, a `ticket_info` string, bare-string acts), so the
    # `baseline` label can be re-run after the live schema and prompt have moved on —
    # which Decision #6's "re-run the baseline under a fixed context window" needs.
    page = tmp_path / "page.html"
    page.write_text("<p>Show 8pm</p>")
    captured: list[dict[str, Any]] = []

    class Completions:
        def create(self, **kwargs: Any) -> Any:
            captured.append(kwargs)
            return VenuePageExtraction(page_readable=True, shows=[])

    monkeypatch.setattr(
        run_eval, "instructor_client", SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    )
    run_eval.extract(
        page, options=extraction.PIPELINE_OPTIONS, config=extraction.PIPELINE_CONFIG, legacy=True
    )
    (call,) = captured
    assert "any ticket info" in call["messages"][0]["content"]
    schema = call["response_model"].model_json_schema()
    show_schema = schema["$defs"]["ShowExtraction"]
    assert "ticket_info" in show_schema["properties"]
    assert "time" in show_schema["required"]
    assert show_schema["properties"]["acts"]["items"] == {"type": "string"}


def test_aggregate_records_whether_a_fixtures_runs_were_identical() -> None:
    # Proves: code review #3 / plan D1 — at temperature 0 five runs may be one sample in
    # disguise, and the comparison must say so. Identical extractions -> True; any difference
    # -> False.
    def ok_run(run: int, shows: list[dict[str, Any]]) -> dict[str, Any]:
        extraction_dump = {"page_readable": True, "shows": shows}
        return {
            "fixture": "x.html", "key": "x", "run": run, "outcome": "ok", "shows": len(shows),
            "attempts_used": 1, "parse_failures": 0, "parse_failure_fields": [], "seconds": 1.0,
            "page_readable": True, "extraction": extraction_dump,
            "score": run_eval.score_extraction(extraction_dump, FixtureReference(), ""),
        }

    same = run_eval.aggregate([ok_run(0, [show(["A"])]), ok_run(1, [show(["A"])])])
    differ = run_eval.aggregate([ok_run(0, [show(["A"])]), ok_run(1, [show(["B"])])])
    assert same["per_fixture"]["x"]["runs_identical"] is True
    assert differ["per_fixture"]["x"]["runs_identical"] is False


def test_runs_identical_compares_runs_of_the_same_page_only() -> None:
    # Proves: two different pages of one venue (White Squirrel's August and October captures
    # share a reference key) are not compared with each other — each page's runs are compared
    # among themselves. The first version grouped by venue and reported False for pages whose
    # runs were in fact identical (found reading the a21-temp0-quick results).
    def ok_run(fixture: str, run: int, acts: list[str]) -> dict[str, Any]:
        extraction_dump = {"page_readable": True, "shows": [show(acts)]}
        return {
            "fixture": fixture, "key": "x", "run": run, "outcome": "ok", "shows": 1,
            "attempts_used": 1, "parse_failures": 0, "parse_failure_fields": [], "seconds": 1.0,
            "page_readable": True, "extraction": extraction_dump,
            "score": run_eval.score_extraction(extraction_dump, FixtureReference(), ""),
        }

    agg = run_eval.aggregate([ok_run("aug.html", 0, ["A"]), ok_run("aug.html", 1, ["A"]),
                              ok_run("oct.html", 0, ["B"]), ok_run("oct.html", 1, ["B"])])
    assert agg["per_fixture"]["x"]["runs_identical"] is True


def test_the_request_record_stores_every_prompt_a_label_sends() -> None:
    # Proves: code review round 2, #3 — a results file is auditable on its own: besides the page
    # model's instruction it stores the act splitter's (which carries the conventions), the
    # status question's, and the one the image route sends. Without them the prompt behind a
    # score would exist nowhere once the code changes.
    record = run_eval.request_record(extraction.PIPELINE_CONFIG, legacy=False)
    assert "numbered event titles" in record["splitter_instruction"]
    assert "cancelled or postponed" in record["status_instruction"]
    assert record["image_instruction"] == extraction.instruction_for(replace(extraction.PIPELINE_CONFIG, title_split=False))


def test_runs_identical_needs_two_runs_of_every_page() -> None:
    # Proves: code review round 2, #5 — "identical" is only claimed when each page of the venue
    # has at least two successful runs; with one run per page it is unknown (None), not True.
    def ok_run(fixture: str, run: int) -> dict[str, Any]:
        extraction_dump = {"page_readable": True, "shows": [show(["A"])]}
        return {
            "fixture": fixture, "key": "x", "run": run, "outcome": "ok", "shows": 1,
            "attempts_used": 1, "parse_failures": 0, "parse_failure_fields": [], "seconds": 1.0,
            "page_readable": True, "extraction": extraction_dump,
            "score": run_eval.score_extraction(extraction_dump, FixtureReference(), ""),
        }

    one_each = run_eval.aggregate([ok_run("aug.html", 0), ok_run("oct.html", 0)])
    assert one_each["per_fixture"]["x"]["runs_identical"] is None
