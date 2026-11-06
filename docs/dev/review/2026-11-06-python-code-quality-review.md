# Python code quality review: `apps/api`

**Date:** November 6, 2026
**Scope:** everything under `apps/api` (`app/`, `agent_worker/`, `scripts/`, `migrations/`), read as a senior Python/FastAPI
reviewer meeting the repository for the first time, with the question Ari asked: *is there anything here a seasoned
Python engineer would immediately read as novice work?*
**Status:** findings only. Nothing in the code, tests or comments was changed. Each finding below is a suggestion for a
later change, with its effort and how much it matters.

Findings in this document are numbered `PQR1-<n>` ("Python Quality Review", round 1). Other documents should cite them as `PQR1-3` and so
on. Decisions from other plans are cited in their scoped form (`C2-D4`), following `docs/dev/conventions.md`.

---

## Summary

**Verdict: the engineering holds up well. The presentation is where it reads as unfinished.** A reviewer who runs the
tests, reads the query layer or follows the reconcile logic will see deliberate, careful work. A reviewer who opens
`app/main.py` and `app/config.py` first (the two files most people open first) sees leftover tutorial scaffolding,
code that was never auto-formatted, and comments addressed to a learner. That first look is what decides whether
they keep reading, and it is cheap to fix.

| Area | Grade | One line |
|---|---|---|
| Architecture and layering | Strong | Thin routers, a query layer, pure decision modules, enforced import direction |
| Correctness discipline | Strong | 1,206 tests passing in 18 s against a real Postgres, 97% branch coverage, strict typing everywhere |
| Modern idiom (FastAPI / Pydantic v2 / SQLAlchemy 2.0) | Strong | `Annotated` dependencies, async sessions, `lazy="raise"`, PEP 695 generics, `SecretStr` |
| Security posture for a pre-alpha | Reasonable | pip-audit finds no vulnerable Python dependencies (23 open Dependabot alerts on `main` need triage), Bandit clean. Two latent risks to fix before community edits ship |
| **Formatting and lint hygiene** | **Weak** | 125 of 167 files differ from `ruff format`; only ruff's default rules are on |
| **Comments as an outsider reads them** | **Mixed** | The "why" is excellent. Tutorial leftovers, stale "not yet" notes and dense plan IDs undercut it |
| Naming and layout | Good | Mostly self-explanatory; a handful of vague or misleading names |

**The five changes that move a reviewer's first impression the most** (all small effort):

1. Run `ruff format`, set a line length, and make CI check formatting (PQR1-1).
2. Remove the tutorial scaffolding and stale "not yet" comments from `main.py`, `config.py`, `state.py` and `schemas.py` (PQR1-2).
3. Write `apps/api/README.md`, which is currently an empty file that `pyproject.toml` points to (PQR1-3).
4. Make the fetch follow redirects and send a User-Agent (PQR1-4, a real bug, confirmed in this review).
5. Turn on a broader ruff rule set. It finds very little, which is itself a good result to show (PQR1-7).

---

## 1. How this review was done

### Read first

