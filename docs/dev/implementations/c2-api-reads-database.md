# C2 — the API reads from the database

**Status:** Plan review
**Date:** October 23, 2026
**Author model:** Claude Sonnet 5.5
**Reviewer model:** (pending — plan review round 1)
**Spec:** `docs/dev/alpha-deployment-plan.md` §6 C2 (and §1.1 rows "API data source", "Sample window", "What C2 changes", "E2E stack", "Schema on Neon"; §5.2 traps "Merging C2 before Neon is migrated" and "C2 breaking B6's end-to-end job"; Dep-D12, Dep-D15, Dep-D16), `docs/dev/alpha-build-plan.md` §2 points 2 and 4 and the A1b pointer, `docs/dev/api-contract.md` §2–§5 and §8, `docs/dev/implementations/b6-accessibility-and-e2e.md` "Follow-ups for other milestones", `docs/dev/implementations/c1-env-revalidation.md` (Neon), `docs/arch/data-model-initial.md` (show, soft delete), `docs/references/fastapi-style-guide.md`, `apps/api/AGENTS.md`

**Designations.** Inside this plan the decisions are `D1`–`D10` and the mutation checks `M1`–`M10`; there are no `TODO(Ari)` key points (D9). Elsewhere they are written `C2-D1`, `C2-M1` and so on (`docs/dev/conventions.md`); code, tests, comments and other documents must use the scoped form, and the build step copies from this file, so copy the scoped form. Review items are `C2-PR<round>-<n>` for the plan review and `C2-CR<round>-<n>` for the code review. The deployment plan's decisions keep their own scope (`Dep-D12`), the build plan's catalogue is `v0.1-G<n>`, and other plans' IDs carry theirs (`B6-D2`, `A6-M2`).

## Context

Every router in `apps/api/app/routers/` still answers from `app/sample_data.py`: an in-memory world of four venues, ten artists and 26 invented shows, with the window pinned to the sample (`start = data.START`, September 28 – October 25). That was always a stand-in. The alpha's definition of done (`alpha-build-plan.md` §2 points 2 and 4) cannot be met until the calendar renders rows the worker wrote, and C1 found that Neon holds no tables at all.

C2 swaps the bodies for queries and keeps what a client can see: every URL, response model, parameter and error code (`api-contract.md` §2). Four things make that bigger than a find-and-replace:

1. **The API's clock becomes real.** `shows.py` reads `data.START` today. Once the window is "the metro's today plus 27 days" the date cliff B6 disproved for the sample arrives for real (B6 "Follow-ups"), and the end-to-end job, which pins only the *Next* server's clock, needs a way to pin the API's (D2).
2. **The sample data keeps three consumers** that are not the routes: the frontend fixtures (`generate_fixtures.py`), the route tests, and B6's end-to-end job. All three need a deterministic, known set of shows. Deleting `sample_data.py` outright would orphan them; D1 decides what replaces it as their source.
3. **The end-to-end job needs a database.** B6-D1 chose the real API on sample data with no Postgres. After C2 the job needs a Postgres service in CI, a database the harness creates and loads itself, and a guard that stops it ever touching a real one (D7).
4. **Production's Neon must be migrated and seeded before the merge** (`alpha-deployment-plan.md` §5.2). Railway deploys `main` on push; merging first would put the production API on tables that do not exist. That is an Ari step against a hosted service, outside the cloud sandbox's reach.

### What C2 delivers

| Piece | Where | What changes |
|---|---|---|
| Queries | `app/queries.py` (new) | One function per read, ORM rows to the existing `schemas.py` models in one place. Routers become thin: parameter rules (422), misses (404), then a call. |
| Routers | `app/routers/*.py` | `async def` against `Annotated[AsyncSession, Depends(get_db)]`. Signatures, response models, parameter names, `NOT_FOUND`, the `upcoming` and `MAX_RANGE` rules: unchanged. |
| Dependencies | `app/db/session.py`, `app/clock.py`, `app/dependencies.py` (new) | `get_db`; `get_now` and the pure `metro_today`; `current_metro`. |
| Relationships | `app/db/models/calendar.py` | `Show.venue`, `Show.lineup`, `ShowArtist.artist`, `Venue.metro`: read-only, never lazy (D4). |
| Sample world | `app/testing/sample_data.py` (moved) | Becomes test and e2e data, plus a loader into Postgres and the fixture payload builder (D1). Deleted from `app/` proper. |
| Seed | `app/db/seed.py` | Dep-D16's venue list (D8). |
| End-to-end job | `app/testing/e2e_database.py`, `app/testing/e2e_app.py` (new), `playwright.config.ts`, `e2e/support/clock.ts`, `ci.yml`, `Makefile` | A Postgres service, a throwaway `calendar_e2e` database loaded with the sample world, and a frozen API clock (D2, D7). |
| Tests | `app/tests/` | `test_routers.py` moves to `httpx.AsyncClient` + `ASGITransport` with `dependency_overrides`, onto a real database. |
| Worker harness | `agent_worker/local_test.py` | Accepts a fixture path and a fetch date, so Ari's laptop can replay two captures of one venue (D10). |
| Neon and local verification | Ari | Migrate and seed Neon before the merge; run the worker twice and look at the calendar. |

