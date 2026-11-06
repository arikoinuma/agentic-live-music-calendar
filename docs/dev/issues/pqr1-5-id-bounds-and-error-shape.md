# PQR1-5: out-of-range ids are a 500, and a 422 has two body shapes

**Status:** Awaiting approval
**Date:** November 6, 2026
**Scope:** PQR1-5, PQR1-11
**Sources:** PQR1-5 → `docs/dev/review/2026-11-06-python-code-quality-review.md` §3 Details row PQR1-5;
PQR1-11 → the same table, row PQR1-11 (the row says "Either … or …" and asks that the choice be recorded in `api-contract.md`)
**Tier:** T2 — PQR1-11 changes the body of an API response that `api-contract.md` documents (a contract change), and the
two fixes the source offers are a design choice that no document settles (D1 below). PQR1-5 alone would be T1: one
area, a clear fix. The record takes the higher tier.
**Author model:** Claude Sonnet 5.5 (record and plan, November 6, 2026; cloud session)
**Reviewer model:** Claude Opus 5.5 (plan review round 1, November 6, 2026; cloud session)
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
generated TypeScript already knows about, never a 500; a test pins each bound. The id lists get **no length cap**: the
review row mentions it, and Ari decided not to (D2), so it is out of "fixed means".

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

**D2 — What an out-of-range id answers (PQR1-5), and whether the id lists get a cap.** The cap part is **decided by
Ari, November 6, 2026: no cap.** The status part still waits on his approval.

