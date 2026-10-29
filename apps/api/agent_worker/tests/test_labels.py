"""Tests that the hand-written labels (`agent_worker/eval/labels.py`) are well-formed.

The labels are the ground truth Ari's accuracy standard is scored against (A2.1-D1,
A2.1-D5, A2.1-D11). A malformed label would make the scorer pass or fail runs for reasons that have
nothing to do with the model, so these checks run before anything is scored. They test the
labels' *shape*, not their truth — whether a label is right is what `source_line` lets a
human check, and what Ari confirms for the flagged rows.

How to read it: one test per property, each over every page label.
"""

from pathlib import Path

import pytest

from agent_worker.eval import labels

# A2.1-D2 as revised by Ari on October 11, 2026: Terminal Bar moved to informational (an outlier layout —
# a date line then one line per act — that no rung fixed without breaking other pages).
GATED_VENUES = {"white_squirrel", "seventh_st_entry", "mortimers"}


def test_every_page_label_has_shows() -> None:
    # Proves: no page is scored against an empty label (which would turn every returned
    # show into a fabrication). The page left for Ari to label (A2.1-D11) is red here until he
    # fills it.
    empty = [name for name, page in labels.PAGE_LABELS.items() if not page.shows]
    assert empty == []


def test_every_show_says_where_it_came_from() -> None:
    # Proves: each row carries the page text it was read from, so a reviewer can check it
    # without opening the fixture, and names at least one act (a listing with none isn't a
    # show; it belongs in `non_shows`).
    for name, page in labels.PAGE_LABELS.items():
        for show in page.shows:
            assert show.source_line.strip(), (name, show)
            assert show.acts, (name, show)


def test_no_page_lists_the_same_show_twice() -> None:
    # Proves: (date, time, normalised acts) is unique per page. Two shows MAY share a date
    # and time — 7th St Entry lists two untimed shows on Oct 31 — which is why the scorer
    # tie-breaks on acts (A2.1-PR2-3).
    from agent_worker.normalize import fold_text

    for name, page in labels.PAGE_LABELS.items():
        keys = [(s.date, s.time, frozenset(fold_text(a) for a in s.acts)) for s in page.shows]
        assert len(keys) == len(set(keys)), name


def test_gated_pages_are_the_reachable_venues() -> None:
    # Proves: A2.1-D2 — only venues production can fetch are gated (White Squirrel, 7th St Entry,
    # Mortimer's); Zhora, the posters and, since October 11, Terminal Bar are informational.
    gated = {page.venue for page in labels.PAGE_LABELS.values() if page.gated}
    assert gated == GATED_VENUES


def test_every_labelled_venue_has_its_facts() -> None:
    # Proves: the harness can hand `extract_page` a venue name and metro zone for every
    # labelled page (A2.1-PR1-16), and capture can find each gated venue's URL.
    for page in labels.PAGE_LABELS.values():
        facts = labels.VENUE_FACTS[page.venue]
        assert facts.name and facts.metro_timezone == "America/Chicago"
    for venue in GATED_VENUES | {"terminal"}:
        assert labels.VENUE_FACTS[venue].url.startswith("https://")


def test_every_non_show_can_match_something() -> None:
    # Proves: A2.1-CR1-11. A non-show with neither a date nor a weekday (or "Sunday = 7")
    # never matches, so every leak on its page would silently become a fabrication — the
    # check that makes Ari's Mortimer's fill-in safe to write.
    for name, page in labels.PAGE_LABELS.items():
        for non_show in page.non_shows:
            assert non_show.title.strip(), (name, non_show)
            assert (non_show.date is None) != (non_show.weekday is None), (name, non_show)
            assert non_show.weekday is None or 0 <= non_show.weekday <= 6, (name, non_show)


# ---------------------------------------------------------------------------
# C5: held-out pages (C5-D3) and the capture-coverage guard
# ---------------------------------------------------------------------------


def with_held_out(monkeypatch: pytest.MonkeyPatch) -> labels.PageLabel:
    """Add one held-out page (a copy of a real one, flagged) to the labels for the duration of a test, and return it."""
    from dataclasses import replace

    held = replace(labels.PAGE_LABELS["mortimers-2026-10-10.html"], held_out=True)
    monkeypatch.setitem(labels.PAGE_LABELS, "held-out-page.html", held)
    return held


def test_a_held_out_page_is_in_no_default_set(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves: C5-D3. A page flagged `held_out` is never in the gated or the informational set, which are the sets the baseline
    # and every default run score, so its results can't be seen (and tuned against) before C6 scores it. Only
    # `held_out_fixtures()` returns it. Without this, "label once, hold out a third" would depend on discipline alone.
    with_held_out(monkeypatch)
    assert "held-out-page.html" not in labels.gated_fixtures()
    assert "held-out-page.html" not in labels.informational_fixtures()
    assert labels.held_out_fixtures() == ["held-out-page.html"]


def test_no_page_is_held_out_until_ari_marks_one() -> None:
    # Proves: C5-D3. The flag defaults to False, so every page labelled before C5 stays in its set; the default sets are
    # unchanged by this milestone.
    assert labels.held_out_fixtures() == []
    assert not any(page.held_out for page in labels.PAGE_LABELS.values())


def test_every_captured_fixture_has_a_label() -> None:
    # Proves: C5-K1 (a local guard; it skips where `eval/fixtures/` holds no captures, as in a cloud checkout and CI). A capture
    # nobody labelled is a page the harness silently ignores, because `select_fixtures` runs only labelled files. Add a file to
    # UNLABELLED_ON_PURPOSE (with the reason) if a capture is deliberately not scored, e.g. a venue behind a bot challenge.
    fixtures = [
        p.name for p in labels_fixtures_dir().iterdir()
        if p.is_file() and p.name != ".gitkeep" and p.suffix != ".ics" and p.name not in UNLABELLED_ON_PURPOSE
    ]
    if not fixtures:
        pytest.skip("no captured fixtures here (they are gitignored); this guard runs on the machine that captures")
    assert sorted(set(fixtures) - set(labels.PAGE_LABELS)) == []


UNLABELLED_ON_PURPOSE: set[str] = set()


def labels_fixtures_dir() -> Path:
    return Path(labels.__file__).parent / "fixtures"
