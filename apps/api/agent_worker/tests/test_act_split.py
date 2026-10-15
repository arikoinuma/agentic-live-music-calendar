"""Tests for the act splitter (`agent_worker/act_split.py`), the JSON-LD route's one model call.

On the JSON-LD route, dates and times come from the venue's structured data; the model is
asked only the question JSON-LD doesn't answer — which performing acts a title names, and
whether it is a music show at all (A2.1-D4, A2.1-D5, A2.1-D12 of the A2.1 plan). The narrow instruction is
`_act_split_instruction` (A2.1-Gap-D); everything around it — numbering the titles, aligning the answer back to
them — is written, and these tests pin that the alignment can't silently put one show's acts
on another.

How to read it: a fake client returns a canned answer -> instruction content -> alignment by
id. No model is called.
"""

from types import SimpleNamespace
from typing import Any

from agent_worker import act_split, extraction, prompts

TITLES = ["Lent w. Gills, Boomdagger", "Open Jam", "Martin Devaney & Friends w. Wesley Church"]


def answering(*items: act_split.ActSplitItem) -> SimpleNamespace:
    """A fake `instructor` client whose one answer is the given items, recording each call."""
    calls: list[dict[str, Any]] = []

    def create(**kwargs: Any) -> act_split.ActSplitAnswer:
        calls.append(kwargs)
        return act_split.ActSplitAnswer(items=list(items))

    return SimpleNamespace(calls=calls, chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def split(client: SimpleNamespace, titles: list[str] = TITLES) -> act_split.SplitResult:
    """Run the splitter with the pipeline's request options."""
    return act_split.split_titles(titles, client=client, options=extraction.PIPELINE_OPTIONS)


def test_the_instruction_carries_the_conventions_and_the_exclusion_rule() -> None:
    # Proves: the splitter is told A2.1-D5's conventions (one shared text with the model route,
    # A2.1-PR2-2) and the non-music rule — JSON-LD lists every event on the calendar,
    # karaoke included, so the exclusion must still run on this route.
    text = act_split._act_split_instruction()
    assert prompts._act_conventions() in text
    assert prompts._non_music_rule() in text
    assert "w." in text and "/" in text


def test_titles_are_sent_numbered() -> None:
    # Proves: the model sees an id per title, which is what alignment keys on.
    client = answering()
    split(client)
    sent = client.calls[0]["messages"][0]["content"]
    assert "0: Lent w. Gills, Boomdagger" in sent
    assert "2: Martin Devaney & Friends w. Wesley Church" in sent


def test_answers_align_by_id_not_position() -> None:
    # Proves: a reordered answer with one item missing still puts each act list on its own
    # title, and the missing id gets no acts and is recorded — a dropped item can't shift
    # every later show's acts onto the wrong show.
    result = split(answering(
        act_split.ActSplitItem(id=2, title=TITLES[2], acts=["Martin Devaney & Friends", "Wesley Church"]),
        act_split.ActSplitItem(id=0, title=TITLES[0], acts=["Lent", "Gills", "Boomdagger"]),
    ))
    assert result.acts == [["Lent", "Gills", "Boomdagger"], [], ["Martin Devaney & Friends", "Wesley Church"]]
    assert result.missing_ids == [1]


def test_a_requoted_echo_is_not_a_mismatch_but_a_different_title_is() -> None:
    # Proves: the echoed title is only a cross-check (A2.1-PR1-10). A model that re-quotes
    # an apostrophe hasn't changed the title; one that echoes different words has, and that
    # is recorded rather than trusted silently.
    titles = ["Aaron James w. Bury ‘Em Deep", "Nona"]
    result = split(answering(
        act_split.ActSplitItem(id=0, title="Aaron James w. Bury 'Em Deep", acts=["Aaron James", "Bury 'Em Deep"]),
        act_split.ActSplitItem(id=1, title="Something Else", acts=["Nona"]),
    ), titles)
    assert result.title_mismatches == [1]


def test_identical_titles_keep_their_own_ids() -> None:
    # Proves: a weekly listing with the same title twice on one page gets each answer by id.
    result = split(answering(
        act_split.ActSplitItem(id=0, title="Nona", acts=["Nona"]),
        act_split.ActSplitItem(id=1, title="Nona", acts=["Nona"]),
    ), ["Nona", "Nona"])
    assert result.acts == [["Nona"], ["Nona"]]
    assert result.missing_ids == []
