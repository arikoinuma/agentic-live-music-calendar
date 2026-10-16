"""Tests for the A2.1 helpers in `agent_worker/normalize.py`: the year rule and text folding.

`infer_year` is A2.1-D13 of docs/dev/implementations/a2.1-extraction-reliability.md: the model is
never trusted with a year a page may not state (Mortimer's states none; the model guessed
2024). Code sets it from the fetch date instead. `fold_text` is the one spelling-normaliser
shared by the act splitter's title cross-check and the eval's scorer, so "The Dan’s" and
"The Dan's" are the same name everywhere.

How to read it: sections run year rule -> text folding. Expected values come from the rule as
A2.1-D13 states it ("the fetch date's year, unless that would put the date more than 31 days
before the fetch date, then the next year") and from what the characters are — never from
the functions under test.
"""

import datetime

import pytest

from agent_worker.normalize import fold_text, infer_year

D = datetime.date


# ---------------------------------------------------------------------------
# infer_year (A2.1-D13)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fetched", "listed", "expected"),
    [
        # Mid-October scan: upcoming dates keep this year.
        (D(2026, 10, 10), D(2024, 10, 31), D(2026, 10, 31)),
        # A date up to 31 days back is still this year (a listing the page hasn't removed yet).
        (D(2026, 10, 10), D(2024, 9, 15), D(2026, 9, 15)),
        # More than 31 days back can't be an upcoming listing, so it's next year.
        (D(2026, 10, 10), D(2024, 8, 1), D(2027, 8, 1)),
        (D(2026, 10, 10), D(2024, 1, 15), D(2027, 1, 15)),
        # Ari's case: scanning January/February listings in November/December.
        (D(2026, 12, 20), D(2024, 2, 3), D(2027, 2, 3)),
        (D(2026, 12, 20), D(2024, 12, 31), D(2026, 12, 31)),
        # Early-January scan: a late-December listing within 31 days is LAST year.
        (D(2027, 1, 10), D(2024, 12, 20), D(2026, 12, 20)),
        # Leap day: the chosen year has a Feb 29 (2028) -> used.
        (D(2027, 12, 20), D(2024, 2, 29), D(2028, 2, 29)),
    ],
)
def test_infer_year_sets_the_year_from_the_fetch_date(
    fetched: datetime.date, listed: datetime.date, expected: datetime.date
) -> None:
    # Proves: A2.1-D13's rule, case by case, including both year boundaries. The listed year
    # (2024 here, what the model guessed for Mortimer's) is ignored on purpose: the rule
    # overrides the model's year even where a page states one, because on a page of
    # upcoming listings the rule gives the same answer and removes a class of guess.
    assert infer_year(listed, fetched) == expected


def test_infer_year_leaves_an_impossible_leap_day_alone() -> None:
    # Proves: a Feb 29 the chosen year doesn't have (2027) doesn't raise. The model's date
    # is returned unchanged and A3's plausibility check is the backstop (plan, A2.1-D13 tests).
    assert infer_year(D(2024, 2, 29), D(2026, 10, 10)) == D(2024, 2, 29)


# ---------------------------------------------------------------------------
# fold_text: one spelling normaliser for names
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "folded"),
    [
        ("The Dan’s", "the dan's"),  # right single quote (the pages' apostrophe)
        ("Bury ‘Em Deep", "bury 'em deep"),  # left single quote
        ("“Quoted”", '"quoted"'),
        ("Back–to—Back", "back-to-back"),  # en and em dash
        ("Martin Devaney &#038; Friends", "martin devaney & friends"),  # HTML entity
        ("Ca Sual", "ca sual"),  # non-breaking space
        ("  extra   spaces \n here ", "extra spaces here"),
        ("ＦＵＬＬＷＩＤＴＨ", "fullwidth"),  # NFKC compatibility form
    ],
)
def test_fold_text_makes_spelling_variants_equal(raw: str, folded: str) -> None:
    # Proves: the variants that appear between a page, its JSON-LD and a model's echo all
    # fold to one form (A2.1-PR1-5: NFKC alone leaves "Dan’s" != "Dan's"). Case is
    # folded too, because act names are compared, not displayed, after folding.
    assert fold_text(raw) == folded
