"""Tests for the scheduled-run gate in `agent_worker/main.py` (C3.1-T11).

HOW TO READ THIS
  A worker started with `--trigger scheduled` exits 0 with one log line when the feature flag
  `worker.scheduled_runs` is off, and runs when it is on; `--trigger manual` ignores the flag (C3.1-D1, C3.1-D13,
  Dep-D12). The gate sits after the model-endpoint and `MONGODB_URI` checks and before the Atlas ping
  (C3.1-D14, C8-D6), so a skipped run proves the configuration is complete without opening a connection.

  Everything `main` would connect to is replaced: `AsyncMongoClient` by a stand-in (that raises if built, or whose
  ping fails, or that answers), `run_all` and `PostgresAuditWriter` by recorders, and the log by a list. The
  tests patch `agent_worker.main.is_enabled`, the name `main` imports (the seam C8's tests also use), except one
  that runs the real function. Exit codes are C8-D6's: 0 for a skip, 2 for a configuration problem. Expected
  values are written here from the plan, not read from the code under test.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from pymongo.errors import ServerSelectionTimeoutError

from agent_worker import main
from app.enums import RunTrigger


class Log:
    """Stands in for the module's structlog logger and records the calls instead of printing them."""

    def __init__(self) -> None:
        self.infos: list[tuple[str, dict[str, Any]]] = []
        self.errors: list[str] = []

    def info(self, event: str, **fields: Any) -> None:
        self.infos.append((event, fields))

    def error(self, event: str, **fields: Any) -> None:
        self.errors.append(event)


@pytest.fixture
def log(monkeypatch: pytest.MonkeyPatch) -> Log:
    recorder = Log()
    monkeypatch.setattr(main, "log", recorder)
    return recorder


@pytest.fixture(autouse=True)
def configured_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    # A configuration that passes both checks before the gate, so each test changes exactly the one thing it is
    # about. `local` may point at a local model endpoint (`model_endpoint_problem`).
    monkeypatch.setattr(main.settings, "app_env", "local")
    monkeypatch.setattr(main.settings, "model_provider", "ollama")
    monkeypatch.setattr(main.settings, "model_base_url", "http://localhost:11434/v1")
    monkeypatch.setattr(main.settings, "mongodb_uri", "mongodb://localhost:1")


def flag(value: bool, asked: list[str] | None = None) -> Any:
    """A replacement `is_enabled` that answers `value` and records the names it was asked about."""

    def is_enabled(name: str, *, metro: str | None = None) -> bool:
        if asked is not None:
            asked.append(name)
        return value

    return is_enabled


class NeverBuilt:
    """An `AsyncMongoClient` replacement that fails the test if the gate lets the run get as far as building one."""

    def __init__(self, *_: Any, **__: Any) -> None:
        raise AssertionError("a MongoDB client was built: the skipped run went past the gate")


class DeadClient:
    """A MongoDB client whose ping fails: `main` returns 2 right after building it. Reaching it proves the run
    went past the gate."""

    built = 0

    def __init__(self, *_: Any, **__: Any) -> None:
        type(self).built += 1
        self.admin = SimpleNamespace(command=self._ping)

    async def _ping(self, *_: Any, **__: Any) -> None:
        raise ServerSelectionTimeoutError("no server")

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# A skipped scheduled run (C3.1-D13)
# ---------------------------------------------------------------------------


async def test_a_scheduled_run_with_the_flag_off_exits_zero_and_opens_nothing(
    monkeypatch: pytest.MonkeyPatch, log: Log
) -> None:
    # Proves (C3.1-T11, C3.1-D1, C3.1-D13): with the flag off, `--trigger scheduled` returns 0 and touches
    # nothing: no MongoDB client is built, no run is opened (`run_all` is never called, so the session factory is
    # never used), and no audit writer is made. Exit 0, not non-zero, because a non-zero exit may be retried by
    # Railway's restart policy (C8-U2). The three replacements raise if reached, so a gate placed too late fails
    # loudly instead of passing by doing nothing.
    async def must_not_run(*_: Any, **__: Any) -> int:
        raise AssertionError("run_all was reached: the skipped run opened runs")

    def must_not_write(*_: Any, **__: Any) -> None:
        raise AssertionError("an audit writer was built for a skipped run")

    monkeypatch.setattr(main, "is_enabled", flag(False))
    monkeypatch.setattr(main, "AsyncMongoClient", NeverBuilt)
    monkeypatch.setattr(main, "run_all", must_not_run)
    monkeypatch.setattr(main, "PostgresAuditWriter", must_not_write)

    assert await main.main(["--trigger", "scheduled"]) == 0


