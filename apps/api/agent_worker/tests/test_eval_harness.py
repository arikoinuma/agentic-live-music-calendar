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
    # which A2-D6's "re-run the baseline under a fixed context window" needs.
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
    # Proves: A2.1-CR1-3 / plan A2.1-D1 — at temperature 0 five runs may be one sample in
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
    # Proves: A2.1-CR2-3 — a results file is auditable on its own: besides the page
    # model's instruction it stores the act splitter's (which carries the conventions), the
    # status question's, and the one the image route sends. Without them the prompt behind a
    # score would exist nowhere once the code changes.
    record = run_eval.request_record(extraction.PIPELINE_CONFIG, legacy=False)
    assert "numbered event titles" in record["splitter_instruction"]
    assert "cancelled or postponed" in record["status_instruction"]
    assert record["image_instruction"] == extraction.instruction_for(replace(extraction.PIPELINE_CONFIG, title_split=False))


def test_runs_identical_needs_two_runs_of_every_page() -> None:
    # Proves: A2.1-CR2-5 — "identical" is only claimed when each page of the venue
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


# ---------------------------------------------------------------------------
# C6: one client factory, hosted provenance, per-run counters, role overrides, the labels sha
# ---------------------------------------------------------------------------


def test_the_harness_client_is_built_the_way_the_pipelines_is() -> None:
    # Proves (C6 plan, Risks): the eval no longer builds its own Ollama client. It is made by the same factory
    # as the pipeline's (`llm.build_clients`) from the same settings, so a hosted parity run cannot silently
    # use Ollama while the pipeline uses DeepInfra.
    # Both URLs are the default under default settings, so equality alone could not tell the old hard-coded
    # client from the factory's (C6-CR1-2). The factory identity and the absence of a direct `OpenAI` import can.
    from agent_worker import llm

    assert run_eval.build_clients is llm.build_clients
    assert not hasattr(run_eval, "OpenAI")
    assert str(run_eval.client.base_url) == str(llm.client.base_url)


