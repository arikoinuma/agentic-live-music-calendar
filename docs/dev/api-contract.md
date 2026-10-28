# Read API contract

**Status:** Draft — shapes settled, endpoints not implemented yet
**Date:** September 28, 2026
**Purpose:** The interface between FastAPI and Next.js, fixed up front so the Python track and the frontend track can move independently. This is Track 0 of `alpha-build-plan.md`.

**Source of truth:** `apps/api/app/schemas.py`. This document explains the shapes and the reasoning; the Pydantic models *are* the shapes. Where the two disagree, the code is right and this file is stale.

Scope is **reads only**. Edit, flag, and submit endpoints are a later phase with their own shapes — see [Inherited fields](#inherited-fields) for the one place where read and write genuinely need to differ.

---

## 1. Why the contract comes first

The two tracks meet here and nowhere else. Fixing the shapes up front means the calendar UI can be built against realistic data before a single read endpoint exists, and the endpoints can be written against a known target rather than being reverse-engineered from whatever the UI ended up calling.

The mechanism is `apps/calendar/lib/fixtures/` — JSON files **generated from the Pydantic models**, not hand-written beside them. That distinction is the point. A hand-maintained fixture drifts, and a UI built on a drifted fixture looks finished right up until it's pointed at the real API.

```
make fixtures     # regenerate after any change to app/schemas.py
```

The generator is `apps/api/scripts/generate_fixtures.py`. Its data is invented but deliberately untidy — shows with no listed start time, multi-act bills, a free show, a day with nothing on it, one artist at two venues. A calendar built against only clean rows gets built assuming clean rows.

---

## 2. Endpoints

Listed here as the agreed surface; each lands with its milestone. All routes exist and, since C2, read Postgres (`app/queries.py`); the "Milestone" column records when each shape landed. (`/metro` shipped in B2.)

| Method | Path | Returns | Serves | Milestone |
|---|---|---|---|---|
| GET | `/shows?start=&end=&venue_id=&artist_id=` | `ShowListResponse` | Home calendar, `/day/[date]`, the calendar embedded on venue and artist pages | A-track; DB-backed in C2 |
| GET | `/shows/{id}` | `ShowDetail` | `/show/[id]` | A-track; DB-backed in C2 |
| GET | `/venues` | `VenueListResponse` | `/venues`, and the calendar's venue filter | A-track; DB-backed in C2 |
| GET | `/venues/{id}` | `VenueDetail` | `/venue/[id]` | A-track; DB-backed in C2 |
| GET | `/artists` | `ArtistListResponse` | `/artists`, and the calendar's artist filter | A-track; DB-backed in C2 |
| GET | `/artists/{id}` | `ArtistDetail` | `/artist/[id]` | A-track; DB-backed in C2 |
| GET | `/calendar/months` | `CalendarMonthsResponse` | The month dropdown | A-track; DB-backed in C2 |
| GET | `/metro` | `MetroSummary` | The root layout: footer metro name and the `description` metadata | B2 (DB-backed since C2) |

**Filtering.** `venue_id` and `artist_id` repeat for multi-select (`?venue_id=1&venue_id=3`). Both filters are AND-ed with the date range and OR-ed within themselves — picking two venues means "either venue," which is what a multi-select visibly implies.

**Open-ended ranges: `start` alone, and `upcoming`.** `start` without `end` means "the default window from `start`" (the
venue page's Earlier/Later paging sends only a `start`, so the window length stays the server's decision). `upcoming=true`
(B4) means "every show from the server's today on, with no upper limit" — the artist page's list. It is refused with a
422 when combined with `start` or `end` (an explicit range contradicts it) and when neither `venue_id` nor `artist_id`
is given (every show in the metro with no upper bound is the unbounded scan `MAX_RANGE` exists to prevent). The response
is still a `ShowListResponse`: `start` is today, `end` is the date of the last show returned, or `start` when there is
none, so the echoed range is always valid. `upcoming=false` is the same as leaving it out.

**Metro scoping.** Every response is implicitly scoped to the single live metro. No `metro_id` parameter exists yet; adding one later is additive. `arch-initial.md` Section 11 already tracks multi-metro enforcement as deferred.

**Pagination.** None. One metro has tens of venues and hundreds of artists, and a four-week window has a bounded number of shows. The envelope shapes leave room to add it without a breaking change — see below.

**Soft-deleted shows.** `status = 'removed'` rows never appear in read responses: not in `/shows` or `/calendar/months`, and `/shows/{id}` answers 404 for one. The status column exists for the audit trail and for reconcile, not for the reader. (Showing cancelled and postponed shows with their status is deferred, `arch-initial.md` §11.)

---

## 3. Conventions

### Summary vs. Detail

A `*Summary` is what a link or a list row needs. A `*Detail` is a whole entity page.

The calendar renders on the order of a hundred shows at once. If `ShowSummary` embedded a full `VenueDetail` for each, the same venue's address, phone numbers, and hours would ship dozens of times over for a block that displays a name.

`ShowDetail` extends `ShowSummary` rather than restating it, so a show's fields can't diverge between the two views.

### Envelopes, not bare arrays

List endpoints return `{"shows": [...]}`, not `[...]`.

A bare top-level array has nowhere to put a total count, a pagination cursor, or an echoed query range without changing the response's type. Nothing needs those today; the envelope is what keeps adding them cheap. `ShowListResponse` already uses the room — it echoes `start` and `end`.

### The server owns "now"

`ShowListResponse` echoes back the date range it actually served rather than trusting the client to remember what it asked for.

This matters most for the home page's four-week window. The browser's clock and timezone aren't the metro's, so "the next four weeks" is a question only the server can answer correctly. Concretely (C2): "today" is the instant the API's clock reads, converted to the metro's timezone and truncated to a date (`app/clock.py`, `metro_today`), not the UTC date: at 22:30 in Minneapolis on October 7 it is already October 8 in UTC. The default window, `upcoming` and `/calendar/months` all start from it. `MetroSummary.timezone` (an IANA name like `America/Chicago`) is carried for the same reason: a Friday show at a Minneapolis venue is Friday regardless of where the reader is sitting.

Render with `Temporal.PlainDate` / `Temporal.PlainTime`. Not `new Date("2026-09-28")` — that parses as UTC midnight and renders as the 27th anywhere west of Greenwich, which is the one bug a calendar can least afford.

---

## 4. Serialization notes

Three places where the JSON isn't the obvious thing.

**Dates and times are ISO strings.** `date` → `"2026-09-28"`, `time` → `"20:00:00"`. There's no date type in JSON. Parse at the edge, keep strings everywhere else.

**`Decimal` is a string, not a number.** `admission_advance` arrives as `"15.00"`. Pydantic does this deliberately, to avoid the float rounding that makes money arithmetic wrong. Format it for display; don't `parseFloat` it, and don't do arithmetic on it without a decimal library.

**Null means "not stated."** This is load-bearing for admission specifically. All three of `admission_advance`, `admission_day`, and `free_admission` being null means the venue's page didn't say what it costs. It does **not** mean free. `free_admission` is true only when the listing says so explicitly — `requirements-initial.md` is direct about this, and rendering an unpriced show as free is a wrong answer the reader acts on.

---

## 5. Inherited fields

`show.age_restriction`, `serves_alcohol`, `setting`, and `seating` are null in the database when the show doesn't override its venue's value.

**The read API returns the resolved value.** If the show's column is null, the API substitutes the venue's, and doesn't say which one it used.

Nothing that renders a show cares about the difference — an all-ages show is all-ages whether that was set on the show or inherited. Pushing the inheritance rule to the frontend would mean every consumer reimplementing it, and having the venue on hand to do so.

**The write API will care**, because "clear this override" and "set this to the same value the venue happens to have" are different actions that behave differently when the venue later changes. That's a real reason the write shape differs from the read shape, and a good argument against reusing one model for both out of habit.

---

## 6. What's deliberately absent

Fields that a reading of `requirements-initial.md` would expect, left out on purpose:

| Missing | Why |
|---|---|
| `VenueDetail.socials`, `ArtistDetail.socials` | The `venue_social` / `artist_social` tables are deferred (`alpha-build-plan.md` §8) |
| `ArtistDetail.genres`, `.members`, `.instrumentation` | Same — the vocabulary and join tables are deferred |
| `VenueDetail.map_url` | Constructed from `address` by the frontend. It's a link format, not data; changing it shouldn't need a backend deploy (`arch-initial.md` §4) |
| Slugs in URLs | Routes are `/venue/[id]` per `requirements-initial.md`. `/venue/3-zhora-darling` would be better for SEO and is cheap to add later, since the id stays the lookup key either way. Worth revisiting before launch, not now |

The first two are absent rather than present-and-always-empty on purpose. A consumer can't tell "this venue has no Instagram" from "this feature doesn't exist yet," and a field that's always `[]` teaches the UI to render an empty state that isn't real. Adding a field later is backward-compatible; removing one isn't.

---

## 7. Keeping the two sides in sync

**Decided: generated from FastAPI's OpenAPI schema.**

```
apps/api/app/schemas.py       Pydantic models — the source of truth
  -> FastAPI                  builds an OpenAPI document from each
                              route's return-type annotation
  -> apps/api/openapi.json    dumped without a server, git-ignored
  -> openapi-typescript       reads the standard, emits TypeScript
  -> apps/calendar/lib/api-types.ts    generated, committed, never edited
  -> apps/calendar/lib/types.ts        ~30 lines of friendly aliases
```

```
make types            # regenerate after changing schemas.py or a router
make contract-check   # fail if the committed output is stale
```

`make contract-check` also runs as its own CI job and is part of `make check`. It snapshots the generated files, regenerates, and diffs — deliberately not `git diff`, so it works on untracked files and outside a checkout. A failing run leaves the regenerated output in place, so the fix is to review the diff and commit it.

**Why a route's return type annotation matters more than it looks.** `def list_venues() -> VenueListResponse` is what puts `VenueListResponse`, and `VenueSummary` nested inside it, into `components.schemas`. FastAPI derives the schema from **routes**, not from the existence of models — a Pydantic model no route references doesn't appear. `response_model=` in the decorator does the same job; prefer the annotation, since mypy can see it too. There's a test (`test_openapi_exposes_the_response_schemas`) guarding this, because a dropped annotation otherwise surfaces as a missing frontend type long after the change that caused it.

**Why not zod.** Generation keeps the two definitions in sync at build time. Zod would additionally check at runtime that the data actually matches — which catches a deployed backend that changed shape without a frontend rebuild, something generation can't. They're complementary, not alternatives. Not adding it now because there's one deployment of each and no independent release cycle to drift between them; zod arrives with the edit forms (`arch-initial.md` §4 already picks it for `react-hook-form`), and that's the moment to reconsider using it at the API boundary too.

**One consequence worth knowing.** Pydantic fields with defaults are not in OpenAPI's `required` list, so they generate as **optional**: `start_time?: string | null`, not `start_time: string | null`. FastAPI does serialize them all, so at runtime they're present-and-null — but the type says `string | null | undefined` and all three need handling. If that gets tiresome, the fix is on the Python side: drop the `= None` defaults so the fields become required-but-nullable, at the cost of verbosity when constructing them.

---

## 8. Fixtures

| File | Shape |
|---|---|
| `metro.json` | `MetroSummary` |
| `shows.json` | `ShowListResponse` — 25 shows across 2026-09-28 → 2026-10-25, the default window (B3 appended four on 2026-10-07: two at one venue, one ending after midnight, one at 1:00 AM). The sample data holds a 26th show, 2026-10-29, which B4 added so `?upcoming=true` has something to reach; the generator keeps it out of this fixture because it is outside the range the fixture claims |
| `show-detail.json` | `ShowDetail` |
| `venues.json` | `VenueListResponse` — the four Phase 5 venues, alphabetical |
| `venue-detail.json` | `VenueDetail` |
| `artists.json` | `ArtistListResponse` — ten artists, alphabetical |
| `artist-detail.json` | `ArtistDetail` |
| `calendar-months.json` | `CalendarMonthsResponse` |

The venues are the same four the Phase 5 extraction fixtures came from. Since C2 they are the sample world's own (`app/testing/sample_data.py`), loaded into the test and end-to-end databases; the seed script (`app/db/seed.py`) carries the real venue list, which is a different set (`C2-D8`), so the fixtures no longer line up with a seeded database.

The fixtures are written from the sample world's pure builders (`app/testing/sample_data.py`, `fixture_payloads()`), with no database, and the sample's dates are fixed rather than `date.today()`, so regenerating produces an empty diff unless the contract actually changed. The real endpoint computes the window from the metro's current local date; `test_fixtures_agree.py` loads the same world into Postgres, pins the API's clock to the sample's start, and requires each route to return exactly what its fixture holds, so the two paths can't drift. `shows.json` is stored in the order the API returns shows.