What C2 does **not** change: `schemas.py` and the OpenAPI document (so `lib/api-types.ts` must come out of `make types` unchanged, D3), the frontend, migrations (the tables exist), the worker's write path.

## Decisions

Recommended; Ari approves them by approving the plan. **D1, D2 and D8 are the ones that need Ari's eyes.**

| ID | Decision | Reason | Alternative and cost |
|---|---|---|---|
| **D1** | **The sample world stays as typed Python at `app/testing/sample_data.py`.** The fixtures keep being generated from it, with no database (`make fixtures` and the `contract` CI job are unchanged). A loader writes it into Postgres for the route tests and the e2e job. One keystone test (below, T4) loads it, calls the real routes, and asserts each response equals the matching fixture file. | This answers the deployment plan's "keep a sample-data source" question. The world is defined once, as `schemas.py` objects. The two things that could drift apart (the pure builders behind the fixtures, and the routes plus database behind the API) are pinned to each other by a test instead of by a hope. The `contract` job stays free of Postgres. The stem `sample_data` is kept so about fifteen comments in the frontend and docs need a path change, not a rename. | *Generate the fixtures from the real API over a loaded database.* One less implementation of the response shapes, but `make fixtures`, `make contract-check` and the `contract` CI job then need Postgres and the migration run, and a failing database becomes a "stale contract" message. Not chosen, and not ruled out later. |
| **D2** | **The API reads its clock through an injected dependency** (`get_now`), never through a "freeze" environment variable that production code honours. The e2e job starts the API through a separate entry module (`app/testing/e2e_app.py`) that overrides `get_now` with the instant in `E2E_API_FROZEN_NOW` and refuses to start without it. **The API is pinned to 12:00 on September 28 (the sample's `START`) while the Next server stays pinned to October 7.** | A production process that obeys `FROZEN_NOW` is a hazard with no upside; a dependency override lives only where tests put it. Pinning the API to `START` keeps the served window at September 28 – October 25, byte for byte what B6's 17 specs and `lib/fixtures` were written against, and keeps "Today" in the middle of the window, which is the only place the Today row can be tested. | *Pin both to October 7.* One honest clock, but the API window becomes October 7 – November 3, every day before the 7th leaves the home page, and the specs' counts and the fixtures' range all change: a B6-sized rewrite. The cost of the recommendation: the e2e job runs the API nine days "earlier" than Next, which production never does. The Python tests (T1, T3) cover the real single-clock behaviour instead. |
| D3 | **The contract is untouched.** No change to `schemas.py`, any route's parameters, or the OpenAPI document. A database with no metro row answers 503 with a plain `detail`; the 503 is **not** declared in `responses=`. | Declaring it would change the OpenAPI document and force a `make types` diff in the generated TypeScript for an operational failure the frontend can do nothing different about. `make types` giving an empty diff is a verification step. | Declare it. More honest documentation; a generated-file change for no consumer. |
| D4 | **Relationships are `viewonly=True` and `lazy="raise"`.** No cascades are configured. | The product never deletes a row (`Show.status` is a soft delete), and the worker writes through explicit foreign keys (A6). A read-only relationship cannot change what the worker writes, so adding them cannot regress A5 or A6; and `lazy="raise"` turns an accidental lazy load under asyncio (a `MissingGreenlet` in production) into an error in the first test. Every query names what it loads (`joinedload` / `selectinload`). This is the cascade choice the milestone asks for. | *Writable relationships with `cascade="all, delete-orphan"`.* The first thing that wants object-graph writes (an admin edit API) revisits it; until then it is dead code with a footgun. |
| D5 | **Read rules** (below). | Each is a decision the contract leaves open or the sample data hid. | Per row. |
| D6 | **Inherited fields are resolved in Python with `is None`**, not truthiness and not `or`. | `serves_alcohol=False` on a show overriding a venue's `True` is the case `show.x or venue.x` gets wrong (it falls through to the venue). `api-contract.md` §5 is explicit that the resolved value is returned. | `COALESCE` in SQL is also correct; Python keeps the rule in one named helper that a test can call. |
| D7 | **The e2e job gets its own database, `calendar_e2e`**, dropped, created, migrated and loaded on every run by `python -m app.testing.e2e_database`, run as the first half of the API's `webServer` command. Its guard refuses any URL whose database is not `calendar_e2e` or whose host is not local; `e2e_app` repeats the name check at import. Playwright passes `DATABASE_URL` explicitly, so a developer's `apps/api/.env` (which may point at Neon, `c1-env-revalidation.md`) is never read. | The same reasoning as `app/testing/db.py` (`calendar_test`): a fixed name that no mistyped variable can redirect a `DROP DATABASE` at something real. A separate database from `calendar_test` lets `make check` run pytest and Playwright without either dropping the other's. | Reuse `calendar_dev`: wipes the developer's data. Reuse `calendar_test`: two suites contend for one database. |
| **D8** | **The seed's venue list** (Dep-D16), provisionally: The White Squirrel Bar, 7th St Entry, Mortimer's, The Terminal Bar, in that insert order. The Midway Saloon and Zhora Darling leave the list. Ari's further venues are added as rows to `VENUES` by Ari or by a one-line request. | Dep-D16: one list for every environment; Midway and Zhora wait for a route because the venue table has no active flag, so a seeded venue would be fetched by the worker and listed by the API. Terminal Bar is Ari's call (Dep-D16); the plan keeps it so the list is not smaller than the one already extracted. **What Ari must supply or confirm:** the two new rows' `fetch_strategy` (the plan assumes `http` for both and has not checked: the cloud cannot reach venue sites, so confirm with a plain GET as `seed.py`'s Midway comment did), whether Terminal Bar stays, and the further venues and URLs. URLs for the two new rows are already in the repo: `https://first-avenue.com/shows/?venues=59161` and `https://www.mortimerscalendar.com/` (`agent_worker/eval/labels.py`). | A list Ari assembles later is the same one-line-per-venue edit; C2 does not wait for it. |
| D9 | **Every C2 item is `[written]`; there are no `TODO(Ari)` gaps** (Dep-D15). | The milestone text marks the two main bullets `[written]` and the rest are infrastructure. If Ari wants one gap for the SQLAlchemy practice, the best candidate is the predicate that composes the `/shows` filters (OR within a type, AND across types, artist anywhere in the lineup, via `EXISTS`): that is where the concept lives. Say so at approval and the plan re-marks it. | — |
| D10 | **Local verification replays two captures of one venue and reads them back through the month filter**, with a stated fallback (Verification, Ari step 2). | Two live runs show inserts then no-ops (`a6-commit.md`); two *different captures* are what can show an update or a soft delete. The captures are from August and October, and the home page now starts at the real today, so the rows are reached with `/?month=2026-08` (a hand-edited past month shows what it says, `B2-D2`), not the default window. | Rely on A5's and A6's database tests for update and soft delete, which the deployment plan allows if stated; the plan keeps the stronger check and names that as the fallback. |