async def test_the_skip_logs_one_line_naming_the_flag_and_its_variable(
    monkeypatch: pytest.MonkeyPatch, log: Log
) -> None:
    # Proves (C3.1-T11, C3.1-D13): a skipped run says so once, naming the flag and the variable that arms it, so
    # whoever reads the Railway log knows it was deliberate and how to change it. A silent exit 0 would look
    # exactly like a worker that ran and found nothing to do. Expected strings are the plan's.
    monkeypatch.setattr(main, "is_enabled", flag(False))
    monkeypatch.setattr(main, "AsyncMongoClient", NeverBuilt)

    await main.main(["--trigger", "scheduled"])

    assert len(log.infos) == 1
    event, fields = log.infos[0]
    assert "skipped" in event and "worker.scheduled_runs" in event
    assert fields["flag"] == "worker.scheduled_runs"
    assert fields["variable"] == "FLAG_WORKER_SCHEDULED_RUNS"


async def test_the_gate_asks_for_the_scheduled_runs_flag_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch, log: Log
) -> None:
    # Proves (C3.1-T11, C3.1-D14): the gate reads exactly `worker.scheduled_runs`, and passes no metro (it is
    # process-level; the flag is environment-scoped). C8's tests patch the same name on the same seam.
    asked: list[str] = []
    monkeypatch.setattr(main, "is_enabled", flag(False, asked))
    monkeypatch.setattr(main, "AsyncMongoClient", NeverBuilt)

    await main.main(["--trigger", "scheduled"])

    assert asked == ["worker.scheduled_runs"]


async def test_the_real_flag_is_off_when_its_variable_is_unset(monkeypatch: pytest.MonkeyPatch, log: Log) -> None:
    # Proves (C3.1-T11, C3.1-D1): with nothing patched and the variable unset, a scheduled run skips: the default
    # is off in every environment, so a freshly created Railway cron service does no work until someone arms it.
    # This is the path that needs `resolve_value` (C3.1-K1) to be filled in.
    monkeypatch.delenv("FLAG_WORKER_SCHEDULED_RUNS", raising=False)
    monkeypatch.setattr(main, "AsyncMongoClient", NeverBuilt)

    assert await main.main(["--trigger", "scheduled"]) == 0
    assert len(log.infos) == 1


async def test_the_real_flag_arms_the_run_when_its_variable_is_true(monkeypatch: pytest.MonkeyPatch, log: Log) -> None:
    # Proves (C3.1-T11, C3.1-D1): with the variable set to `true` and nothing patched, a scheduled run gets past the
    # gate (it reaches the MongoDB client and fails at the ping, 2). Needs `resolve_value` (C3.1-K1) filled in.
    monkeypatch.setenv("FLAG_WORKER_SCHEDULED_RUNS", "true")
    monkeypatch.setattr(main, "AsyncMongoClient", DeadClient)

    assert await main.main(["--trigger", "scheduled"]) == 2


# ---------------------------------------------------------------------------
# A scheduled run with the flag on, and a manual run (C3.1-D13, Dep-D12)
# ---------------------------------------------------------------------------


async def test_a_scheduled_run_with_the_flag_on_proceeds_past_the_gate(
    monkeypatch: pytest.MonkeyPatch, log: Log
) -> None:
    # Proves (C3.1-T11, C3.1-D14): with the flag on, the run is not skipped: it builds the MongoDB client and pings
    # it (the dead stand-in then makes `main` return 2). That `DeadClient` was built is the evidence the gate let
    # the run through; the exit code alone could not tell "gated" from "proceeded and failed".
    DeadClient.built = 0
    monkeypatch.setattr(main, "is_enabled", flag(True))
    monkeypatch.setattr(main, "AsyncMongoClient", DeadClient)

    assert await main.main(["--trigger", "scheduled"]) == 2
    assert DeadClient.built == 1
    assert log.infos == []


async def test_a_manual_run_ignores_the_flag(monkeypatch: pytest.MonkeyPatch, log: Log) -> None:
    # Proves (C3.1-T11, C3.1-D13, Dep-D12): `--trigger manual` (the default) proceeds with the flag off, and does
    # not even consult it. A gate that applied to every trigger would stop Ari's own `make worker` runs.
    asked: list[str] = []
    DeadClient.built = 0
    monkeypatch.setattr(main, "is_enabled", flag(False, asked))
    monkeypatch.setattr(main, "AsyncMongoClient", DeadClient)

    assert await main.main([]) == 2
    assert await main.main(["--trigger", "manual"]) == 2
    assert DeadClient.built == 2
    assert asked == []


