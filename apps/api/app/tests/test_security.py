"""Tests for `app/security.py`: the shared-secret comparison, the hosted start-up rule and the docs switch (C10).

HOW TO READ THIS
  Three sections, all pure functions with no app and no database:
    1. `check_shared_secret` (C10-K1): which header values the guard accepts.
    2. `shared_secret_problem` (C10-K2): which secrets a hosted API refuses to start with.
    3. `openapi_url_for` (C10-D2): where the API serves its own schema.

  Where expected values come from: every row below is written by hand from the plan (the 32-character floor is
  C10-D9's own number), never read from the functions under test.
"""

import pytest

from app.config import settings
from app.main import app
from app.security import MIN_SECRET_LENGTH, check_shared_secret, openapi_url_for, shared_secret_problem

SECRET = "k" * 40

# --- check_shared_secret (C10-K1) ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("supplied", "expected_result"),
    [
        (SECRET, True),  # the right value
        ("j" * 40, False),  # the same length, every character different
        (SECRET[:-1], False),  # a prefix of the secret
        (SECRET + "k", False),  # an extension of it
        ("", False),  # an empty header
        (None, False),  # no header at all
        ("é" * 40, False),  # non-ASCII: a `str` compare_digest would raise here
        ("🔑" * 10, False),  # not even Latin-1
    ],
    ids=["right", "same-length", "prefix", "extension", "empty", "absent", "latin1", "emoji"],
)
def test_check_shared_secret_accepts_only_the_exact_value(supplied: str | None, expected_result: bool) -> None:
    # Proves (C10-K1, C10-D8): only the exact secret passes, an absent header is the same plain refusal as a wrong one
    # (C10-D7), and a non-ASCII value is refused rather than crashing: `secrets.compare_digest` on `str` raises
    # `TypeError` for non-ASCII text, which would turn an attacker-chosen header into a 500, a visible difference from
    # the 401 every other wrong value gets. A timing-safe comparison cannot be shown by a table, so the call itself
    # is also read in code review (C10-M2).
    assert check_shared_secret(supplied, SECRET) is expected_result


# --- shared_secret_problem (C10-K2) --------------------------------------------------------------------------------


@pytest.mark.parametrize("app_env", ["dev", "staging", "prod"])
def test_shared_secret_problem_refuses_a_missing_secret(app_env: str) -> None:
    # Proves (C10-K2, C10-D9): a hosted API with no secret is a problem, named by variable, so the start-up failure
    # tells whoever reads the deploy log what to set. The alternative ("enforce only when it is set") makes a forgotten
    # variable a public API with a green deploy.
    problem = shared_secret_problem(app_env, None)  # type: ignore[arg-type]
    assert problem is not None and "API_SHARED_SECRET" in problem and app_env in problem


@pytest.mark.parametrize("app_env", ["dev", "staging", "prod"])
def test_shared_secret_problem_enforces_the_length_floor(app_env: str) -> None:
    # Proves (C10-K2, C10-D9): 31 characters is refused and 32 passes, so a pasted placeholder ("changeme") fails at
    # deploy time instead of becoming a guessable production secret. The sentence never contains the value it
    # rejects (a deploy log is not a place for secrets).
    too_short = "s" * (MIN_SECRET_LENGTH - 1)
    problem = shared_secret_problem(app_env, too_short)  # type: ignore[arg-type]
    assert problem is not None and "API_SHARED_SECRET" in problem and too_short not in problem
    assert shared_secret_problem(app_env, "s" * MIN_SECRET_LENGTH) is None  # type: ignore[arg-type]


def test_the_length_floor_is_the_plans_number() -> None:
    # Proves (C10-D9): the floor is 32, the length of 16 random bytes in hex; a changed constant would move the
    # boundary rows above along with it, so the number is pinned here as a literal.
    assert MIN_SECRET_LENGTH == 32


# --- openapi_url_for (C10-D2, PQR1-12) -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("app_env", "url"),
    [("local", "/openapi.json"), ("dev", "/openapi.json"), ("staging", None), ("prod", None)],
)
def test_openapi_url_for_serves_the_schema_only_where_a_developer_reads_it(app_env: str, url: str | None) -> None:
    # Proves (C10-D2, PQR1-12): `/docs`, `/redoc` and `/openapi.json` exist on a laptop and in dev and are switched
    # off on staging and production. They are plain Starlette routes, so the shared-secret guard never runs on them:
    # leaving them on would serve the API's schema to anyone even with the guard in place.
    assert openapi_url_for(app_env) == url  # type: ignore[arg-type]


def test_the_app_is_built_with_the_switch() -> None:
    # Proves (C10-D2): the switch is wired into the app, not just defined. The suite runs as `local`, so the schema
    # route is served, which is also what `make dev` relies on.
    assert app.openapi_url == openapi_url_for(settings.app_env)
