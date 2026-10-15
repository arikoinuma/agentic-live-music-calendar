"""Tests for the plumbing A3 added around extraction, fetch and the eval: retry hints, image links, fetch retries.

Milestone A3 (docs/dev/implementations/a3-validation-and-retry.md, §3 "test_extraction.py additions"; kept in
its own file so test_extraction.py, which A2.1 closed, stays untouched). None of this is a decision about
whether a page passes; it is the wiring that lets a retry change a request, and keeps a first attempt's
request exactly what scored 56 of 60.

How to read it, in order:
1. The pinned requests. Today's four request texts, as SHA-256 literals computed BEFORE any A3 code
   change and confirmed equal to the `instruction`, `splitter_instruction`, `image_instruction` and
   `status_instruction` stored in eval/results/a21-review2.json (the run that scored 56/60). A first
   attempt, with no hint, must still send exactly these. The expectation is a literal on purpose: a test
   that rebuilt it from `prompts.py` would follow a refactor of `prompts.py` instead of catching it.
2. The retry hints: each reaches the call that produces the field, and no other.
3. `clean_text` with image links (G25).
4. The status merge's `added_indices`.
5. Fetch: transient errors retried, 4xx not, an empty page is a failure, not a pass.
6. The eval's image-URL check.
"""

import datetime
import hashlib
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from tenacity import wait_none

from agent_worker import act_split, extraction, nodes, status_check
from agent_worker.eval import run_eval
from agent_worker.eval.reference import FixtureReference
from agent_worker.state import VenueGraphState
from agent_worker.tests.fakes import (
    PAGE,
    SPLITTER,
    STATUS,
    completions,
    event,
    jsonld_page,
    listing,
    listings_answer,
    message_text,
    scripted_client,
    split_answer,
    text_page,
)

FETCHED = datetime.date(2026, 10, 12)
CHICAGO = "America/Chicago"

# SHA-256 of today's request texts (see the module docstring for where they come from).
PINNED = {
    "instruction": "1c13629a64b055427496f1c6fe709ae1a5dc39c1d9455b2ff4742345e64228d7",
    "splitter_instruction": "31bbe13056781917a9473e985339b374506e20c18788cdf79d542b1dae3dc75b",
    "image_instruction": "1ebdb600f25e59257bdbfecd503f4ffea700d5b1d1009c9b3f56b073ffded58a",
    "status_instruction": "80eb31bb1a485cdb5bcdfb9a03451ef739d6e3449cdda60fe89335b1c85d4752",
}


def sha(text: str) -> str:
    """SHA-256 hex of a string."""
    return hashlib.sha256(text.encode()).hexdigest()


def run(html: str, client: Any, **config: Any) -> extraction.PageExtractionResult:
    """Call `extract_page` with the pipeline's options and the pipeline's configuration, overridden by the given switches."""
    return extraction.extract_page(
        html, venue_name="The Venue", metro_timezone=CHICAGO, fetch_date=FETCHED, client=client,
        options=extraction.PIPELINE_OPTIONS, config=replace(extraction.PIPELINE_CONFIG, **config),
    )


# ---------------------------------------------------------------------------
# 1. A first attempt sends exactly what scored 56/60
# ---------------------------------------------------------------------------


def test_the_first_attempts_page_request_is_byte_identical_to_the_measured_one() -> None:
    # Proves: with no hint, the model route's message is the pinned instruction followed by the page
    # text — nothing appended, nothing reordered. The failing state before A3 was the missing hint parameter.
    html = text_page("Nona", "Oct 20", "8 pm")
    client = scripted_client({PAGE: [listings_answer(listing("2026-10-20", "Nona"))], SPLITTER: [split_answer(("Nona", ["Nona"]))]})
    run(html, client)
    sent = message_text(completions(client).calls_for(PAGE)[0])
    text = extraction.clean_text(html, extraction.PIPELINE_CONFIG.keep_line_breaks)
    assert sent.endswith(text) and sha(sent[: -len(text)]) == PINNED["instruction"]


def test_the_first_attempts_splitter_request_is_byte_identical_to_the_measured_one() -> None:
    # Proves: the same for the act splitter, on the JSON-LD route (where it is the only model call).
    html = jsonld_page(event("Nona", "2026-10-20T21:00:00-05:00"))
    client = scripted_client({SPLITTER: [split_answer(("Nona", ["Nona"]))]})
    run(html, client)
    sent = message_text(completions(client).calls_for(SPLITTER)[0])
    assert sha(sent[: sent.index("\n0: ")]) == PINNED["splitter_instruction"]


