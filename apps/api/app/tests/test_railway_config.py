"""Tests that `railway.toml` keeps the deploy settings the plan depends on (C3-D8).

HOW TO READ THIS
  `apps/api/railway.toml` is the API service's deploy configuration, in the repo instead of only in Railway's
  dashboard. Nothing here runs Railway; the file is parsed with the standard library and three properties are
  pinned. The expected values are literals from the plan (`c3-environments-and-deploy.md`, C3-D8 and T4), not read
  from the file under test.
"""

import tomllib
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[2] / "railway.toml"


def load() -> dict[str, dict[str, object]]:
    return tomllib.loads(CONFIG.read_text())


def test_the_start_command_binds_railways_port() -> None:
    # Proves: the service starts uvicorn on `$PORT`, the port Railway assigns. A hard-coded port, or a missing
    # `--host 0.0.0.0`, deploys fine and then never answers its health check.
    start = str(load()["deploy"]["startCommand"])
    assert "uvicorn app.main:app" in start
    assert "--host 0.0.0.0" in start
    assert "--port $PORT" in start


def test_the_health_check_is_health_and_never_health_db() -> None:
    # Proves (C3-D8): the deploy-time check is `/health`, which answers without querying the database. `/health/db`
    # would wake Neon on every deploy and make a database blip fail a deploy that is otherwise fine. This also
    # pins that a health check exists at all: without one Railway cannot keep the old deployment when a new one
    # refuses to start (the point of C3-D4's refusal).
    assert load()["deploy"]["healthcheckPath"] == "/health"


def test_migrations_run_before_the_new_code_starts() -> None:
    # Proves (C3-D8): `alembic upgrade head` is the pre-deploy command, so a deploy can never put code on a
    # database that lacks its tables (the failure C2's merge risked). A migration that fails stops the deploy and
    # the old version keeps serving.
    assert load()["deploy"]["preDeployCommand"] == ["uv run alembic upgrade head"]
