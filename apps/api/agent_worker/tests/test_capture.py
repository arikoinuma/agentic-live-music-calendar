"""Tests for `agent_worker/eval/capture.py`, which saves venue pages as eval fixtures.

A captured page is what a label describes (A2.1-D2: labels describe the captured page,
and "re-capturing means re-labelling"). So capture must never silently replace a fixture that
already exists, and must not keep asking a venue that has told us no (Midway's bot challenge,
A2.1-D3). No network is used: the fetch is replaced by a stand-in.

How to read it: one test per rule, each against a temporary fixtures directory.
"""

import datetime
from pathlib import Path

import pytest

from agent_worker.eval import capture

TODAY = datetime.date(2026, 10, 10)


@pytest.fixture
def fixtures_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A temporary fixtures directory, and a fetch that returns a page naming its URL."""
    monkeypatch.setattr(capture, "FIXTURES_DIR", tmp_path)
    monkeypatch.setattr(capture, "fetch_html", lambda url: f"<html><body>{url} " + "x" * 600 + "</body></html>")
    return tmp_path


def test_an_existing_fixture_is_not_overwritten(fixtures_dir: Path) -> None:
    # Proves: code review #10. A second capture on the same date leaves the labelled fixture
    # alone unless forced — otherwise the page under a label changes without anyone noticing.
    existing = fixtures_dir / f"terminal-{TODAY.isoformat()}.html"
    existing.write_text("the labelled page")
    capture.capture("terminal", TODAY)
    assert existing.read_text() == "the labelled page"
    capture.capture("terminal", TODAY, force=True)
    assert existing.read_text() != "the labelled page"


def test_a_blocked_venue_is_skipped_unless_named() -> None:
    # Proves: code review #10 / A2.1-D3. Midway answered with a bot challenge; capturing "every
    # venue" doesn't ask it again. Naming it explicitly still can.
    assert "midway" not in capture.default_venues()
    assert "white_squirrel" in capture.default_venues()
