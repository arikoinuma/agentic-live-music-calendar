"""Capture venue pages exactly as the pipeline fetches them, as eval fixtures.

A2's fixtures were Chrome "Save Page As" captures: the page *after* JavaScript ran. The
pipeline fetches with one plain GET, which runs none — and on two of the four venues that
difference decided everything (Zhora's listings are drawn by a script; Midway answers a bot
challenge). So A2.1's fixtures are captured with the pipeline's own `nodes.fetch_html`
(docs/dev/implementations/a2.1-extraction-reliability.md, Context and Step 3).

How to read it: one capture per venue in `labels.VENUE_FACTS` (or the ones named on the command
line), saved as `fixtures/<venue>-<YYYY-MM-DD>.html` (git-ignored, like every fixture). A venue
with a public calendar feed also gets its feed saved as `.ics` (informational: no reader yet).
A failed fetch or a page with almost no text is reported, never saved silently as if it were
a listing.

    uv run python -m agent_worker.eval.capture                 # every venue
    uv run python -m agent_worker.eval.capture white_squirrel  # one venue
"""

import argparse
import datetime
from pathlib import Path

import httpx

from agent_worker.eval.labels import VENUE_FACTS
from agent_worker.extraction import clean_text
from agent_worker.nodes import fetch_html, metro_today

FIXTURES_DIR = Path(__file__).parent / "fixtures"
# Fewer visible characters than this means the listings weren't in what was fetched (Zhora's
# plain fetch had 314; a real calendar page has thousands). Reported, still saved, so the
# evidence is kept.
_THIN_PAGE = 500


def default_venues() -> list[str]:
    """The venues a bare `capture` run fetches: all but the blocked ones (A2.1-D3: Midway answered
    with a bot challenge and isn't asked again; Zhora's listings need a browser). A blocked
    venue can still be captured by naming it."""
    return sorted(key for key, facts in VENUE_FACTS.items() if not facts.blocked)


def capture(venue: str, today: datetime.date, force: bool = False) -> None:
    """Fetch one venue's calendar (and feed, if any) and save it under FIXTURES_DIR. An existing
    fixture is never replaced unless `force`: a label describes that exact page, and
    re-capturing means re-labelling (code review #10)."""
    facts = VENUE_FACTS[venue]
    targets = [(facts.url, "html")] + ([(facts.feed_url, "ics")] if facts.feed_url else [])
    for url, suffix in targets:
        path = FIXTURES_DIR / f"{venue}-{today.isoformat()}.{suffix}"
        if path.exists() and not force:
            print(f"{venue}: kept existing {path.name} (pass --force to replace it, then re-label)")
            continue
        try:
            body = fetch_html(url)
        except httpx.HTTPError as err:
            print(f"{venue}: NOT captured — {url}: {type(err).__name__}: {err}")
            continue
        path.write_text(body)
        note = ""
        if suffix == "html" and len(clean_text(body, keep_line_breaks=False)) < _THIN_PAGE:
            note = "  — WARNING: almost no visible text; the listings are probably not in the fetched page"
        print(f"{venue}: saved {path.name} ({len(body):,} bytes){note}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("venues", nargs="*", help=f"venue keys (default: {default_venues()})")
    parser.add_argument("--force", action="store_true", help="replace an existing fixture (then re-label it)")
    args = parser.parse_args()
    for venue in args.venues or default_venues():
        # The capture date is the fixture's fetch date for the year rule, so it is the metro's
        # date, as the pipeline's is (nodes.metro_today).
        capture(venue, metro_today(VENUE_FACTS[venue].metro_timezone), force=args.force)


if __name__ == "__main__":
    main()