def test_the_first_attempts_image_and_status_requests_are_byte_identical_to_the_measured_ones() -> None:
    # Proves: the poster (image) route and the status question — the other two requests a hint-plumbing
    # change could disturb — still send exactly the measured text.
    client = scripted_client({
        extraction.page_model_for(replace(extraction.PIPELINE_CONFIG, title_split=False)): [
            {"page_readable": True, "shows": []}
        ],
        STATUS: [{"items": []}],
    })
    extraction.extract_image(
        "AAAA", mime="image/png", fetch_date=FETCHED, client=client, options=extraction.PIPELINE_OPTIONS,
        config=extraction.PIPELINE_CONFIG,
    )
    content = completions(client).calls[0]["messages"][0]["content"]
    assert sha(content[0]["text"]) == PINNED["image_instruction"]
    status_check.ask("Some page text", client=client, options=extraction.PIPELINE_OPTIONS)
    sent = message_text(completions(client).calls_for(STATUS)[0])
    assert sha(sent[: -len("Some page text")]) == PINNED["status_instruction"]


# ---------------------------------------------------------------------------
# 2. The hints reach the call that produces the field
# ---------------------------------------------------------------------------

HINTED = {"retry_hint": "- show 0 is dated 2026-03-01", "splitter_hint": ""}


def model_route(**config: Any) -> Any:
    """Run the model route over a small text page with the given configuration overrides; return the scripted client so a test can read what was sent."""
    html = text_page("Nona", "Oct 20", "8 pm")
    client = scripted_client({PAGE: [listings_answer(listing("2026-10-20", "Nona"))], SPLITTER: [split_answer(("Nona", ["Nona"]))]})
    run(html, client, **config)
    return client


def test_a_page_hint_reaches_the_page_instruction_and_nothing_else() -> None:
    # Proves (round 1 #5): a date problem's hint is appended to the page model's instruction, and the act
    # splitter's request is byte-identical to the unhinted one — a date sentence can't perturb the call
    # A2.1 found most sensitive.
    plain, hinted = model_route(), model_route(**HINTED)
    assert "2026-03-01" in message_text(completions(hinted).calls_for(PAGE)[0])
    assert message_text(completions(hinted).calls_for(SPLITTER)[0]) == message_text(completions(plain).calls_for(SPLITTER)[0])


def test_a_splitter_hint_reaches_the_splitters_instruction_and_nothing_else() -> None:
    # Proves (round 1 #5): the reverse.
    plain = model_route()
    hinted = model_route(splitter_hint="- return every id")
    assert "return every id" in message_text(completions(hinted).calls_for(SPLITTER)[0])
    assert message_text(completions(hinted).calls_for(PAGE)[0]) == message_text(completions(plain).calls_for(PAGE)[0])


def test_the_splitter_hint_reaches_the_json_ld_route_where_it_is_the_only_model_call() -> None:
    # Proves: the JSON-LD route has no page model call, so the splitter hint is the retry's only lever
    # there; `_from_jsonld` must carry it.
    html = jsonld_page(event("Nona", "2026-10-20T21:00:00-05:00"))
    client = scripted_client({SPLITTER: [split_answer(("Nona", ["Nona"]))]})
    run(html, client, splitter_hint="- return every id")
    assert "return every id" in message_text(completions(client).calls_for(SPLITTER)[0])


def test_the_splitter_hint_reaches_the_status_merges_own_splitter_call() -> None:
    # Proves (round 2 #11): the status merge calls `split_titles` a third time (to split the acts of a
    # cancelled listing the main extraction skipped); it gets the same hint, and the shows it adds are
    # recorded in `notes["added_indices"]` for validation to leave out of the confidence.
    html = text_page("Ghost Band Oct 20 CANCELLED")
    client = scripted_client({
        PAGE: [listings_answer()],  # the page model found nothing
        STATUS: [{"items": [{"date": "2026-10-20", "acts": ["Ghost Band"], "status": "cancelled"}]}],
        SPLITTER: [split_answer(("Ghost Band", ["Ghost Band"]))],
    })
    result = run(html, client, splitter_hint="- return every id")
    assert "return every id" in message_text(completions(client).calls_for(SPLITTER)[0])
    assert result.notes["added_indices"] == [0] and len(result.extraction.shows) == 1


