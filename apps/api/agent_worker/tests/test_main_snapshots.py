"""Tests for how `main` wires page snapshots: the configuration check, the preflight, the start line (C9-T10).

HOW TO READ THIS
  C9 adds two checks to `main` and one field to its start line, and C8-D6 pinned the ORDER of everything `main` does
  (the endpoint and `MONGODB_URI` checks, then the scheduled-run gate, then the Atlas ping, then the start line). These
  tests pin where C9's pieces sit in that order:

    * `snapshot_config_problem` is a PURE check, so it sits with the other two before the gate: a skipped scheduled run
      with the flag off still exits 2 on a hosted service with no R2 settings, which is how a skip proves the service's
      configuration is complete (C9-D8; production's skip proof at C11 will exercise it);
    * `store.check()` is I/O, so it sits after the Atlas ping and before the start line: a wrong token stops the worker
      before any venue is fetched, and a run that stops there logs no start line (C9-D8).

  Nothing here reaches R2, MongoDB or Postgres. The tests replace `snapshot_store_from_settings` (the one module-level
  function `main` builds its store through, C9-D8) with a stand-in, and `configure_worker` pins the four `R2_*` settings
  whatever a laptop's `.env` holds (C9-PR1-2). Stand-ins for the client and the log are in `main_stubs.py`. Expected
  exit codes and lines are written here from the plan.

docs/dev/implementations/c9-r2-snapshots.md, C9-D2, C9-D8, C9-PR1-1, C9-PR1-2; c8-worker-on-railway.md, C8-D6.
"""

from typing import Any

import pytest
from pydantic import SecretStr

from agent_worker import main
from agent_worker.snapshots import NoSnapshotStore, SnapshotError
from agent_worker.tests.main_stubs import AnsweringClient, DeadClient, Log, RecordingWriter, configure_worker


@pytest.fixture
def log(monkeypatch: pytest.MonkeyPatch) -> Log:
    """Replace `main.log` with a recorder, so a test can read the lines `main` logged (their text and fields)."""
    recorder = Log()
    monkeypatch.setattr(main, "log", recorder)
    return recorder


class NeverBuilt:
    """An `AsyncMongoClient` replacement that fails the test if the run got as far as building one."""

    def __init__(self, *_: Any, **__: Any) -> None:
        raise AssertionError("a MongoDB client was built: the run went past a check that should have stopped it")


class StandInStore:
    """Replaces the real store: `check()` succeeds, or raises the `SnapshotError` it was given. Connects to nothing."""

    def __init__(self, *, check_error: SnapshotError | None = None) -> None:
        self.check_error = check_error
        self.checked = 0

    async def put(self, **_: Any) -> None:
        return None

    async def check(self) -> None:
        self.checked += 1
        if self.check_error is not None:
            raise self.check_error


def use_store(monkeypatch: pytest.MonkeyPatch, store: StandInStore | NoSnapshotStore) -> None:
    """Make `main` build `store` instead of a real store."""
    monkeypatch.setattr(main, "snapshot_store_from_settings", lambda: store)


async def no_venues(*_: Any, **__: Any) -> int:
    """A `run_all` stand-in that processes no venue and reports zero failures, so `main` runs to a clean exit 0."""
    return 0


# ---------------------------------------------------------------------------
# The configuration check, before the gate (C9-D8)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("trigger", ["scheduled", "manual"])
async def test_a_hosted_start_with_no_r2_settings_returns_two(
    monkeypatch: pytest.MonkeyPatch, log: Log, trigger: str
) -> None:
    # Proves (C9-D8, C9-D2): a HOSTED worker with none of the four R2 settings returns 2 and logs a sentence that names
    # them, before any connection is made (the MongoDB client is one that raises if built). Under C9 a hosted worker
    # without a bucket would write fetch rows with no page behind them, so it refuses to start instead.
    configure_worker(monkeypatch, "staging")
    for name in ("r2_endpoint_url", "r2_access_key_id", "r2_secret_access_key", "r2_bucket"):
        monkeypatch.setattr(main.settings, name, None)
    monkeypatch.setattr(main, "AsyncMongoClient", NeverBuilt)

    assert await main.main(["--trigger", trigger]) == 2

    assert len(log.errors) == 1 and "R2_" in log.errors[0][0]
    assert log.infos == []


