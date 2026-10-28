"""Dump the sample world to JSON fixtures for the frontend.

Run: `uv run python -m scripts.generate_fixtures` (from apps/api)

Note the `-m`: this project sets `package = false`, so `app` is not
installed into the venv and a plain `python scripts/foo.py` puts only
the script's own directory on sys.path, not the project root. Running
it as a module puts the current directory there instead.

These fixtures are a *secondary* path. The primary one is HTTP: the routes
in app/routers/ answer from the database over the URLs the frontend calls.
The files exist for frontend tests that shouldn't need a running backend
(vitest, milestone B5), and for reading the shapes without starting anything.

What the bodies are lives in `app.testing.sample_data.fixture_payloads()`, not
here, so that `test_fixtures_agree.py` can compare the real routes (over the same
world loaded into Postgres) with exactly what this script writes (C2-D1).
"""

import json
from pathlib import Path

from app.testing.sample_data import fixture_payloads

OUT_DIR = Path(__file__).resolve().parents[2] / "calendar" / "lib" / "fixtures"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Writing fixtures:")
    for name, model in fixture_payloads().items():
        path = OUT_DIR / name
        # mode="json" matters: it applies the same serialization the API
        # does (dates as ISO strings, Decimal as a string), so the fixture
        # is identical in shape to a real response rather than a
        # Python-flavored approximation of one.
        path.write_text(json.dumps(model.model_dump(mode="json"), indent=2) + "\n")
        print(f"  {path.relative_to(OUT_DIR.parents[3])}")


if __name__ == "__main__":
    main()
