"""Tests for the labelling helper (`eval/label_draft.py`): candidate source lines, and nothing that answers the question.

Milestone C5 (docs/dev/implementations/c5-pipeline-eval-harness.md, Step 7, C5-K1). A label is what a PERFECT run would produce,
read from the page text; it must not be read from JSON-LD or a model's output (`labels.py` docstring). The helper exists to save
the copying, so it prints the page's visible lines, numbered, with the ones that look dated flagged, and it must never print an
act name from structured data.

Expected values are the constructed page's own lines.
"""

from agent_worker.eval import label_draft

PAGE = """<html><head>
<script type="application/ld+json">{"@type": "Event", "name": "Hidden Act From JSON-LD", "startDate": "2026-10-20"}</script>
</head><body>
<h1>Calendar</h1>
<p>Cowboy Thoughts / Buried Animals / Sat, Oct 10</p>
<p>Calendar</p>
<p>Open Mic Every Monday</p>
<p>Nona / Monday August 17 @ 9:00 pm</p>
</body></html>"""


def test_it_lists_the_visible_lines_numbered_and_flags_the_dated_ones() -> None:
    # Proves: the helper gives Ari ready-to-paste `source_line` candidates. Visible lines only, numbered in page order; those
    # containing a month and a day are flagged as dated. "Open Mic Every Monday" has a weekday but no date, so it is listed
    # unflagged (it is a recurring header, a `non_shows` entry, not a dated show).
    lines = label_draft.candidate_lines(PAGE)
    by_text = {text: (number, dated) for number, text, dated in lines}
    assert by_text["Cowboy Thoughts / Buried Animals / Sat, Oct 10"][1] is True
    assert by_text["Nona / Monday August 17 @ 9:00 pm"][1] is True
    assert by_text["Open Mic Every Monday"][1] is False
    numbers = [n for n, _, _ in lines]
    assert numbers == sorted(numbers)


def test_it_prints_each_repeated_line_once() -> None:
    # Proves: page chrome that repeats ("Calendar" in a heading and a nav link) is listed once, so the output is a list of
    # things to read, not the page's markup.
    texts = [text for _, text, _ in label_draft.candidate_lines(PAGE)]
    assert texts.count("Calendar") == 1


def test_it_never_prints_a_name_from_structured_data() -> None:
    # Proves: the labelling rule. The JSON-LD block names an act that appears nowhere in the visible text; the helper must not
    # show it, or the label would be drafted from structured data (and agree with the JSON-LD route by construction).
    printed = "\n".join(text for _, text, _ in label_draft.candidate_lines(PAGE))
    assert "Hidden Act From JSON-LD" not in printed
