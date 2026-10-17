"""Tests for matching a named act to an artist we already have: exact, ambiguous, new, and the model's part.

Milestone A5 (docs/dev/implementations/a5-reconcile.md, Test approach §3). Sources of the expected values:
`requirements-initial.md` ("Agent Artist Creation & Matching": clear matches and clear non-matches resolve
automatically, ambiguous matches go through a review step; a new artist is created with the name only), decisions D8
(what counts as exactly the same name), D9 (what to do when the model is unsure) and D12 (how similarity is measured)
in the plan, and the `difflib` ratios D12 records, which were measured on October 16, 2026: Dessa/Desa 0.889,
Low/Lowe 0.857, Zhora/Zhora Band 0.667. The model is `fakes.scripted_client`; the real model is not run here, so how
well it answers is not measured by these tests (plan, "What is not covered").
"""

import pytest
from instructor.core.exceptions import InstructorError

from agent_worker import prompts
from agent_worker.artist_match import (
    Ambiguous,
    ArtistMatchAnswer,
    ArtistMatchPolicy,
    Exact,
    KnownArtist,
    New,
    artist_key,
    classify_artist,
    decide_ambiguous,
    resolve_artists,
)
from agent_worker.tests.fakes import ARTIST_MATCH, completions, scripted_client
from agent_worker.tests.reconcile_support import OPTIONS

ZHORA = KnownArtist(8, "Zhora")
ZHORA_BAND = KnownArtist(12, "Zhora Band")

# ---------------------------------------------------------------------------
# Names (D8)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("incoming", "known"),
    [
        ("The Hold Steady", "Hold Steady"),  # a leading "The"
        ("Poliça", "Polica"),  # accents
        ("Jenny Lake & Friends", "Jenny Lake and Friends"),  # "&" and "and"
        ("  nona ", "NONA"),  # case and spacing
        ("Dessa!", "Dessa"),  # punctuation
    ],
)
def test_names_that_differ_only_in_tidiable_details_are_exactly_the_same_artist(incoming: str, known: str) -> None:
    # Proves (D8): these are one artist with no review and no model call. Decided by Ari (October 17, 2026), and
    # each is a real kind of difference between a venue page and our records.
    assert isinstance(classify_artist(incoming, [KnownArtist(1, known)]), Exact)


def test_a_name_made_only_of_punctuation_does_not_match_another() -> None:
    # Proves (plan review finding 11): "!!!" is a real touring band. Dropping punctuation would leave an empty key,
    # and empty keys are equal, so "!!!" would exactly match "???" (or any all-punctuation name). The key falls back
    # to the plain folded name, and such a name never reaches the word-containment rule with an empty word set.
    assert artist_key("!!!") == "!!!"
    assert isinstance(classify_artist("???", [KnownArtist(1, "!!!")]), New)
    assert isinstance(classify_artist("!!!", [KnownArtist(1, "!!!")]), Exact)


# ---------------------------------------------------------------------------
# Exact, ambiguous or new (K4, D8, D12)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("incoming", "known"),
    [
        ("Dessa", "Desa"),  # ratio 0.889
        ("Low", "Lowe"),  # ratio 0.857
        ("Zhora Band", "Zhora"),  # containment (ratio 0.667 is far too low to catch it)
    ],
)
def test_similar_but_not_equal_names_are_ambiguous(incoming: str, known: str) -> None:
    # Proves (D12): "clear matches and clear non-matches resolve automatically; ambiguous matches ... go through a
    # review step rather than a fixed rule" (requirements). A similar name is neither a match nor a miss. It must
    # not be merged with no review, and must not silently become a duplicate.
    found = classify_artist(incoming, [KnownArtist(3, known)])
    assert isinstance(found, Ambiguous) and found.candidates == (KnownArtist(3, known),)


def test_an_unrelated_name_is_new() -> None:
    # Proves: the clear non-match. "Prince" against "Zhora" shares nothing, so a new artist is created with the
    # name only (requirements).
    assert isinstance(classify_artist("Prince", [ZHORA]), New)


