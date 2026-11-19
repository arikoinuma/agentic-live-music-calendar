"""Stand-ins for everything `agent_worker.main.main` would connect to, shared by the C8 tests of its messages and summary.

HOW TO READ THIS
  `main()` builds a MongoDB client, pings it, builds an audit writer and runs every venue. A test of what `main` SAYS
  (the message when Atlas does not answer, the start and finish lines of a run) must not connect to anything, so each
  piece is replaced here by something small:

    * `Log` stands in for the module's structlog logger and records each call, so a test reads what was logged and in
      which order instead of parsing console output.
    * `DeadClient` is an `AsyncMongoClient` whose ping fails (`main` then returns 2); `AnsweringClient` answers it, so
      the run goes on to its writer and `run_all`.
    * `configure_worker` sets the settings `main` reads to a combination that passes the three checks before the
      scheduled-run gate (`model_endpoint_problem`, `MONGODB_URI` and, since C9, `snapshot_config_problem`), for a
      chosen `app_env`. It pins the four `R2_*` settings too, so no test that drives `main` reads a laptop's `.env` and
      reaches a real bucket (C9-PR1-2).

  `test_main_gate.py` (C3.1-T11) defines the same kind of stand-ins inline, for its own purposes; this module is for
  the tests C8 added beside it, which share these. Nothing here is imported by production code.

docs/dev/implementations/c8-worker-on-railway.md, C8-D6, C8-D8; c9-r2-snapshots.md, C9-PR1-2.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr
from pymongo.errors import ServerSelectionTimeoutError

from agent_worker import main
from app.config import AppEnv


class Log:
    """Stands in for the module's structlog logger and records the calls instead of printing them, in order."""

    def __init__(self) -> None:
        self.infos: list[tuple[str, dict[str, Any]]] = []
        self.errors: list[tuple[str, dict[str, Any]]] = []

    def info(self, event: str, **fields: Any) -> None:
        self.infos.append((event, fields))

    def error(self, event: str, **fields: Any) -> None:
        self.errors.append((event, fields))


def configure_worker(monkeypatch: pytest.MonkeyPatch, app_env: AppEnv = "local") -> None:
    """Make the settings `main` reads pass both checks that come before the gate, for the given environment.

    A hosted environment may not point at localhost (`model_endpoint_problem`), so a hosted `app_env` gets a
    non-local endpoint; the provider stays `ollama` so no real API key is needed. A hosted `app_env` also needs all four
    `R2_*` settings (C9-D8), so it gets a complete set; a laptop gets none, which is snapshots off (C9-D2).
    """
    monkeypatch.setattr(main.settings, "app_env", app_env)
    monkeypatch.setattr(main.settings, "model_provider", "ollama")
    local = app_env == "local"
    monkeypatch.setattr(
        main.settings, "model_base_url", "http://localhost:11434/v1" if local else "https://models.test/v1"
    )
    monkeypatch.setattr(main.settings, "model_name", "test-model")
    monkeypatch.setattr(main.settings, "mongodb_uri", "mongodb://localhost:1")
    pin_r2_settings(monkeypatch, app_env)


def pin_r2_settings(monkeypatch: pytest.MonkeyPatch, app_env: AppEnv) -> None:
    """Set the four `R2_*` settings to what a correct configuration of `app_env` holds, whatever `.env` says (C9-PR1-2)."""
    complete = app_env != "local"
    monkeypatch.setattr(main.settings, "r2_endpoint_url", "https://r2.test" if complete else None)
    monkeypatch.setattr(main.settings, "r2_access_key_id", "test-key-id" if complete else None)
    monkeypatch.setattr(main.settings, "r2_secret_access_key", SecretStr("test-secret") if complete else None)
    monkeypatch.setattr(main.settings, "r2_bucket", f"pebblebeats-snapshots-{app_env}" if complete else None)


class DeadClient:
    """A MongoDB client whose ping fails, so `main` logs the unreachable message and returns 2."""

    def __init__(self, *_: Any, **__: Any) -> None:
        self.admin = SimpleNamespace(command=self._ping)

    async def _ping(self, *_: Any, **__: Any) -> None:
        raise ServerSelectionTimeoutError("no server")

    async def close(self) -> None:
        pass


class FakeCollection:
    """What `client[database][collection]` returns; `MongoStager` only stores it, so nothing here is called."""

    def __getitem__(self, _: str) -> "FakeCollection":
        return self


class AnsweringClient:
    """A MongoDB client whose ping succeeds, so `main` goes on to build its writer and call `run_all`."""

    def __init__(self, *_: Any, **__: Any) -> None:
        self.admin = SimpleNamespace(command=self._ping)

    async def _ping(self, *_: Any, **__: Any) -> None:
        return None

    def __getitem__(self, _: str) -> FakeCollection:
        return FakeCollection()

    async def close(self) -> None:
        pass


class RecordingWriter:
    """Replaces `PostgresAuditWriter`: nothing is written, and building it connects to nothing."""

    def __init__(self, *_: Any, **__: Any) -> None:
        pass
