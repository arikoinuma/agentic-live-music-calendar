"""Stand-ins for everything `agent_worker.main.main` would connect to, shared by the C8 tests of its messages and summary.

HOW TO READ THIS
  `main()` builds a MongoDB client, pings it, builds an audit writer and runs every venue. A test of what `main` SAYS
  (the message when Atlas does not answer, the start and finish lines of a run) must not connect to anything, so each
  piece is replaced here by something small:

    * `Log` stands in for the module's structlog logger and records each call, so a test reads what was logged and in
      which order instead of parsing console output.
    * `DeadClient` is an `AsyncMongoClient` whose ping fails (`main` then returns 2); `AnsweringClient` answers it, so
      the run goes on to its writer and `run_all`.
    * `configure_worker` sets the settings `main` reads to a combination that passes both checks before the
      scheduled-run gate (`model_endpoint_problem` and `MONGODB_URI`), for a chosen `app_env`.

  `test_main_gate.py` (C3.1-T11) defines the same kind of stand-ins inline, for its own purposes; this module is for
  the tests C8 added beside it, which share these. Nothing here is imported by production code.

docs/dev/implementations/c8-worker-on-railway.md, C8-D6, C8-D8.
"""

from types import SimpleNamespace
from typing import Any

import pytest
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
    non-local endpoint; the provider stays `ollama` so no real API key is needed.
    """
    monkeypatch.setattr(main.settings, "app_env", app_env)
    monkeypatch.setattr(main.settings, "model_provider", "ollama")
    local = app_env == "local"
    monkeypatch.setattr(
        main.settings, "model_base_url", "http://localhost:11434/v1" if local else "https://models.test/v1"
    )
    monkeypatch.setattr(main.settings, "model_name", "test-model")
    monkeypatch.setattr(main.settings, "mongodb_uri", "mongodb://localhost:1")


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
