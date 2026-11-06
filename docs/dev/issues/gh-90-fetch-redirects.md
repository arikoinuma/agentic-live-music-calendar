# GH-90: the worker's fetch doesn't follow redirects

**Status:** Code review
**Date:** November 6, 2026
**Scope:** GH-90, PQR1-4 (the same issue, filed twice: once as a review finding, once as a GitHub issue)
**Sources:** GH-90 → https://github.com/arikoinuma/agentic-live-music-calendar/issues/90 (no comments);
PQR1-4 → `docs/dev/review/2026-11-06-python-code-quality-review.md` §3 Details row PQR1-4, and §6 item 1 ("Check locally")
**Tier:** T1 — one function's behavior changes (`fetch_html`, `fetch_node` in `agent_worker/nodes.py`), the fix is the
one the issue names, and nothing touches the contract, a migration or a convention
**Author model:** Claude Opus 5.5 (record, fix and tests, November 6, 2026; cloud session)
**Reviewer model:** Claude Opus 5.5, at Ari's request (code review round 1, November 6, 2026). The usual rule
(`AGENTS.md`, "Running a review round") asks for a different model; Ari chose a second Opus for this run, so the
review is a fresh, separate instance with no context from the author, not a different model.
**Branch / PR:** `claude/happy-knuth-edh3br` (designated by the cloud session, restarted from `main` after PR 91 merged) / PR link once opened

**Designations.** Review items here are bare (`CR1-2`). Outside this record they are `GH-90-CR1-2`
(`docs/dev/issues/README.md`, `docs/dev/conventions.md`).

## Issues

### GH-90 / PQR1-4: a venue page that redirects can never be fetched

**What's wrong.** `fetch_html` calls `httpx.get(url)` and then `raise_for_status()`. Since httpx 0.24, `raise_for_status()`
raises on a 3xx as well, and `httpx.get` defaults to `follow_redirects=False` (checked against the pinned 0.28.1:
`follow_redirects: bool = False`). `_is_transient` treats only a 5xx status as transient, so tenacity makes one attempt and
stops, `fetch_node` records `HTTPStatusError: Redirect response '301 Moved Permanently' …` in `fetch_error`, and
`route_after_fetch` escalates. A venue whose page moved (http to https, `www` added, a trailing slash) escalates on every
scheduled run and its shows never update.

**Also in scope, because both sources name them for this change:**
- No `User-Agent` is sent, so the request goes out as `python-httpx/0.28.1`, which some sites block. The issue asks for a
  generic project client name, not a personal email.
- `state.calendar_url.startswith("http")` also matches strings like `httpfoo`, which then get sent to httpx as a URL.
  The issue asks for `urlparse(url).scheme in {"http", "https"}`.
