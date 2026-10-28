"""The API's notion of "today": the metro's local date, not UTC's (C2-D5).

No database. Expected values are calendar arithmetic from the zone's stated offset: America/Chicago is
UTC-5 (CDT) until the first Sunday of November (November 1, 2026) and UTC-6 (CST) after it.
"""

import datetime

import pytest

from app.clock import get_now, metro_today

CHICAGO = "America/Chicago"


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime.datetime:
    return datetime.datetime(year, month, day, hour, minute, tzinfo=datetime.UTC)


def test_today_is_the_metros_date_not_utcs() -> None:
    # Proves (C2-M3): at 03:30 UTC on October 8 it is 22:30 on October 7 in Minneapolis (CDT, UTC-5), so "today" is
    # the 7th. This is the case that separates "metro-local" from "UTC": a window that starts on the UTC date would
    # show tomorrow's shows to everyone planning the evening.
    assert metro_today(_utc(2026, 10, 8, 3, 30), CHICAGO) == datetime.date(2026, 10, 7)


def test_today_turns_over_at_the_metros_midnight() -> None:
    # Proves: 05:00 UTC on October 8 is exactly midnight CDT, so the date is the 8th. One minute earlier is still the
    # 7th, so the boundary is where the zone says, not at a round hour.
    assert metro_today(_utc(2026, 10, 8, 5, 0), CHICAGO) == datetime.date(2026, 10, 8)
    assert metro_today(_utc(2026, 10, 8, 4, 59), CHICAGO) == datetime.date(2026, 10, 7)


def test_the_year_turns_at_the_metros_midnight() -> None:
    # Proves: the year boundary follows the metro: 05:59 UTC on January 1 is 23:59 on December 31 in Minneapolis (CST,
    # UTC-6), and 06:00 UTC is January 1. A calendar that rolled its year on UTC would be wrong for six hours.
    assert metro_today(_utc(2027, 1, 1, 5, 59), CHICAGO) == datetime.date(2026, 12, 31)
    assert metro_today(_utc(2027, 1, 1, 6, 0), CHICAGO) == datetime.date(2027, 1, 1)


def test_the_offset_changes_when_daylight_time_ends() -> None:
    # Proves: the offset is read from the zone, not hard-coded to -5. Daylight time ends at 2:00 on November 1, 2026, so
    # 05:59 UTC on November 2 is 23:59 on November 1 (CST, UTC-6). A constant -5 would say November 2.
    assert metro_today(_utc(2026, 11, 2, 5, 59), CHICAGO) == datetime.date(2026, 11, 1)


def test_a_naive_datetime_is_refused() -> None:
    # Proves: a datetime with no timezone is an error, not silently treated as UTC or local. It carries no instant, and a
    # guess would be a bug that only shows up near midnight.
    with pytest.raises(ValueError, match="timezone-aware"):
        metro_today(datetime.datetime(2026, 10, 7, 12, 0), CHICAGO)


def test_get_now_is_aware() -> None:
    # Proves: the production clock returns an aware UTC instant, which is what `metro_today` requires; a naive one would
    # make every request raise.
    assert get_now().tzinfo is not None