def test_the_ratio_threshold_comes_from_the_policy() -> None:
    # Proves (D12): the similarity bar is a named policy value, not a literal, so A8 can calibrate it. "Low" and
    # "Lowe" score 0.857: ambiguous at the default 0.85, new when the bar is raised to 0.9. (The containment rule
    # doesn't apply: "low" is not one of the words of "lowe".)
    low = [KnownArtist(1, "Lowe")]
    assert isinstance(classify_artist("Low", low), Ambiguous)
    assert isinstance(classify_artist("Low", low, ArtistMatchPolicy(ratio=0.9)), New)


def test_the_model_is_shown_at_most_the_policys_number_of_candidates_closest_first() -> None:
    # Proves (D12): with many close artists the model sees the closest three (not all), best first, ties by id.
    known = [KnownArtist(i, f"Zhora Band {i}") for i in range(1, 6)] + [KnownArtist(9, "Zhora Band")]
    found = classify_artist("Zhora Band", known)
    assert isinstance(found, Exact)  # equal to a known artist
    found = classify_artist("Zhora Bands", known)
    assert isinstance(found, Ambiguous) and len(found.candidates) == 3 and found.candidates[0].id == 9


def test_two_artists_with_the_same_name_resolve_to_the_lowest_id_and_report_the_other() -> None:
    # Proves: duplicates exist until merge is built (data-model-initial.md §5). The lowest id is used, so the choice
    # is the same every run, and the duplicate is reported.
    found = classify_artist("Nona", [KnownArtist(20, "nona"), KnownArtist(5, "Nona")])
    assert found == Exact(artist_id=5, duplicates=(20,))


# ---------------------------------------------------------------------------
# The model decides the ambiguous case (K5, D9)
# ---------------------------------------------------------------------------


def _ask(answer: object, candidates: tuple[KnownArtist, ...] = (ZHORA,), name: str = "Zhora Band"):
    client = scripted_client({ARTIST_MATCH: [answer]})
    return decide_ambiguous(name, candidates, client=client, options=OPTIONS), client


def test_a_confident_same_act_answer_links_the_existing_artist() -> None:
    # Proves (D9): the model says "Zhora Band" is Zhora (8) at 0.93: the existing artist is linked, decided by the
    # model, with the model's name, confidence and reason recorded for the audit row.
    resolution, _ = _ask({"matched_artist_id": 8, "confidence": 0.93, "reason": "same band, longer name"})
    assert (resolution.outcome, resolution.artist_id, resolution.decided_by) == ("matched_by_model", 8, "model")
    assert (resolution.model_used, resolution.confidence) == ("test-model", 0.93)
    assert resolution.reason == "same band, longer name"


def test_a_different_act_answer_creates_a_new_artist() -> None:
    # Proves (D9): "null" (a different act) means a new artist, still a model decision with its confidence.
    resolution, _ = _ask({"matched_artist_id": None, "confidence": 0.9, "reason": "a different band"})
    assert (resolution.outcome, resolution.artist_id, resolution.decided_by) == ("new_after_model", None, "model")


def test_an_unsure_same_act_answer_creates_a_new_artist() -> None:
    # Proves (D9): "probably the same, 0.6" is below the 0.8 bar. A duplicate artist is visible and revertable
    # (merging is deferred); a wrong merge silently puts two acts on one artist page. So unsure means new.
    resolution, _ = _ask({"matched_artist_id": 8, "confidence": 0.6, "reason": "maybe"})
    assert resolution.outcome == "new_after_model" and resolution.artist_id is None and resolution.confidence == 0.6


def test_the_confidence_bar_comes_from_the_policy() -> None:
    # Proves: 0.8 is `ArtistMatchPolicy.min_confidence`, not a literal. At a bar of 0.5, the 0.6 answer links.
    client = scripted_client({ARTIST_MATCH: [{"matched_artist_id": 8, "confidence": 0.6, "reason": "maybe"}]})
    resolution = decide_ambiguous(
        "Zhora Band", (ZHORA,), client=client, options=OPTIONS, policy=ArtistMatchPolicy(min_confidence=0.5)
    )
    assert resolution.outcome == "matched_by_model"


def test_an_artist_the_model_was_not_shown_is_never_linked() -> None:
    # Proves (D9): a model can name an id that does not exist or that it was not offered (99). Linking it would put a
    # wrong or nonexistent artist id into the database, so it is treated as no match.
    resolution, _ = _ask({"matched_artist_id": 99, "confidence": 0.99, "reason": "sure"})
    assert resolution.outcome == "new_after_model" and resolution.artist_id is None


