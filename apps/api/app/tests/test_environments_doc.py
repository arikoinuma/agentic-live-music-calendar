"""Tests that `docs/dev/environments.md` lists exactly the variables `Settings` reads (C3-T6).

HOW TO READ THIS
  `docs/dev/environments.md` carries the secrets inventory: every variable, per environment, with no values. It is
  only worth having if it cannot drift from the code, so this test compares it with the real `Settings` class.
  The API's variables sit in the inventory between two marker comments (`settings-inventory:start` and
  `settings-inventory:end`), one table row each, the name in backticks in the first column. Variables that
  `Settings` does not read (Vercel's, Railway's own) live outside the markers and are not compared.

  The expected set comes from `Settings.model_fields`, not from the document; the document is what is checked.
"""

import re
from pathlib import Path

import pytest

from app.config import Settings

DOC = Path(__file__).resolve().parents[4] / "docs" / "dev" / "environments.md"
START, END = "<!-- settings-inventory:start -->", "<!-- settings-inventory:end -->"


def inventory_names() -> set[str]:
    """The variable names listed between the markers: the backticked token that opens each table row."""
    text = DOC.read_text()
    assert START in text and END in text, "environments.md has lost its settings-inventory markers"
    block = text.split(START, 1)[1].split(END, 1)[0]
    return set(re.findall(r"^\|\s*`([A-Z][A-Z0-9_]*)`", block, flags=re.MULTILINE))


def test_every_settings_field_is_in_the_inventory() -> None:
    # Proves: a variable added to `Settings` without a line in the inventory fails the build, so the document
    # that Ari sets Railway's variables from cannot silently miss one (a missing variable is a failed deploy).
    expected = {name.upper() for name in Settings.model_fields}
    assert expected - inventory_names() == set()


def test_the_inventory_lists_no_variable_settings_does_not_read() -> None:
    # Proves: a variable renamed or removed in `Settings` cannot linger in the inventory, where it would be set
    # in a dashboard and do nothing. (`Settings` forbids unknown keys in `.env` but ignores unknown process
    # variables, so such a leftover would never raise.)
    expected = {name.upper() for name in Settings.model_fields}
    assert inventory_names() - expected == set()


@pytest.mark.parametrize("prefix", ["R2_", "API_SHARED_SECRET"])
def test_no_row_is_left_marked_reserved_outside_the_inventory_once_its_setting_exists(prefix: str) -> None:
    # Proves (C9-T14, C9-PR1-13, C10-T10): the two tests above read only the block between the markers, so an old
    # "reserved" row for a variable (outside them, in the table of variables `Settings` does not read) would survive the
    # milestone that built it without either failing. Once the four R2 settings (C9) and `API_SHARED_SECRET` (C10) exist
    # and are in the inventory, a leftover row saying they are reserved for a later milestone is stale documentation, and
    # this is the test that finds it. `API_SHARED_SECRET` has a Vercel-side row outside the markers, which must say what
    # it is now (the same secret, set on Vercel), never "reserved".
    text = DOC.read_text()
    outside = text.split(START, 1)[0] + text.split(END, 1)[1]
    stale = [
        line for line in outside.splitlines() if re.match(rf"^\|\s*`{prefix}", line) and "reserved" in line.lower()
    ]
    assert stale == []
