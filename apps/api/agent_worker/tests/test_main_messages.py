"""Tests for what the worker says when MongoDB (Atlas, once hosted) does not answer (C8-D8).

HOW TO READ THIS
  Before any venue is fetched, `main` pings MongoDB and returns 2 when it does not answer. Locally the cause is a
  stopped Docker container and the fix is `make db-up`. On Railway there is no Docker to start: the likely causes are
  a PAUSED Atlas free cluster (C1 found one and had to restart it by hand, C8-U5), a wrong `MONGODB_URI`, or Atlas's
  Network Access list not allowing Railway (C8-U6). So the message depends on `APP_ENV`, and a hosted operator is not
  sent to Docker (C8-D8).

  Expected wording is written here from C8-D8 as the pieces an operator needs, not as the code's exact sentence, so
  the message can be reworded without breaking these tests and cannot lose the part that matters.

Stand-ins for the client and the logger are in `main_stubs.py`.
"""

import pytest

from agent_worker import main
from agent_worker.tests.main_stubs import DeadClient, Log, configure_worker

HOSTED = ["dev", "staging", "prod"]


@pytest.fixture
def log(monkeypatch: pytest.MonkeyPatch) -> Log:
    recorder = Log()
    monkeypatch.setattr(main, "log", recorder)
    return recorder


# ---------------------------------------------------------------------------
# The message, as a table over the environments (C8-D8)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("app_env", HOSTED)
def test_a_hosted_message_points_at_atlas_not_at_docker(app_env: str) -> None:
    # Proves (C8-D8): on a hosted environment the message names Atlas, a paused cluster and the Network Access list,
    # and never tells the operator to start Docker. An operator at 4 a.m. reading `make db-up` on Railway has nothing
    # to run it on, and the real causes (a paused free cluster, an access list that excludes Railway) go unmentioned.
    message = main.mongo_unreachable_message(app_env)  # type: ignore[arg-type]
    assert "Atlas" in message
    assert "paused" in message
    assert "Network Access" in message
    assert "MONGODB_URI" in message
    assert "make db-up" not in message


def test_a_local_message_keeps_the_docker_instruction() -> None:
    # Proves (C8-D8): a laptop still gets the original advice (`make db-up`, check MONGODB_URI) and is not told about
    # Atlas, which it does not use. The hosted wording must not have replaced the local one.
    message = main.mongo_unreachable_message("local")
    assert "make db-up" in message
    assert "MONGODB_URI" in message
    assert "Atlas" not in message


# ---------------------------------------------------------------------------
# `main` logs the right one and still exits 2 (C8-D8, C8-D6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("app_env", ["local", "staging", "prod"])
async def test_main_logs_the_message_for_its_environment_and_returns_two(
    monkeypatch: pytest.MonkeyPatch, log: Log, app_env: str
) -> None:
    # Proves (C8-D8, C8-D6): wired through `main` (not only the function), an unreachable MongoDB returns 2, the exit
    # status that means "configuration or connection problem" and not "a venue failed" (1), and the line logged is the
    # one for the current `APP_ENV`. A manual run is used so the scheduled-run gate is not what is being tested; the
    # error text carries the driver's own message too, so the cause is not lost.
    configure_worker(monkeypatch, app_env)  # type: ignore[arg-type]
    monkeypatch.setattr(main, "AsyncMongoClient", DeadClient)

    assert await main.main(["--trigger", "manual"]) == 2

    assert len(log.errors) == 1
    event, fields = log.errors[0]
    assert event == main.mongo_unreachable_message(app_env)  # type: ignore[arg-type]
    assert "no server" in fields["error"]