def test_a_failed_model_call_creates_a_new_artist_and_records_why() -> None:
    # Proves (D9): the model server being down, or instructor giving up, must not crash reconcile or merge anything:
    # the fallback is a new artist, and the reason says the call failed (the audit row shows it). The failure is
    # one of the named `EXTRACTION_ERRORS`, never a bare Exception.
    client = scripted_client({ARTIST_MATCH: [InstructorError("could not parse the answer")]})
    resolution = decide_ambiguous("Zhora Band", (ZHORA,), client=client, options=OPTIONS)
    assert resolution.outcome == "new_after_model" and resolution.artist_id is None
    assert resolution.reason is not None and "model call failed" in resolution.reason
    assert resolution.model_used == "test-model" and resolution.confidence is None


def test_an_error_in_our_own_code_is_not_swallowed() -> None:
    # Proves: only the named model-call errors become a fallback. A KeyError is a bug in our code and must
    # crash (apps/api/AGENTS.md: never catch bare Exception), not be filed as "the model failed".
    client = scripted_client({ARTIST_MATCH: [KeyError("bug")]})
    with pytest.raises(KeyError):
        decide_ambiguous("Zhora Band", (ZHORA,), client=client, options=OPTIONS)


def test_the_confidence_is_bounded_to_zero_to_one() -> None:
    # Proves (plan review finding 16): like the other schemas the model fills, an out-of-range confidence is a
    # validation error, not a "match" at 1.7.
    with pytest.raises(ValueError, match="confidence"):
        ArtistMatchAnswer.model_validate({"matched_artist_id": 8, "confidence": 1.7, "reason": "sure"})


def test_the_question_carries_the_name_the_candidates_and_the_null_instruction() -> None:
    # Proves: what the model is sent. The incoming name, each candidate WITH its id (the answer is an id), and the
    # instruction to answer null when unsure, which makes the conservative direction the default.
    text = prompts.artist_match_instruction("Zhora Band", [(8, "Zhora"), (12, "Zhorra")])
    assert "Zhora Band" in text and "8: Zhora" in text and "12: Zhorra" in text and "null" in text


def test_the_question_uses_the_given_options() -> None:
    # Proves: the call is configured from the options passed in (the pipeline's, temperature 0), so a run is
    # repeatable and `model_used` is the model that answered.
    _, client = _ask({"matched_artist_id": None, "confidence": 0.9, "reason": "no"})
    [call] = completions(client).calls
    assert call["model"] == "test-model" and call["temperature"] == 0.0


# ---------------------------------------------------------------------------
# Once per name
# ---------------------------------------------------------------------------


def test_an_exact_name_makes_no_model_call() -> None:
    # Proves: clear matches resolve automatically (requirements). The client is unscripted, so a model call here
    # would fail the test.
    resolved = resolve_artists(["The Zhora"], [ZHORA], client=scripted_client({}), options=OPTIONS)
    [resolution] = resolved.values()
    assert resolution.outcome == "exact" and resolution.artist_id == 8 and resolution.decided_by == "rule"


def test_an_ambiguous_name_on_two_shows_asks_the_model_once() -> None:
    # Proves: reconcile resolves per distinct name per run. "Zhora Band" on the 18th and the 25th is one question,
    # not two (cost, and two answers that could disagree).
    client = scripted_client({ARTIST_MATCH: [{"matched_artist_id": 8, "confidence": 0.9, "reason": "same"}]})
    resolved = resolve_artists(["Zhora Band", "zhora band"], [ZHORA], client=client, options=OPTIONS)
    assert len(resolved) == 1 and len(completions(client).calls) == 1


def test_the_same_new_artist_on_three_shows_is_one_new_artist() -> None:
    # Proves: reconcile runs before commit, so the database can't tell it an artist was already created for another
    # show. Three shows naming the same unknown artist must yield one resolution (commit then creates one
    # artist), not three.
    resolved = resolve_artists(["Sunny Day", "Sunny Day", "sunny day"], [ZHORA], client=scripted_client({}), options=OPTIONS)
    assert len(resolved) == 1 and next(iter(resolved.values())).outcome == "new"
