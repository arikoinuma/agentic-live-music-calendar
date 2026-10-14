"""Tests for `app/log_config.py`: structlog configured once, console locally and JSON otherwise.

Milestone A4 (docs/dev/implementations/a4-auditability.md, step 3 and D7; closes gap G12). The point of the
configuration is that a log line is joinable to the audit trail: every line in a run carries the `run_id`
bound with `structlog.contextvars`, and a cron job (not a terminal) gets machine-readable JSON.

How to read it: each test configures logging, emits one line, and reads what reached stderr. Expected
values are literals from the plan: the keys `event`, `level` and `timestamp` are structlog's own names, and
`run_id` is the key the plan binds.
"""

import json
from collections.abc import Iterator

import pytest
import structlog

from app.log_config import configure_logging


@pytest.fixture(autouse=True)
def _clean_logging() -> Iterator[None]:
    """Each test starts from unbound context and structlog's defaults, and leaves them that way, so a
    test that binds a `run_id` can't leak it into another."""
    structlog.contextvars.clear_contextvars()
    yield
    structlog.contextvars.clear_contextvars()
    structlog.reset_defaults()


def lines(capsys: pytest.CaptureFixture[str]) -> list[str]:
    return [line for line in capsys.readouterr().err.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# The JSON renderer
# ---------------------------------------------------------------------------


def test_json_format_emits_one_object_per_line_with_the_bound_run_id(capsys: pytest.CaptureFixture[str]) -> None:
    # Proves: with fmt="json" a line is one parseable JSON object carrying the event, the level, an ISO
    # timestamp, its own key/value fields, and the `run_id` bound for the run. That last key is what lets a
    # log line be joined to `audit_log.run_id`; losing `merge_contextvars` from the chain would drop it silently.
    configure_logging("json")
    structlog.contextvars.bind_contextvars(run_id=7)
    structlog.get_logger().info("page fetched", venue_id=1)
    [line] = lines(capsys)
    record = json.loads(line)
    assert record["event"] == "page fetched"
    assert record["level"] == "info"
    assert record["venue_id"] == 1
    assert record["run_id"] == 7
    assert "T" in record["timestamp"]  # ISO 8601


def test_json_format_renders_an_exception_as_a_field_not_a_traceback_dump(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Proves: a logged exception stays inside the single JSON line (under `exception`), so a log shipper that
    # reads line by line doesn't split one failure across many records.
    configure_logging("json")
    try:
        raise ValueError("boom")
    except ValueError:
        structlog.get_logger().exception("run crashed")
    [line] = lines(capsys)
    assert "ValueError: boom" in json.loads(line)["exception"]


# ---------------------------------------------------------------------------
# The console renderer and the switch
# ---------------------------------------------------------------------------


def test_console_format_is_not_json_but_carries_the_event_and_fields(capsys: pytest.CaptureFixture[str]) -> None:
    # Proves: the local format is for a person: the event text and the key=value pairs are on the line, and
    # it does not parse as JSON.
    configure_logging("console")
    structlog.get_logger().info("page fetched", venue_id=1)
    [line] = lines(capsys)
    assert "page fetched" in line
    assert "venue_id" in line
    with pytest.raises(json.JSONDecodeError):
        json.loads(line)


def test_auto_format_is_json_when_stderr_is_not_a_terminal(capsys: pytest.CaptureFixture[str]) -> None:
    # Proves: "auto" chooses JSON off a terminal, which is what a Railway cron job is. pytest's captured
    # stderr is not a TTY, so no monkeypatching is needed to put it in that situation.
    configure_logging("auto")
    structlog.get_logger().info("hello")
    [line] = lines(capsys)
    assert json.loads(line)["event"] == "hello"


def test_configuring_twice_is_harmless(capsys: pytest.CaptureFixture[str]) -> None:
    # Proves: calling `configure_logging` again (the worker and a script may both do it) replaces the
    # configuration rather than stacking processors, so a line is still emitted exactly once.
    configure_logging("json")
    configure_logging("json")
    structlog.get_logger().info("once")
    assert len(lines(capsys)) == 1
