"""Tests for the results file: its labels hash, held-out flag, slim snapshot and loading (`model_eval/saved_run_reports/results_file.py`).

Milestone C5 (docs/dev/implementations/c5-pipeline-eval-harness.md, Steps 3 and 8). A run is stored in a gitignored file that holds
the venues' page text and every extraction; a slim summary of it is what gets committed. These tests pin what the file records,
what the summary keeps and drops, and that a missing run is reported clearly.

How to read it: `heavy_results` builds a results dict carrying everything a snapshot must leave out. Tests that read or write the
results and snapshot folders redirect `results_file.RESULTS_DIR` / `SNAPSHOT_DIR` to a temporary folder (they are read as module
attributes at call time, so the patch reaches the code), and never touch the real ones.
"""

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from agent_worker.model_eval.saved_run_reports import (
    aggregate_scores,
    markdown_report,
    results_file,
)
from agent_worker.tests.model_eval.test_aggregate_scores import GATED, record

# ---------------------------------------------------------------------------
# The file: labels hash, held-out
# ---------------------------------------------------------------------------


def test_the_labels_hash_changes_when_a_label_does(tmp_path: Path) -> None:
    # Proves: a results file names the labels that scored it. Two label files that differ by one character hash differently,
    # and the same text hashes the same.
    one, two = tmp_path / "one.py", tmp_path / "two.py"
    one.write_text("PAGE_LABELS = {'a': 1}")
    two.write_text("PAGE_LABELS = {'a': 2}")
    assert results_file.labels_sha(one) != results_file.labels_sha(two)
    assert results_file.labels_sha(one) == results_file.labels_sha(one)


def test_the_file_records_whether_a_held_out_page_was_scored() -> None:
    # Proves: C5-D3. The first held-out scoring is C6's, so the file says outright whether any held-out page was scored here.
    held = dataclasses.replace(GATED, held_out=True)
    assert results_file.held_out_scored(["a.html"], {"a.html": GATED}) is False
    assert results_file.held_out_scored(["a.html", "b.html"], {"a.html": GATED, "b.html": held}) is True


# ---------------------------------------------------------------------------
# Snapshots: a slim, committable summary of a run (raw results stay gitignored)
# ---------------------------------------------------------------------------


def heavy_results() -> dict[str, Any]:
    """A results dict carrying the heavy parts a snapshot must leave out: extractions, staged documents (page text) and the prompt."""
    run = record("page.html", raw={"shows": [{"date": "2026-10-20"}]})
    run["validated"] = run["committed"] = run["raw"]
    run["staged_documents"] = [{"attempt": 1, "page_text": "THE VENUE PAGE TEXT " * 500, "raw_extraction": run["raw"]}]
    return {
        "label": "demo", "started_at": "2026-11-04T17:00:00+00:00", "set": "all", "scenario": None, "labels_sha": "abc",
        "held_out_scored": False, "harness_commit": "def", "config": {"route": "auto"}, "request_options": {"model": "m"},
        "request": {"instruction": "A LONG PROMPT " * 500, "instruction_sha": "1234abcd56", "response_schema": {"big": "schema"},
                    "response_schema_sha": "9999aaaa00", "response_schema_chars": 4000},
        "policy": {"confidence_threshold": 0.8}, "provenance": {"m": {"model_digest": "d"}},
        "aggregate": aggregate_scores.aggregate([run], {"page.html": GATED}), "scenarios": [], "runs": [run],
    }


def test_a_snapshot_drops_the_page_text_extractions_and_prompt_but_keeps_the_scores() -> None:
    # Proves: a snapshot is safe and small enough to commit. It must NOT carry the venue pages' text (staged documents), the raw
    # extractions, or the full prompt (the raw results are gitignored for exactly these reasons), and must keep everything the
    # report and --compare read: the aggregate, each run's scores and attempts, the policy, the model and the prompt's hashes
    # (they identify which prompt produced the numbers).
    data = heavy_results()
    snap = results_file.slim(data)
    text = json.dumps(snap)
    assert "THE VENUE PAGE TEXT" not in text and "A LONG PROMPT" not in text and "raw_extraction" not in text
    assert len(text) < len(json.dumps(data)) / 2  # the real guarantees are the absences above; this only catches a bulky regression
    assert snap["aggregate"] == data["aggregate"] and snap["labels_sha"] == "abc"
    assert snap["request"] == {"instruction_sha": "1234abcd56", "response_schema_sha": "9999aaaa00", "response_schema_chars": 4000}
    assert snap["runs"][0]["raw_score"] == data["runs"][0]["raw_score"] and "raw" not in snap["runs"][0]
    assert snap["runs"][0]["attempts"] == data["runs"][0]["attempts"]


