"""Root conftest: registers the shared DB fixtures as a plugin.

Lives at apps/api/ (the pytest rootdir) so the plugin is available to both
app/tests/ and, from A7, agent_worker/. See app/testing/db.py.
"""

# A pytest "plugin" here is just a module whose fixtures pytest loads for
# every test under this directory. Listing app.testing.db makes the database
# fixtures (db_conn, db_session, migrated_engine, ...) available by name to
# any test that asks for them as arguments — no import needed in the test.
pytest_plugins = ["app.testing.db"]