- **Status:** the review suggests `Path(ge=1, le=2**31 - 1)`, which answers **422**. The alternative is a 404 ("no such
  show"). Recommendation: **422 with `ge=1, le=2**31-1`**. The frontend already refuses anything outside 1..2,147,483,647
  before it calls the API (`parseIdParam`, `MAX_ID = 2147483647`, `apps/calendar/lib/params.ts:66`), so the page answers
  404 itself and the API's 422 is only seen by other clients, for whom "your value is invalid" is the accurate answer.
  Side effect to accept: `/shows/0` and `/shows/-1` change from 404 to 422 (the frontend never sends them).
- **List cap: none (Ari's decision).** The review row also asks for a length cap on `venue_id` / `artist_id`. Ari chose
  not to add one: the metro is expected to stay under 100 venues, artists are not near 100 either, and a cap would
  solve a problem that does not exist yet. Reasons and trade-offs weighed before deciding:
  - A cap adds little protection on its own: the URL length limit (roughly 8 to 16 KB, reasoned and not measured) stops a
    request at several hundred ids, before any database limit.
  - A cap needs a frontend half. `parseIdList` (`apps/calendar/lib/params.ts:134`) forwards every distinct valid id, so a
    shared URL over the cap would become a 422 and the error page (PQR1-5-PR1-3), or, if the frontend truncated, a page
    that silently filters fewer ids than its URL names. Neither was worth building now.
  - **Revisit when:** a "select all" exists in the filter UI, or artists approach the hundreds. Then add `max_length` to the
    list alias and cap `parseIdList` in the same change. The review row (PQR1-5) stays open on this point in the tracker's
    note, so it is not lost.

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
   database. Fails today: `2**31` and `99999999999` raise `DBAPIError` (through the stock `sample_client` the error
   propagates into the test, which is the failing-first evidence to record; `app/testing/api_client.py` is not changed,
   PR1-1), and `0`/`-1` are 404.
2. **`test_the_largest_int32_id_is_still_a_404`** — `/shows/2147483647`, `/venues/…`, `/artists/…` answer 404. Proves the
   upper bound is inclusive and not off by one (it is the boundary that `le` and the column share). Passes today and must
   keep passing; it guards the fix from over-tightening.
3. **`test_id_filters_are_bounded`** — `/shows?venue_id=2147483648` and `?artist_id=0` are 422, and `?venue_id=2147483647` is
   200 (an empty result, the inclusive upper bound). Fails today for the first two (500, 200). The existing
   `test_repeated_filter_values_are_or_ed` already sends valid repeated ids, so it guards the alias against the
   `Query(ge=…)` mistake in step 2 (PR1-2).
4. **`test_every_422_has_the_same_body_shape`** — the four hand-raised sites (`end` before `start`, range too wide,
   `upcoming` with `start`, `upcoming` with no filter) plus one FastAPI-raised one (`start=notadate`): each body is
   `{"detail": [...]}` with a non-empty list whose items have `type`, `loc`, `msg`. Fails today for the four.
5. **`test_a_hand_raised_422_names_its_parameter`** — pins all four `loc`s from the table in step 4 (`end` before `start` and
   range too wide → `["query","end"]`; both `upcoming` guards → `["query","upcoming"]`). Proves why D1-A was chosen; fails
   today.
The existing `test_invalid_ranges_are_rejected` and `test_upcoming_rejects_contradictory_or_unbounded_requests` keep
asserting the status and stay green. `test_unknown_id_is_404_not_500` (999, 99) is unaffected.

### Steps

1. Write the five tests; run them; record the failures in the Implementation log.
2. `app/dependencies.py` (PQR1-5): add `MAX_DB_ID = 2**31 - 1` and the aliases
   `DbId = Annotated[int, Path(ge=1, le=MAX_DB_ID)]` and
   `IdFilter = Annotated[list[Annotated[int, Field(ge=1, le=MAX_DB_ID)]] | None, Query()]` (no `max_length`: D2). The
   item-level `Field` is deliberate and verified by the reviewer: `Query(ge=1)` on a `list[int]` registers without error but
   answers 500 to every supplied value (`TypeError: Unable to apply constraint 'ge'`), so the alias's comment says "do not
   move these onto `Query`" and the existing repeated-ids test guards it (PR1-2). The module docstring's list of aliases is
   updated.
3. `app/routers/shows.py`, `venues.py`, `artists.py` (PQR1-5): use `DbId` for the three path ids and `IdFilter` for the two
   filters. Comments say why (the column is int32; cite PQR1-5 once, at the alias).
4. `app/routers/common.py` + `app/routers/shows.py` (PQR1-11): add `unprocessable(param, message, value)` returning a
   `RequestValidationError` with one `{type: "value_error", loc: ("query", param), msg: message, input: value}`; the four
   sites become `raise unprocessable(...)`, with these locs (PR1-5):

   | Site | `loc` | `input` |
   |---|---|---|
   | `end` before `start` | `["query","end"]` | the `end` value |
   | range too wide | `["query","end"]` (with `end` alone, `start` is the server's default, so naming `start` would echo a value the client never sent) | the `end` value |
   | `upcoming` with `start` or `end` | `["query","upcoming"]` | `true` |
   | `upcoming` with no venue or artist | `["query","upcoming"]` | `true` |

   Hand-raised `input` values pass through `jsonable_encoder` (a date becomes `"2025-01-01"`, `True` becomes JSON `true`,
   where FastAPI's own errors echo the raw string); harmless, and written in the contract. The messages stay as they are,
   so no client's text changes. The `HTTPException`
   import in `shows.py` stays for the 404.
5. `docs/dev/api-contract.md` §3 Conventions, a new "Errors" subsection (PQR1-11, PQR1-5, PR1-6): 422 is always
   `{"detail": [{type, loc, msg, input, ctx?}]}` (FastAPI's `HTTPValidationError`; `ctx` appears on FastAPI-raised items only,
   hand-raised ones have none), 404 and 503 are `{"detail": "<string>"}`; an id (path or filter) outside 1..2,147,483,647
   is a 422; the id lists have no length cap. Record the decisions there as `PQR1-5-D1` and `PQR1-5-D2` (a bare `D1` fails
   `make designation-check`), each with its one-line reason.
5a. `apps/calendar/lib/params.ts` and `params.test.ts` (PR1-4), **comments only**: reword the comment
   at `params.ts:62-65` ("a 500 once the routers are DB-backed" becomes: the API now answers 422 at the edge, which the
   page would show as the error page, so the frontend answers 404 itself) and the one at `params.test.ts:61-64` the same way.
   `b2-routes-and-data-loading.md` is history and stays. This is a comment-only pass on two files, so it is verified as one
   (syntax trees compared before and after, then `make check`; `AGENTS.md`, Conventions).
6. `docs/dev/review/2026-11-06-python-code-quality-review.md` §8: set the PQR1-5 and PQR1-11 rows to `In PR` with the PR link
   and this record (step 7 of the run).
7. Run `make types fixtures` and confirm no diff in `apps/calendar/lib/api-types.ts` or `lib/fixtures/` (the OpenAPI
   document gains `minimum`/`maximum` on the ids, which `openapi-typescript` does not render; if it does change them, the
   regenerated output is committed, never hand-edited).

### Critical files

`apps/api/app/dependencies.py`, `apps/api/app/routers/{shows,venues,artists,common}.py`,
`apps/api/app/tests/test_routers.py`, `apps/calendar/lib/params.ts`, `apps/calendar/lib/params.test.ts`,
`docs/dev/api-contract.md`, the review doc's §8 tracker.

### Verification

- The five new tests fail first and pass after (recorded in the log).
- `make check` (lint, typecheck, tests, contract-check, designation-check, e2e) and
  `make designation-check BASE=1bb52299cc8124434fa9ba0146d6911566b0caa8`.
- Reproduce the probe table above against the fixed app: the four 500s become 422; `/shows/0` becomes 422.
- Nothing needs the model or the network to venue sites, so there is no **local check pending**.
- Sandbox caveat from `AGENTS.md`: Node 22 here and 24 in CI, so a green JS check here is not quite a green CI.

### Out of scope, noticed

- The id-list length cap the review row asks for is **deliberately not done** (D2, Ari). When the tracker row moves to
  `In PR`, its note says "int32 bounds done; list cap deferred by decision".
- 404 and 503 still use a string `detail` (see D1). If Ari wants one shape for every error, that is a separate record.

## Plan review

### Round 1 (Claude Opus 5.5, November 6, 2026)

**Scope:** the plan as committed in `ad48a60` (Issues and Approach), against diff base
`1bb52299cc8124434fa9ba0146d6911566b0caa8`. No code exists yet.

**What was checked and how.** Read `AGENTS.md`, `docs/dev/issues/README.md`, the review doc's PQR1-5 and PQR1-11 rows and
§8 tracker, `docs/dev/api-contract.md` §2–§3, the FastAPI style guide's Anti-patterns table, and the code the plan names
(`app/dependencies.py`, `app/routers/{shows,venues,artists,calendar,metro,common}.py`, `app/tests/conftest.py`,
`app/testing/api_client.py`, `app/tests/test_routers.py`, `apps/calendar/lib/params.ts`, `lib/api.ts`, `lib/api-types.ts`).
Installed versions: FastAPI 0.162.0, Pydantic 2.13.4, Starlette 1.6.0. Experiments ran in a throwaway `git worktree`
under the session scratchpad (removed afterwards) and in standalone scripts there:

- Standalone FastAPI app with the plan's `DbId` and `IdFilter` aliases: `/s/0` and `/s/2147483648` → 422
  (`greater_than_equal` / `less_than_equal`, with `ctx`); `/s/2147483647` → 200; `?venue_id=0` → 422 with
  `loc ["query","venue_id",0]`; 101 ids → 422 `too_long`; 100 ids → 200. OpenAPI gains `minimum`/`maximum` on the items and
  `maxItems: 100`. CONFIRMED.
- The alternative `Annotated[list[int] | None, Query(ge=1)]`: the route registers, an omitted parameter is 200, and **any
  supplied value is a 500** (`TypeError: Unable to apply constraint 'ge' to supplied value [0]`). CONFIRMED (see PR1-2).
- Worktree with the aliases applied to the three detail routes and `/shows`: the full `app/tests` suite passes (186), `mypy
  app` is clean, and `make types`-equivalent regeneration (`scripts.dump_openapi` + `openapi-typescript` 7.13.0) produces
  **no diff** in `apps/calendar/lib/api-types.ts`. CONFIRMED (step 7's prediction holds).
- One hand-raised site rewritten as `raise RequestValidationError([{type, loc, msg, input}])` in the real app: `GET
  /shows?end=2020-01-01` → `422 {"detail":[{"type":"value_error","loc":["query","end"],"msg":"`end` must be on or after
  `start`","input":"2020-01-01"}]}`; the `get_db` yield dependency is unaffected and a following request on the same
  `sample_client` is 200; `mypy` is clean on the file. CONFIRMED (D1-A's mechanics are sound).
- On unmodified `HEAD`, a test through the stock `sample_client` for `/shows/99999999999` and `/shows?venue_id=99999999999`
  fails with the `DBAPIError` raised into the test, and the session is still usable afterwards. CONFIRMED (see PR1-1).

**Tier:** T2 is right. Even setting aside whether `api-contract.md` "documents" the 422 body today (it names the status
only; the OpenAPI document is what promises the list shape), the source offers two fixes and no doc chooses, which is
the README's "decision that belongs to Ari" condition. D1 and D2 are clearly marked and each has a recommendation; both
recommendations hold up against the experiments above.

**Test approach:** tests come first and each one named would fail today as claimed, apart from PR1-1's harness detail. The
existing `test_invalid_ranges_are_rejected`, `test_upcoming_rejects_contradictory_or_unbounded_requests`,
`test_unknown_id_is_404_not_500`, `test_non_integer_id_is_422` and the 503 test (which reads `detail` as a string,
`test_routers.py:519`) all stay green; no frontend code reads a 422 body.

**Counts:** 0 blocker, 3 should-fix, 3 nit. **Verdict: proceed after fixes.**

| # | Sev | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|
| PR1-1 | should-fix | Test 1 says the client "needs `raise_app_exceptions=False`" and "the plan picks the first", but `sample_client` is built by `app/testing/api_client.py`, which hard-codes `ASGITransport(app=app)`, and that file is not in Critical files or Steps. It isn't needed: with the stock `sample_client` the test already fails first (the `DBAPIError` propagates as a test error), and passes after the fix. Drop the `raise_app_exceptions` sentence and record the raised `DBAPIError` as the failing-first evidence; or, if a 500 status is wanted in the log, add an opt-in parameter to `api_client()` and list the file. | CONFIRMED: probe test on `HEAD` through `sample_client` failed with `sqlalchemy.exc.DBAPIError … value out of int32 range` for `/shows/99999999999` and `/shows?venue_id=99999999999`; a following `GET /shows/1` on the same client was 200. `app/testing/api_client.py` builds the transport with no option. | The implementer either edits a shared test helper (used by the keystone fixture tests too) outside the stated scope, or stalls on how to "pick the first". | **Fixed.** Test approach item 1 no longer mentions `raise_app_exceptions`; it records the propagated `DBAPIError` as the failing-first evidence and says `app/testing/api_client.py` is unchanged. |
| PR1-2 | nit | Step 2 leaves open "whether `Query(ge=…, le=…)` applies to each item or to the list", to be checked "in step 1's probe" (step 1 is writing tests, not a probe). It's settled: on a `list[int]` it applies to the list, and the failure is a request-time 500 for every supplied value, not a startup error. The item-level `Field` is correct. Write the fact into step 2 and have the alias's comment say it, so nobody later "simplifies" to `Query(ge=1, le=…)`; test 3's "100 ids → 200" case is what would catch that regression, so keep it with real in-range ids. | CONFIRMED: standalone app with `Query(ge=1)` on `list[int] \| None`: `/q` → 200, `/q?venue_id=5` → 500 (`TypeError: Unable to apply constraint 'ge' to supplied value`). The `Field` form gives 422 with `loc ["query","venue_id",0]`. | A tidy-up that moves the bounds onto `Query` passes import, lint and typecheck, then 500s on every filtered calendar page. | **Fixed.** Step 2 states the verified fact and requires a "do not move onto `Query`" comment on the alias; test 3's in-range 100-id case is named as the guard. |
| PR1-3 | should-fix | D2's case for the cap of 100 is incomplete. It cites "tens of venues" (`api-contract.md` §2, "Pagination"), but that same sentence says "hundreds of artists", and `artist_id` gets the same cap. And "a multi-select can only send ids it was shown" is not true: the URL is the state, and `parseIdList` (`apps/calendar/lib/params.ts:134`) forwards every distinct in-range id with no count cap. A URL with 101 artist or venue ids goes from 200 today to a 422, which `lib/api.ts` turns into an `ApiError` and the page into the error boundary (the B2-PR1-8 pattern, `params.ts:91-94`). Put that consequence in D2 for Ari, and either cap the list in `parseIdList` (adds a frontend file and a vitest case) or record that the error page is accepted for such URLs. Justify the number for artists as well as venues. | CONFIRMED by reading `params.ts:134-140` (dedupe and sort, no cap) and `api-contract.md` §2 "Pagination". PLAUSIBLE that the result is the error page (from `lib/api.ts`'s non-404 → `ApiError` path, not run). | Ari approves a cap on reasoning that doesn't match the contract, and a hand-edited or shared URL turns a working page into the error page with nothing recording that as a choice. | **Fixed, then closed by Ari's decision.** D2 was rewritten with the 101-id consequence and the "hundreds of artists" correction; Ari then chose **no list cap**, so the finding's concern no longer applies and no frontend cap is built. The reasoning stays in D2 for the day a cap is wanted. |
| PR1-4 | should-fix | Two frontend comments become wrong after the fix and aren't in the plan: `apps/calendar/lib/params.ts:62-65` ("A bigger number can only ever be an out-of-range error from the database (a 500 once the routers are DB-backed)") and `apps/calendar/lib/params.test.ts:61-64` ("…or that Postgres would reject as out of range once the routers are DB-backed"). After this change the API answers 422 at the edge, which is still the reason the frontend caps (a 422 would be the error page, not a 404). Add both to Critical files with a one-line rewording; leave `b2-routes-and-data-loading.md` alone (history). | CONFIRMED by `grep -rn "out of range\|int4"` over `apps/calendar/lib`. | The repo's comments state a behavior that no longer exists, against "Verify, don't assume" / "Cite the source of a decision". | **Fixed.** Both comments are in step 5a and Critical files with the rewording; `b2-routes-and-data-loading.md` left alone as history. |
| PR1-5 | nit | The four hand-raised sites aren't mapped to their `loc` and `input`: D1's table lists three locs for four sites, and step 4 doesn't say which goes where. Suggest: `end` before `start` → `["query","end"]`, input `end`; range too wide → `["query","end"]` (with `?end=2030-01-01` alone, `start` is the server's default, so `["query","start"]` would echo a value the client never sent); `upcoming` with `start`/`end` and `upcoming` with no filter → `["query","upcoming"]`, input `True`. Note that hand-raised `input` values go through `jsonable_encoder` (a date becomes `"2025-01-01"`, `True` becomes JSON `true`, where FastAPI's own errors echo the raw string `"true"`); harmless, but say it. Then test 5 can pin all four locs, not two. | CONFIRMED that a `datetime.date` input serializes as `"2020-01-01"` (worktree probe). The mapping is reasoning from `shows.py:80-113`. | The implementer picks locs ad hoc and the contract paragraph can't say what `loc` means for a cross-field rule. | **Fixed.** Step 4 has the site → `loc`/`input` table, including the `jsonable_encoder` note; test 5 pins all four locs. |
| PR1-6 | nit | Step 5's contract paragraph: (a) FastAPI-raised items also carry `ctx` (e.g. `{"le": 2147483647}`), so the documented item shape is `{type, loc, msg, input, ctx?}`, which matches the generated `ValidationError` (`api-types.ts:456-464`, `input?`); hand-raised items have no `ctx`. (b) Name the section ("§3 Conventions, new 'Errors' subsection" rather than "§2/§3"). (c) In `api-contract.md` the decisions must be written `PQR1-5-D1` / `PQR1-5-D2`, not `D1`/`D2`; `make designation-check` would fail the PR otherwise. | CONFIRMED: the `ctx` key appears in the probes' `less_than_equal` / `greater_than_equal` bodies; designation rule from `AGENTS.md` "Cross-references carry a scope". | A client written to the contract's exact four-key shape is surprised by `ctx`; a bare `D1` in the contract fails CI. | **Fixed.** Step 5 names §3 Conventions, documents `ctx?`, and requires `PQR1-5-D1` / `PQR1-5-D2` in the contract. |

Rejected: none. All six findings were accepted. (PR1-3 was then overtaken by Ari's decision of no list cap, recorded in D2.)

## Implementation log

## Code review
