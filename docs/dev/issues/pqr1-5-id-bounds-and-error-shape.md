# PQR1-5: out-of-range ids are a 500, and a 422 has two body shapes

**Status:** Plan review
**Date:** November 6, 2026
**Scope:** PQR1-5, PQR1-11
**Sources:** PQR1-5 → `docs/dev/review/2026-11-06-python-code-quality-review.md` §3 Details row PQR1-5;
PQR1-11 → the same table, row PQR1-11 (the row says "Either … or …" and asks that the choice be recorded in `api-contract.md`)
**Tier:** T2 — PQR1-11 changes the body of an API response that `api-contract.md` documents (a contract change), and the
two fixes the source offers are a design choice that no document settles (D1 below). PQR1-5 alone would be T1: one
area, a clear fix. The record takes the higher tier.
**Author model:** Claude Sonnet 5.5 (record and plan, November 6, 2026; cloud session)
**Reviewer model:** not yet run
**Branch / PR:** `claude/dazzling-dirac-aguwd0` (designated by the cloud session; no commits beyond `main`, so no restart
was needed) / none yet

**Designations.** Review items here are bare (`CR1-2`, `PR1-1`). Outside this record they are `PQR1-5-CR1-2`,
`PQR1-5-PR1-1` (`docs/dev/issues/README.md`, `docs/dev/conventions.md`). Decisions are written `D1`, `D2` here and
`PQR1-5-D1` elsewhere.

**Diff base:** `1bb52299cc8124434fa9ba0146d6911566b0caa8` (`main` at the start of this run).

## Issues

### PQR1-5: an out-of-range id is a 500, not a 404 or 422

**What's wrong.** The three detail routes take `show_id: int`, `venue_id: int`, `artist_id: int`, and `/shows` takes
`venue_id` and `artist_id` as `list[int]`. The database columns are `integer` (int32). A value above 2,147,483,647
passes FastAPI's validation, reaches asyncpg, and comes back as an unhandled `DBAPIError`. The two list parameters also
have no length cap.

**Evidence (reproduced in this session, against the real app and the sandbox Postgres, through an ASGI transport that
returns the 500 instead of raising it):**

| Request | Today |
|---|---|
| `GET /shows/99999999999` | 500 Internal Server Error |
| `GET /venues/99999999999` | 500 |
| `GET /artists/99999999999` | 500 |
| `GET /shows?venue_id=99999999999` | 500 |
| `GET /shows/0` | 404 `{"detail":"Show not found"}` |

The review's second claim, that "a list of 5,000 `venue_id` values was accepted", is taken from the review, not
reproduced here.

**Fixed means:** no id or id-filter value can reach the database outside int32 range; such a request answers a 4xx the
generated TypeScript already knows about, never a 500; the lists have a documented cap; a test pins each bound.

### PQR1-11: two error-body shapes for a 422

**What's wrong.** `app/routers/shows.py` raises four hand-written `HTTPException(status_code=422, detail="<string>")`.
FastAPI's own validation answers 422 with `detail` as a list of `{type, loc, msg, input}` objects. A client has to handle
both under one status code.

**Evidence (reproduced in this session):**

- `GET /shows?start=2026-01-01&end=2025-01-01` → `422 {"detail":"`end` must be on or after `start`"}`
- `GET /shows?start=notadate` → `422 {"detail":[{"type":"date_from_datetime_parsing","loc":["query","start"],"msg":"Input should be a valid date or datetime, input is too short","input":"notadate"}]}`
- The generated `apps/calendar/lib/api-types.ts` declares `HTTPValidationError` (`detail?: ValidationError[]`) as the 422 body
  of the routes. So the OpenAPI document and the generated types already promise the list shape; the four
  hand-raised 422s are the ones that break the promise.
- Nothing in `apps/calendar` reads the 422 body: `lib/api.ts` turns any non-2xx other than a 404 on a detail route into
  an `ApiError` carrying the status, and `grep` for `.detail` finds no consumer. The change is invisible to the frontend,
  and visible to any other client.

**Fixed means:** every 422 the API produces has the same body shape; the choice and the shape are written in
`api-contract.md`; a test pins it for each of the four hand-raised sites and for one FastAPI-raised 422.

## Approach

### Decisions for Ari