def test_no_shows_added_by_the_merge_means_an_empty_added_list() -> None:
    # Proves: `added_indices` is [] (not missing) when the status question found nothing to add.
    result = run(text_page("Nona", "Oct 20"), scripted_client({
        PAGE: [listings_answer(listing("2026-10-20", "Nona"))], SPLITTER: [split_answer(("Nona", ["Nona"]))],
    }))
    assert result.notes["added_indices"] == []


def test_a_hinted_page_request_keeps_the_blank_line_before_the_page_text() -> None:
    # Proves (code review round 1, #5b): the unhinted instruction ends with a blank line before the page
    # text; the hinted one must keep it, or the last hint line runs into the page's first line.
    hinted = message_text(completions(model_route(**HINTED)).calls_for(PAGE)[0])
    text = extraction.clean_text(text_page("Nona", "Oct 20", "8 pm"), True)
    assert hinted.endswith("\n\n" + text)


def test_a_request_with_no_hint_adds_no_hint_text() -> None:
    # Proves: the hint introduction text appears only when there is a hint.
    sent = message_text(completions(model_route()).calls_for(PAGE)[0])
    assert "earlier attempt" not in sent


# ---------------------------------------------------------------------------
# 3. Image links in cleaned text (G25)
# ---------------------------------------------------------------------------


def test_image_urls_stay_in_the_cleaned_text_where_the_image_sat_when_asked() -> None:
    # Proves (G25): an <img src> becomes a "[image: URL]" line at its position, so the model has the URL
    # as text to copy. Before A3 `image_url` was null in practice on every text page.
    html = '<p>Nona</p><img src="https://v.example/uploads/nona.png"><p>8 pm</p>'
    text = extraction.clean_text(html, keep_line_breaks=True, keep_image_urls=True)
    assert text.split("\n") == ["Nona", "[image: https://v.example/uploads/nona.png]", "8 pm"]


def test_the_default_cleaning_is_unchanged() -> None:
    # Proves: with the switch off (the default) the cleaned text is what it was — the property the 56/60
    # score depends on (A3-D12).
    html = '<p>Nona</p><img src="https://v.example/nona.png"><p>8 pm</p>'
    assert extraction.clean_text(html, keep_line_breaks=True) == "Nona\n8 pm"
    assert extraction.clean_text(html, keep_line_breaks=False) == "Nona 8 pm"


def test_a_lazy_loaded_image_uses_its_data_src() -> None:
    # Proves: WordPress-style lazy loading puts a `data:` placeholder in `src` and the real address in
    # `data-src`; the real one is kept.
    html = '<img src="data:image/gif;base64,R0lG" data-src="https://v.example/real.jpg">'
    assert extraction.clean_text(html, False, True) == "[image: https://v.example/real.jpg]"
    only_data_src = '<img data-src="https://v.example/real.jpg">'
    assert extraction.clean_text(only_data_src, False, True) == "[image: https://v.example/real.jpg]"


def test_an_image_with_no_usable_source_adds_nothing() -> None:
    # Proves: a data: URI (an inline placeholder or icon) and an <img> with no source are skipped,
    # never turned into "[image: data:...]" noise that costs tokens on every page.
    html = '<p>Nona</p><img src="data:image/png;base64,AAAA"><img alt="logo">'
    assert extraction.clean_text(html, True, True) == "Nona"


def test_an_entity_in_an_image_address_is_unescaped_like_the_page_parser_does() -> None:
    # Proves: the URL in the text is the parsed attribute (`&`), which is what validation checks it
    # against (verify_image_url unescapes the HTML for the same reason).
    html = '<img src="https://v.example/p.jpg?a=1&amp;b=2">'
    assert extraction.clean_text(html, False, True) == "[image: https://v.example/p.jpg?a=1&b=2]"


def test_the_model_route_sends_image_links_only_when_the_switch_is_on() -> None:
    # Proves: `ExtractionConfig.keep_image_urls` reaches what the model reads (and defaults off).
    html = '<html><body><p>Nona Oct 20</p><img src="https://v.example/nona.png"></body></html>'
    assert extraction.ExtractionConfig().keep_image_urls is False and extraction.PIPELINE_CONFIG.keep_image_urls is False
    for on in (False, True):
        client = scripted_client({PAGE: [listings_answer()], STATUS: [{"items": []}]})
        run(html, client, keep_image_urls=on)
        assert ("[image: https://v.example/nona.png]" in message_text(completions(client).calls_for(PAGE)[0])) is on


