"""The manual replay script's command line (C2-D10). No database, no model: only the argument parsing is tested."""

import datetime

from agent_worker.local_test import FETCHED_ON, FIXTURE, parse_args


def test_no_arguments_replays_the_original_capture() -> None:
    # Proves: running the script with no arguments behaves as it did before C2 (the August capture, fetched August 17),
    # so existing habits and docs that say `uv run python -m agent_worker.local_test` still mean the same thing.
    args = parse_args([])
    assert (args.fixture, args.fetched_on) == (FIXTURE, FETCHED_ON)
    assert FETCHED_ON == datetime.date(2026, 8, 17)


def test_another_capture_and_date_can_be_named() -> None:
    # Proves: the October capture can be replayed with its own date. Expected values are the October capture's name and
    # date as agent_worker/eval/labels.py records them (`white_squirrel-2026-10-10.html`, captured 2026-10-10).
    args = parse_args(["--fixture", "agent_worker/eval/fixtures/white_squirrel-2026-10-10.html", "--fetched-on", "2026-10-10"])
    assert args.fixture.endswith("white_squirrel-2026-10-10.html")
    assert args.fetched_on == datetime.date(2026, 10, 10)