- `docs/references/fastapi-style-guide.md` (the repo's own idiom authority and its Anti-patterns table)
- `docs/arch/project-overview.md`, `arch-initial.md`, `data-model-initial.md`, `requirements-initial.md`
- `apps/api/AGENTS.md` (its "Deliberate divergences" table was respected: those choices are not findings)

### Commands run (cloud sandbox, Postgres available, no model)

| Command | Result |
|---|---|
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | **125 files would be reformatted, 42 already formatted** (979 diff hunks) |
| `uv run mypy` | Success: no issues in 152 source files |
| `REQUIRE_DB=1 uv run pytest` | **1,206 passed, 16 skipped in 18.25 s**. Skips: gitignored eval fixtures (14), no MongoDB (1), no captured pages (1) |
| `uv run coverage run -m pytest && coverage report` | **97% total** (branch coverage, `model_eval/` excluded by config) |
| `uvx pip-audit` on the exported Python lockfile (`uv.lock`) | No known vulnerabilities found. This covers the Python dependencies only: on November 6, 2026 GitHub reported 23 open Dependabot alerts on `main` (14 high, 8 moderate, 1 low), ecosystem not checked here. See section 6 |
| `uvx bandit -r app agent_worker -ll` (tests excluded) | 0 high, 1 medium (a false positive in a test helper, `app/testing/sample_data.py:441`) |
| `uvx pylint --enable=duplicate-code --min-similarity-lines=8` | One block: the frozen `model_eval/legacy.py` copy of the schema, which is deliberate |
| `ruff check --select E,W,F,I,B,UP,SIM,RUF,N,ASYNC,S,DTZ,PT,C4,RET --statistics` | See PQR1-7. Almost all hits are line length and `assert` in tests |
| Temporary probe test against the real app (deleted afterwards, tree left clean) | `/shows/99999999999` raises an unhandled `DBAPIError` (PQR1-5); `/docs` is served (PQR1-12) |
| `httpx` redirect check with `MockTransport` | A 301 raises `HTTPStatusError` under the code's `raise_for_status()` (PQR1-4) |

### Outside sources used as the yardstick

| Topic | Source |
|---|---|
| API security risks | [OWASP API Security Top 10 (2023)](https://owasp.org/API-Security/editions/2023/en/0x11-t10/): API4 Unrestricted Resource Consumption, API7 Server-Side Request Forgery. Summaries: [Akamai](https://akamai.com/glossary/what-is-owasp-api-top-10), [Barracuda](https://blog.barracuda.com/2023/03/17/owasp-top-10-api-security-risks-2023) |
| LLM application risks | [OWASP Top 10 for LLM Applications 2025](https://genai.owasp.org/llm-top-10/): LLM01 Prompt Injection, LLM05 Improper Output Handling. Summaries: [HackerOne](https://www.hackerone.com/ai/owasp-top-10-llms-2025), [PointGuard AI](https://www.pointguardai.com/blog/understanding-the-owasp-top-10-for-llms) |
| HTTP client behavior | [HTTPX compatibility notes](https://www.python-httpx.org/compatibility/): no automatic redirects; default timeouts. Verified locally: `httpx.get` defaults are `follow_redirects=False`, `timeout=5.0` (httpx 0.28.1) |
| FastAPI | [FastAPI docs: Path parameters and numeric validations](https://fastapi.tiangolo.com/tutorial/path-params-numeric-validations/), [Lifespan events](https://fastapi.tiangolo.com/advanced/events/), [Handling errors](https://fastapi.tiangolo.com/tutorial/handling-errors/) |
| SQLAlchemy async | [SQLAlchemy 2.0 asyncio guide](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html) (preventing implicit IO, `lazy="raise"`, engine disposal) |
| Style | [PEP 8](https://peps.python.org/pep-0008/), [PEP 257 (docstrings)](https://peps.python.org/pep-0257/), [Ruff rules reference](https://docs.astral.sh/ruff/rules/), [Ruff formatter](https://docs.astral.sh/ruff/formatter/) |

---

## 2. What is good (and what a senior reviewer will notice positively)

These are concrete. Each one is something experienced reviewers look for, and many codebases at this stage lack.

| Strength | Evidence | Why it reads as mature |
|---|---|---|
| **Thin routes, one query layer** | `app/routers/*.py` validate, call one `app/queries.py` function, map a miss to 404 | Textbook separation; easy to test and reason about |
| **No implicit lazy loads under asyncio** | `viewonly=True, lazy="raise"` on every relationship (`app/db/models/calendar.py`); `_show_loads()` names `joinedload` vs `selectinload` with the reason (`app/queries.py`) | The `MissingGreenlet` trap is the most common async SQLAlchemy bug. This design rules it out at the first test |
| **N+1 avoided deliberately** | `selectinload(Show.lineup).joinedload(ShowArtist.artist)`; the artist filter is `EXISTS` (`lineup.any(...)`), not a join that duplicates rows | Shows understanding of query shape, not just correctness |
| **Bounded queries** | `MAX_RANGE` of 366 days; `upcoming` refused without a venue or artist filter (`app/routers/shows.py`) | Directly addresses OWASP API4 (resource consumption) before anyone asked |
| **Injected clock, metro-local "today"** | `app/clock.py` `get_now` dependency, `metro_today` refuses naive datetimes | Time bugs are a classic senior-vs-junior tell; this one is handled correctly, including DST |
| **Modern dependency injection** | `Db`, `LiveMetro`, `Today` as `Annotated[..., Depends(...)]` aliases (`app/dependencies.py`) | Current FastAPI idiom, not the legacy default-argument form |
| **Configuration that refuses to be wrong** | `environment_problem()` cross-checks `APP_ENV`, DB host, role suffix, Railway's name, Mongo DB name (`app/config.py`); keys are `SecretStr` | Guards against the realistic production incident (copied variables), not just typos |
| **Real-database tests, not mocks** | `calendar_test` dropped and recreated per session, guarded to a local host and fixed name (`app/testing/db.py`) | The style guide's own anti-pattern table warns against mocking the DB; this follows it |
| **Tests that state what they prove** | Every test opens with `Proves:`; DB tests explain their seeded table (`agent_worker/tests/test_reconcile_db.py`) | Rare clarity of intent in a test suite; reviewers can audit the test suite itself |
| **Strict typing across the whole package** | mypy clean over 152 files including tests and the eval harness | Most Python projects type the app and leave tests and scripts untyped |
| **Pure decision modules, enforced layering** | `validation.py` / `policy.py` / `reconcile.py` / `commit.py` take plain arguments; tests enforce import direction (`test_layering.py`, `test_no_testing_imports.py`) | Architecture rules enforced by tests, not just by convention |
| **Database errors classified by SQLSTATE** | `calendar_writer.is_decision_error`, with fakes for each shape in `tests/fakes.py` | Distinguishes "this row is bad" from "the connection died". That distinction is often learned from a production incident |
| **Audit rows written in the same transaction as the change** | `calendar_writer.py` | A rolled-back write leaves no audit row; this is the correct design for an audit trail |
| **LLM output is treated as untrusted** | Schema-validated extraction; `verify_image_url` drops a URL not found verbatim on the page (`validation.py:316`); the frontend runs `httpUrlOrNull` on `original_url` | Matches OWASP LLM05's main advice ("treat model output as untrusted input") |
| **Modern Python** | PEP 695 generics (`def _inherit[T]`), `StrEnum`, `X \| Y` unions, frozen dataclasses | Up to date with Python 3.13 |
| **Supply chain basics** | `uv.lock` committed, Dependabot and CodeQL workflows present, pip-audit clean on the Python lockfile | Many portfolio projects have none of these (but see the open Dependabot alerts, section 6) |

The deliberate divergences in `apps/api/AGENTS.md` (flat `app/`, one `Settings`, returning models with a return-type
annotation) are each defensible, and documenting them, rather than silently diverging, is itself a sign of maturity.

---

## 3. Opportunities, by criticality and effort

**Criticality**: *High* = a reviewer notices it within minutes, or it is a real bug. *Medium* = noticed on a closer read,
or a latent bug. *Low* = polish, or matters only later.
**Effort**: *S* = under an hour; *M* = a few hours to a day; *L* = several days, or touches most files.

### At a glance

| | **S effort** | **M effort** | **L effort** |
|---|---|---|---|
| **High** | PQR1-1 formatting, PQR1-2 tutorial and stale comments, PQR1-3 empty README, PQR1-4 redirects | | |
| **Medium** | PQR1-5 id overflow 500, PQR1-6 missing docstrings, PQR1-7 lint rules, PQR1-8 unused dependencies, PQR1-9 duplication, PQR1-14 model timeouts | PQR1-21 fetch hardening (before community edits) | PQR1-10 comment density and plan IDs (Ari's decision) |
| **Low** | PQR1-12 docs in prod, PQR1-13 lifespan, PQR1-15 health routes, PQR1-16 migration name, PQR1-17 exception names, PQR1-18 variable `l` | PQR1-11 error shape, PQR1-19 graph state mutation, PQR1-22 LLM URL schemes | PQR1-20 pagination |

### Details

| # | Crit | Effort | Finding | Evidence | What a seasoned reviewer concludes | Suggested fix |
|---|---|---|---|---|---|---|
| PQR1-1 | High | S | **Code is not auto-formatted, and CI doesn't check it.** No `line-length` is configured, so ruff assumes 88 while the code is written at roughly 120 and wider. Several call sites pack many keyword arguments per line. | `ruff format --check`: 125 of 167 files would change. `app/main.py` is missing the two blank lines before `@app.get("/health")`; `app/config.py` uses `'.env'` against double quotes everywhere else and has no final newline. CI (`.github/workflows/ci.yml:73`) runs only `ruff check`. | "Nobody runs a formatter here." In 2026 Python, `ruff format` / `black` output is expected, so unformatted code is the fastest visual tell. | Add `[tool.ruff] line-length = 120` to `pyproject.toml`, run `ruff format` once as its own commit, verify with an AST comparison (the repo's comment-only pass procedure), and add `ruff format --check` to CI and `make lint`. |
| PQR1-2 | High | S | **Tutorial scaffolding and stale "not yet" comments remain in the most-read files.** They are addressed to a learner, and some are no longer true. | `app/main.py:37-48` ("Steps: 1. Open a connection… You don't need to catch exceptions yet"); `app/main.py:16-19` ("the whole reason these stub routes exist before the database does", but the routes read the DB since C2); `app/config.py` ("declare a field named `database_url`…", "instantiate the class once at module load time, e.g.:"); `agent_worker/state.py:19-29` ("reconsider if it turns out awkward once you're actually wiring add_node… in the next step") and `state.py` "The worker doesn't read the database yet (A4/A5)"; `app/schemas.py:3-5` ("No route returns them yet"); `app/routers/venues.py` (a lecture on `is None` vs `== "None"`); `app/routers/common.py` ("Worth knowing as a general Python point"). | "Generated or tutorial code that was pasted in and never cleaned up." Stale comments also make readers distrust the accurate ones. | One cleanup pass on these files using the repo's existing step-4 procedure for closed `TODO(Ari)` gaps: keep the *why*, drop the instructions and the history. AST-compare, then `make check`. |
| PQR1-3 | High | S | **`apps/api/README.md` is an empty file**, and `pyproject.toml` declares it as the package readme. | `wc -c apps/api/README.md` gives 0. | On GitHub this is the first page a visitor to `apps/api/` sees. An empty README makes the directory look abandoned. | A short README: what the two halves are (`app/`, `agent_worker/`), how to run, test and check them, and a link to `AGENTS.md` and `docs/`. |
| PQR1-4 | High (latent bug) | S | **The fetch does not follow redirects, so a venue page that redirects can never be fetched.** `httpx.get(url)` defaults to `follow_redirects=False`, and `raise_for_status()` raises on a 3xx. `_is_transient` classes a 3xx as not transient, so the run escalates with no retry. Also no `User-Agent` is sent (some sites block the default `python-httpx/…`), and `calendar_url.startswith("http")` also matches strings like `httpfoo`. | `agent_worker/nodes.py:111`. Verified in this review: a `MockTransport` 301 gives `HTTPStatusError: Redirect response '301 Moved Permanently'`. | "Hasn't run against the real web much." Redirects (http to https, adding `www`, a trailing slash) are routine on venue sites. | `httpx.get(url, follow_redirects=True, timeout=…, headers={"User-Agent": "…"})`, or one module-level `httpx.Client` with those settings. Use a generic project User-Agent, not a personal email. Parse the scheme with `urlparse(url).scheme in {"http", "https"}`. Add a test with `httpx.MockTransport` for the 301. See also PQR1-21. **Check locally**, below. |
| PQR1-5 | Medium | S | **An out-of-range id is a 500, not a 404 or 422.** Path ids are a plain `int` and the column is `integer` (int32), so asyncpg rejects the value and the route raises an unhandled `DBAPIError`. The same applies to `venue_id` / `artist_id` list items, and the lists have no length cap. | Probe: `GET /shows/99999999999` raised `DBAPIError … value out of int32 range`. A list of 5,000 `venue_id` values was accepted. | "Inputs aren't bounded at the edge." It's a small thing, but fuzzers and security scanners find it in seconds, and it maps to OWASP API4. | One shared alias in `app/dependencies.py`, for example `DbId = Annotated[int, Path(ge=1, le=2**31 - 1)]` (and a `Query` twin with `max_length` on the list), used by every route. Add a parametrized test for the bounds. |
| PQR1-6 | Medium | S | **Four modules break the repo's own "every module opens with a docstring" rule**, and `constants.py` has oddly indented docstrings with trailing whitespace and "Same as above". | `app/main.py`, `agent_worker/graph.py`, `agent_worker/state.py`, `agent_worker/constants.py` (W291 ×3, W292). | Inconsistency with the stated convention is more noticeable than having no convention at all. | Add the docstrings. Rewrite the `constants.py` docstrings in PEP 257 form. |
| PQR1-7 | Medium | S | **Only ruff's default rules are on** (`E4`, `E7`, `E9`, `F`). A broader set barely fires here, so turning it on is cheap and shows rigor. | Wider run: `I`, `B`, `UP`, `SIM`, `C4`, `RET` are close to zero. Real hits: `E741` ambiguous `l` ×13 (`agent_worker/reconcile.py:408-463, 653`), `N818` ×3, `DTZ001` ×3 (tests), `W291/W292` (PQR1-6), `RUF100` unused `noqa` ×2. `S101` (`assert`) ×1,670 and `PT018` are test-only and should be ignored there. | A `[tool.ruff.lint] select = [...]` block is something reviewers look for. Its absence reads as "defaults, never configured". | `select = ["E", "W", "F", "I", "B", "UP", "SIM", "C4", "RET", "RUF", "N", "ASYNC", "DTZ", "S"]`, `per-file-ignores` for tests (`S101`, `PT018`), fix the dozen real hits. |
| PQR1-8 | Medium | S | **Declared but unused runtime dependencies.** | `boto3`, `resend`, `slowapi` and `playwright` (Python) are in `[project.dependencies]` but imported nowhere (grep across `app`, `agent_worker`, `scripts`, `migrations`). They are planned in `arch-initial.md` §3 and §5. | "Dependencies added from a plan, not from need." It also enlarges the install and the supply-chain surface (`boto3` is large). | Remove them now and add each in the milestone that first imports it (C9 for R2, C10 for rate limiting). |
| PQR1-9 | Medium | S | **Small duplications of one concept.** | `metro_today` exists twice with different signatures: `app/clock.py:19` and `agent_worker/nodes.py:75`. The local-host set `("localhost", "127.0.0.1", "::1")` appears five times (`app/config.py:58,77`, `app/testing/db.py:79`, `agent_worker/main.py:185`, `model_eval/labeled_page_runs/scratch_database.py:36`). `state.fetched_on or metro_today(state.metro_timezone)` is repeated in `nodes.py` (×2) and `trace.py`. | Small, but "same name, two meanings" is what a reviewer flags in review. | Have the worker call `app.clock.metro_today(datetime.now(UTC), tz)`, or move one helper to a shared module. One `LOCAL_HOSTS` constant with an `is_local_host()` helper. One `effective_fetch_date(state)`. |
| PQR1-10 | Medium | L | **Comment density, and internal plan IDs, make the code hard to read for someone outside the project.** There are 1,260 scoped plan references (`C3-D4`, `A4-K3`, `v0.1-G6`…) in non-test code, and many comments narrate history ("the old router returned…", "A2.1 moved them to…", "Confirmed directly against the pinned langgraph…"). | `grep` counts across `app` and `agent_worker`, tests excluded. Examples: `agent_worker/graph.py`, `agent_worker/nodes.py:46-62`, `app/config.py`. | Two readings: "unusually well documented decisions" (true), or "a changelog living in the comments, and I can't follow it without five other documents" (also true). Senior engineers usually keep history in git and design docs, and keep the reason and an invariant in the code. | **This is Ari's decision**, because `AGENTS.md` deliberately chose comment density for a learning project. A middle path: keep every *why* sentence; move "what used to be here" notes to the plan files; replace a run of IDs with one pointer per module docstring ("Decisions: `docs/dev/implementations/c2-…md`"). Do it gradually, file by file, as a comment-only pass. |
| PQR1-11 | Low | M | **Two error-body shapes for a 422.** Hand-raised 422s return `{"detail": "<string>"}`; FastAPI's own validation 422s return `{"detail": [{loc, msg, type…}]}`. | Probe: `?start=2026-01-01&end=2025-01-01` vs `?start=notadate`. | Clients must handle both. A common review comment for public APIs. | Either raise `RequestValidationError` with a `loc`, or add one exception handler that wraps domain errors in the same list shape. Record the choice in `api-contract.md`. |
| PQR1-12 | Low | S | **`/docs`, `/redoc` and `/openapi.json` are served in every environment.** | Probe: `/docs` gives 200. The style guide (§ "Hide docs outside selected envs") recommends otherwise. | Harmless today: it's a read API, and the contract is public in the repo anyway. It will matter once C10's shared secret gates the API. | `openapi_url=None` unless `settings.app_env in {"local", "dev"}`. The OpenAPI dump script can call `app.openapi()` directly. |
| PQR1-13 | Low | S | **No lifespan hook, and import-time side effects.** `Settings()`, the engine, the OpenAI clients and the compiled graph are all created at import. The API never disposes the engine. | `app/config.py` (end of file), `app/db/session.py`, `agent_worker/llm.py` (`client, instructor_client = build_clients(settings)`). | Common in FastAPI, and the style guide does it too, so not wrong. A lifespan that disposes the engine is the expected touch. | `FastAPI(lifespan=…)` that runs `await engine.dispose()` on shutdown. Keep the import-time settings (they fail fast, which is deliberate, C3-D4). |
| PQR1-14 | Medium | S | **Model-call timeout and retries are implicit.** The OpenAI client is built without `timeout=` (the SDK default is 10 minutes) or `max_retries=` (the SDK default is 2), and instructor adds its own `max_retries=1` on top. | `agent_worker/llm.py` `build_clients` and `request_kwargs`. | On a hosted, per-token provider (C6), a hung or retried call costs money and time without anyone seeing it. | Pass `timeout=` and `max_retries=` explicitly from `Settings`, and write down how the retry layers stack (tenacity for fetch, the SDK, instructor, `policy.py` attempts). |
| PQR1-15 | Low | S | **The health routes are the least polished code in the app.** No return-type annotation (`async def health():`); `health_db` returns from inside `async with`; neither declares a response model. | `app/main.py:27-50`. | It's the file everyone opens first (see PQR1-2). | `-> dict[str, str]` or a tiny `HealthResponse` model; return after the block; add a module docstring. |
| PQR1-16 | Low | S | **The first migration's filename has no date prefix** while the others do. | `migrations/versions/db2aedec0bb9_create_metro_and_venue_tables.py`. | Minor inconsistency. | Leave it alone (it's applied history), or rename the file only. Alembic keys on the revision id inside, not the filename. Mention it in `notes.md` if left. |
| PQR1-17 | Low | S | **Exception names without an `Error` suffix.** | `EmptyResponse` (`nodes.py:66`), `ShowGone` (`calendar_writer.py:73`), `ScenarioNotRunnable` (N818). | PEP 8: "you should use the suffix 'Error' on your exception names (if the exception actually is an error)". | `EmptyPageError`, `ShowGoneError`, and so on. |
| PQR1-18 | Low | S | **Single-letter `l` as a variable name** (13 times). | `agent_worker/reconcile.py` (ruff E741). <!-- designation-ok --> | PEP 8 explicitly names `l` as a character never to use, because it reads like `1`. | `listing`. |
| PQR1-19 | Low | M | **Graph nodes mutate the state in place and return the whole object.** The node docstrings already work around the consequence ("Every per-attempt field is assigned on every attempt… LangGraph keeps a field's old value"). | `agent_worker/nodes.py` (`fetch_node`, `extract_node`), `trace.py` runs them in a thread and rebinds `state`. | LangGraph's idiom is to return a partial update dict; mutating shared state in a worker thread is a smell, even though it's safe here because runs are sequential. | Not urgent. If nodes are touched again, return `{"field": value}` updates, or `state.model_copy(update=…)`, so each node's output is explicit. |
| PQR1-20 | Low | L | **List endpoints are unpaginated and sorted in Python.** | `queries.list_artists` loads every artist row; ordering in Python is deliberate (collation, documented in the module docstring). | Fine at tens or hundreds of rows, and it's already acknowledged in the route docstring. | When artists reach the thousands: keyset pagination in the existing envelope, plus an explicit `COLLATE "C"` or ICU collation if sorting moves to SQL. |
| PQR1-21 | Medium (High before community edits) | M | **The fetch trusts `venue.calendar_url` completely.** A value that doesn't start with `http` is read as a **local file path** (`Path(state.calendar_url).read_text()`), and an `http` URL can point anywhere, including private addresses and cloud metadata endpoints. | `agent_worker/nodes.py:140-148`. Today only the seed writes venues. `project-overview.md` requires community-editable venue information. | Once a public user can edit a venue, this becomes arbitrary file read plus SSRF (OWASP API7:2023). | Before any venue edit endpoint ships: production fetch accepts only `https?` URLs; refuse private, loopback and link-local addresses after DNS resolution; cap the response size; move the local-file mode behind an explicit test or local flag (for example `fetch_strategy == FILE`, refused when `app_env != "local"`). |
| PQR1-22 | Low | M | **Prompt injection is accepted by design, and mitigated well. One edge remains.** The venue's HTML goes to the model (OWASP LLM01); the model has no tools and its output is schema-validated, which limits the damage to "wrong listings". `image_url` must appear verbatim on the page, but its *scheme* isn't checked in Python. | `agent_worker/validation.py:316-347`; `agent_worker/schemas.py:176` (`image_url: str`). The frontend guards `original_url` with `httpUrlOrNull`. | Good defence in depth. The remaining gap is a small one. | Validate model-produced URLs as `http`/`https` in the extraction schema (Pydantic `HttpUrl`, or a validator) so the guarantee doesn't depend on the frontend. |

---

## 4. Naming and folder layout

Overall, names describe the job, especially in `model_eval/` (`labeled_page_runs/` does things, `saved_run_reports/` only
reads, and its README maps every file to its group). Specific opportunities:

| Name | Issue | Suggestion |
|---|---|---|
| `agent_worker/local_test.py` | Reads as a test module; it's a manual script that opens real databases and calls a model. `pyproject.toml` has a guard comment *because* of the name. | `run_local_fixture.py` or `scripts/try_pipeline.py`. Then the guard comment isn't needed. |
| `agent_worker/trace.py` | "Trace" suggests OpenTelemetry or tracing; it actually holds the audit wrapper and the reconcile read and commit write orchestration. | `audited_node.py` or `node_wrapper.py`. |
| `app/schemas.py` and `agent_worker/schemas.py` | Same name, different jobs (API responses vs. the model's extraction schema). | `app/schemas.py` is conventional; rename the worker's to `extraction_schema.py`. |
| `agent_worker/constants.py` | Holds only two enums used by the graph. | Move them into `graph.py`, or name the file `graph_names.py`. |
| `agent_worker/model_eval/legacy.py`, `reference.py` | Vague out of context. `legacy.py` says to delete it "when A2's measurement is no longer needed". | Decide whether A2's baseline is still needed. If not, delete it. Rename `reference.py` to `fixture_facts.py`. |
| `app/testing/` inside the production package | Unusual (test helpers usually live in `tests/` or `conftest.py`), but justified: the e2e app and fixture generator import it, and `test_no_testing_imports.py` keeps production code away from it. | Keep it. Add one line to the README explaining why it's there. |
| `apps/api/ollama/` | Clear once opened; it's a Modelfile. | Fine. A line in the README covers it. |
| `routers/common.py` | Holds one constant. | Fine, but `responses.py` would say what it is. |

---

## 5. Security notes in context

This is a pre-alpha read API with no confidential data, and no authentication yet (the shared secret is planned in
C10). With that in mind:

- **Already good:** no SQL built from strings in production code (Bandit's one hit is a test helper using table names
  from code); secrets in `SecretStr`; no CORS surface (the BFF pattern); bounded date ranges; Python dependencies with no known
  CVEs (the open Dependabot alerts are an open item, section 6); CodeQL and Dependabot enabled; destructive test fixtures refuse non-local hosts and non-test database names.
- **Fix now (small):** PQR1-5 (id bounds), PQR1-4 (fetch settings).
- **Fix before the API is public (C10/C11):** the shared-secret check; PQR1-12 (docs off); rate limiting (then add
  `slowapi` back, PQR1-8); `/health` reporting `app_env` is a deliberate choice (C3-D6), and once the API is public it's
  worth restricting to the shared-secret caller.
- **Fix before community edits:** PQR1-21 (SSRF and local file read) and PQR1-22 (URL schemes). `requirements-initial.md`
  already plans bot checks and verified identity for those edits.

---

## 6. Things to check in an environment with the model and the network

The cloud sandbox has no route to venue sites, no Ollama and no MongoDB, so these need a local session.

1. **Do any seeded venue URLs redirect today?** (PQR1-4)

   ```bash
   for u in https://whitesquirrelbar.com/calendar/ "https://first-avenue.com/shows/?venues=59161" https://www.mortimerscalendar.com/ https://terminalbarmn.com/live-music/; do curl -s -o /dev/null -w "%{http_code} %{redirect_url}  $u\n" "$u"; done
   ```

   Any `301`/`302` line is a venue that currently escalates on every run.

2. **What does the default User-Agent get?** Repeat the loop with `-A "python-httpx/0.28.1"` and compare the status codes.
3. **The full suite with MongoDB running** (`make db-up`, then `make check`), so the one Mongo-only test and the
   14 real-page validation tests (`test_validation_on_real_pages.py`) run too.
4. **One worker run per venue** (`VENUE=<id> make worker`), then the saved audit queries in `docs/dev/audit-queries.sql`.
   Look for escalations whose reason starts with `HTTPStatusError: Redirect response`.
5. **Model-call timeout behavior** (PQR1-14): stop Ollama mid-run and see how long the worker takes to give up.
6. **Triage the open Dependabot alerts** (GitHub reported 23 on `main` on November 6, 2026: 14 high, 8 moderate, 1 low).
   Check which ecosystem each is in (Python `uv.lock`, or the JS lockfile) at
   `https://github.com/arikoinuma/agentic-live-music-calendar/security/dependabot`. The review's pip-audit found none in
   the Python lockfile, so they are most likely JavaScript, but this sandbox could not read the alert list.

---

## 7. Suggested order

| Step | Findings | Why this order |
|---|---|---|
| 1. First-impression pass | PQR1-1, PQR1-2, PQR1-3, PQR1-6, PQR1-15 | Mostly comment and format only (verify with an AST comparison and `make check`); the biggest change in how the code reads, for an hour or two of work |
| 2. Lint and dependency hygiene | PQR1-7, PQR1-8, PQR1-17, PQR1-18 | Mechanical, small diffs, each visible in `pyproject.toml` |
| 3. Real fixes, with tests first | PQR1-4, PQR1-5, PQR1-9, PQR1-14 | Behavior changes. Each gets a failing test before the fix, as the repo already does |
| 4. Decide | PQR1-10 | Ari's call on comment style for an outside audience |
| 5. Before public or community features | PQR1-11, PQR1-12, PQR1-13, PQR1-21, PQR1-22, PQR1-20 | Tied to C10/C11 and to the edit features |

---

## 8. Resolution tracker

Appended after the review, November 6, 2026. The findings above stay as written; this table records what happened to
each one. `/resolve-issue` updates a row when its PR opens (`docs/dev/issues/README.md`). Merge state lives on GitHub.

| Finding | Criticality | Effort | Finding (short) | Status | PR | Record |
|---|---|---|---|---|---|---|
| PQR1-1 | High | S | Code is not auto-formatted, and CI doesn't check it | Open | | |
| PQR1-2 | High | S | Tutorial scaffolding and stale "not yet" comments remain in the most-read files | Open | | |
| PQR1-3 | High | S | `apps/api/README.md` is an empty file | Open | | |
| PQR1-4 | High (latent bug) | S | The fetch does not follow redirects, so a venue page that redirects can never be fetched | Open | | |
| PQR1-5 | Medium | S | An out-of-range id is a 500, not a 404 or 422 | Open | | |
| PQR1-6 | Medium | S | Four modules break the repo's own "every module opens with a docstring" rule | Open | | |
| PQR1-7 | Medium | S | Only ruff's default rules are on | Open | | |
| PQR1-8 | Medium | S | Declared but unused runtime dependencies | Open | | |
| PQR1-9 | Medium | S | Small duplications of one concept | Open | | |
| PQR1-10 | Medium | L | Comment density, and internal plan IDs, make the code hard to read for someone outside the project | Open | | |
| PQR1-11 | Low | M | Two error-body shapes for a 422 | Open | | |
| PQR1-12 | Low | S | `/docs`, `/redoc` and `/openapi.json` are served in every environment | Open | | |
| PQR1-13 | Low | S | No lifespan hook, and import-time side effects | Open | | |
| PQR1-14 | Medium | S | Model-call timeout and retries are implicit | Open | | |
| PQR1-15 | Low | S | The health routes are the least polished code in the app | Open | | |
| PQR1-16 | Low | S | The first migration's filename has no date prefix | Open | | |
| PQR1-17 | Low | S | Exception names without an `Error` suffix | Open | | |
| PQR1-18 | Low | S | Single-letter `l` as a variable name | Open | | |
| PQR1-19 | Low | M | Graph nodes mutate the state in place and return the whole object | Open | | |
| PQR1-20 | Low | L | List endpoints are unpaginated and sorted in Python | Open | | |
| PQR1-21 | Medium (High before community edits) | M | The fetch trusts `venue.calendar_url` completely | Open | | |
| PQR1-22 | Low | M | Prompt injection is accepted by design, and mitigated well. One edge remains | Open | | |

---

## Summary (again)

- **Strong where it is hard to fake:** architecture, async SQLAlchemy discipline, time handling, configuration safety,
  audit-trail transactions, real-database tests, full strict typing. 1,206 tests pass in 18 s, coverage is 97%, mypy
  is clean, and pip-audit finds no known vulnerable Python dependencies (GitHub's 23 open Dependabot alerts on `main` still need triage, section 6).
- **Weak where it is easiest to see:** unformatted code (125 files), tutorial and stale comments in `main.py`,
  `config.py` and `state.py`, an empty `apps/api/README.md`, and a default-only lint configuration. Each is a small fix.
- **One real bug found:** the fetch can't follow redirects (PQR1-4). **One unhandled 500:** out-of-range ids (PQR1-5).
- **One decision for Ari:** how much plan history and how many IDs the code itself should carry for an outside reader (PQR1-10).
- **Security:** reasonable for a pre-alpha. Fetch hardening (PQR1-21) must land before venues become community-editable.