### D5 — the read rules

| Question | Rule | Why |
|---|---|---|
| Which metro? | The lowest-id `metro` row (`current_metro`); every venue, show and month query is scoped to it. Artists are global. No metro row: 503, `detail` says to run the seed. | `api-contract.md` §2: every response is implicitly scoped to the single live metro. Scoping now means C4's slug adds a lookup instead of rewriting every query. |
| "Today"? | `get_now()` converted to the metro's timezone, `.date()` (`metro_today`). Not UTC's date. | At 22:30 in Minneapolis on October 7 it is already October 8 in UTC; a UTC date shows tomorrow's window on every evening show-goer's phone. |
| Removed shows? | `status != 'active'` never appears: not in `/shows`, not in `/calendar/months`, and `/shows/{id}` answers 404. | `api-contract.md` §2, "Soft-deleted shows". The detail route is not mentioned there; 404 is the only answer that does not leak a row the reader is told does not exist. |
| Months? | Months that have at least one active show on or after the metro's today; `show_count` counts those same upcoming shows. Sorted by (year, month). | Requirements: "future facing, only months with shows". The count is not rendered anywhere (`show_count` appears only in the generated types), so the stricter reading costs nothing. |
| Order of shows? | The existing `_ordering` key (date, then no-time last, then time, then venue name), plus the show id as the last tie-break, applied in Python to the fetched rows. | Postgres collation differs between a laptop's Docker image, the cloud sandbox (Postgres 16), CI (18) and Neon, and none is verified to sort like Python. A key the tests state in Python is the same everywhere. The row count is bounded by `MAX_RANGE`. |
| Order of lists? | `/venues` and `/artists`: `(name.casefold(), id)` in Python. The test's expectation changes from `sorted(names)` to the same key. | Same collation reason, plus "alphabetical" should not put `iPhone` after `Zebra`. |
| Order of a lineup? | `sequence_number` ascending, nulls last, then `artist_id`. In Python. | The sample numbers every act, but the worker leaves it null when a listing gives no order (`schemas.py`). |
| NULL arrays and JSON? | `phone_numbers` / `emails` NULL → `[]`; `extra_metadata` NULL → `{}`. | The response models default to `[]` / `{}`; the columns are nullable. |
| `original_url`? | The `show.original_url` column, as stored. | `data-model-initial.md`: the page the show was most recently extracted from. |
| An unknown id? | 404 for a venue not in the live metro, as for a missing one. | Metro scoping, above. |