@pytest.mark.parametrize("trigger", [RunTrigger.SUBMISSION, RunTrigger.FLAG_THRESHOLD])
async def test_the_triggers_nothing_starts_yet_are_refused(trigger: RunTrigger) -> None:
    # Proves (C3.1-T11, C3.1-D13): `submission` and `flag_threshold` are real `RunTrigger` values but nothing
    # starts them, and `main` would run every venue for them with the gate skipped. Argument parsing refuses them
    # (argparse exits with status 2), so a mistyped cron command cannot walk past the gate. Widen `choices` when
    # something starts them, on purpose.
    with pytest.raises(SystemExit) as exit_info:
        await main.main(["--trigger", trigger.value])
    assert exit_info.value.code == 2


# ---------------------------------------------------------------------------
# The gate's place in the order (C3.1-D14, C8-D6)
# ---------------------------------------------------------------------------


async def test_a_skipped_run_still_requires_the_model_endpoint(monkeypatch: pytest.MonkeyPatch, log: Log) -> None:
    # Proves (C3.1-T11, C3.1-D14, C8-D6): with the flag OFF, a missing `MODEL_BASE_URL` still returns 2. The skip
    # therefore proves the service's configuration is complete; if the gate came first, a cron service with a
    # broken model endpoint would "skip" happily and fail only on the day someone armed it. Mutation M5 (the gate
    # moved above these checks) turns this and the next test red.
    monkeypatch.setattr(main.settings, "model_base_url", None)
    monkeypatch.setattr(main, "is_enabled", flag(False))
    monkeypatch.setattr(main, "AsyncMongoClient", NeverBuilt)

    assert await main.main(["--trigger", "scheduled"]) == 2
    assert log.infos == []


async def test_a_skipped_run_still_requires_mongodb_uri(monkeypatch: pytest.MonkeyPatch, log: Log) -> None:
    # Proves (C3.1-T11, C3.1-D14, C8-D6): the same for `MONGODB_URI`, the second check before the gate.
    monkeypatch.setattr(main.settings, "mongodb_uri", None)
    monkeypatch.setattr(main, "is_enabled", flag(False))
    monkeypatch.setattr(main, "AsyncMongoClient", NeverBuilt)

    assert await main.main(["--trigger", "scheduled"]) == 2
    assert log.infos == []


# ---------------------------------------------------------------------------
# The recorded snapshot (C3.1-D15)
# ---------------------------------------------------------------------------


async def test_main_hands_the_flag_snapshot_to_the_audit_writer(monkeypatch: pytest.MonkeyPatch, log: Log) -> None:
    # Proves (C3.1-T11, C3.1-D15): `main` takes ONE snapshot (`effective_flags()`) and gives it to the writer, which
    # writes it on every run. The snapshot is a sentinel dict the real function would never return, so a `main` that
    # built the writer without it, or with a different dict, fails here. Mutation M4 (drop `feature_flags=`)
    # turns this red. Nothing is connected to: the client, the stager and `run_all` are stand-ins.
    snapshot = {"worker.scheduled_runs": True, "sentinel.flag": False}
    built: list[dict[str, Any]] = []

    class RecordingWriter:
        def __init__(self, *_: Any, **kwargs: Any) -> None:
            built.append(kwargs)

    class FakeCollection:
        def __getitem__(self, _: str) -> "FakeCollection":
            return self

    class AnsweringClient:
        def __init__(self, *_: Any, **__: Any) -> None:
            self.admin = SimpleNamespace(command=self._ping)

        async def _ping(self, *_: Any, **__: Any) -> None:
            return None

        def __getitem__(self, _: str) -> FakeCollection:
            return FakeCollection()

        async def close(self) -> None:
            pass

    async def no_venues(*_: Any, **__: Any) -> int:
        return 0

    monkeypatch.setattr(main, "is_enabled", flag(True))
    monkeypatch.setattr(main, "effective_flags", lambda: snapshot)
    monkeypatch.setattr(main, "AsyncMongoClient", AnsweringClient)
    monkeypatch.setattr(main, "PostgresAuditWriter", RecordingWriter)
    monkeypatch.setattr(main, "run_all", no_venues)

    assert await main.main(["--trigger", "scheduled"]) == 0
    assert len(built) == 1
    assert built[0]["feature_flags"] == snapshot