- No explicit `timeout` (httpx's implicit default is 5 s on each phase).

**What "fixed" means** (GH-90's Acceptance list):
1. A test using `httpx.MockTransport` proves a 301 is followed to the final page, written first and failing before the fix.
2. The existing fetch and retry tests still pass (`make check`).
3. Locally, with network access, check which seeded venue URLs redirect today (**local check pending**: the cloud sandbox has no route to venue sites).

**Not in scope** (both sources say so): the wider fetch hardening of PQR1-21 (allowed schemes enforced at the edge,
private-address blocking, a response size cap, moving the local-file mode behind a flag).

## Approach

Keep the call shape: `fetch_html` still makes one `httpx.get` per attempt, now with the fetch settings passed explicitly
(`follow_redirects=True`, a `timeout`, and a `User-Agent` header). These are held in module-level constants next to
`FETCH_ERRORS`, so the capture script (`model_eval/capture.py`, which shares `fetch_html`) gets them too, and a captured
page is still exactly what production fetches. Keeping `httpx.get` rather than introducing a module-level `httpx.Client`
means the existing tests that patch `nodes.httpx.get` stay valid as written, and it's the smallest change the issue asks for.

A redirect that fails at its final hop still lands in the same place as before: `follow_redirects=True` makes httpx raise
`TooManyRedirects` (an `httpx.HTTPError`, so already in `FETCH_ERRORS`) on a loop, and the final response's status is what
`raise_for_status()` sees.

`fetch_node` decides the HTTP branch with a small `_is_http_url` helper (`urlparse(url).scheme in {"http", "https"}`).
Anything else stays on the local-file branch, as today.

**Tests first** (`agent_worker/tests/test_retry_plumbing.py`, section 5, Fetch). The fake routes `nodes.httpx.get` through a real
`httpx.Client` with a `MockTransport`, forwarding whatever keyword arguments production passes. So the test exercises the
real redirect handling under production's settings, rather than a stand-in that says "followed":
- a 301 to a final page is followed, and the page is what `fetch_node` keeps (fails before the fix with the redirect `HTTPStatusError`);
- the request carries the project User-Agent, not `python-httpx/…` (fails before the fix);
- `httpfoo://…` and `HTTPS://…` go to the right branch (the first fails before the fix by reaching httpx).

## Implementation log

### Round 1

- **Scope:** diff base `9b8f0b39fdd18595f58989f10fa122701493f8bb` (`main` after PR 91 merged), uncommitted working tree.
  Files: `apps/api/agent_worker/nodes.py`, `apps/api/agent_worker/tests/test_retry_plumbing.py`, this record.
- **GH-90 / PQR1-4, what changed** (`agent_worker/nodes.py`):
  - New `FETCH_SETTINGS` next to `FETCH_ERRORS`: `follow_redirects=True`, `timeout=httpx.Timeout(20.0)`, and a
    `User-Agent` of `agentic-live-music-calendar/0.1 (+<repo URL>)`. `fetch_html` passes them to its one `httpx.get`.
    The capture script shares `fetch_html`, so it gets the same settings.
  - New `_is_http_url` (`urlparse(url).scheme.lower() in {"http", "https"}`) replaces `startswith("http")` in `fetch_node`.
  - `fetch_html`'s docstring no longer says "one plain GET".
- **Failed first, then passed** (`agent_worker/tests/test_retry_plumbing.py`, section 5, new block "Redirects,
  User-Agent and the URL check"). Before the fix, 4 of the 6 new cases failed:
  - `test_a_redirected_page_is_fetched_from_where_it_moved`: `fetch_error` was
    `HTTPStatusError: Redirect response '301 Moved Permanently' …`
  - `test_the_fetch_names_the_project_not_python_httpx`: the request went out as `python-httpx/…`
  - `test_only_an_http_or_https_url_is_fetched_over_http[HTTPS://…]`: went to the local-file branch
  - `…[httpfoo://…]`: reached httpx

  The `https://` and `ftp://` cases passed before and after, as controls. After the fix, all 37 tests in the file pass.
  The fake (`RedirectingSite`) is a real `httpx.Client` on a `MockTransport` that forwards production's keyword
  arguments, so the redirect is followed by httpx itself, and only if production asks it to.
- **Departures from the approach:** none.
- **Verification:**
  - `make check`: exit 0. ruff clean; mypy clean (156 files); pytest 1279 passed, 20 skipped (was 1273: +6 new
    cases); vitest 525 passed; e2e 107 passed.
  - `make designation-check BASE=9b8f0b3`: clean.
  - **local check pending**: GH-90's Acceptance step 3 and the review's §6 item 1 (which seeded venue URLs redirect
    today, and whether any blocks `python-httpx`) need network access to venue sites, which the cloud sandbox doesn't have:

    ```bash
    for u in https://whitesquirrelbar.com/calendar/ "https://first-avenue.com/shows/?venues=59161" https://www.mortimerscalendar.com/ https://terminalbarmn.com/live-music/; do curl -s -o /dev/null -w "%{http_code} %{redirect_url}  $u\n" "$u"; done
    ```

    Then one `VENUE=<id> make worker` for a venue that redirects, to confirm it reaches extract.
- **Noticed, not in scope:** the wider fetch hardening (PQR1-21), which matters more now that redirects are followed: a
  redirect can now take the fetch to a different host, including a private address. Today only the seed writes venue
  URLs, so this isn't reachable yet. PQR1-21 must cover the redirect target as well as the first URL (for example by
  checking each hop in an httpx event hook) before venues become community-editable.
- **Where to look hardest:** the timeout value (20 s per phase, times three attempts, is the worst case per venue
  run), and whether `RedirectingSite` really can't pass without production's `follow_redirects`.

## Code review
