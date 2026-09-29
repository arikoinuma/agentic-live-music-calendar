"""Dump the sample data to JSON fixtures for the frontend.

Run: `uv run python -m scripts.generate_fixtures` (from apps/api)

Note the `-m`: this project sets `package = false`, so `app` is not
installed into the venv and a plain `python scripts/foo.py` puts only
the script's own directory on sys.path, not the project root. Running
it as a module puts the current directory there instead.

These fixtures are a *secondary* path. The primary one is HTTP — the
routers in app/routers/ serve the same data over the same URLs the real
API will use, so the frontend should call those. These files exist for
frontend tests that shouldn't need a running backend (vitest, milestone
B5), and for reading the shapes without starting anything.

Both paths read app/sample_data.py, so they can't disagree.
"""

import json
from pathlib import Path

from app import sample_data as data
from app.schemas import (
    ArtistListResponse,
    CalendarMonthsResponse,
    ShowListResponse,
    VenueListResponse,
)

OUT_DIR = Path(__file__).resolve().parents[2] / "calendar" / "lib" / "fixtures"


def write(name: str, model: object) -> None:
    path = OUT_DIR / name
    # mode="json" matters: it applies the same serialization the API
    # does (dates as ISO strings, Decimal as a string), so the fixture
    # is identical in shape to a real response rather than a
    # Python-flavored approximation of one.
    payload = model.model_dump(mode="json")  # type: ignore[attr-defined]
    path.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"  {path.relative_to(OUT_DIR.parents[3])}")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Writing fixtures:")

    write("shows.json", ShowListResponse(start=data.START, end=data.END, shows=data.SHOWS))
    write("show-detail.json", data.show_detail(2))
    write("venues.json", VenueListResponse(venues=sorted(data.VENUES, key=lambda v: v.name)))
    write("venue-detail.json", data.venue_detail(3))
    write("artists.json", ArtistListResponse(artists=sorted(data.ARTISTS, key=lambda a: a.name)))
    write("artist-detail.json", data.artist_detail(1))
    write("calendar-months.json", CalendarMonthsResponse(months=data.calendar_months()))


if __name__ == "__main__":
    main()
