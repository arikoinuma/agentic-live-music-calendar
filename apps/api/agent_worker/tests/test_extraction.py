"""Tests for the one extraction entry point (`agent_worker/extraction.py`) and its wiring.

A2.1 adds a routing decision (JSON-LD first, the model as fallback — A2.1-D4), a second model
call (the act splitter) and the experiment switches (`ExtractionConfig`). A2's lesson was that
the pipeline and the eval drift apart when each builds its own request, so both now call
`extract_page`, and these tests prove (a) the route is chosen correctly, (b) every switch
reaches what is actually *sent*, and (c) the pipeline and the harness send the same thing.

How to read it: a fake client stands in for `instructor` (no model is called) -> routing
(A2.1-K3) -> the JSON-LD route's output -> the switches, checked against the sent
request -> the year rule -> pipeline/harness wiring -> fetch_node. HTML snippets are written
here in the fixtures' shapes; the fixtures themselves are never read.
"""

import base64
import datetime
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agent_worker import act_split, extraction, nodes, prompts, schemas, status_check
from agent_worker.eval import run_eval
from agent_worker.state import VenueGraphState

CHICAGO = "America/Chicago"
FETCHED = datetime.date(2026, 10, 10)
# The full-page "shows" route as it was before title split was adopted: several tests exercise its
# mechanics (year rule, status merge, switches) and say so explicitly rather than depend on defaults.
SHOWS_ROUTE = {"title_split": False, "keep_line_breaks": False, "act_conventions": False}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeCompletions:
    """Stands in for `client.chat.completions`. Records every `create(...)` call and answers
    by response model: the act splitter's model gets `split_answer`, the status question's gets
    `status_answer`; anything else (the full-page extraction) gets `page_shows` wrapped in
    whatever page model was requested, so a test sees exactly the schema the code asked for."""

    def __init__(self, page_shows: list[dict[str, Any]] | None = None,
                 split_answer: act_split.ActSplitAnswer | None = None,
                 status_answer: status_check.StatusAnswer | None = None,
                 listings: list[dict[str, Any]] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.page_shows = page_shows or []
        self.listings = listings or []
        self.split_answer = split_answer or act_split.ActSplitAnswer(items=[])
        self.status_answer = status_answer or status_check.StatusAnswer(items=[])

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        model = kwargs["response_model"]
        if model is act_split.ActSplitAnswer:
            return self.split_answer
        if model is status_check.StatusAnswer:
            return self.status_answer
        if model is schemas.VenueListingsExtraction:
            return model.model_validate({"page_readable": True, "listings": self.listings})
        return model.model_validate({"page_readable": True, "shows": self.page_shows})


def fake_client(**kwargs: Any) -> SimpleNamespace:
    """A stand-in for an `instructor` client exposing only `.chat.completions.create`."""
    return SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions(**kwargs)))


def sent_content(client: SimpleNamespace, index: int = 0) -> str:
    """The text message of the `index`-th call the code under test made."""
    content = client.chat.completions.calls[index]["messages"][0]["content"]
    assert isinstance(content, str)
    return content


def run(html: str, client: SimpleNamespace, **config: Any) -> extraction.PageExtractionResult:
    """Call `extract_page` with the pipeline's options and the given config switches."""
    return extraction.extract_page(
        html, venue_name="The White Squirrel Bar", metro_timezone=CHICAGO, fetch_date=FETCHED,
        client=client, options=extraction.PIPELINE_OPTIONS,
        config=replace(extraction.PIPELINE_CONFIG, **config),
    )


def jsonld_page(*events: dict[str, Any]) -> str:
    """A page carrying the given events as one ld+json list block, like White Squirrel's."""
    block = json.dumps([{"@type": "WebSite", "name": "Site"}, *events])
    return f'<html><head><script type="application/ld+json">{block}</script></head><body>Listings</body></html>'