## Test approach (written first, watched fail, then made green)

Tests first (`alpha-build-plan.md` §3). The new Python tests are the bulk; the frontend gets one changed unit test and the existing browser suite, unchanged. Where the expected values come from is stated per group: **hand-derived from the rows in `sample_data.py`** (as `test_routers.py` already does), never read back from the code under test.

The DB tests run on `calendar_test` through the existing fixtures (`db_session`, rolled back per test). `pytest-asyncio` runs tests and fixtures on one session-scoped loop (`pyproject.toml`), which is what lets the app's `AsyncSession` and the test's session share a connection.

### The route-test fixture (`app/tests/conftest.py`, new)

`sample_client`: per test, load the sample world into `db_session` (flush, no commit), override `get_db` to yield that session and `get_now` to return a fixed instant (`2026-09-28T17:00:00Z`, noon in Minneapolis, the sample's `START`), build `httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")`, and clear the overrides afterwards. Tests that need a different clock or an emptier database build their own client from the same pieces (a small `make_client(session, now)` helper).

### T0. Production code does not import the sample world (`test_no_testing_imports.py`, no database)

Proves: no module under `app/` outside `app/tests/` and `app/testing/` imports anything from `app.testing` (parsed with `ast`, not grepped). This is the regression C2 exists to prevent: a router that quietly falls back to sample data would pass every route test, because the route tests run on the sample world. Fails if any router adds `from app.testing import sample_data`. (M7.)

### T1. The clock (`test_clock.py`, no database)

`metro_today(now, timezone)`:
- `2026-10-08T03:30Z` in `America/Chicago` is October 7 (the UTC date is the 8th). The test that separates "metro-local" from "UTC". (M3.)
- `2026-10-08T05:00Z` is October 8 (midnight CDT exactly).
- A winter instant (`2027-01-15T05:59Z`, CST, UTC−6) is January 14: the offset is read from the zone, not hard-coded to −5.
- A naive datetime is rejected (`ValueError`) rather than silently treated as local or UTC.

Expected values: arithmetic from the stated UTC offsets (CDT −5 until November 1, 2026; CST −6 after).

### T2. The loader and the seed (`test_sample_data_loader.py`, `test_seed.py`; database)

Loader, against an empty migrated database:
- Row counts: 1 metro, 4 venues, 10 artists, 26 shows, and one `show_artist` row per lineup entry (the sum of the sample's lineup lengths, worked out from `_SHOW_ROWS`).
- Ids equal the sample's (`venue 3` is Zhora Darling, `show 2` is its September 30 show). The loader inserts explicit ids because the fixtures and e2e specs name them.
- **The sequences are advanced**: inserting one more venue then one more show through the ORM gets id 5 and id 27, not a unique-violation on 1. (M8.)
- Venue 3 and artist 1 carry the detail the sample writes out; venue 1 carries the on-the-fly values the sample invents (`https://example.com/1/calendar`).
- Loading into a database that already has any metro, venue, artist or show row raises, so the loader cannot top up a real database.

`test_seed.py` (updated): `EXPECTED_VENUES` is the D8 list, typed out in the test as an independent statement of it; Midway and Zhora are absent; running twice changes nothing. The docstring's claim that seed ids line up with the fixtures is removed: they no longer do, and nothing depends on it (the fixtures' world is the sample world's, not the seed's).

### T3. The routes (`test_routers.py`, migrated; database)

**Ported unchanged in meaning** (all 22 current tests): envelopes, alphabetical lists (key per D5), unknown id 404 (999 and 99 stay above every sample id), non-integer id 422, the detail routes return the asked-for record, inherited-field resolution for show 2, date-range echo, repeated filters OR-ed, different filters AND-ed, artist anywhere in the lineup, order by date then time, invalid ranges 422, the OpenAPI checks, `/metro`, and the seven `upcoming` tests. The two that monkeypatch `data.START` now override `get_now` instead; `test_upcoming_starts_from_the_servers_today` keeps proving the lower bound is the server's today. The module docstring's "these cover shape and status code, not data correctness" is rewritten: with a database behind it, they now also cover data.

**New, each with its own hand-derived expectation:**
- *A removed show is invisible everywhere.* Mark show 2 `removed`: gone from `/shows`, `/shows/2` is 404, and its month count drops by one. A second case removes the only show of a month and the month disappears from `/calendar/months`. (M1.)
- *The default window starts at the metro's today.* With the clock at `2026-09-29T03:30Z` (still September 28 in Minneapolis), the echoed `start` is `2026-09-28`, not the 29th. (M3.)
- *Months are future-facing.* With the clock at `2026-10-20T17:00Z`, September is absent and October's count covers only shows from the 20th on.
- *Inheritance.* A show with `serves_alcohol=False` at a venue with `True` returns `False`; a show with `NULL` returns the venue's; both `NULL` returns `null`. Same shape for `age_restriction`, `setting`, `seating`. (M2.)
- *Missing array columns.* A venue with `phone_numbers`, `emails` and `extra_metadata` all `NULL` returns `[]`, `[]`, `{}`.
- *Metro scoping.* A second metro with a venue and a show: neither appears in `/venues`, `/shows`, `/calendar/months`, and `/venues/{its id}` and `/shows/{its id}` are 404. (M5.)
- *An empty database.* No metro row: every metro-scoped route answers 503 with a `detail` that names the seed; `/health` is unaffected.
- *Ordering.* A show with no time sorts after the timed shows on its date; two shows at the same time sort by venue name, then id. Lineup entries with a null `sequence_number` follow the numbered ones. (M4.)
- *Collation-proof lists.* Venues named `Zebra Room`, `apple hall`, `Mortimer's` come back as `apple hall`, `Mortimer's`, `Zebra Room`.
- *No N+1.* The number of SQL statements for `GET /shows` is the same for the 26-show world and for a world with 200 more shows (counted with a `before_cursor_execute` listener on the test connection). With `lazy="raise"` (D4) a missed eager load fails the first route test instead. (M6.)

### T4. The keystone: the routes agree with the fixtures (`test_fixtures_agree.py`; database)

For each fixture the generator writes (`metro`, `shows`, `show-detail`, `venues`, `venue-detail`, `artists`, `artist-detail`, `calendar-months`), call the real route on the loaded sample world (clock at `START`) and assert the JSON equals `fixture_payloads()[name].model_dump(mode="json")`. Expected values come from the pure builders in `sample_data.py`; the actual values come from the routes and the database. Neither side is read from the other, so a drift in either (a route that orders differently, a loader that drops a field, a builder edit) fails here. This is what justifies D1. It also covers the one place the sample's rules and the database's could differ without any other test noticing: `Decimal` and `time` round-tripping through `Numeric(10, 2)` and `Time`.

### T5. The end-to-end harness's own guards (`test_e2e_guards.py`; no database)

- `check_e2e_database_url`: refuses a database not named `calendar_e2e`, and refuses a non-local host; accepts `127.0.0.1` and `localhost` (the mirror of `check_test_database_url`'s tests).
- `e2e_app` refuses to import without `E2E_API_FROZEN_NOW`, and when `DATABASE_URL` names a database other than `calendar_e2e`.

### T6. The browser suite (`apps/calendar`)

`e2e/support/clock.test.ts` (Vitest) changes: it now guards **two** pins. The API pin's metro-local date must equal `shows.start` in `lib/fixtures/shows.json` (so the served window is the fixture's), and the Next pin must still fall inside the window on a day that has shows. Proves: moving the sample's `START` without moving the API pin, or the reverse, goes red the same day. The 17 Playwright specs and `screens.ts` are not edited: that they pass unchanged on the database-backed API is the test. Run `--repeat-each=3` once (the "three green runs" rule, `b6` plan).

### Mutation checks (`C2-M<n>`; each run during the build and logged)

A deliberate break of the code under test that a named test must catch. A mutation that no test catches means a missing test.

| # | Break | Test that must go red |
|---|---|---|
| M1 | Drop the `status == ACTIVE` filter from one query | the removed-show tests (list, detail, months) |
| M2 | Resolve an inherited field with `show.x or venue.x` | the `serves_alcohol=False` inheritance test |
| M3 | Take today from the UTC date | T1 first case; the default-window test |
| M4 | Skip the lineup / show sort | the ordering tests |
| M5 | Drop the metro scope from `/venues` or `/shows` | the second-metro test |
| M6 | Remove an eager-load option | the first route test (`lazy="raise"`), and the statement-count test |
| M7 | Import the sample world from a router | T0 |
| M8 | Skip the sequence reset in the loader | the loader's next-id test |
| M9 | Turn the OR across `venue_id` values into AND | `test_repeated_filter_values_are_or_ed` |
| M10 | Point `e2e_database` at a non-`calendar_e2e` name | T5 |

## Implementation steps

Branch `c2-api-reads-database` (matches the plan file, `AGENTS.md` "Branches and PRs"). Everything is `[written]` (D9). Tests for a step are written and watched fail before the step's code.

### 1. The sample world moves, and gains a loader — `[written]`

- `git mv apps/api/app/sample_data.py apps/api/app/testing/sample_data.py`. Rewrite the docstring: it no longer "stands in for the database" or is "TEMPORARY"; it is the one deterministic world that the fixtures, the route tests and the e2e job share (D1), and nothing under `app/` outside `app/testing/` may import it (T0).
- Add `fixture_payloads() -> dict[str, BaseModel]` (the eight fixture bodies, moved out of `generate_fixtures.py`'s `main`, including the in-window filter and its B4 comment) and `async load_sample_data(session)` (explicit ids, sequence reset with `setval(pg_get_serial_sequence(...))`, refuses a non-empty database). Show `original_url` is set to the venue's `calendar_url`, as the sample's `show_detail` already returns it.
- `scripts/generate_fixtures.py` becomes a thin writer over `fixture_payloads()`.
- A comment-only pass over the roughly fifteen files that name `apps/api/app/sample_data.py` (frontend tests, `e2e/support/*`, `playwright.config.ts`, docs): the path gains `testing/`. Verified as a comment-only change (syntax trees before and after, `AGENTS.md` "Comment-only passes"). The routers and `test_routers.py` are rewritten in later steps, not edited here.

### 2. Relationships — `[written]`

`app/db/models/calendar.py`: `Show.venue`, `Show.lineup` (to `ShowArtist`), `ShowArtist.artist`, `Venue.metro`, each `viewonly=True, lazy="raise"` (D4). Update the module docstring's "No `relationship()`s" paragraph to say what was added, by which consumer, and why read-only. No migration (relationships are not schema); `test_db_metadata.py` and the autogenerate drift test stay green.

### 3. The clock and the dependencies — `[written]`

- `app/clock.py`: `get_now()` (the aware UTC instant; the only place the process clock is read) and `metro_today(now, timezone)` (T1).
- `app/db/session.py`: `get_db()`, yielding one `SessionFactory()` session per request. Update the docstring that said no `get_db` exists yet.
- `app/dependencies.py`: `current_metro` (the lowest-id metro, 503 when absent) and the `Annotated` aliases the routers use.

### 4. Queries and routers — `[written]`

- `app/queries.py`: `list_venues`, `get_venue`, `list_artists`, `get_artist`, `list_shows`, `get_show`, `list_months`, each taking the session (and metro and today where they need them) and returning `schemas.py` models. One `_summary(show)` builder is the single place an ORM show becomes a `ShowSummary`; `resolve_inherited` is the D6 helper. Loads are explicit (`joinedload(Show.venue)`, `selectinload(Show.lineup).joinedload(ShowArtist.artist)`). The `venue_id` / `artist_id` predicate is the OR-within, AND-across rule from the contract; the artist test is `EXISTS` over the lineup.
- Each router: `async def`, signature and `responses=NOT_FOUND` unchanged, the `upcoming` and `MAX_RANGE` rules kept where they are (they are request validation, not data), `data.START` replaced by `today`. Docstrings lose "TEMPORARY IMPLEMENTATION".
- `app/main.py` and `/health/db`: unchanged (D3; the schema-aware health check is C3's, with `APP_ENV`).

### 5. Route tests migrate — `[written]`

`test_routers.py` moves to the `sample_client` fixture and `httpx.AsyncClient`, per T3. The `StarletteDeprecationWarning` that `apps/api/AGENTS.md` names disappears with `TestClient`; delete that divergence row. New files: `test_clock.py`, `test_no_testing_imports.py`, `test_sample_data_loader.py`, `test_fixtures_agree.py`, `test_e2e_guards.py`; `test_seed.py` updated.

### 6. The seed list — `[written]`

`app/db/seed.py`: `VENUES` becomes the D8 list, with a comment per entry saying where its URL and strategy came from and what is unverified (the two new rows' strategy). Update the "same four venues as sample_data" paragraph and the `make seed` description in `apps/api/AGENTS.md`.

### 7. The end-to-end job — `[written]`

- `app/testing/e2e_database.py`: `check_e2e_database_url`, then drop, create, `alembic upgrade head`, `load_sample_data`; runnable as `python -m app.testing.e2e_database`.
- `app/testing/e2e_app.py`: imports `app.main.app`, checks the database name, reads `E2E_API_FROZEN_NOW`, overrides `get_now`, exposes `app`.
- `e2e/support/clock.ts`: add `E2E_API_NOW = "2026-09-28T17:00:00Z"` beside `E2E_NOW`, each with its reason (D2). `clock.test.ts` per T6.
- `playwright.config.ts`: the API entry's command becomes `uv run python -m app.testing.e2e_database && exec uv run uvicorn app.testing.e2e_app:app --host 127.0.0.1 --port ${API_PORT}`, with `DATABASE_URL` set to the `calendar_e2e` URL (overridable by `E2E_DATABASE_URL` for a different Postgres host) and `E2E_API_FROZEN_NOW`. **`exec` matters**: the existing config's `gracefulShutdown` comment explains that `uv run` is a parent and a child; wrapping it in `sh -c "a && b"` without `exec` leaves the shell between Playwright's SIGTERM and uvicorn, and an orphaned listener on 8101 makes the next run fail. Verify no listener remains after the suite (`notes.md`, "`pkill -f next start` kills the shell that runs it", is the nearby trap).
- `ci.yml`: the `e2e` job gains the `postgres:18` service the `python` job uses and its health check; its comments ("No Postgres", "sample data") are rewritten.
- `Makefile`: the `e2e` comment drops "needs no Postgres"; the target fails early with the fix in its message when Postgres is unreachable (the guard's connection error already says `make db-up`).

### 8. The local-verification harness — `[written]`

`agent_worker/local_test.py` takes `--fixture PATH` and `--fetched-on YYYY-MM-DD`, defaulting to today's constants so `uv run python -m agent_worker.local_test` behaves as before. Not collected by pytest (its name, `AGENTS.md` / `apps/api/AGENTS.md`). One small test for the argument parsing if the parsing is separable; the run itself needs Ollama and is Ari's.

### 9. Docs and plan bookkeeping — `[written]`

- `api-contract.md`: §2 intro and the "Milestone" column (the routes read the database; `/metro` too); §3 "The server owns now" gains the concrete rule (D5: the metro's timezone); §8 says where the fixtures' source now lives (D1) and that the window is the sample's because the fixture test pins the clock to `START`.
- `notes.md`: rewrite the B6-owned section "Only the 'Today' row follows the real clock" (the API's clock is real now; the e2e job pins both, deliberately apart, D2). Add the entries this milestone earns once the build has: `viewonly`/`lazy="raise"`, collation-proof ordering, and anything the build finds.
- `docs/dev/conventions.md`: add the `C2` scope row. `alpha-build-plan.md`: the A1b pointer says done. `alpha-deployment-plan.md`: tick C2's boxes and update the §1.1 rows "API data source", "Sample window", "What C2 changes" and "E2E stack" to their new state.
- `c1-env-revalidation.md`: append a dated "C2" line under Neon recording what Ari found and did (it is the document `AGENTS.md` points at for what hosted services look like today).
- **`AGENTS.md` (Ari approves):** the "Never hand-edit" paragraph names `app/sample_data.py` (now `app/testing/sample_data.py`); the Cloud sessions paragraph says `make e2e` "needs no Postgres, because the API it starts serves the sample data" (now it needs Postgres, which the sandbox has); "Suited to cloud" already lists "routes onto the DB" and stays. These change project instructions, so the build proposes the edit and Ari signs it off, as C1 did.

### 10. Ari: Neon, before the merge (not a cloud task)

Ordered; the merge waits for all of it.

1. **Reset the Neon database password and update Railway's `DATABASE_URL`** (`c1-env-revalidation.md`: the password was pasted into a chat during C1). Never paste a connection string or password into a chat, a doc or a commit.
2. From `apps/api`, with the one-command override (never edit `apps/api/.env`): `DATABASE_URL='postgresql+asyncpg://…' uv run alembic upgrade head`, then `DATABASE_URL=… uv run python -m scripts.seed`. The URL has no `sslmode` or `channel_binding` parameters (`notes.md`).
3. Run this branch's API against it: `DATABASE_URL=… uv run uvicorn app.main:app --port 8000`, and check every route (Verification, Ari step 1).
4. Record the result in the implementation log and in `c1-env-revalidation.md`.

The Neon branch in question is whichever branch the *current* production Railway service uses (the default branch today); C3 later splits environments.

### 11. Ari: local verification — see Verification.

## `TODO(Ari)` gaps

None (D9). The nearest candidate, if Ari wants one: the `/shows` filter predicate in `queries.list_shows` (OR within a type, AND across types, artist anywhere in the lineup through `EXISTS`). Mutation M9 and the existing OR / AND tests are its check.

## Critical files

| File | Why |
|---|---|
| `apps/api/app/routers/{shows,venues,artists,calendar,metro}.py` | Bodies replaced; signatures and error codes held |
| `apps/api/app/queries.py` (new) | Where ORM rows become `schemas.py` models |
| `apps/api/app/clock.py`, `app/dependencies.py`, `app/db/session.py` | The clock, the metro, `get_db` |
| `apps/api/app/db/models/calendar.py` | Relationships |
| `apps/api/app/testing/sample_data.py` (moved), `app/testing/e2e_database.py`, `app/testing/e2e_app.py` | The shared world and the harness that loads it |
| `apps/api/app/db/seed.py` | Dep-D16's list |
| `apps/api/app/tests/*` | The migrated and new tests |
| `apps/api/scripts/generate_fixtures.py` | Becomes a writer over `fixture_payloads()` |
| `apps/calendar/playwright.config.ts`, `e2e/support/clock.ts`, `clock.test.ts` | The API's start command and the two pins |
| `.github/workflows/ci.yml`, `Makefile` | Postgres for the e2e job |
| `apps/api/agent_worker/local_test.py` | Replay two captures |
| `docs/dev/api-contract.md`, `notes.md`, `conventions.md`, `alpha-*-plan.md`, `c1-env-revalidation.md`, `AGENTS.md` | Bookkeeping (step 9) |

## Verification

**In the cloud (and what the build records):**

1. `make check` green: ruff, mypy, pytest with `REQUIRE_DB=1`, vitest, `contract-check`, `designation-check`, and the Playwright suite on the database-backed API.
2. `make types fixtures` produces an **empty diff** (D3, D1).
3. The mutation table: each M run, red as stated, reverted.
4. `make e2e E2E_ARGS="--repeat-each=3"` once, then `ss -ltn | grep -E ':(8101|8102|3100)\b'` shows no listener left behind.
5. The Neon and local steps below are *not* run here: no route to Neon, Ollama or the venue sites.

**Ari, step 1 — Neon (before the merge).** After the migration and seed, against the locally run API pointed at Neon:

| Request | Expect |
|---|---|
| `GET /health/db` | 200 |
| `GET /metro` | 200, `Minneapolis/St. Paul`, `America/Chicago` |
| `GET /venues` | 200, the D8 list, alphabetical |
| `GET /venues/{id of a seeded venue}` | 200 |
| `GET /shows` | 200, `shows: []`, `start` = today in Minneapolis (Dep-D12: empty until a worker run) |
| `GET /calendar/months` | 200, `months: []` |
| `GET /artists` | 200, `artists: []` |
| `GET /venues/9999`, `/artists/9999`, `/shows/9999` | 404 |
| `alembic current` | the latest revision (`67609c405218`) |

**Ari, step 2 — local, the worker twice (needs Ollama, Docker, the venue sites).** `make db-reset` for a clean `calendar_dev`, then `uv run python -m agent_worker.local_test --fixture <first White Squirrel capture> --fetched-on <its date>`, then the second capture the same way. The captures are gitignored under `agent_worker/eval/fixtures/` and **their file names are not visible from the cloud; unverified here**. Then:

- Read the audit trail with the queries in `docs/dev/audit-queries.sql`: the first run inserts; the second shows what reconcile decided (insert, update, soft delete, or no change) for each show.
- `make dev`, then open `/?month=<the capture's month>` (the home page's default window now starts at the real today, and the captures are from August and October). The venue, show and artist pages open through their links.
- Two things this will show that are not bugs: `show.original_url` is the fixture's file path (`local_test` passes it as the URL), so the "source" link is a path; and the date range the page shows is the month, not four weeks.
- **If the two captures turn out not to differ enough to produce an update and a soft delete, say so in the implementation log** and rely on A5's and A6's database tests for those two (`a5-reconcile.md`, `a6-commit.md`), as the deployment plan allows. Do not claim point 2 closed on inserts and no-ops alone.

**After the merge:** Railway deploys; `GET /health/db` and `GET /shows` on the Railway URL answer as in step 1; the Vercel production page loads (an empty calendar, Dep-D12) rather than an error page.

## Not doing in C2

- A schema-aware `/health/db`, `APP_ENV`, migrations on deploy, and environments (C3). Merging C2 does not make future migrations run themselves.
- An index on `show(date)` or `show(status)`. The window query filters by date across venues and `show(venue_id, date)` leads with `venue_id`; at tens of venues and tens of shows a month a sequential scan is cheap. Add one when a measurement says so.
- Pagination, caching (`arch-initial.md` §11), any new endpoint or parameter, the venue "active" flag, the metro slug (C4).
- Editing any of the 17 Playwright specs, `lib/fixtures/` or `lib/api-types.ts` by hand.
- A route-smoke script. The Neon table above is nine requests; C3 and C8 are where a reusable one would earn its place.
- Running the worker's write path through the new relationships (they are read-only).

## Unverified, stated plainly

- The two new venues' `fetch_strategy` (D8): assumed `http`, not checked, because the cloud cannot reach venue sites.
- That Playwright's `webServer` runs a `&&` command through a shell and that `exec` leaves no orphan (step 7). Checked during the build, not assumed.
- The names of the White Squirrel captures, and whether the two differ in a way reconcile will call an update and a removal (step 2).
- Neon's current state after the password reset: C1 recorded no tables; this plan assumes that is still true and treats `alembic upgrade head` as the first migration, not a catch-up.
- That Python-side sorting and collation-free queries agree across Postgres 16 (the sandbox), 18 (CI, Docker) and Neon: the design avoids relying on any of them (D5), and T3's collation test is what would catch a regression.

## Plan review

## Implementation log

## Code review
