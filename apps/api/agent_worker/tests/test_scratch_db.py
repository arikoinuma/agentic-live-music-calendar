"""Tests for the guard in front of the evaluation harness's scratch database (`eval/scratch_db.py`).

Milestone C5 (docs/dev/implementations/c5-pipeline-eval-harness.md, C5-D2). The harness creates and drops a database called
`calendar_eval` and truncates tables in it, so, like the test fixtures (`app/testing/db.py`), it refuses to touch anything else. It
cannot reuse those helpers: `app/tests/test_no_testing_imports.py` scans `agent_worker/eval/` and forbids `app.testing` imports,
so the guard is its own small copy and these are its tests. No database is involved: the guard is pure.

Expected values are the rules in the plan: the name is the constant `calendar_eval` and the host is this machine.
"""

import pytest
from sqlalchemy.engine import make_url

from agent_worker.eval import scratch_db


def test_the_eval_database_url_is_the_configured_server_with_the_eval_name() -> None:
    # Proves: the target is derived from DATABASE_URL by swapping the database name, so the harness always runs on the same
    # server (and credentials) the developer already uses, never a name somebody typed.
    url = scratch_db.eval_database_url("postgresql+asyncpg://postgres:pw@localhost:5432/calendar_dev")
    assert url.database == "calendar_eval"
    assert (url.host, url.username, url.port) == ("localhost", "postgres", 5432)


def test_the_guard_accepts_the_eval_database_on_a_local_host() -> None:
    # Proves: the one allowed target passes. (Both loopback spellings.)
    for host in ("localhost", "127.0.0.1", "[::1]"):  # an IPv6 literal is bracketed in a URL
        scratch_db.check_eval_database_url(make_url(f"postgresql+asyncpg://u:p@{host}/calendar_eval"))


@pytest.mark.parametrize("name", ["calendar_test", "calendar_dev", "calendar", "postgres", "calendar_eval2"])
def test_the_guard_refuses_any_other_database_name(name: str) -> None:
    # Proves: C5-M7. The harness drops and truncates, so any name but the constant is refused, including the test database
    # (which another run may be using) and the developer's. If the guard accepted `calendar_test`, a harness run could wipe a
    # running test session's data.
    with pytest.raises(scratch_db.UnsafeEvalDatabaseError, match=name):
        scratch_db.check_eval_database_url(make_url(f"postgresql+asyncpg://u:p@localhost/{name}"))


def test_the_guard_refuses_a_host_that_is_not_this_machine() -> None:
    # Proves: a DATABASE_URL pointing at a hosted Neon branch would otherwise make `calendar_eval` a CREATE DATABASE on the
    # hosted server. The rule from AGENTS.md ("reach a hosted database only with a one-command override") applies: the harness
    # never does.
    with pytest.raises(scratch_db.UnsafeEvalDatabaseError, match="neon.example"):
        scratch_db.check_eval_database_url(make_url("postgresql+asyncpg://u:p@neon.example/calendar_eval"))