def ws_event(name: str, start: str, **extra: Any) -> dict[str, Any]:
    """A White Squirrel-shaped schema.org Event."""
    return {"@type": "Event", "name": name, "startDate": start, **extra}


def model_show(day: int, *acts: str, year: int = 2026) -> dict[str, Any]:
    """One show as the fake model returns it on the model route."""
    return {
        "venue": "Terminal Bar", "date": datetime.date(year, 10, day).isoformat(),
        "acts": [{"name": a} for a in acts], "is_ambiguous": False, "confidence": 0.9,
    }


# ---------------------------------------------------------------------------
# Routing (A2.1-K3)
# ---------------------------------------------------------------------------


def test_a_page_with_dated_events_takes_the_json_ld_route() -> None:
    # Proves: deterministic first. With usable JSON-LD the only model call is the act
    # splitter's — no full-page extraction is requested.
    html = jsonld_page(ws_event("Nona", "2026-08-17T21:00:00-05:00"))
    client = fake_client(split_answer=act_split.ActSplitAnswer(items=[
        act_split.ActSplitItem(id=0, title="Nona", acts=["Nona"]),
    ]))
    result = run(html, client, route="auto")
    assert result.source == "jsonld"
    assert [c["response_model"] for c in client.chat.completions.calls] == [act_split.ActSplitAnswer]


def test_a_page_with_only_non_event_json_ld_takes_the_model_route() -> None:
    # Proves: "has JSON-LD" is not "has events". Every page carries some JSON-LD (WebSite,
    # Restaurant); routing on that would send Terminal Bar down a route that returns nothing.
    html = jsonld_page()  # only the WebSite block
    client = fake_client(page_shows=[model_show(2, "Griffin", "Alec C")])
    result = run(html, client, route="auto", **SHOWS_ROUTE)
    assert result.source == "model"
    assert len(result.extraction.shows) == 1


def test_events_without_a_start_date_are_not_usable() -> None:
    # Proves: an Event that can't produce a show (no startDate) doesn't count; the page
    # falls back to the model route.
    html = jsonld_page({"@type": "Event", "name": "Undated"})
    result = run(html, fake_client(), route="auto")
    assert result.source == "model"


def test_route_model_ignores_json_ld() -> None:
    # Proves: the ladder's switch works (A2.1-PR1-3) — `route="model"` measures the model
    # route even on a page that has usable JSON-LD, and no splitter call is made.
    html = jsonld_page(ws_event("Nona", "2026-08-17T21:00:00-05:00"))
    client = fake_client()
    result = run(html, client, route="model", **SHOWS_ROUTE)
    assert result.source == "model"
    assert act_split.ActSplitAnswer not in [c["response_model"] for c in client.chat.completions.calls]


# ---------------------------------------------------------------------------
# The JSON-LD route's output
# ---------------------------------------------------------------------------


def test_the_json_ld_route_builds_shows_from_events_and_the_splitter() -> None:
    # Proves: dates and times come from JSON-LD (converted into the metro's zone), acts from
    # the splitter, the venue from the caller; a title the splitter gave no acts (a non-music
    # entry) is kept with `acts: []` for A3 to drop, and noted; a cancelled event keeps its
    # status (A2.1-D12). `confidence` 1.0 is a recorded placeholder (A2.1-PR1-15).
    html = jsonld_page(
        ws_event("Lent w. Gills", "2026-08-20T21:00:00-05:00"),
        ws_event("Open Jam", "2026-08-21T23:00:00Z"),
        ws_event("Nona", "2026-08-22T18:00:00-05:00", eventStatus="https://schema.org/EventCancelled"),
    )
    client = fake_client(split_answer=act_split.ActSplitAnswer(items=[
        act_split.ActSplitItem(id=0, title="Lent w. Gills", acts=["Lent", "Gills"]),
        act_split.ActSplitItem(id=1, title="Open Jam", acts=[]),
        act_split.ActSplitItem(id=2, title="Nona", acts=["Nona"]),
    ]))
    result = run(html, client, route="auto")
    shows = result.extraction.shows
    assert [s.date for s in shows] == [datetime.date(2026, 8, d) for d in (20, 21, 22)]
    assert shows[1].time == datetime.time(18, 0)  # 23:00Z in August is 18:00 CDT
    assert [[a.name for a in s.acts] for s in shows] == [["Lent", "Gills"], [], ["Nona"]]
    assert {s.venue for s in shows} == {"The White Squirrel Bar"}
    assert [s.status for s in shows] == ["scheduled", "scheduled", "cancelled"]  # type: ignore[attr-defined]
    assert {s.confidence for s in shows} == {1.0}
    assert result.notes["no_acts"] == ["Open Jam"]


