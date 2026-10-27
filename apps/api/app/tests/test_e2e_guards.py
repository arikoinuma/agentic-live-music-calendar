"""The end-to-end harness's own safety checks (C2-D7, C2-M10).

No database. The e2e job drops and recreates a database and starts the real API on a frozen clock. These
tests pin the guards that stop it ever doing that to the wrong database, or running unfrozen.
"""

import datetime
import importlib

import pytest
from sqlalchemy.engine import make_url

from app.testing.e2e_database import (
    E2E_DB_NAME,
    UnsafeE2eDatabaseError,
    check_e2e_database_url,
    frozen_now_from,
)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_a_local_calendar_e2e_database_is_accepted(host: str) -> None:
    # Proves: the guard accepts the one target the harness is for: a database named `calendar_e2e` on this machine.
    # Expected values are the stated rule (name constant, loopback hosts), the mirror of `check_test_database_url`.
    host_part = f"[{host}]" if ":" in host else host
    check_e2e_database_url(make_url(f"postgresql+asyncpg://u:p@{host_part}:5432/{E2E_DB_NAME}"))


@pytest.mark.parametrize("name", ["calendar_dev", "calendar_test", "postgres", "calendar", "calendar_e2e_2"])
def test_any_other_database_name_is_refused(name: str) -> None:
    # Proves (C2-M10): only the exact name `calendar_e2e` passes, so a stray DATABASE_URL (the laptop's `.env` points
    # at calendar_dev, and once pointed at Neon) can't have its database dropped. The names include the neighbours a
    # typo or a prefix match would let through.
    with pytest.raises(UnsafeE2eDatabaseError, match="calendar_e2e"):
        check_e2e_database_url(make_url(f"postgresql+asyncpg://u:p@127.0.0.1:5432/{name}"))


@pytest.mark.parametrize("host", ["ep-cool-123.us-east-2.aws.neon.tech", "db.internal", "10.0.0.5"])
def test_a_non_local_host_is_refused_even_with_the_right_name(host: str) -> None:
    # Proves (C2-M10): the right name on a remote host is still refused. The hosted database could carry the name; the
    # host is the check that keeps `DROP DATABASE` on this machine.
    with pytest.raises(UnsafeE2eDatabaseError, match="local"):
        check_e2e_database_url(make_url(f"postgresql+asyncpg://u:p@{host}:5432/{E2E_DB_NAME}"))


def test_the_frozen_instant_is_parsed_with_its_zone() -> None:
    # Proves: `E2E_API_FROZEN_NOW` is an ISO instant with a zone ("Z" included, as the TypeScript constant is written),
    # and comes back timezone-aware. Expected: 17:00 UTC on September 28, 2026, the pin `e2e/support/clock.ts` carries.
    assert frozen_now_from("2026-09-28T17:00:00Z") == datetime.datetime(2026, 9, 28, 17, 0, tzinfo=datetime.UTC)


@pytest.mark.parametrize("raw", [None, "", "2026-09-28T17:00:00"])
def test_a_missing_or_zoneless_frozen_instant_is_refused(raw: str | None) -> None:
    # Proves: no value, an empty value, or a value with no zone stops the API from starting, instead of running on the
    # real clock (the e2e expectations assume the pinned window) or on a guessed zone.
    with pytest.raises(RuntimeError, match="E2E_API_FROZEN_NOW"):
        frozen_now_from(raw)


def test_the_e2e_app_will_not_start_without_its_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves: importing the e2e entry module with no `E2E_API_FROZEN_NOW` fails. Uvicorn imports it, so this is "the API
    # does not come up unfrozen". Nothing is left behind: the checks run before the app is touched.
    monkeypatch.delenv("E2E_API_FROZEN_NOW", raising=False)
    with pytest.raises(RuntimeError, match="E2E_API_FROZEN_NOW"):
        importlib.import_module("app.testing.e2e_app")


def test_the_e2e_app_will_not_start_on_another_database(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (C2-M10): even with its pin, importing the entry module fails when the process's DATABASE_URL names
    # something other than `calendar_e2e`. This test process's DATABASE_URL is the dev or CI database, so the guard
    # must refuse it, which is the situation a developer's `.env` creates.
    monkeypatch.setenv("E2E_API_FROZEN_NOW", "2026-09-28T17:00:00Z")
    with pytest.raises(UnsafeE2eDatabaseError):
        importlib.import_module("app.testing.e2e_app")