def test_a_snapshot_renders_a_report_and_compares_like_the_full_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves: the point of the snapshot. After the raw results are gone (a new laptop, a cleaned folder), the committed snapshot is
    # enough for `--report` and `--compare`. The report from the snapshot equals the report from the full file.
    data = heavy_results()
    snapshots = tmp_path / "snapshots"
    monkeypatch.setattr(results_file, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(results_file, "SNAPSHOT_DIR", snapshots)
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "graph-demo.json").write_text(json.dumps(data))
    out = results_file.snapshot("demo")
    assert out == snapshots / "demo.json" and out.is_file()
    (tmp_path / "results" / "graph-demo.json").unlink()  # the raw file is gone
    loaded = results_file.load_results("demo")
    assert markdown_report.render(loaded, {"page.html": GATED}) == markdown_report.render(results_file.slim(data), {"page.html": GATED})
    assert "labels_sha" in markdown_report.compare_table({"demo": loaded})


def test_load_results_prefers_the_raw_file_and_says_where_it_looked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves: a missing label gives an error naming both places it looked, instead of a bare FileNotFoundError, and a label present in
    # both places loads the full raw file (the snapshot is the fallback).
    monkeypatch.setattr(results_file, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(results_file, "SNAPSHOT_DIR", tmp_path / "snapshots")
    with pytest.raises(FileNotFoundError, match="snapshots"):
        results_file.load_results("nope")
    (tmp_path / "results").mkdir()
    (tmp_path / "snapshots").mkdir()
    (tmp_path / "results" / "graph-both.json").write_text(json.dumps({"which": "raw"}))
    (tmp_path / "snapshots" / "both.json").write_text(json.dumps({"which": "snapshot"}))
    assert results_file.load_results("both") == {"which": "raw"}


# ---------------------------------------------------------------------------
# Code review round 2 (C5-CR2-2): the file's shape is defined in one place
# ---------------------------------------------------------------------------


def test_build_record_has_the_keys_a_report_and_a_snapshot_read_and_survives_a_round_trip(tmp_path: Path) -> None:
    # Proves: the results file's shape is one function, and what it builds is plain JSON that `load_results` reads back
    # unchanged. The key list is what `markdown_report.render`, `slim` and `--compare` read; a key dropped here breaks them.
    from agent_worker.model_eval import run_eval
    from agent_worker.policy import DEFAULT_POLICY

    config, options = run_eval.configure({})[1], run_eval.configure({})[0]
    run = record("page.html", raw={"shows": []})
    built = results_file.build_record(
        label="demo", started_at="2026-11-05T00:00:00+00:00", set_name="all", scenario=None, fixture_names=["page.html"],
        page_labels={"page.html": GATED}, config=config, options=options, request={"instruction_sha": "abc"}, policy=DEFAULT_POLICY,
        provenance=None, aggregate=aggregate_scores.aggregate([run], {"page.html": GATED}), scenarios=[], runs=[run],
    )
    assert list(built) == [
        "label", "started_at", "set", "scenario", "labels_sha", "held_out_scored", "harness_commit", "config", "request_options",
        "request", "policy", "provenance", "aggregate", "scenarios", "runs",
    ]
    assert built["held_out_scored"] is False and built["policy"]["max_attempts"] == DEFAULT_POLICY.max_attempts
    out = results_file.write_results(tmp_path / "graph-demo.json", built)
    assert json.loads(out.read_text()) == json.loads(json.dumps(built, default=str))


def test_a_snapshot_keeps_the_c7_numbers_and_still_no_page_text() -> None:
    # Proves (C7, Test approach §5): the per-attempt confidences, seconds and tokens are what C7's tables read, so a committed
    # snapshot must keep them (a report from it equals one from the raw file); the page text and extractions stay out.
    data = heavy_results()
    data["runs"][0]["attempts"][0].update(
        confidence=0.9, show_confidences=[0.9], judged_indices=[0], excluded_indices=[], seconds=2.5, tokens={"prompt": 5, "completion": 1},
    )
    data["runs"][0]["tokens_after_last_attempt"] = {"prompt": 0, "completion": 0}
    snap = results_file.slim(data)
    kept = snap["runs"][0]["attempts"][0]
    assert (kept["show_confidences"], kept["tokens"], kept["seconds"]) == ([0.9], {"prompt": 5, "completion": 1}, 2.5)
    assert snap["runs"][0]["tokens_after_last_attempt"] == {"prompt": 0, "completion": 0}
    assert "THE VENUE PAGE TEXT" not in json.dumps(snap)