> **These two need Ari's answer before code.** Each has a recommendation, and the plan below is written for the
> recommended option. Approving the record with "go ahead" accepts both recommendations.

**D1 — How to unify the 422 body (PQR1-11).** The source offers two ways; no document chooses.

| | A. Raise `RequestValidationError` from the route (recommended) | B. One exception handler that wraps string 422s |
|---|---|---|
| What changes | The four `raise HTTPException(422, …)` become `raise RequestValidationError([{type, loc, msg, input}])` through one small helper in `app/routers/common.py` | A handler for `HTTPException` with status 422 turns `detail: str` into a one-item list |
| `loc` | Names the real parameter: `["query","end"]`, `["query","upcoming"]`, `["query","start"]`. A client can highlight the field | Has no parameter to point at; `loc` would be `[]` or `["query"]` |
| New machinery | None. FastAPI's own handler produces the body (verified in this session: `{"detail":[{"type":"value_error","loc":["query","end"],"msg":"…","input":"2025-01-01"}]}`) | A new global handler that every later `HTTPException(422)` silently goes through |
| Risk | A hand-built error dict is not type-checked against Pydantic's `ErrorDetails` | The handler hides a wrong shape instead of failing a test |

Recommendation: **A**. It reuses the mechanism FastAPI already uses for the other 422s, gives `loc` a real value, and adds
no global behavior. Not in scope under either option: 404 and 503 keep `{"detail": "<string>"}` (the review row covers
422 only); `api-contract.md` will say so, so "two shapes" does not come back as a surprise for 404.

**D2 — What an out-of-range id answers (PQR1-5), and the cap on the id lists.**