# ---------------------------------------------------------------------------
# Switches reach what is sent (A2.1-PR1-1, A2.1-PR1-3; A2.1-PR2-4)
# ---------------------------------------------------------------------------

BR_PAGE = "<h2>Friday August 28th<br/>Man Down<br/>Justin Payne / Larrkins</h2>"


def test_clean_text_keeps_line_breaks_only_when_asked() -> None:
    # Proves: the line-break rung changes exactly what it says. Terminal Bar marks each act
    # with <br>; the flat form (today's) erases that boundary.
    assert extraction.clean_text(BR_PAGE, keep_line_breaks=False) == "Friday August 28th Man Down Justin Payne / Larrkins"
    assert extraction.clean_text(BR_PAGE, keep_line_breaks=True) == "Friday August 28th\nMan Down\nJustin Payne / Larrkins"


def test_every_switch_reaches_the_sent_request() -> None:
    # Proves: each switch changes the request actually sent through `extract_page`, not
    # just a helper (A2.1-PR2-4): line breaks in the page text, the status field in the
    # response schema and its sentence in the instruction, the conventions text, and the
    # split-acts description in the schema. And each is off by default (today's behaviour).
    def sent(**config: Any) -> tuple[str, str]:
        client = fake_client()
        run(BR_PAGE, client, **{**SHOWS_ROUTE, **config})
        call = client.chat.completions.calls[0]
        return call["messages"][0]["content"], json.dumps(call["response_model"].model_json_schema())

    text, schema = sent()
    assert "Man Down Justin Payne" in text
    assert '"status"' not in schema
    assert "cancelled" not in text.lower()

    assert "Man Down\nJustin Payne" in sent(keep_line_breaks=True)[0]
    status_text, status_schema = sent(status_field=True)
    assert '"status"' in status_schema and "cancelled" in status_text.lower()
    assert "tour" in sent(act_conventions=True)[0].lower()
    assert "separate" in sent(acts_split_description=True)[1].lower()


def test_old_rules_survive_the_move() -> None:
    # Proves: `include_new_rules=False` (A2's `schema-only` instruction) still omits the two
    # A2 rules through the new entry point (A2.1-PR1-16).
    client = fake_client()
    run("<p>x</p>", client, include_new_rules=False)
    assert "karaoke" not in sent_content(client).lower()


def test_temperature_and_seed_are_top_level_arguments() -> None:
    # Proves: like `seed`, a temperature must be a top-level argument — Ollama's /v1 ignores
    # `options` (docs/dev/notes.md) — and that None sends no temperature at all (the model's
    # own default, which every A2 label ran at).
    client = fake_client()
    extraction.extract_page(
        "<p>x</p>", venue_name="V", metro_timezone=CHICAGO, fetch_date=FETCHED, client=client,
        options=replace(extraction.PIPELINE_OPTIONS, temperature=None),
        config=extraction.PIPELINE_CONFIG, seed=3,
    )
    call = client.chat.completions.calls[0]
    assert "temperature" not in call
    assert call["seed"] == 3
    assert call["extra_body"] == {"options": {"num_ctx": 32768}}