# ---------------------------------------------------------------------------
# 5. Fetch: what is retried, what is not, and an empty page
# ---------------------------------------------------------------------------

URL = "https://venue.example/calendar"
OK_HTML = "<html><body><p>Nona Oct 20 8 pm</p></body></html>"


class FakeGet:
    """Stands in for `httpx.get`: answers from a list of outcomes (an Exception is raised, a
    (status, body) pair becomes a response) and counts the calls."""

    def __init__(self, *outcomes: Exception | tuple[int, str]) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    def __call__(self, url: str, **_: Any) -> httpx.Response:
        outcome = self.outcomes[min(self.calls, len(self.outcomes) - 1)]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        status, body = outcome
        return httpx.Response(status, text=body, request=httpx.Request("GET", url))


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make tenacity's backoff instant so the retry tests don't sleep (the wait is not what is tested)."""
    monkeypatch.setattr(nodes.fetch_html.retry, "wait", wait_none())


def fetch(monkeypatch: pytest.MonkeyPatch, get: FakeGet) -> VenueGraphState:
    """Run `fetch_node` for a URL with `httpx.get` replaced by `get`; return the state it produced."""
    monkeypatch.setattr(nodes.httpx, "get", get)
    return nodes.fetch_node(VenueGraphState(
        venue_id=1, calendar_url=URL, venue_name="V", metro_timezone=CHICAGO, fetched_on=FETCHED,
    ))


def test_three_server_errors_are_three_calls_then_a_recorded_fetch_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (A3-D6): a 5xx is transient — retried with backoff, three attempts in all (arch-initial.md §7) —
    # and the failure that survives is recorded in `fetch_error`, not raised out of the graph.
    get = FakeGet((503, "unavailable"))
    state = fetch(monkeypatch, get)
    assert get.calls == 3 and "HTTPStatusError" in (state.fetch_error or "")


def test_a_connection_error_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves: a network failure is transient: two ConnectErrors, then the page arrives.
    get = FakeGet(httpx.ConnectError("refused"), httpx.ConnectError("refused"), (200, OK_HTML))
    state = fetch(monkeypatch, get)
    assert get.calls == 3 and state.fetch_error is None and state.page_html == OK_HTML


def test_a_404_is_one_call_then_a_recorded_fetch_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves: a 4xx is the venue's answer, not a glitch — retrying a gone page three times only delays
    # the escalation. Patching `fetch_html` would have bypassed tenacity; this patches `httpx.get`.
    get = FakeGet((404, "not found"))
    state = fetch(monkeypatch, get)
    assert get.calls == 1 and "404" in (state.fetch_error or "")


def test_a_server_error_then_a_page_is_a_page(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves: a transient 503 followed by a good response is just a page: the retry hands back the good one
    # with no error recorded (the recovery path of the 5xx retry).
    get = FakeGet((503, "busy"), (200, OK_HTML))
    state = fetch(monkeypatch, get)
    assert get.calls == 2 and state.fetch_error is None and state.page_content


def test_an_empty_body_is_retried_and_then_a_fetch_error_not_a_page(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (round 1 #3, round 2 #8): arch-initial.md §7 counts an empty response as a fetch failure that
    # is retried with backoff; one that survives is recorded, never handed to a model.
    get = FakeGet((200, "<html><body></body></html>"))
    state = fetch(monkeypatch, get)
    assert get.calls == 3 and "nothing to read" in (state.fetch_error or "")


def test_a_page_with_no_visible_text_but_json_ld_events_is_not_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (round 2 #8c): a script shell whose events live in JSON-LD is something the JSON-LD route can
    # serve, so it must not be rejected as an empty response.
    shell = jsonld_page(event("Nona", "2026-10-20T21:00:00-05:00"), body="")
    state = fetch(monkeypatch, FakeGet((200, shell)))
    assert state.fetch_error is None and state.page_html == shell


def test_an_empty_local_text_file_is_a_fetch_error_after_one_attempt(tmp_path: Path) -> None:
    # Proves: the empty rule covers a local text page too (round 2 #8a), without retrying a file.
    path = tmp_path / "empty.html"
    path.write_text("<html></html>")
    state = nodes.fetch_node(VenueGraphState(
        venue_id=1, calendar_url=str(path), venue_name="V", metro_timezone=CHICAGO, fetched_on=FETCHED,
    ))
    assert "nothing to read" in (state.fetch_error or "")


def test_a_missing_local_file_is_a_fetch_error(tmp_path: Path) -> None:
    # Proves: a calendar_url that is a path that doesn't exist reads the same as a bad URL: a recorded fetch
    # error (FileNotFoundError), not a crash out of the graph.
    state = nodes.fetch_node(VenueGraphState(
        venue_id=1, calendar_url=str(tmp_path / "gone.html"), venue_name="V", metro_timezone=CHICAGO,
        fetched_on=FETCHED,
    ))
    assert "FileNotFoundError" in (state.fetch_error or "")


def test_a_good_fetch_clears_an_earlier_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves: `fetch_error` is reset on every call (LangGraph keeps a field's old value otherwise).
    monkeypatch.setattr(nodes.httpx, "get", FakeGet((200, OK_HTML)))
    state = nodes.fetch_node(VenueGraphState(
        venue_id=1, calendar_url=URL, venue_name="V", metro_timezone=CHICAGO, fetched_on=FETCHED,
        fetch_error="an old error",
    ))
    assert state.fetch_error is None


def test_the_capture_script_still_gets_an_empty_page_it_asked_for(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves: `reject_empty` is off by default, so eval/capture.py (which saves what a venue serves)
    # isn't turned into a different tool by the pipeline's empty-page rule.
    monkeypatch.setattr(nodes.httpx, "get", FakeGet((200, "<html></html>")))
    assert nodes.fetch_html(URL) == "<html></html>"


# ---------------------------------------------------------------------------
# 6. The eval's image-URL check
# ---------------------------------------------------------------------------


def _extraction_dump(*urls: str) -> dict[str, Any]:
    """A one-listing-per-URL extraction as the eval's JSON dump has it, for `score_extraction`."""
    return {"shows": [{"venue": "V", "date": "2026-10-20", "acts": [{"name": "A"}], "image_url": u} for u in urls]}