- **Status:** the review suggests `Path(ge=1, le=2**31 - 1)`, which answers **422**. The alternative is a 404 ("no such
  show"). Recommendation: **422 with `ge=1, le=2**31-1`**. The frontend already refuses anything outside 1..2,147,483,647
  before it calls the API (`parseIdParam`, `MAX_ID = 2147483647`, `apps/calendar/lib/params.ts:66`), so the page answers
  404 itself and the API's 422 is only seen by other clients, for whom "your value is invalid" is the accurate answer.
  Side effect to accept: `/shows/0` and `/shows/-1` change from 404 to 422 (the frontend never sends them).
- **List cap:** `venue_id` and `artist_id` get `max_length`. Recommendation: **100**. The metro has tens of venues
  (`api-contract.md` §2, "Pagination") and a multi-select can only send ids it was shown, so 100 is above any real request
  and bounds the `IN (…)` list. Ari may prefer a different number; nothing else depends on it.

### Context

Both issues are about the edge of the read API: what a request may contain, and what a refusal looks like. They share the
files (`app/routers/*.py`, `app/dependencies.py`, `docs/dev/api-contract.md`, `app/tests/test_routers.py`) and one theme,
"a 4xx is a documented, uniform answer", which is why they are one record. Neither touches `app/schemas.py`, a migration,
or the worker.

### Test approach (tests first)

All tests go in `apps/api/app/tests/test_routers.py` beside the route tests they extend, using `sample_client`. Each opens
with `Proves:` and says where the expected values come from. Each is run before the fix and shown to fail.

1. **`test_ids_outside_int32_are_422_not_500`** — parametrized over `/shows/{n}`, `/venues/{n}`, `/artists/{n}` for
   `n` in `0`, `-1`, `2**31`, `99999999999`. Proves: a path id outside 1..2,147,483,647 is a 422 and never reaches the
   database. Fails today: `2**31` and `99999999999` raise `DBAPIError` (the test client needs `raise_app_exceptions=False`, or
   `pytest.raises`, so the failure shows as a 500 and not an exception; the plan picks the first, matching the probe), and
   `0`/`-1` are 404.
2. **`test_the_largest_int32_id_is_still_a_404`** — `/shows/2147483647`, `/venues/…`, `/artists/…` answer 404. Proves the
   upper bound is inclusive and not off by one (it is the boundary that `le` and the column share). Passes today and must
   keep passing; it guards the fix from over-tightening.
3. **`test_id_filters_are_bounded`** — `/shows?venue_id=2147483648` and `?artist_id=0` are 422; `?venue_id=` repeated 101
   times is 422; repeated 100 times (ids that exist or not) is 200. Fails today for the first two (500, 200).
4. **`test_every_422_has_the_same_body_shape`** — the four hand-raised sites (`end` before `start`, range too wide,
   `upcoming` with `start`, `upcoming` with no filter) plus one FastAPI-raised one (`start=notadate`): each body is
   `{"detail": [...]}` with a non-empty list whose items have `type`, `loc`, `msg`. Fails today for the four.
5. **`test_a_hand_raised_422_names_its_parameter`** — `end` before `start` has `loc == ["query","end"]`; `upcoming` with
   `start` has `loc == ["query","upcoming"]`. Proves why D1-A was chosen; fails today.

The existing `test_invalid_ranges_are_rejected` and `test_upcoming_rejects_contradictory_or_unbounded_requests` keep
asserting the status and stay green. `test_unknown_id_is_404_not_500` (999, 99) is unaffected.

### Steps

1. Write the five tests; run them; record the failures in the Implementation log.
2. `app/dependencies.py` (PQR1-5): add `MAX_DB_ID = 2**31 - 1`, `MAX_ID_FILTERS = 100`, and the aliases
   `DbId = Annotated[int, Path(ge=1, le=MAX_DB_ID)]` and
   `IdFilter = Annotated[list[Annotated[int, Field(ge=1, le=MAX_DB_ID)]] | None, Query(max_length=MAX_ID_FILTERS)]`. The
   item-level `Field` is deliberate: whether `Query(ge=…, le=…)` applies to each item or to the list must be verified in
   step 1's probe, not assumed (a Pydantic v2 / FastAPI detail). The module docstring's list of aliases is updated.
3. `app/routers/shows.py`, `venues.py`, `artists.py` (PQR1-5): use `DbId` for the three path ids and `IdFilter` for the two
   filters. Comments say why (the column is int32; cite PQR1-5 once, at the alias).
4. `app/routers/common.py` + `app/routers/shows.py` (PQR1-11): add `unprocessable(param, message, value)` returning a
   `RequestValidationError` with one `{type: "value_error", loc: ("query", param), msg: message, input: value}`; the four
   sites become `raise unprocessable(...)`. The messages stay as they are, so no client's text changes. The `HTTPException`
   import in `shows.py` stays for the 404.
5. `docs/dev/api-contract.md` §2/§3 (PQR1-11, PQR1-5): add an "Errors" paragraph: 422 is always
   `{"detail": [{type, loc, msg, input}]}` (FastAPI's `HTTPValidationError`), 404 and 503 are `{"detail": "<string>"}`; an id
   outside 1..2,147,483,647 or a list of more than 100 ids is a 422. Record D1 and D2 there with their one-line reasons.
6. `docs/dev/review/2026-11-06-python-code-quality-review.md` §8: set the PQR1-5 and PQR1-11 rows to `In PR` with the PR link
   and this record (step 7 of the run).
7. Run `make types fixtures` and confirm no diff in `apps/calendar/lib/api-types.ts` or `lib/fixtures/` (the OpenAPI
   document gains `minimum`/`maximum`/`maxItems`, which `openapi-typescript` does not render; if it does change them, the
   regenerated output is committed, never hand-edited).

### Critical files

`apps/api/app/dependencies.py`, `apps/api/app/routers/{shows,venues,artists,common}.py`,
`apps/api/app/tests/test_routers.py`, `docs/dev/api-contract.md`, the review doc's §8 tracker.

### Verification

- The five new tests fail first and pass after (recorded in the log).
- `make check` (lint, typecheck, tests, contract-check, designation-check, e2e) and
  `make designation-check BASE=1bb52299cc8124434fa9ba0146d6911566b0caa8`.
- Reproduce the probe table above against the fixed app: the four 500s become 422; `/shows/0` becomes 422.
- Nothing needs the model or the network to venue sites, so there is no **local check pending**.
- Sandbox caveat from `AGENTS.md`: Node 22 here and 24 in CI, so a green JS check here is not quite a green CI.

### Out of scope, noticed

- `PQR1-20` (pagination) interacts with the id-list cap only in that both bound request size; left alone.
- 404 and 503 still use a string `detail` (see D1). If Ari wants one shape for every error, that is a separate record.

## Plan review

## Implementation log

## Code review
