"""Tests for the shared extraction instruction (`agent_worker/prompts.py`) and for the two
places that send it (`nodes.extract_node` and `eval/run_eval.extract`).

Two kinds of test live here, deliberately separate:

* **Content tests** check the instruction text states the rules it must (the non-music
  exclusion, the one-show-vs-several rule, no stale "ticket info"). Honest limit: a string
  match pins that the text is *present*, not that the model *obeys* it — whether it obeys
  is what the eval measures. These tests guard against the rule being deleted.
* **Wiring tests** check that both callers really send what `prompts` returns. The point
  of prompts.py is that the pipeline and the eval use one copy; asserting only that both
  *import* the function could pass while a module still sent its own string (the drift
  that already happened once). So these run the real code against a fake client that
  captures what would have been sent.

No model is called. Expected values come from docs/arch/requirements-initial.md ("One Show
or Several?", "…don't have performing artists") and the plan's decided scope, not from
prompts.py.
"""

import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agent_worker import extraction, nodes, prompts
from agent_worker.eval import run_eval
from agent_worker.state import VenueGraphState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeCompletions:
    """Stands in for `instructor_client.chat.completions`: records each `create(...)`
    call's keyword arguments and returns an empty-but-valid page, so the code under
    test runs to the end without a model."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        # An empty-but-valid answer of whatever schema was asked for (the pipeline's title-split
        # route asks for listings, not shows).
        model = kwargs["response_model"]
        key = "listings" if "listings" in model.model_fields else "shows"
        return model.model_validate({"page_readable": True, key: []})


def fake_client() -> SimpleNamespace:
    """A stand-in for the whole `instructor_client`, wrapping a fresh FakeCompletions so
    each test gets its own record of calls. Only `.chat.completions.create` exists on it,
    which is all the code under test touches."""
    return SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))


def sent_text(client: SimpleNamespace) -> str:
    """The single text message the code under test sent (text fixtures send a string)."""
    (call,) = client.chat.completions.calls
    content = call["messages"][0]["content"]
    assert isinstance(content, str)
    return content


# ---------------------------------------------------------------------------
# Content: what the instruction says
# ---------------------------------------------------------------------------


def test_instruction_without_new_rules_keeps_the_page_readable_paragraph() -> None:
    # Proves: the page_readable guidance is part of the shared instruction. The eval's
    # private copy used to lack it, which made eval results unrepresentative of the
    # pipeline.
    assert "page_readable" in prompts.extraction_instruction(include_new_rules=False)


def test_full_instruction_keeps_the_page_readable_paragraph() -> None:
    # Proves: the same, for the default (full) instruction the pipeline actually sends —
    # the new rules are inserted without displacing it.
    assert "page_readable" in prompts.extraction_instruction()


def test_instruction_without_new_rules_omits_both_rules() -> None:
    # Proves: `include_new_rules=False` is base + page_readable only, so the eval's
    # `schema-only` label changes the schema but not the two new rules — which is what
    # lets a regression be attributed to one or the other. (Its base sentence is A2's
    # edited wording, not the literal pre-A2 text the `baseline` label used.)
    text = prompts.extraction_instruction(include_new_rules=False).lower()
    assert "karaoke" not in text
    assert "single show" not in text


def test_instruction_states_the_non_music_exclusion() -> None:
    # Proves: the instruction tells the model to skip karaoke,
    # open mic and the like, and that "Hosted by" is not a performance
    # (requirements-initial.md, "…don't have performing artists"). This is the same
    # failure shape as Phase 5's documented one: a non-music entry mixed into a musical
    # listing.
    text = prompts.extraction_instruction().lower()
    assert "karaoke" in text
    assert "open mic" in text
    assert "hosted by" in text


def test_instruction_states_the_one_show_vs_several_rule() -> None:
    # Proves: listings under one time / ticket link are one
    # multi-artist show. This decides insert-vs-update downstream (A5's composite key is
    # venue + date + time), so a model that splits or merges shows differently between
    # runs would read as churn.
    text = prompts.extraction_instruction().lower()
    assert "single show" in text
    assert "ticket link" in text


def test_instruction_no_longer_asks_for_ticket_info() -> None:
    # Proves: the base wording was updated when `ticket_info` was replaced by typed
    # admission fields. Leaving "any ticket info" would ask the model for a field that
    # no longer exists. (Checked on the no-new-rules path so it holds independent of #3/#4.)
    assert "ticket info" not in prompts.extraction_instruction(include_new_rules=False).lower()


# ---------------------------------------------------------------------------
# A2.1 additions: the cancelled sentence and the shared act conventions
# ---------------------------------------------------------------------------


def test_the_cancelled_rule_keeps_cancelled_listings_with_their_status() -> None:
    # Proves: A2.1-D12 of the A2.1 plan — a cancelled or postponed listing is still extracted
    # (reconcile must match it to the stored show), and the sentence is only sent when the
    # rung asks for it.
    rule = prompts._cancelled_rule().lower()
    assert "cancelled" in rule and "postponed" in rule and "status" in rule
    assert prompts._cancelled_rule() in prompts.extraction_instruction(cancelled_rule=True)
    assert prompts._cancelled_rule() not in prompts.extraction_instruction()


def test_the_act_conventions_are_one_text_for_both_routes() -> None:
    # Proves: A2.1-D5's conventions (tour names, parentheticals, named DJs, splitting markers) are
    # one text, sent to the model route when the rung asks for it — the same text the
    # JSON-LD splitter gets (A2.1-PR2-2; test_act_split.py checks the other side).
    text = prompts._act_conventions().lower()
    assert "tour" in text and "parenthes" in text and "dj" in text
    # Ari, October 11, 2026: a DJ keeps "DJ" in the name ("DJ Dedicated Enemy", not "Dedicated Enemy").
    assert "keep 'dj'" in text
    assert prompts._act_conventions() in prompts.extraction_instruction(act_conventions=True)
    assert prompts._act_conventions() not in prompts.extraction_instruction()


def test_the_exclusion_rule_leans_toward_including_shows() -> None:
    # Proves: Ari's preference (October 11, 2026; requirements-initial.md, "When in doubt, include
    # it") reaches the model: a listing that names a performer is a show even if it also mentions
    # karaoke or a series name; only entries naming no performer are skipped. The earlier wording
    # read as "when in doubt, skip" and dropped two real shows ("Cole Diamond's Whiskey
    # Wednesdays"; "Absolutely Yours Album Release Show w/ Embahn + … + Karaoke").
    rule = prompts._non_music_rule().lower()
    assert "when in doubt, include" in rule
    assert "karaoke" in rule and "series" in rule
    assert "names no performer" in rule or "name no performer" in rule


def test_hosts_and_album_releases_follow_aris_conventions() -> None:
    # Proves: Ari's decisions of October 11, 2026 reach both routes. A named host of a music
    # show or series is one of its acts ("Alex & Toke's … Acoustic Tuesdays") — open mics and
    # comedy nights are screened out anyway; and in "X Album Release Show", X is the artist
    # releasing the album ("Absolutely Yours" — the splitter dropped it in a21-title-split).
    conventions = prompts._act_conventions().lower()
    assert "host" in conventions and "is an act" in conventions
    assert "album release" in conventions
    assert "a host is not an act" not in conventions
    rule = prompts._non_music_rule().lower()
    assert "hosted by" in rule
    assert "never list a host" not in rule


def test_no_prompt_quotes_a_labelled_answer() -> None:
    # Proves: A2.1-CR2-2 — the model-facing texts give examples, but none of them is
    # an act name from the eval's labels, so a score on the labelled pages is out of sample. (The
    # first conventions quoted the gated pages' own hard titles with their answers; three were
    # added right after their row failed.) Expected act names come from labels.py, not prompts.py.
    from agent_worker import act_split, extraction, policy
    from agent_worker.eval.labels import PAGE_LABELS
    from agent_worker.normalize import fold_text
    from agent_worker.schemas import SPLIT_ACTS_DESCRIPTION

    # Every text the model is sent: the page rules, the splitter's instruction, the schema text.
    sent = [
        prompts._act_conventions(), prompts._non_music_rule(), prompts._one_show_rule(),
        prompts._date_heading_rule(), prompts._title_rule(), prompts._cancelled_rule(),
        act_split._act_split_instruction(), SPLIT_ACTS_DESCRIPTION,
        # A3's retry hints (policy.py): the fixed sentences sent on every retry, and what introduces them.
        *policy._ADVICE.values(), *policy._REASON_ADVICE.values(), policy._FINAL_PAGE_ADVICE,
        policy._FINAL_SPLITTER_ADVICE, extraction._HINT_INTRO, act_split._HINT_INTRO,
    ]
    texts = fold_text(" ".join(sent))
    names = {fold_text(a) for page in PAGE_LABELS.values() for show in page.shows for a in show.acts}
    quoted = sorted(n for n in names if len(n) > 3 and n in texts)
    assert quoted == []


def test_a_presenter_is_not_an_act() -> None:
    # Proves: A2.1-CR2-10 — the labels treat "X Presents:" as a promoter, and the
    # model is now told so (Zhora's "Crazy Clyde Presents:" was counted as an act in every
    # confirmation run once hosts became acts).
    assert "presents" in prompts._act_conventions().lower()


def test_the_date_heading_rule_goes_to_the_model_route_only() -> None:
    # Proves: the layout sentence added after a21-conventions-newlines (October 11, 2026) — the
    # lines under one date heading, up to the next date, are that one show's acts — is sent on
    # the full-page model route with the conventions, and NOT to the JSON-LD act splitter, which
    # sees single titles, not page layout. Terminal Bar lists a date line then one line per act;
    # with line breaks the model took only the first line and turned the rest into extra shows.
    rule = prompts._date_heading_rule()
    assert "date" in rule.lower() and "next date" in rule.lower()
    assert rule in prompts.extraction_instruction(act_conventions=True)
    assert rule not in prompts.extraction_instruction()
    assert rule not in prompts._act_conventions()


def test_the_title_split_instruction_asks_only_for_what_a_listing_can_hold() -> None:
    # Proves: A2.1-CR2-9 — on the title-split route the model returns a listing
    # (`ListingExtraction`: one verbatim title, no acts), so the instruction must not ask it to
    # "put each artist's own start time on that artist", a rule it has no field to follow. The
    # one-show-vs-several rule itself stays (it decides how many listings there are); the other
    # routes keep the per-artist sentence (requirements-initial.md, "Artist(s) performing").
    per_act = "each artist's own start time"
    assert per_act not in prompts.extraction_instruction(title_split=True)
    assert "single show with several artists" in prompts.extraction_instruction(title_split=True)
    assert per_act in prompts.extraction_instruction()


def test_the_listing_schemas_describe_themselves_to_the_model() -> None:
    # Proves: A2.1-CR2-9b — instructor sends a model's class docstring to the model
    # as its schema description (A2.1-CR1-2), so the title-split schemas' docstrings
    # say what a listing is, not which pipeline route uses them (wording the model can't use).
    from agent_worker.schemas import ListingExtraction, VenueListingsExtraction

    for cls in (ListingExtraction, VenueListingsExtraction):
        description = cls.model_json_schema()["description"].lower()
        assert "route" not in description and "split" not in description, cls.__name__


# ---------------------------------------------------------------------------
# Wiring: both callers send what prompts returns
# ---------------------------------------------------------------------------
# A2.1 moved request-building into `extraction.extract_page`, which both `extract_node` and
# the eval harness call; these A2 guarantees are kept, retargeted at that one place.

SENTINEL = "SENTINEL-INSTRUCTION: not the real prompt."
PAGE_HTML = "<html><body><p>Show 8pm</p><script>x()</script></body></html>"
CHICAGO = "America/Chicago"


def node_state() -> VenueGraphState:
    """A graph state as fetch_node leaves it for a text page."""
    return VenueGraphState(
        venue_id=1, calendar_url="page.html", page_html=PAGE_HTML, venue_name="Test Venue",
        metro_timezone=CHICAGO, fetched_on=datetime.date(2026, 10, 10),
    )


def eval_extract(page: Path, seed: int | None = None) -> None:
    """Run the harness's extraction of one text fixture with the pipeline's configuration."""
    run_eval.extract(
        page, venue_name="Test Venue", metro_timezone=CHICAGO, fetch_date=datetime.date(2026, 10, 10),
        options=extraction.PIPELINE_OPTIONS, config=extraction.PIPELINE_CONFIG, seed=seed,
    )


def test_extract_node_sends_whatever_prompts_returns(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves: extract_node's message is built from `extraction_instruction()` and not from a
    # private string. A sentinel replaces the function; if any copy of the text lived
    # elsewhere the sentinel would not appear.
    client = fake_client()
    monkeypatch.setattr(nodes, "instructor_client", client)
    monkeypatch.setattr(extraction, "extraction_instruction", lambda *_a, **_k: SENTINEL)
    nodes.extract_node(node_state())
    assert sent_text(client) == SENTINEL + "Show 8pm"


def test_eval_extract_sends_whatever_prompts_returns(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Proves: the eval harness, too, takes its instruction from prompts.py — the very drift
    # this module exists to end. Run against a real temporary text fixture.
    page = tmp_path / "page.html"
    page.write_text(PAGE_HTML)
    client = fake_client()
    monkeypatch.setattr(run_eval, "instructor_client", client)
    monkeypatch.setattr(extraction, "extraction_instruction", lambda *_a, **_k: SENTINEL)
    eval_extract(page)
    # html is cleaned to visible text on the way in (script dropped).
    assert sent_text(client) == SENTINEL + "Show 8pm"


def test_both_callers_send_the_real_instruction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Proves: with nothing patched, the pipeline and the eval send byte-identical
    # instruction text — the property every eval measurement depends on.
    page = tmp_path / "page.html"
    page.write_text(PAGE_HTML)
    node_client, eval_client = fake_client(), fake_client()
    monkeypatch.setattr(nodes, "instructor_client", node_client)
    nodes.extract_node(node_state())
    monkeypatch.setattr(run_eval, "instructor_client", eval_client)
    eval_extract(page)
    expected = extraction.instruction_for(extraction.PIPELINE_CONFIG) + "Show 8pm"
    assert sent_text(node_client) == expected
    assert sent_text(eval_client) == expected


def test_retries_are_stated_not_implicit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Proves: both call sites pass `max_retries=1` explicitly. A3-D7 lowered it from instructor's
    # default of 3: the graph's own 3-attempt cap multiplies it (3 x (4 + 4 + 4) = 36 model calls per
    # venue before), and the 45 a21-confirm runs used none. The literal is the decision; it should be
    # visible where it's spent, and a change to it should be a decision, not a drift.
    page = tmp_path / "page.html"
    page.write_text(PAGE_HTML)
    node_client, eval_client = fake_client(), fake_client()
    monkeypatch.setattr(nodes, "instructor_client", node_client)
    nodes.extract_node(node_state())
    monkeypatch.setattr(run_eval, "instructor_client", eval_client)
    eval_extract(page)
    assert node_client.chat.completions.calls[0]["max_retries"] == 1
    assert eval_client.chat.completions.calls[0]["max_retries"] == 1


def test_eval_passes_its_seed_as_a_top_level_argument(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Proves: the run index reaches Ollama as the OpenAI-style top-level `seed`, which its
    # /v1 endpoint honours. The earlier form, `options.seed`, is silently IGNORED by /v1
    # (verified: identical output only with the top-level argument), so a seed placed there
    # looks reproducible and isn't. `num_ctx` is still sent in `options`, matching the
    # pipeline, though /v1 ignores that too (see docs/dev/notes.md).
    page = tmp_path / "page.html"
    page.write_text(PAGE_HTML)
    client = fake_client()
    monkeypatch.setattr(run_eval, "instructor_client", client)
    eval_extract(page, seed=2)
    call = client.chat.completions.calls[0]
    assert call["seed"] == 2
    assert "seed" not in call["extra_body"]["options"]
    assert call["extra_body"]["options"] == {"num_ctx": 32768}
