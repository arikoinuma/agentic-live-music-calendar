"""Root conftest: registers the shared DB fixtures as a plugin.

Lives at apps/api/ (the pytest rootdir) so the plugin is available to both
app/tests/ and, from A7, agent_worker/. See app/testing/db.py.
"""

# A pytest "plugin" here is just a module whose fixtures pytest loads for
# every test under this directory. Listing app.testing.db makes the database
# fixtures (db_conn, db_session, migrated_engine, ...) available by name to
# any test that asks for them as arguments — no import needed in the test.
pytest_plugins = ["app.testing.db"]

import pytest  # noqa: E402 - after `pytest_plugins`, which pytest reads from the module's top-level names

from app.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def _no_shared_secret_unless_a_test_sets_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test with no `API_SHARED_SECRET`, whatever a laptop's `apps/api/.env` holds (C10-D16, C10-PR1-2).

    The guard (`app/security.py`) lets a request through when the secret is unset and `APP_ENV` is `local`, which is what
    every route test relies on: they call the app with no header. A developer who put a secret in `.env` to try the
    wiring by hand would otherwise see 401 from the whole suite. A test that is about the guard sets the secret itself
    afterwards (an autouse fixture runs first), and `monkeypatch` puts the real value back. The same pattern pins the R2
    settings for the worker's tests (C9-D8).
    """
    monkeypatch.setattr(settings, "api_shared_secret", None)
