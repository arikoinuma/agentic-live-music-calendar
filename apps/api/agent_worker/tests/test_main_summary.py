"""Tests for the start and finish lines of a worker run (C8-D6; the plan's test row for Railway's log view).

HOW TO READ THIS
  A scheduled run on Railway is read from its log, not from the database: a person opens the deployment and wants to
  see, without a query, that a run started, what it was (trigger, environment, model, which venue) and how it ended
  (how many venues failed, how long it took). `main` logs one line at each end of a run that actually does work.

  WHERE the lines sit is the part these tests pin, because other tests depend on it: `test_main_gate.py` (C3.1-T11)
  asserts that a SKIPPED run logs exactly one line, and that a run which fails at the MongoDB ping logs no info line
  at all. So the start line comes AFTER the ping succeeds, and neither line appears on a run that stops at a check or
  at the gate. `run_all` and the audit writer are replaced, so nothing here reaches a database or a model.

Stand-ins are in `main_stubs.py`. Expected field values are written here from the plan, not read from the code.
"""

from typing import Any

import pytest

from agent_worker import main
from agent_worker.tests.main_stubs import AnsweringClient, DeadClient, Log, RecordingWriter, configure_worker


@pytest.fixture
def log(monkeypatch: pytest.MonkeyPatch) -> Log:
    recorder = Log()
    monkeypatch.setattr(main, "log", recorder)
    return recorder


@pytest.fixture(autouse=True)
def stores_replaced(monkeypatch: pytest.MonkeyPatch) -> None:
    # Everything `main` connects to is replaced, and the settings are a valid local configuration.
    configure_worker(monkeypatch)
    monkeypatch.setattr(main, "AsyncMongoClient", AnsweringClient)
    monkeypatch.setattr(main, "PostgresAuditWriter", RecordingWriter)


def run_all_failing(failed: int, seen: list[int] | None = None, log: Log | None = None) -> Any:
    """A replacement `run_all` that reports `failed` failures and notes how many info lines existed when it ran."""

    async def run_all(*_: Any, **__: Any) -> int:
        if seen is not None and log is not None:
            seen.append(len(log.infos))
        return failed

    return run_all


async def test_a_run_logs_one_start_line_and_one_finish_line(monkeypatch: pytest.MonkeyPatch, log: Log) -> None:
    # Proves (C8-D6): a run that does work logs exactly two info lines, start then finish, with the facts a reader
    # needs. The start line names the trigger, the environment, the model and the venue filter (None for "every
    # venue"); the finish line says how many venues failed and how long the run took. Exit status is unchanged (0 here).
    monkeypatch.setattr(main, "run_all", run_all_failing(0))

    assert await main.main(["--trigger", "manual"]) == 0

    assert [event for event, _ in log.infos] == ["worker run started", "worker run finished"]
    _, start = log.infos[0]
    assert start == {"trigger": "manual", "app_env": "local", "model": "test-model", "venue": None}
    _, finish = log.infos[1]
    assert finish["failed"] == 0
    assert isinstance(finish["seconds"], float) and finish["seconds"] >= 0


async def test_the_start_line_names_the_venue_filter(monkeypatch: pytest.MonkeyPatch, log: Log) -> None:
    # Proves (C8-D6): `--venue 3` shows up on the start line, so a one-venue manual run is not mistaken for a full one
    # when someone reads the log later.
    monkeypatch.setattr(main, "run_all", run_all_failing(0))

    await main.main(["--venue", "3"])

    assert log.infos[0][1]["venue"] == 3


async def test_the_start_line_comes_before_the_run_and_the_finish_line_after(
    monkeypatch: pytest.MonkeyPatch, log: Log
) -> None:
    # Proves (C8-D6): the start line is logged BEFORE `run_all` begins (one info line exists when it is called), and
    # the finish line only after it returns. A finish line logged first would be a lie on a run that crashes, and a
    # start line logged after `run_all` would not be a start line.
    seen: list[int] = []
    monkeypatch.setattr(main, "run_all", run_all_failing(0, seen, log))

    await main.main([])

    assert seen == [1]


async def test_the_finish_line_reports_failures_and_the_exit_status_stays_one(
    monkeypatch: pytest.MonkeyPatch, log: Log
) -> None:
    # Proves (C8-D6): two failed venues appear as `failed=2` and the process still exits 1 (at least one venue failed),
    # which Railway reads as a failed run. The summary is information; it must not change the exit status.
    monkeypatch.setattr(main, "run_all", run_all_failing(2))

    assert await main.main([]) == 1

    assert log.infos[1][1]["failed"] == 2


async def test_a_run_that_stops_at_the_ping_logs_neither_line(monkeypatch: pytest.MonkeyPatch, log: Log) -> None:
    # Proves (C8-D6): when MongoDB does not answer, `main` returns 2 before the start line. This pins the placement
    # that `test_main_gate.py`'s "flag on proceeds past the gate" test depends on (it asserts no info line at all),
    # so moving the start line above the ping fails here with a message that says why.
    monkeypatch.setattr(main, "AsyncMongoClient", DeadClient)

    assert await main.main([]) == 2
    assert log.infos == []