def test_the_pipeline_runs_at_temperature_zero() -> None:
    # Proves: A2.1-D8 as adopted by Ari (October 10, 2026, after a21-temp0-quick): the pipeline sends
    # temperature 0. It scored about the same as the model's default of 1 and made 5 of 6 pages
    # byte-identical run to run — a calendar re-extracted daily must not flicker between answers.
    plain = fake_client()
    run("<p>x</p>", plain)
    assert plain.chat.completions.calls[0]["temperature"] == 0.0


# ---------------------------------------------------------------------------
# The year rule (A2.1-D13)
# ---------------------------------------------------------------------------


def test_the_year_rule_rewrites_model_route_years_only_when_on() -> None:
    # Proves: the A2.1-D13 rung changes exactly one thing. Mortimer's states no year and the model
    # guessed 2024; with the rule on, the fetch date decides.
    on = run("<p>x</p>", fake_client(page_shows=[model_show(31, "Band", year=2024)]), year_rule=True, **SHOWS_ROUTE)
    off = run("<p>x</p>", fake_client(page_shows=[model_show(31, "Band", year=2024)]), year_rule=False, **SHOWS_ROUTE)
    assert on.extraction.shows[0].date == datetime.date(2026, 10, 31)
    assert off.extraction.shows[0].date == datetime.date(2024, 10, 31)


# ---------------------------------------------------------------------------
# Pipeline and harness send the same thing (A2's wiring guarantee, extended)
# ---------------------------------------------------------------------------


def test_the_harness_with_no_flags_is_the_pipeline() -> None:
    # Proves: the eval keeps measuring the adopted pipeline (A2.1-PR2-5) — with no override
    # flags the harness builds exactly the pipeline's options and config, and one flag
    # changes exactly one field.
    assert run_eval.configure(run_eval.parse_overrides([])) == (
        extraction.PIPELINE_OPTIONS, extraction.PIPELINE_CONFIG,
    )
    options, config = run_eval.configure(run_eval.parse_overrides(["--line-breaks"]))
    assert options == extraction.PIPELINE_OPTIONS
    assert config == replace(extraction.PIPELINE_CONFIG, keep_line_breaks=True)
    options, _ = run_eval.configure(run_eval.parse_overrides(["--temperature", "0"]))
    assert options == replace(extraction.PIPELINE_OPTIONS, temperature=0.0)