async def test_a_skipped_scheduled_run_still_requires_the_r2_settings(
    monkeypatch: pytest.MonkeyPatch, log: Log
) -> None:
    # Proves (C9-D8, C8-D6): with the scheduled-run flag OFF, a hosted worker missing one R2 setting still exits 2, not 0.
    # The check is placed BEFORE the gate, like the model endpoint and `MONGODB_URI`, so a skipped run proves the
    # service is configured completely. If the check sat after the gate, a production cron service would "skip"
    # happily and fail only on the day someone armed it. This is the order trap the plan's Step 6 warns about.
    configure_worker(monkeypatch, "staging")
    monkeypatch.setattr(main.settings, "r2_secret_access_key", None)
    monkeypatch.setattr(main, "is_enabled", lambda *_, **__: False)
    monkeypatch.setattr(main, "AsyncMongoClient", NeverBuilt)

    assert await main.main(["--trigger", "scheduled"]) == 2
    assert log.infos == []


async def test_a_skipped_scheduled_run_with_the_r2_settings_complete_still_exits_zero(
    monkeypatch: pytest.MonkeyPatch, log: Log
) -> None:
    # Proves (C9-D8, C8-D6): the same hosted worker with all four settings set and the flag off skips as before (exit 0,
    # the one skip line) and touches no store: the preflight is I/O and sits after the gate, so a skipped run opens
    # nothing. A stand-in that raises if built would catch a preflight placed before the gate.
    configure_worker(monkeypatch, "staging")
    monkeypatch.setattr(main, "is_enabled", lambda *_, **__: False)
    monkeypatch.setattr(main, "AsyncMongoClient", NeverBuilt)

    def must_not_build() -> None:
        raise AssertionError("a snapshot store was built for a skipped run")

    monkeypatch.setattr(main, "snapshot_store_from_settings", must_not_build)

    assert await main.main(["--trigger", "scheduled"]) == 0
    assert len(log.infos) == 1


# ---------------------------------------------------------------------------
# The preflight, after the ping and before the start line (C9-D8)
# ---------------------------------------------------------------------------


async def test_a_failing_preflight_returns_two_with_no_start_line(monkeypatch: pytest.MonkeyPatch, log: Log) -> None:
    # Proves (C9-D8, C9-D14): when `store.check()` fails (a wrong token, a wrong bucket) `main` logs the reason and its
    # `kind` and returns 2 BEFORE the start line and before any venue run, so a bad credential stops the worker
    # instead of failing every venue's snapshot mid-run. The Atlas ping has already succeeded (the store is checked
    # after it), and `run_all` is a stand-in that fails the test if reached.
    configure_worker(monkeypatch, "staging")
    monkeypatch.setattr(main, "AsyncMongoClient", AnsweringClient)
    monkeypatch.setattr(main, "PostgresAuditWriter", RecordingWriter)
    use_store(monkeypatch, StandInStore(check_error=SnapshotError("denied", kind="auth", code="AccessDenied")))

    async def must_not_run(*_: Any, **__: Any) -> int:
        raise AssertionError("run_all was reached after a failed preflight")

    monkeypatch.setattr(main, "run_all", must_not_run)

    assert await main.main(["--trigger", "manual"]) == 2

    assert log.infos == []
    assert len(log.errors) == 1
    _, fields = log.errors[0]
    assert fields["kind"] == "auth" and fields["code"] == "AccessDenied"