def test_the_eval_does_not_count_a_json_ld_url_as_invented() -> None:
    # Proves (round 1 #11): a21-confirm reported 225 "invented" image URLs, every one a JSON-LD show
    # checked against cleaned text that can't contain them. The check is source-aware.
    score = run_eval.score_extraction(
        _extraction_dump("https://v.example/a.png"), FixtureReference(), page_text="Nona", source="jsonld",
    )
    assert score["invented_image_urls"] == []


def test_the_eval_counts_a_model_route_url_the_page_does_not_contain() -> None:
    # Proves: a model-route URL absent from both the text and the unescaped HTML is invented; one present in
    # the HTML with an escaped ampersand, or in the text as an "[image: …]" line, is not.
    html = '<img src="https://v.example/real.png?a=1&amp;b=2">'
    score = run_eval.score_extraction(
        _extraction_dump("https://v.example/real.png?a=1&b=2", "https://v.example/made-up.png", "https://v.example/in-text.png"),
        FixtureReference(), page_text="[image: https://v.example/in-text.png]", source="model", page_html=html,
    )
    assert score["invented_image_urls"] == ["https://v.example/made-up.png"]


def test_the_eval_scoring_without_a_source_keeps_checking_as_before() -> None:
    # Proves: existing callers (no `source`, no HTML) still get the cleaned-text check, so older tests and
    # old result files stay comparable.
    score = run_eval.score_extraction(_extraction_dump("https://v.example/x.png"), FixtureReference(), page_text="")
    assert score["invented_image_urls"] == ["https://v.example/x.png"]


def test_the_image_urls_flag_is_an_override_of_the_pipeline_config() -> None:
    # Proves (G25 rung a3-image-urls): `--image-urls` flips exactly one field, and no flag leaves the pipeline's own.
    parser = run_eval.argparse.ArgumentParser()
    run_eval.add_override_flags(parser)
    on = run_eval.overrides_from(parser.parse_args(["--image-urls"]))
    assert run_eval.configure(on)[1] == replace(extraction.PIPELINE_CONFIG, keep_image_urls=True)
    assert run_eval.configure({})[1] == extraction.PIPELINE_CONFIG


def test_act_split_hint_is_empty_by_default() -> None:
    # Proves: `split_titles`' hint parameter defaults to nothing, so every existing caller is unchanged.
    client = scripted_client({SPLITTER: [split_answer(("Nona", ["Nona"]))]})
    act_split.split_titles(["Nona"], client=client, options=extraction.PIPELINE_OPTIONS)
    assert "earlier attempt" not in message_text(completions(client).calls[0])
