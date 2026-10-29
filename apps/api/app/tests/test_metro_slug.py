"""Metro slugs: the shape rule and the reserved-word list, checked against the seed and the sample world.

WHAT THIS COVERS
  A metro's slug is the first label of its web address (`msp.<domain>`), so two rules apply to it (C4-D2):
  its shape (3 to 32 characters, a letter first, lowercase letters, digits and hyphens, not ending in a hyphen)
  and a list of reserved words (`www`, `api`, `staging`, ...) that can never be a metro, because they are
  already something else in the environment's addressing (Dep-D3).

  The database enforces the shape (a CHECK constraint, tested in test_db_schema.py). The reserved list lives in
  one JSON file the Next.js app also imports, `apps/calendar/lib/reserved-slugs.json`; the API's deploy root
  cannot read it at run time, which is fine because only this test, run in CI where the whole repo is checked
  out, needs to. So the test is the guard that a slug added to the seed or the sample world is allowed.

Expected values are written in this file from the rule, not read from the code under test.
"""

import json
import re
from pathlib import Path

from app.db.seed import METRO_SLUG
from app.testing import sample_data

# apps/api/app/tests/ -> the repository root is four parents up from this file's directory.
RESERVED_FILE = Path(__file__).resolve().parents[4] / "apps" / "calendar" / "lib" / "reserved-slugs.json"

# The shape rule of C4-D2, restated here independently of the migration's CHECK expression.
SHAPE = re.compile(r"[a-z][a-z0-9-]{1,30}[a-z0-9]")


def _reserved() -> list[str]:
    return json.loads(RESERVED_FILE.read_text())


def test_the_reserved_list_exists_and_holds_the_words_the_environments_use() -> None:
    # Proves (C4-D2): the shared file is present, is a list of lowercase words, and holds at least the words Dep-D3
    # names plus the two environment names. `dev` and `staging` matter most: `staging.<domain>` is the staging
    # zone's apex and must never parse as a metro of the production zone.
    reserved = _reserved()
    assert all(word == word.lower() for word in reserved)
    assert {"www", "api", "admin", "dev", "staging"} <= set(reserved)


def test_the_seeded_metro_slug_is_well_formed_and_not_reserved() -> None:
    # Proves (C4-D2, Dep-D3): the production seed's slug is `msp`, matches the shape rule, and is not reserved.
    # Fails the day someone seeds a metro called `api`.
    assert METRO_SLUG == "msp"
    assert SHAPE.fullmatch(METRO_SLUG)
    assert METRO_SLUG not in _reserved()


def test_the_sample_worlds_metro_slug_is_well_formed_and_not_reserved() -> None:
    # Proves (C4-D2): the sample world (tests, fixtures, the e2e database) carries a slug that obeys the same rules,
    # so the fixtures the frontend reads never hold an address the real parser would refuse.
    slug = sample_data.METRO.slug
    assert SHAPE.fullmatch(slug)
    assert slug not in _reserved()