async def test_the_preflight_comes_after_the_atlas_ping(monkeypatch: pytest.MonkeyPatch, log: Log) -> None:
    # Proves (C9-D8, C8-D6): when MongoDB does not answer, `main` returns 2 at the ping and never builds the store, so C8's
    # message for an unreachable Atlas is still the one an operator sees and the order C8 pinned has not moved.
    configure_worker(monkeypatch, "staging")
    monkeypatch.setattr(main, "AsyncMongoClient", DeadClient)

    def must_not_build() -> None:
        raise AssertionError("the store was built before the Atlas ping answered")

    monkeypatch.setattr(main, "snapshot_store_from_settings", must_not_build)

    assert await main.main(["--trigger", "manual"]) == 2
    assert log.errors[0][0] == main.mongo_unreachable_message("staging")


# ---------------------------------------------------------------------------
# What the run reports and hands to the graph (C9-D2, C9-D6)
# ---------------------------------------------------------------------------


async def test_a_laptop_with_no_r2_settings_runs_with_snapshots_off(monkeypatch: pytest.MonkeyPatch, log: Log) -> None:
    # Proves (C9-D2): a local worker with none of the four settings runs, exits 0, and its start line says
    # `snapshots="off"`, so the missing bucket is stated in the log and not silent. With the real
    # `snapshot_store_from_settings` (not replaced here) the store it builds is the one that writes nothing.
    configure_worker(monkeypatch, "local")
    monkeypatch.setattr(main, "AsyncMongoClient", AnsweringClient)
    monkeypatch.setattr(main, "PostgresAuditWriter", RecordingWriter)
    monkeypatch.setattr(main, "run_all", no_venues)

    assert await main.main([]) == 0

    assert log.infos[0][1]["snapshots"] == "off"
    assert main.snapshot_store_from_settings().__class__ is NoSnapshotStore


async def test_a_configured_worker_names_its_bucket_and_hands_the_store_to_the_context(
    monkeypatch: pytest.MonkeyPatch, log: Log
) -> None:
    # Proves (C9-D2, C9-D6, C9-D8): a hosted worker's start line carries its bucket name in `snapshots`, its store is
    # checked exactly once, and that same store object is the one on the `WorkerContext` that `run_all` receives, so
    # the graph writes to the bucket the log names. A `main` that built the store but left the context's default
    # in place would pass the first two and fail the third.
    configure_worker(monkeypatch, "staging")
    store = StandInStore()
    use_store(monkeypatch, store)
    monkeypatch.setattr(main, "AsyncMongoClient", AnsweringClient)
    monkeypatch.setattr(main, "PostgresAuditWriter", RecordingWriter)
    received: list[Any] = []

    async def run_all(_session_factory: Any, ctx: Any, **__: Any) -> int:
        received.append(ctx)
        return 0

    monkeypatch.setattr(main, "run_all", run_all)

    assert await main.main(["--trigger", "manual"]) == 0

    assert log.infos[0][1]["snapshots"] == "pebblebeats-snapshots-staging"
    assert store.checked == 1
    assert received[0].snapshots is store


# ---------------------------------------------------------------------------
# The real store builder (C9-D8)
# ---------------------------------------------------------------------------


def test_the_store_builder_returns_a_real_store_only_when_all_four_are_set(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (C9-D2, C9-D8): `snapshot_store_from_settings` returns the real store when the four settings are set and the
    # write-nothing store when they are not. Building the real store only constructs a boto3 client (no network), so this
    # needs no stand-in; the bucket on it is the one the settings name.
    from agent_worker.snapshots import S3SnapshotStore

    configure_worker(monkeypatch, "staging")
    built = main.snapshot_store_from_settings()
    assert isinstance(built, S3SnapshotStore)

    monkeypatch.setattr(main.settings, "r2_secret_access_key", SecretStr("test-secret"))
    monkeypatch.setattr(main.settings, "r2_bucket", None)
    assert isinstance(main.snapshot_store_from_settings(), NoSnapshotStore)