def test_hosted_provenance_makes_no_request_to_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (C6 plan, Test 3): `model_provenance` asked Ollama's /api endpoints on localhost:11434, which a
    # hosted run has no use for (it would fail, or describe a different model). Under a hosted provider it
    # makes no request and records provider, host and the requested model instead.
    import httpx

    def fail(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("provenance must not call Ollama's API under a hosted provider")

    monkeypatch.setattr(httpx, "get", fail)
    options = replace(extraction.PIPELINE_OPTIONS, model="vendor/some-model", provider="openai_compatible")
    provenance = run_eval.model_provenance(options, "https://api.example.test/v1/openai")
    assert provenance["provider"] == "openai_compatible"
    assert provenance["base_url_host"] == "api.example.test" and provenance["model"] == "vendor/some-model"


def test_counters_are_per_run_so_concurrent_runs_cannot_mix_them() -> None:
    # Proves (C6-PR1-6): parse errors and token usage are counted per run, not in module-level lists that
    # `run_once` clears. Two runs on two threads each see only their own counts, which Step 11's parallel
    # throughput measurement depends on.
    import threading

    results: dict[str, tuple[int, int | None]] = {}
    barrier = threading.Barrier(2)

    def one_run(name: str, errors: int, tokens: int) -> None:
        counters = run_eval.new_counters()
        barrier.wait()  # both runs are inside their run at the same moment
        for _ in range(errors):
            run_eval._record_parse_error(ValueError("x"))
        run_eval._record_completion(SimpleNamespace(usage=SimpleNamespace(prompt_tokens=tokens, completion_tokens=1)))
        barrier.wait()
        results[name] = (len(counters.parse_errors), (counters.tokens_record() or {}).get("prompt"))

    threads = [threading.Thread(target=one_run, args=("a", 2, 100)), threading.Thread(target=one_run, args=("b", 5, 700))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == {"a": (2, 100), "b": (5, 700)}


def test_a_completion_without_usage_records_none_not_zero() -> None:
    # Proves (C6 plan, Test 3): a provider that returns no `usage` must read as unknown cost, never as 0 tokens.
    counters = run_eval.new_counters()
    run_eval._record_completion(SimpleNamespace(usage=None))
    assert counters.tokens_record() is None


def test_usage_is_summed_over_every_call_in_the_run() -> None:
    # Proves (C6 plan, Test 3): a run's tokens are the sum over its page, splitter and status calls.
    counters = run_eval.new_counters()
    for prompt, completion in ((100, 10), (50, 5), (20, 2)):
        run_eval._record_completion(SimpleNamespace(usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion)))
    assert counters.tokens_record() == {"prompt": 170, "completion": 17}


def test_role_overrides_change_only_the_role_they_name_and_are_recorded() -> None:
    # Proves (C6 plan, Step 9): `--splitter-model` changes the splitter's model and nothing else, so a rung's
    # change is attributable to the splitter; no flag leaves the pipeline's own roles.
    overrides = run_eval.parse_overrides(["--splitter-model", "big-model"])
    assert overrides == {"splitter_model": "big-model"}
    roles = run_eval.configure_roles(overrides)
    base = extraction.PIPELINE_ROLES
    assert roles.splitter.model == "big-model"
    assert (roles.page, roles.status, roles.matcher) == (base.page, base.status, base.matcher)
    assert run_eval.configure_roles({}) == base
    assert run_eval.configure_roles(run_eval.parse_overrides(["--model", "m2"])).page.model == "m2"


def test_the_labels_sha_is_the_sha_of_the_labels_file() -> None:
    # Proves (C6-D8): a results file records which labels it was scored against, so a held-out score can be
    # shown to postdate its labels. The expected value is computed here from the file, not by the harness.
    import hashlib

    from agent_worker.eval import labels

    expected = hashlib.sha256(Path(labels.__file__).read_bytes()).hexdigest()
    assert run_eval.labels_sha() == expected


def test_run_once_sends_the_splitter_its_roles_model(tmp_path: Path) -> None:
    # Proves (C6-CR1-1): the harness passes the roles it was configured with into the extraction, so a
    # `--splitter-model` rung really changes the model that splits the acts. Without this wiring every rung
    # would silently measure the page model. The fixture is named after a labelled page so `run_once` finds its
    # venue facts; its content is only a listing the scripted answers match.
    from agent_worker.tests.fakes import (
        PAGE,
        SPLITTER,
        STATUS,
        completions,
        listing,
        listings_answer,
        scripted_client,
        split_answer,
        text_page,
    )

    name = next(n for n in run_eval.PAGE_LABELS if n.endswith(".html"))
    fixture = tmp_path / name
    fixture.write_text(text_page("Nona", "Oct 20"))
    client = scripted_client({
        PAGE: [listings_answer(listing("2026-10-20", "Nona"))], SPLITTER: [split_answer(("Nona", ["Nona"]))],
        STATUS: [{"items": []}],
    })
    base = extraction.PIPELINE_ROLES
    roles = replace(base, splitter=replace(base.splitter, model="split-m"))
    original = run_eval.instructor_client
    run_eval.instructor_client = client
    try:
        record = run_eval.run_once(fixture, 0, base.page, extraction.PIPELINE_CONFIG, roles=roles)
    finally:
        run_eval.instructor_client = original
    assert record["outcome"] == "ok"
    assert [c["model"] for c in completions(client).calls_for(SPLITTER)] == ["split-m"]


def test_both_counting_hooks_are_registered_on_the_harness_client() -> None:
    # Proves (C6-CR1-8): `register_hooks` attaches the parse-error and the completion hook. Deleting either would
    # leave every test green and every results file with no retry counts, or `tokens: null`.
    registered: list[str] = []
    run_eval.register_hooks(SimpleNamespace(on=lambda name, handler: registered.append(name)))
    assert sorted(registered) == ["completion:response", "parse:error"]
    assert run_eval.register_hooks is not None
