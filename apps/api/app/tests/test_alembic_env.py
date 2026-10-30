"""How `migrations/env.py` reads the database URL, tested through the real `alembic` command.

WHAT THIS COVERS
  The rest of the suite drives Alembic with an injected connection (app/testing/db.py), which skips the line of
  `env.py` that copies `DATABASE_URL` into Alembic's config. That line is what a hosted deploy and a person at a prompt
  actually use, so it needs a test that goes through it: the real `alembic` process, started the way the pre-deploy
  step starts it, with the URL in the environment.

  Found by the C4 migration-rehearsal smoke test (docs/dev/environments.md, "Rehearsing a migration"): Alembic keeps
  its settings in a `configparser` object, which treats `%` as the start of an interpolation, so a URL with a
  percent-encoded character in it (any role password containing `@`, `:`, `/` or `#`, once encoded) crashed
  `alembic upgrade head` with "invalid interpolation syntax". Neon role passwords are chosen by us (C3-D9), so this
  is reachable.
"""

import asyncio
import os
import sys

from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine

from app.testing.db import API_DIR


async def test_alembic_accepts_a_database_url_that_contains_a_percent_escape(
    database_url_for_tests: URL,
    migrated_engine: AsyncEngine,  # not used directly: it makes sure calendar_test exists and is at head
) -> None:
    # Proves: `alembic current` runs, and reports the head revision, when `DATABASE_URL` holds a percent-encoded
    # character. The URL here is the test database's own with the first letter of the user name written as `%70`
    # (`p`), which decodes to the same user, so it connects exactly as before and the ONLY difference is the `%`.
    # Catches env.py handing the raw URL to configparser (fails with "invalid interpolation syntax").
    user = database_url_for_tests.username
    assert user, "the test database URL has no user name to encode"
    plain = database_url_for_tests.render_as_string(hide_password=False)
    escaped = plain.replace(f"//{user}:", f"//%{ord(user[0]):02X}{user[1:]}:", 1)
    assert "%" in escaped and escaped != plain

    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "alembic",
        "current",
        cwd=API_DIR,
        env={**os.environ, "DATABASE_URL": escaped},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    # Alembic reports through its logger, which alembic.ini sends to stderr, so read both streams.
    output = stdout.decode() + stderr.decode()
    assert process.returncode == 0, output
    assert "(head)" in output
