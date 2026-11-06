# GH-90: the worker's fetch doesn't follow redirects

**Status:** PR open
**Date:** November 6, 2026
**Scope:** GH-90, PQR1-4 (the same issue, filed twice: once as a review finding, once as a GitHub issue)
**Sources:** GH-90 → https://github.com/arikoinuma/agentic-live-music-calendar/issues/90 (no comments);
PQR1-4 → `docs/dev/review/2026-11-06-python-code-quality-review.md` §3 Details row PQR1-4, and §6 item 1 ("Check locally")
**Tier:** T1 — one function's behavior changes (`fetch_html`, `fetch_node` in `agent_worker/nodes.py`), the fix is the
one the issue names, and nothing touches the contract, a migration or a convention
**Author model:** Claude Opus 5.5 (record, fix and tests, November 6, 2026; cloud session)
**Reviewer model:** Claude Opus 5.5 (code review round 1, November 6, 2026). A separate instance with no author context,
but the same model as the author: Ari asked for "another Opus" as the reviewer when he started this run, which departs
from `AGENTS.md`'s different-model rule for this run only. The PR body says so at the top for him to confirm (CR1-3).
**Branch / PR:** `claude/happy-knuth-edh3br` (designated by the cloud session, restarted from `main` after PR 91 merged) / [PR 92](https://github.com/arikoinuma/agentic-live-music-calendar/pull/92)

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

### Round 1

**Scope.** Implementation log Round 1: `git diff 9b8f0b3` (`apps/api/agent_worker/nodes.py`,
`apps/api/agent_worker/tests/test_retry_plumbing.py`) plus this record. The prompt described the change as uncommitted; during the
review the author committed it as `5bfec93` ("fix(api): follow redirects in the worker's fetch (GH-90, #90, PQR1-4)").
`git diff 9b8f0b3 HEAD --stat` matches the working-tree diff that was reviewed (nodes.py +29/-4, tests +78, record +110), so
this round covers that commit. This round itself is uncommitted.

**What was checked, and how.**
- Read `AGENTS.md`, `docs/dev/issues/README.md`, `.claude/skills/resolve-issue/SKILL.md`, the PQR1-4 row and §6 item 1 of
  `docs/dev/review/2026-11-06-python-code-quality-review.md`, and the Anti-patterns table of
  `docs/references/fastapi-style-guide.md`. Nothing in that table applies to this change: `fetch_node` was already synchronous.
- `make check`: exit 0 (ruff clean, pytest 1279 passed and 20 skipped, vitest 525 passed, e2e 107 passed). CONFIRMED.
- `make designation-check BASE=9b8f0b3`: clean. CONFIRMED.
- Red before the fix: in a throwaway worktree at `9b8f0b3` with only the new test file copied in, `4 failed, 2 passed` for
  the six new cases, matching the log (the 301 case failed with the redirect `HTTPStatusError`, the User-Agent case failed,
  and so did `HTTPS://` and `httpfoo://`). CONFIRMED.
- The log's open question, whether `RedirectingSite` can pass without production's `follow_redirects`: with the fixed
  `nodes.py` minus only `"follow_redirects": True`, the redirect test fails (`HTTPStatusError: Redirect response '301 Moved
  Permanently'`) and the other five pass. So it can't. CONFIRMED.
- Mutation with the fixed `nodes.py` minus only the `timeout` entry: all 47 fetch, redirect and http tests in
  `agent_worker/tests/` still pass (CR1-1). CONFIRMED.
- `urlparse("HTTPS://x/y").scheme` returns `"https"` (CR1-2). CONFIRMED.
- Tier T1 is right: nothing touches `app/schemas.py`, a migration or a convention. Following a redirect to another host does
  bear on security, but the log records that under PQR1-21, which both sources leave out of scope. The **local check
  pending** item (which seeded URLs redirect today) is reported as pending, not as verified. Closing the loop with the
  sources (the review doc's tracker, a comment on GH-90) comes at skill step 7, so its absence isn't a finding.
- On the timeout value the log asks about: `httpx.Timeout(20.0)` applies 20 s to each phase, and the read limit applies to
  each read rather than the whole body. Only a `TransportError` (which includes `TimeoutException`) is retried, so a
  venue that stops answering costs about 3 × 20 s plus 1–2 s of backoff. That's acceptable for a scheduled worker, so no
  finding. PLAUSIBLE.
- The worktree was removed afterwards (`git worktree list` shows only the main checkout).

**Counts:** 0 blocker, 1 should-fix, 2 nit. **Verdict:** proceed after fixes.

| # | Sev | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|
| CR1-1 | should-fix | The explicit timeout is a behavior change (httpx's implicit 5 s becomes 20 s), and no test pins it. `docs/dev/issues/README.md`'s rule, and this review's brief, ask for every behavior change to have a test that fails before the fix. Suggested fix: in `test_the_fetch_names_the_project_not_python_httpx` (or a sibling test), assert `site.seen[0].extensions["timeout"] == {"connect": 20.0, "read": 20.0, "write": 20.0, "pool": 20.0}`. httpx records the effective timeout on the request, and before the fix it reads 5.0, so the test fails first. Take the expected 20.0 from the record's Approach as a literal, not from `FETCH_SETTINGS`. | Mutation: the fixed `nodes.py` with only `"timeout": httpx.Timeout(20.0),` removed passes `pytest agent_worker/tests/ -k "fetch or redirect or http"` (47 passed). CONFIRMED. | If someone drops or changes the timeout later, nothing fails, and slow venue sites quietly go back to timing out at 5 s. | **Fixed.** New `test_the_fetch_waits_20_seconds_per_phase_not_httpx_default` in `agent_worker/tests/test_retry_plumbing.py` asserts `extensions["timeout"]` with 20.0 written as a literal. Shown red first: with the `timeout` entry removed from `FETCH_SETTINGS` it failed (`{'connect': 5.0, …}`), and with it restored it passes. |
| CR1-2 | nit | `_is_http_url` calls `.lower()` on a scheme that `urlparse` already lowercases, and the docstring presents the comparison as something the code does. Either drop `.lower()` and say that `urlparse` normalizes the scheme, or keep it and call it belt-and-braces. The `HTTPS://` test case passes either way. | `nodes.py` `_is_http_url`; `python3 -c "from urllib.parse import urlparse; print(urlparse('HTTPS://x/y').scheme)"` prints `https`. CONFIRMED. | Nothing at runtime. A reader is led to think the `.lower()` is what makes upper-case schemes work. | **Fixed.** Dropped `.lower()` from `_is_http_url` in `nodes.py`. Its docstring now says that `urlparse` lowercases the scheme (RFC 3986 §3.1). The `HTTPS://` case still passes. |
| CR1-3 | nit | This round ran on the same model as the author (Opus 5.5). `AGENTS.md` ("Running a review round") and the README rule ("a code review by a different model") ask for a different one. The header says Ari asked for this, but the record has no way to show that. Put the same-model review at the top of the PR body so Ari confirms it when he merges, rather than relying on the header. Relatedly, the change was committed (`5bfec93`) before this round was resolved, while skill step 7 commits after step 6. The fixes and this round will need a follow-up commit. | Header `Reviewer model` line; `git log -1` shows `5bfec93` at 16:52 while this review was running. CONFIRMED. | A process exception that Ari never confirmed becomes precedent without anyone deciding it. | **Fixed.** Ari did ask for a second Opus in his prompt for this run. The record can't show that, so the header now quotes it, says it applies to this run only, and the PR body states it at the top. On the early commit: `5bfec93` was pushed before this round to save work against the container being reclaimed. The resolutions are in a follow-up commit, and the PR opens only after them, as step 7 says. |

Rejected: none.

**After the fixes:** `make check` exit 0 (ruff clean; mypy clean, 156 files; pytest 1280 passed, 20 skipped; vitest 525
passed; e2e 107 passed). `make designation-check BASE=9b8f0b3` clean.