def test_extract_node_and_the_harness_send_identical_requests(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Proves: the same page through `extract_node` and through the harness produces the same
    # message and the same request arguments (the property every eval result depends on).
    html = "<html><body><p>Friday October 2nd</p><p>Griffin / Alec C</p></body></html>"
    page = tmp_path / "page.html"
    page.write_text(html)

    node_client = fake_client()
    monkeypatch.setattr(nodes, "instructor_client", node_client)
    nodes.extract_node(VenueGraphState(
        venue_id=1, calendar_url=str(page), page_html=html, venue_name="Terminal Bar",
        metro_timezone=CHICAGO, fetched_on=FETCHED,
    ))

    eval_client = fake_client()
    monkeypatch.setattr(run_eval, "instructor_client", eval_client)
    run_eval.extract(
        page, venue_name="Terminal Bar", metro_timezone=CHICAGO, fetch_date=FETCHED,
        options=extraction.PIPELINE_OPTIONS, config=extraction.PIPELINE_CONFIG,
    )

    node_call, eval_call = node_client.chat.completions.calls[0], eval_client.chat.completions.calls[0]
    assert node_call == eval_call


# ---------------------------------------------------------------------------
# fetch_node keeps the raw page
# ---------------------------------------------------------------------------


def test_fetch_node_keeps_raw_html_and_cleaned_text(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Proves: the JSON-LD route has its input (JSON-LD lives in <script>, which cleaning
    # strips), `page_content` is still the cleaned text local_test shows, and the run's date
    # — on the metro's clock, not the machine's — is recorded for the year rule, for a live
    # URL and for a fixture path.
    html = '<html><head><script type="application/ld+json">[]</script></head><body><p>Show 8pm</p></body></html>'
    monkeypatch.setattr(nodes.httpx, "get", lambda url, **_: SimpleNamespace(text=html, raise_for_status=lambda: None))
    live = nodes.fetch_node(VenueGraphState(
        venue_id=1, calendar_url="https://venue.example/", venue_name="V", metro_timezone=CHICAGO,
    ))
    assert live.page_html == html
    assert live.page_content == extraction.clean_text(html, extraction.PIPELINE_CONFIG.keep_line_breaks)
    assert live.fetched_on == nodes.metro_today(CHICAGO)

    page = tmp_path / "page.html"
    page.write_text(html)
    local = nodes.fetch_node(VenueGraphState(
        venue_id=1, calendar_url=str(page), venue_name="V", metro_timezone=CHICAGO,
    ))
    assert local.page_html == html


def test_events_without_a_name_are_not_usable() -> None:
    # Proves: A2.1-CR1-6b. An Event with a start but no name can't be split into acts; the
    # module docstring promises such a site falls back to the model route, not that it yields
    # a show with an empty title.
    html = jsonld_page({"@type": "Event", "startDate": "2026-08-17T21:00:00-05:00"})
    result = run(html, fake_client(), route="auto")
    assert result.source == "model"


def test_schema_variants_keep_the_class_descriptions() -> None:
    # Proves: A2.1-CR1-2. A variant schema differs from the base ONLY by its change — the
    # `status` property for A2.1-D12 — so a rung measures one thing. `create_model` drops class
    # docstrings unless told otherwise, which would silently remove two descriptions the model
    # is sent.
    from agent_worker.schemas import page_model

    base = page_model(status=False, split_acts=False).model_json_schema()
    variant = page_model(status=True, split_acts=False).model_json_schema()
    assert variant["description"] == base["description"]
    show = variant["$defs"]["ShowExtraction"]
    assert show["description"] == base["$defs"]["ShowExtraction"]["description"]
    show_props = dict(show["properties"])
    del show_props["status"]
    assert show_props == base["$defs"]["ShowExtraction"]["properties"]


def test_fetch_node_keeps_a_fetch_date_it_was_given(tmp_path: Path) -> None:
    # Proves: A2.1-CR1-7. local_test runs an AUGUST fixture; once the year rule is on, a
    # fetch date of today would put its shows a year ahead. A caller that knows when the page
    # was captured passes `fetched_on`, and fetch_node keeps it.
    page = tmp_path / "page.html"
    page.write_text("<p>Show</p>")
    state = nodes.fetch_node(VenueGraphState(
        venue_id=1, calendar_url=str(page), venue_name="V", metro_timezone=CHICAGO,
        fetched_on=datetime.date(2026, 8, 17),
    ))
    assert state.fetched_on == datetime.date(2026, 8, 17)


def test_fetch_node_reads_a_local_image_as_base64_and_leaves_the_html_unset(tmp_path: Path) -> None:
    # Proves (A7): a calendar URL that is a local image file (a venue whose shows are a poster, the image route) is
    # read as bytes and stored base64-encoded in `page_content`, which is what `extract_image` sends the model; it
    # is not read as text (an image isn't valid UTF-8) and it leaves `page_html` unset, so the JSON-LD route has
    # nothing to try. The expected string is computed here from the bytes the test wrote, not by the node.
    poster = tmp_path / "poster.png"
    poster.write_bytes(b"\x89PNG\r\n\x1a\n not really an image")
    state = nodes.fetch_node(VenueGraphState(
        venue_id=1, calendar_url=str(poster), venue_name="V", metro_timezone=CHICAGO,
    ))
    assert state.fetch_error is None
    assert state.page_content == base64.b64encode(poster.read_bytes()).decode()
    assert state.page_html is None


def test_extract_node_and_the_harness_send_identical_image_requests(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Proves: A2.1-CR1-12 — the image route has the same pipeline/harness parity as the
    # page route, and the year rule (A2.1-D13) rewrites a poster's guessed year there too.
    poster = tmp_path / "poster.png"
    poster.write_bytes(b"not really a png")
    b64 = run_eval.load_image_fixture(poster)

    node_client = fake_client(page_shows=[model_show(7, "The Envies", year=2024)])
    monkeypatch.setattr(nodes, "instructor_client", node_client)
    monkeypatch.setattr(extraction, "PIPELINE_CONFIG", replace(extraction.PIPELINE_CONFIG, year_rule=True))
    monkeypatch.setattr(nodes, "PIPELINE_CONFIG", extraction.PIPELINE_CONFIG)
    state = nodes.extract_node(VenueGraphState(
        venue_id=1, calendar_url=str(poster), page_content=b64, venue_name="V",
        metro_timezone=CHICAGO, fetched_on=datetime.date(2026, 8, 17),
    ))
    assert state.extraction is not None
    assert state.extraction.shows[0].date == datetime.date(2026, 10, 7)

    eval_client = fake_client(page_shows=[model_show(7, "The Envies", year=2024)])
    monkeypatch.setattr(run_eval, "instructor_client", eval_client)
    run_eval.extract(
        poster, venue_name="V", metro_timezone=CHICAGO, fetch_date=datetime.date(2026, 8, 17),
        options=extraction.PIPELINE_OPTIONS, config=extraction.PIPELINE_CONFIG,
    )
    assert node_client.chat.completions.calls[0] == eval_client.chat.completions.calls[0]


def test_the_json_ld_route_keeps_only_end_times_the_page_states() -> None:
    # Proves: A2.1-D10 end to end — the JSON-LD route checks endDate against the page's own visible
    # text, so a platform default end time never reaches the extraction.
    stated = ws_event("Nona", "2026-08-17T18:00:00-05:00", endDate="2026-08-17T20:00:00-05:00")
    unstated = ws_event("Lent", "2026-08-18T18:00:00-05:00", endDate="2026-08-18T22:00:00-05:00")
    block = json.dumps([stated, unstated])
    html = (f'<html><head><script type="application/ld+json">{block}</script></head>'
            "<body>Nona 6:00 pm - 8:00 pm. Lent 6:00 pm.</body></html>")
    client = fake_client(split_answer=act_split.ActSplitAnswer(items=[
        act_split.ActSplitItem(id=0, title="Nona", acts=["Nona"]),
        act_split.ActSplitItem(id=1, title="Lent", acts=["Lent"]),
    ]))
    shows = run(html, client, route="auto").extraction.shows
    assert [s.end_time for s in shows] == [datetime.time(20, 0), None]


def test_the_pipeline_adopts_the_year_rule_and_the_json_ld_route() -> None:
    # Proves: the two rungs Ari adopted on October 11, 2026 after the overnight ladder are the
    # pipeline's defaults — the year rule (a21-year: Mortimer's 7 missed -> 2) and the JSON-LD
    # route (a21-structured: White Squirrel August 12 of 12). The harness starts from these, so
    # every later label includes them without a flag.
    assert extraction.PIPELINE_CONFIG.year_rule is True
    assert extraction.PIPELINE_CONFIG.route == "auto"


def test_the_pipeline_adopts_conventions_line_breaks_and_title_split() -> None:
    # Proves: adopted by Ari on October 11, 2026 after `a21-title-split` (55 of 60 correct; no
    # missed, invented or leaked show): the act conventions, line-break cleaning and title split
    # on the model route are the pipeline's defaults.
    assert extraction.PIPELINE_CONFIG.act_conventions is True
    assert extraction.PIPELINE_CONFIG.keep_line_breaks is True
    assert extraction.PIPELINE_CONFIG.title_split is True


# ---------------------------------------------------------------------------
# The cancelled/postponed status question (A2.1-D12, as decided by Ari on October 11)
# ---------------------------------------------------------------------------

CANCELLED_PAGE = (
    "<p>Oct 10 Cancelled Robert Ellis with Philip Bowen</p><p>Oct 11 Karina Rykman with Tarias</p>"
    "<p>Oct 21 postponed Baby Bugs with Elliot Lee</p>"
)


def status_item(day: int, *acts: str, status: str) -> status_check.StatusItem:
    """One listing the status question says is cancelled or postponed."""
    return status_check.StatusItem(date=datetime.date(2026, 10, day), acts=list(acts), status=status)


def test_no_status_question_when_the_page_never_says_cancelled() -> None:
    # Proves: the code check comes first — a page with no "cancelled"/"postponed" costs no
    # second model call, and every show stays scheduled. That is most pages.
    client = fake_client(page_shows=[model_show(11, "Karina Rykman")])
    result = run("<p>Oct 11 Karina Rykman</p>", client, status_pass=True, **SHOWS_ROUTE)
    assert [c["response_model"] for c in client.chat.completions.calls if c["response_model"] is status_check.StatusAnswer] == []
    assert [s.status for s in result.extraction.shows] == ["scheduled"]  # type: ignore[attr-defined]


def test_the_status_question_marks_matched_shows_and_adds_skipped_ones() -> None:
    # Proves: A2.1-D12 by a narrow second question, not a schema field (the field hurt act splitting,
    # a21-cancelled). A cancelled listing the main extraction returned gets its status; one it
    # skipped is added with its status, so reconcile can still find the stored show. The year
    # rule applies to the added show's date as to every other.
    client = fake_client(
        page_shows=[model_show(10, "Robert Ellis", "Philip Bowen"), model_show(11, "Karina Rykman")],
        status_answer=status_check.StatusAnswer(items=[
            status_item(10, "Robert Ellis", "Philip Bowen", status="cancelled"),
            status_item(21, "Baby Bugs", "Elliot Lee", status="postponed"),
        ]),
    )
    shows = run(CANCELLED_PAGE, client, status_pass=True, **SHOWS_ROUTE).extraction.shows
    by_date = {s.date: (s.status, [a.name for a in s.acts]) for s in shows}  # type: ignore[attr-defined]
    assert by_date[datetime.date(2026, 10, 10)] == ("cancelled", ["Robert Ellis", "Philip Bowen"])
    assert by_date[datetime.date(2026, 10, 11)] == ("scheduled", ["Karina Rykman"])
    assert by_date[datetime.date(2026, 10, 21)] == ("postponed", ["Baby Bugs", "Elliot Lee"])


def test_the_status_question_does_not_change_the_main_schema() -> None:
    # Proves: the main extraction is asked for the same schema as without the switch — no
    # `status` field in it — which is the point of asking separately.
    with_pass, without = fake_client(), fake_client()
    run(CANCELLED_PAGE, with_pass, status_pass=True)
    run(CANCELLED_PAGE, without)
    main = [c for c in with_pass.chat.completions.calls if c["response_model"] is not status_check.StatusAnswer]
    assert main[0]["response_model"] is without.chat.completions.calls[0]["response_model"]
    assert '"status"' not in json.dumps(main[0]["response_model"].model_json_schema())


def test_the_pipeline_asks_the_status_question() -> None:
    # Proves: adopted by Ari on October 11, 2026 after `a21-status-pass` (7th St Entry: every
    # status right, including two cancelled and one postponed; no other page asked or changed).
    assert extraction.PIPELINE_CONFIG.status_pass is True


# ---------------------------------------------------------------------------
# Title split on the model route (A2-S6, October 11, 2026)
# ---------------------------------------------------------------------------


def listing(day: int, title: str, year: int = 2026) -> dict[str, Any]:
    """One listing as the full-page model returns it on the title-split route."""
    return {
        "venue": "7th St Entry", "date": datetime.date(year, 10, day).isoformat(), "title": title,
        "is_ambiguous": False, "confidence": 0.9,
    }


def test_title_split_asks_for_verbatim_titles_and_splits_them_separately() -> None:
    # Proves: the model route can work like the JSON-LD route, which scored 23 of 23 on White
    # Squirrel: the full-page model returns each listing's performer text verbatim (no act list
    # in its schema), and the same act splitter turns every title into acts. The year rule still
    # applies to the listings' dates; a title the splitter rejects is kept with no acts for A3.
    client = fake_client(
        listings=[listing(1, "Owen Riegling | In The Feeling Tour | with | Payton Smith", year=2024),
                  listing(5, "Open Mic Night")],
        split_answer=act_split.ActSplitAnswer(items=[
            act_split.ActSplitItem(id=0, title="Owen Riegling | In The Feeling Tour | with | Payton Smith",
                                   acts=["Owen Riegling", "Payton Smith"]),
            act_split.ActSplitItem(id=1, title="Open Mic Night", acts=[]),
        ]),
    )
    result = run("<p>listings</p>", client, title_split=True, status_pass=False)
    models = [c["response_model"] for c in client.chat.completions.calls]
    assert models == [schemas.VenueListingsExtraction, act_split.ActSplitAnswer]
    shows = result.extraction.shows
    assert [s.date for s in shows] == [datetime.date(2026, 10, 1), datetime.date(2026, 10, 5)]
    assert [[a.name for a in s.acts] for s in shows] == [["Owen Riegling", "Payton Smith"], []]
    assert result.notes["titles"] == ["Owen Riegling | In The Feeling Tour | with | Payton Smith", "Open Mic Night"]


def test_title_split_sends_layout_but_not_the_splitting_conventions_to_the_page_model() -> None:
    # Proves: on this route the page model only copies titles, so it gets the date-heading rule
    # (a listing's lines belong together) and the instruction to copy titles verbatim, but not
    # the act conventions — those go to the act splitter, which does the splitting.
    client = fake_client()
    run("<p>x</p>", client, title_split=True, act_conventions=True, status_pass=False)
    sent = sent_content(client)
    assert prompts._date_heading_rule() in sent
    assert prompts._title_rule() in sent
    assert prompts._act_conventions() not in sent
    schema = json.dumps(client.chat.completions.calls[0]["response_model"].model_json_schema())
    assert '"acts"' not in schema and '"title"' in schema


def test_every_listing_field_carries_over_to_its_show() -> None:
    # Proves: A2.1-CR2-11 — on the title-split route a listing's fields (time, end
    # time, prices, free admission after A2-F1, image, ambiguity, confidence) reach the show
    # unchanged; and ListingExtraction has exactly ShowExtraction's fields, with `title` in place
    # of `acts`, so a field added to one and not the other fails here instead of silently dropping.
    assert set(schemas.ListingExtraction.model_fields) == (set(schemas.ShowExtraction.model_fields) - {"acts"}) | {"title"}
    full = {**listing(9, "Lent w. Gills"), "time": "8pm", "end_time": "23:00", "admission_advance": 12.5,
            "admission_day": 15.0, "free_admission": False, "image_url": "https://x.example/p.png",
            "is_ambiguous": True, "confidence": 0.7}
    client = fake_client(listings=[full], split_answer=act_split.ActSplitAnswer(items=[
        act_split.ActSplitItem(id=0, title="Lent w. Gills", acts=["Lent", "Gills"])]))
    show = run("<p>x</p>", client, title_split=True, status_pass=False, year_rule=False).extraction.shows[0]
    assert (show.time, show.end_time) == (datetime.time(20, 0), datetime.time(23, 0))
    assert (show.admission_advance, show.admission_day, show.free_admission) == (12.5, 15.0, None)
    assert (show.image_url, show.is_ambiguous, show.confidence) == ("https://x.example/p.png", True, 0.7)
    assert [a.name for a in show.acts] == ["Lent", "Gills"]
