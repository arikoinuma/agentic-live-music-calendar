# Dev Notes

Evergreen, standalone findings that don't belong in `env-setup.md` (a sequential
"do this once" runbook) or `docs/arch/arch-initial.md` (design decisions). This
is for reusable gotchas and techniques discovered along the way — things worth
knowing the *next* time something similar comes up, in no particular order.
Add an entry whenever a real debugging session turns up something non-obvious
enough that future-you (or anyone else on this repo) shouldn't have to
rediscover it from scratch.

---

## Railway's dashboard variable editor can silently be out of sync with the live service

**Symptom:** the "raw format" multi-variable editor in Railway's web dashboard
showed correct values (`MODEL_NAME` present, `DATABASE_URL` with the right
`+asyncpg` driver suffix) — but the actual deployed service kept crashing with
`pydantic.ValidationError: model_name Field required`, as if the variable
didn't exist at all.

**Root cause:** the dashboard editor was showing pasted/draft text that had
never actually been committed to the service. There was no error, no failed
save indicator — it just silently didn't match what was live. Confirmed via
the Railway CLI: `railway variables` (linked project) showed `MODEL_NAME`
completely absent and `DATABASE_URL` still missing `+asyncpg`, despite both
looking correct in the dashboard.

**Fix / takeaway:** don't trust the dashboard's raw editor as a source of truth.
Verify (and set) variables through the CLI instead, which writes and reads
directly against the real service:

```
railway link -p <project-name>          # one-time, per machine
railway variable list --kv               # see what's actually live (raw values)
railway variable set KEY=value           # set one — triggers a redeploy by default
railway variable set KEY=value --skip-deploys   # set without redeploying yet
railway redeploy -y                      # redeploy the current deployment
```

`railway status` shows the linked service's live state (`Online` / `Crashed` /
`Deploying`) without needing to check the dashboard at all.

---

## Neon's default connection string breaks `asyncpg` specifically

**Symptom:** `/health/db` returned a 500, and the actual exception (visible via
`railway logs`) was:

```
TypeError: connect() got an unexpected keyword argument 'sslmode'
```

This only surfaced *after* fixing the missing-`MODEL_NAME` crash above — it
was hidden underneath a different failure the whole time.

**Root cause:** Neon's dashboard generates connection strings with
`?sslmode=require&channel_binding=require` in the query string — parameter
names from the `libpq`/`psycopg2` world. SQLAlchemy's `asyncpg` dialect passes
URL query parameters straight through as keyword arguments to asyncpg's own
`connect()`, and `asyncpg` doesn't recognize either of those parameter names
(it has its own, differently-shaped SSL configuration) — so it raises a
`TypeError` rather than silently ignoring them. This would never show up with
`psycopg2` (the sync driver, and coincidentally the wrong one — see
`env-setup.md` Phase 3 for why this project uses `asyncpg`), which is exactly
why Neon's own generated string looks correct at a glance.

**Fix:** strip both `sslmode=require` and `channel_binding=require` from the
query string entirely. `asyncpg` negotiates SSL with Neon correctly on its own
without them being spelled out. Confirmed directly — a real `SELECT 1` against
the production Neon database succeeded immediately once those two params were
removed from the URL, both locally and once applied to Railway's
`DATABASE_URL`.

---

## `@repo/ui` only resolved `.tsx` files — the shadcn button couldn't import its own `cn()`

**Symptom:** `tsc` in an *app* failed with `Cannot find module '@repo/ui/lib/utils'`
as soon as that app imported `@repo/ui/components/button` — while `packages/ui`'s
own `check-types` passed. It was invisible until B1 because nothing outside
`packages/ui` imported a shadcn component yet.

**Root cause:** `packages/ui/package.json` had `"exports": {"./*": "./src/*.tsx"}`.
That maps every subpath to a `.tsx` file, but `src/lib/utils.ts` is a `.ts` file, so
the pattern points at a file that doesn't exist. Inside the package the same import
resolved fine through `tsconfig.json`'s `paths` (`@repo/ui/*` → `./src/*`), which
tries extensions — a second resolution mechanism that masks the broken one. Apps
don't use the package's `paths`; they go through `exports`.

**Fix:** add a more specific entry above the catch-all —
`"./lib/*": "./src/lib/*.ts"`. Longest matching pattern wins, so order is cosmetic
but the specificity matters. If shadcn ever generates `.ts` files elsewhere
(e.g. `hooks/`), each folder needs its own entry.

---

## Tailwind v4 doesn't scan `packages/ui` — shared components render unstyled

**Symptom (predicted in B1, hit and confirmed in B3):** the first calendar page that
imports a `@repo/ui` component compiles, type-checks and renders, but without the
component's classes. B3's filter header (the combobox and select) is the first such page;
the built CSS contained none of the combobox classes until `@source` was added.

**Root cause:** Tailwind v4 generates only the utilities it finds by scanning source
files, and its automatic detection starts from the app's own directory. Class names that
live in `../../packages/ui/src` are outside it, so those utilities are never emitted.

**Fix:** add `@source "../../../packages/ui/src";` to `apps/calendar/app/globals.css`. The
path is relative to the CSS file, which is `apps/calendar/app/`, so it takes **three** `..`
to reach the repo root. **This entry used to say `"../../packages/ui/src"` — that is wrong**
(it resolves to `apps/packages/ui/src`, which doesn't exist, and Tailwind silently scans
nothing). Measured in B3 by building three ways and grepping the CSS for `combobox-chip`:
old two-`..` path → absent; no `@source` → absent; three-`..` path → present. `apps/admin`
has no Tailwind at all, which is why its shared button renders unstyled.

---

## Alembic's `add_column` never creates a Postgres enum type

**Symptom:** an autogenerated migration that adds an enum-typed column to an *existing*
table fails on upgrade with `type "venue_type" does not exist`. Enum-typed columns inside
`create_table` appear to work, which makes this easy to miss.

**Root cause:** Alembic creates enum types only as part of `op.create_table`. `op.add_column`
emits a bare `ALTER TABLE ... ADD COLUMN`, so a type used *only* on columns added to an
existing table (here `venue.venue_type` and `venue.fetch_strategy`) is never created. Types
shared with a new table (`age_restriction`, `setting`, `seating`) work only by luck of
operation order. Autogenerate also never emits `DROP TYPE` in `downgrade()`, which leaves
orphaned types behind. Autogenerate's own `create_table` path creates types with
`checkfirst=False`, so an orphan makes the next `upgrade` fail with `type already exists`;
a hand-written `.create()` defaults to `checkfirst=True` and would silently adopt it, even
with different labels — so the hand-written calls pass `checkfirst=False` too.

**Fix:** create every enum type explicitly at the top of `upgrade()`
(`postgresql.ENUM(*labels, name=name).create(op.get_bind())`), reference them in columns with
`postgresql.ENUM(..., create_type=False)`, and drop them after the tables in `downgrade()`.
Keep the label lists in the migration as frozen copies, not imports from `app/enums.py` — a
migration must keep meaning what it meant when it was written.
`app/tests/test_db_schema.py` runs `upgrade → downgrade → upgrade` and asserts no enum types
survive the downgrade, so a missed drop is a red test, not a surprise.

---

## SQLAlchemy persists enum member names, not values, unless told otherwise

`Enum(AgeRestriction)` stores `"ALL_AGES"`, not `"all_ages"`, even for a `StrEnum`. Set
`values_callable=lambda e: [m.value for m in e]` (done once, in `app/db/types.py`) so the
Postgres labels match `app/enums.py` and `data-model-initial.md` section 4. The silent
failure is that everything works until something compares the database's labels to the API's.
`test_enum_labels_are_the_python_values_not_the_member_names` guards it.

---

## Alembic's `env.py` overwrites the URL — tests must inject a connection

The stock `migrations/env.py` calls `config.set_main_option("sqlalchemy.url",
settings.database_url)` unconditionally, so any test that sets its own URL on an Alembic
`Config` is silently ignored and the migration — including `downgrade base` — runs against the
**dev** database. It also calls `asyncio.run`, which can't run inside pytest-asyncio's loop,
and `fileConfig()`, which disables existing loggers for the rest of the session.
`env.py` now honours `config.attributes["connection"]` (a synchronous connection, obtained via
`AsyncConnection.run_sync`) and skips all three when it is set. If that connection is already
inside a transaction, Alembic's `begin_transaction()` becomes a no-op and never commits, so
commit explicitly afterwards (`app/testing/db.py`, `run_alembic`).

---

## `TEST_DATABASE_URL` in `.env` breaks the whole app

`Settings` forbids unknown keys, so an extra line in `.env` raises a `ValidationError` at
import — for the app, Alembic and every test. pydantic-settings also doesn't export `.env`
values to `os.environ`, so a test fixture reading `os.environ` wouldn't see it anyway. Test
variables (`TEST_DATABASE_URL`, `REQUIRE_DB`) are shell / CI environment only.

---

## A `catch` around a `fetch` breaks `next build` unless it calls `unstable_rethrow` first

In Next 16 (default caching model), a `cache: "no-store"` fetch reached during prerender
**throws** a `DynamicServerError` (`digest: "DYNAMIC_SERVER_USAGE"`) before any network call.
That throw is how Next learns "this route is dynamic". A `catch` that wraps it (into an
`ApiError`) or swallows it (`return null`) fails the build with `Error occurred prerendering
page`, whether or not the API is up. Unit tests can't see it: Vitest has no patched `fetch`.
Call `unstable_rethrow(err)` (from `next/navigation`) first in every such `catch`;
`lib/api.test.ts` and `lib/metro.test.ts` pin it with a hand-built error carrying that digest.
The related `server-only` trap: the package throws on import under Vitest, so
`vitest.config.ts` aliases it to `test/server-only-stub.ts`.

---

## With the API down, a data page is a bare 500 document, and `error.tsx` needs `retry`

Without a `<Suspense>`/`loading.tsx` above the page, a Server Component that throws before the
first flush makes Next answer HTTP 500 with a bare `<html id="__next_error__">` document: no
header, footer or `error.tsx` markup in the server HTML (React's server renderer doesn't run
error boundaries). `error.tsx` renders only after hydration. Adding `loading.tsx` streams the shell
first, but then `notFound()` returns 200 (a soft 404) — a trade-off recorded as B2-D4 in the B2 plan.
Separately, in Next 16.3 `error.tsx`'s `reset()` re-renders the *same* failed payload; `retry()`
re-fetches, so it is the one a "Try again" button needs.


---

## In Pydantic v2, `X | None` without `= None` is still required — and that decides what the model is told

`time: datetime.time | None` with no default raises a `missing` error when the key is absent, and
it lands in the JSON schema's `required` list — which is what `instructor` sends the model. So
"make `time` optional" needs the default as well as the type, or the schema still tells the model
the field is mandatory (and it invents a value). `agent_worker/tests/test_extraction_schema.py`
pins the exact required set. Related: a field's `description` is part of that request, so how the
model is told to say "not stated" (the fixed phrase "otherwise null") is an instruction, not a
comment.

Two more things found building A2's time handling: Pydantic's `datetime.time` parsing is strict
(`"7pm"`, `"7:30 PM"`, `"8:00pm"`, `"24:00"` are all rejected), while an *integer* like `68400` is
accepted as a timezone-**aware** `19:00+00:00` that will never compare equal to the database's
naive `time`. `agent_worker/normalize.py` is a `BeforeValidator` that converts the unambiguous
spellings and refuses the rest — and it only sees `"n/a"` if the `| None` sits *inside* the
`Annotated[...]`, not outside it.
(Since October 10, 2026 a time with no AM/PM is read as PM — a product decision, see
`requirements-initial.md` — but a two-digit `"10:30"` is still trusted as 24-hour, because that is
the format the model was asked for; only the field description can make the model assume PM there.)

---

## Ollama's `/v1` endpoint ignores `options` — `num_ctx` and `seed` placed there do nothing

Found measuring A2's baseline (Oct 9 2026, Ollama 0.35.0, `gemma4:e4b`). `extract_node` and
`eval/run_eval.py` both send `extra_body={"options": {"num_ctx": 32768}}`, which Phase 5 recorded
as a load-bearing fix for Ollama's 4096-token default. Through the OpenAI-compatible `/v1`
endpoint it is **silently ignored**:

- After a `/v1` call carrying `options.num_ctx = 32768`, `GET /api/ps` reports
  `context_length: 4096`. The same option on the native `/api/chat` loads the model at 32768.
- A model warmed at 32768 through `/api/chat` is reloaded back to 4096 by the next `/v1` call.
- `options.seed` is ignored the same way (three identical prompts: varied output). The OpenAI-style
  **top-level** `seed` argument works (three identical outputs), so the eval passes that.
- Effect on the baseline: 10 of 18 runs ended in `IncompleteOutputException`, including all nine
  runs on the three largest text pages (White Squirrel, Midway, Zhora; 66–84 s each), where a
  4096-token window truncates the answer. **Confirmed for White Squirrel (Oct 9 2026)** by replaying
  the exact messages `instructor` sends (schema in a system prompt, JSON mode — 1747 prompt tokens)
  through native `/api/chat` with the same model, seed and `num_predict` 16000: at `num_ctx` 4096 it
  stopped with `done_reason: "length"` after 2349 output tokens (1747 + 2349 = 4096) and the JSON was cut
  off mid-string; at `num_ctx` 32768 it finished (`stop`, 2754 tokens) and parsed to 12 shows, matching
  the page. `instructor` turns that `length` finish into `IncompleteOutputException` — so the failure is
  the context window, **not** the 16000-token `max_tokens` budget (the model never got near it). Phase 5
  attributed the same exception to "interpretive judgment calls"; at least for this page, that was the
  window. Midway and Zhora are not yet re-checked this way.
- **Fixed (Oct 9 2026) with a derived model**, not a code change: `apps/api/ollama/gemma4-e4b-32k.Modelfile`
  (`FROM gemma4:e4b`, `PARAMETER num_ctx 32768`), created with
  `ollama create gemma4-e4b-32k -f apps/api/ollama/gemma4-e4b-32k.Modelfile`. It reuses the same weights
  (`ollama list` shows 9.6 GB for each, but nothing is copied) and a model's *own* default context is the one
  setting `/v1` honours. Set `MODEL_NAME=gemma4-e4b-32k` in `apps/api/.env`. Verified: a `/v1` call to it
  loads with `context_length: 32768` (about 3.4 GB resident here), and White Squirrel through the eval harness
  completed first attempt with 12 shows. Undo: `ollama rm gemma4-e4b-32k` and set `MODEL_NAME` back.
  `run_eval.py` now follows `MODEL_NAME` instead of a hard-coded tag, and still records
  `loaded_context_length` in every results file, so a label run at the wrong window says so. The now-dead
  `options.num_ctx` in `nodes.py` / `run_eval.py` is left in place (it matches Phase 5's code and is harmless);
  remove it when someone next touches those call sites. Other models would need the same treatment.

---

## The Ollama app updates itself, so an eval's environment can change under it

Found closing A2 (October 10, 2026). The A2 labels were measured on Ollama **0.35.0**; the next
morning `curl localhost:11434/api/version` said **0.40.2** — the macOS app had updated itself
(`/Applications/Ollama.app` modified 06:04), and `gemma4-e4b-32k` had been re-created with a new
digest (`654af1bf75f4` vs `08aefbf02b7c` in the results files; the base `gemma4:e4b` weights were
unchanged). Nothing in the code changed, yet a new run is no longer like-for-like with the stored
ones, and behaviours this file records for 0.35.0 (the `/v1` endpoint ignoring `num_ctx`) may no
longer hold. The eval harness stores `ollama_version` and `model_digest` per label for exactly this
reason: **compare them before comparing numbers**, and re-run a baseline when they differ.

---

## A nested `acts` object made the model stop splitting acts

Found closing A2 (October 10, 2026), from the stored eval results. With `acts: list[str]` and the
description "The name(s) of the act(s) performing", `gemma4:e4b` split "Lent w. Gills, Boomdagger"
into three acts on most multi-act listings. With `acts: list[ActExtraction]` (an object with a
`name`, plus optional per-act time and order) and the description "The act(s) performing", it
almost always returned **one** act named with the whole title: Zhora went from ~17 of 23 shows
split to 0 in every run. The richer schema was measured for completions and leaks, and this
slipped past because nobody compared act counts across labels. Takeaway for schema changes: when a
field's *shape* changes, re-check the field's own content, not just whether the output parses.
Cause not yet isolated (the shape or the lost "name(s)"); A2.1 tests it
(`docs/dev/implementations/a2-extraction-schema.md`, Eval results › Addendum).

---

## A browser-saved fixture is not what the pipeline fetches

Found planning A2.1 (October 10, 2026). A2's eval fixtures were Chrome "Save Page As" captures —
the page *after* JavaScript ran. The pipeline fetches with one plain `httpx.get`, which runs no
JavaScript. One plain GET per venue showed the difference decides everything:

- **Zhora Darling**: the saved page had 24 listings (and 24 schema.org `MusicEvent` blocks); the
  plain fetch has 314 characters of visible text and no events. The DICE widget draws both
  client-side.
- **Midway**: the saved page had a full month grid; the plain fetch gets **HTTP 403** and a
  Cloudflare "Enable JavaScript and cookies to continue" page — a bot challenge. Not something to
  work around (A2.1-D3).
- **White Squirrel** and **Terminal Bar**: the same listings either way (and White Squirrel's
  schema.org JSON-LD is server-rendered, so it survives the plain fetch).

So an eval built on browser captures measured two pages production never sees. A2.1's fixtures
are captured with the pipeline's own fetch (`agent_worker/eval/capture.py`, which calls
`nodes.fetch_html`). Rule of thumb: **capture fixtures with the same code that fetches in
production**, and when a page is thin (`capture.py` warns under 500 visible characters), the
listings are being drawn by a script.

---

## A gate with nothing in scope must not pass

Found smoke-testing A2.1's scorer (October 10, 2026). `scoring.gate(runs, route="jsonld")` over
a label where no page took the JSON-LD route returned PASS with zero failures — "every run met
every tier" is vacuously true of no runs. It printed as "gate [jsonld]: PASS", which reads as
evidence the route works. The gate now counts the pages in scope and never passes on zero
(`test_a_gate_with_no_pages_does_not_pass`); `--compare` shows such a scope as "n/a (no pages)".

*Rechecked October 10, 2026 on Ollama 0.40.2:* `/v1` still ignores `options.num_ctx` (a request for 8192 left
`gemma4-e4b-32k` loaded at 32768 per `/api/ps`), so the derived model is still how the working window is set.

---

## `PlainYearMonth.toLocaleString("en-US", …)` throws

Found writing B3's month dropdown labels (`lib/dates.ts`). `Temporal.PlainYearMonth.from("2026-10")
.toLocaleString("en-US", { month: "long", year: "numeric" })` throws `cannot format PlainYearMonth with
calendar iso8601 in locale with calendar gregory`: a year-month has no day, so the polyfill refuses to
guess which calendar to apply. Go through a full date instead — `ym.toPlainDate({ day: 1 })
.toLocaleString(...)` gives "October 2026". (`PlainDate` and `PlainTime` format fine; and a `PlainDate`
prints the same text under any `TZ`, because it has no zone to shift.)

Related: Temporal objects throw on `<`, `>` and `<=` (their `valueOf()` raises on purpose, so a bare
comparison can't silently compare strings). Use `Temporal.PlainDate.compare` / `PlainTime.compare`.

---

## The shadcn CLI in this monorepo: run it from `packages/ui`, then fix what it writes

B3 added the combobox and select (`pnpm dlx shadcn@latest add combobox select`). Four surprises, none
visible until the files were on disk:

1. **Run it from `packages/ui`, not `apps/calendar`.** From the app it stops with `Could not resolve the
   following aliases … ui` — the app's `components.json` points `ui` at `@repo/ui/components`, which the
   CLI can only resolve from inside the package that owns that tsconfig path. (`--dry-run` is safe and
   shows the file list first.)
2. **It writes `import { cn } from "cn"`** into every generated file and adds an unrelated npm package
   called `cn` to `packages/ui/package.json`. The repo's helper is `@repo/ui/lib/utils`. Rewrite the
   imports and remove the dependency.
3. **It offers to overwrite `components/button.tsx`** (the combobox depends on `button`). The registry
   version differs from ours only in that same `cn` import, so restore ours with `git checkout`.
4. **Its dependencies come along**: `combobox` also writes `input-group`, `input` and `textarea`, and
   imports `lucide-react`, which `apps/calendar` had but `packages/ui` didn't (pnpm doesn't hoist across
   workspaces, so `@repo/ui` failed to resolve it until it was added to `packages/ui/package.json`).

---

## A scroll container must be the grid item itself, or it widens the page

Found checking B3's calendar rows (`app/_components/calendar-grid.tsx`). A grid item's automatic minimum
width is its content's min-content width — *unless the item is itself a scroll container*, whose automatic
minimum is 0. So a row `<div class="overflow-x-auto">` that is the direct child of a `1fr` grid track
scrolls sideways on its own. Wrap it in a bare `<div>` and that wrapper's minimum becomes the combined width
of every venue column: the track grows to fit it and the **page** scrolls sideways. Measured in headless
Chrome on the real calendar, page `scrollWidth` with the scroller direct / wrapped / wrapped with `min-w-0`:
768px **768 / 1232 / 768**, 1024px **1024 / 1232 / 1024**, 1280px **1280 / 1296 / 1280** (only 16px there, easy to
miss — test at tablet width), and at 375px **375 / 375 / 375**: below `md` the row is block flow, where a wrapper is
harmless. The fix for a wrapper is `min-w-0` (or `minmax(0, 1fr)` on the track).

Also: `position: sticky` sticks only within its own grid *area*. In a one-column grid that is the heading's
own row, so it never sticks; below `md` the row is plain block flow (the `<li>` is the containing block),
and only from `md` up is it a two-column grid.

---

## An unchanged retry at temperature 0 is the same call — including attempt 3 when attempt 2 failed the same way

Found by A3's graph test, not by reading. The pipeline runs at temperature 0, so a retry that sends the same
request returns the same answer (A2.1's `a21-confirm`: five runs, byte-identical). A3 makes each retry
different by adding a hint built from the findings that failed. But the hint for attempt 3 is the union of every
earlier attempt's findings, and if attempt 2 failed the *same* check as attempt 1, that union is the same text as
attempt 2's: on a machine with no larger model to swap in, attempt 3 was byte-identical to attempt 2. The last
attempt therefore adds a sentence of its own (`policy._FINAL_PAGE_ADVICE`). Anything that builds retry requests
from history needs a test that asserts *consecutive attempts differ*, not just that "a hint is present".

## A fixture-based test can't run in CI: `eval/fixtures/` and `eval/results/` are gitignored

The venue pages and the stored eval results are not in the repo, so CI and a fresh clone have neither, and the
existing tests never read them (`test_extraction.py` says so). Tests that need real pages are therefore a separate,
local-only layer that skips when the data is absent (`tests/test_validation_on_real_pages.py`, visible with `-rs`);
everything CI must prove is tested on small synthetic pages in the fixtures' shapes, with any real artefact pinned as
a literal (the SHA-256 of today's four request texts, checked locally against `a21-review2.json`).

## An image `src` with `&amp;` isn't a substring of the HTML that contains it

`<img src="a?b=1&amp;c=2">` is read by the HTML parser as `a?b=1&c=2`. A model that copies the URL from the
cleaned text writes `&`, so `url in page_html` is false for a URL it copied correctly. The pipeline's image check
(`validation.verify_image_url`) and the eval's `invented_image_urls` compare against the *unescaped* HTML. The eval's
old check (against cleaned text) also counted every JSON-LD URL as invented (225 in `a21-confirm`), since a
structured source's URL never appears in visible text; it now skips `jsonld` and `image` runs.

---

## Two ways a calendar page scrolls sideways that no unit test can see, and the measuring trap that hid one

Found in B4 by measuring `document.documentElement.scrollWidth` against `clientWidth` in headless Chromium at 375px.
Both are the same family as B3-K5 (what the scroll container actually contains):

1. **`.sr-only` inside a scroll container widens the page.** `sr-only` is `position: absolute`, and an `overflow-x: auto`
   container does not clip an absolutely positioned descendant whose containing block lies *outside* it. B4 put a
   visually hidden ", show details" in the show block's link; the block lives in the calendar's per-date scroller, so on
   the four-venue row the hidden text sat far to the right and `/` measured **889px wide on a 375px phone** with no
   visible element out of place. The fix is `relative` on the link, so the link is the containing block and the text
   scrolls and clips with its row. Any `sr-only` inside the grid needs the same.
2. **A long unbreakable value in a `grid-cols-[auto_1fr]` list widens it.** A grid item's automatic minimum width is its
   longest unbreakable word, and the detail pages print URLs and emails scraped from the web: a calendar URL pushed
   `/venue/3` 9px past a 375px screen. `min-w-0 [overflow-wrap:anywhere]` on the `<dd>` (`DetailRow`).

**The measuring trap:** `/` streams (B3-D4), so `waitUntil: "load"` can fire before the Suspense body arrives, and the
page measures as the skeleton: `/` read "fine" at 375px until the check waited for `networkidle`. Measure a streamed
page after its body is in.

## `pkill -f next start` kills the shell that runs it

The pattern matches the shell's own command line (it contains "next start"), so the shell dies with exit 144 and the
rest of the command never runs. Find the server's pid with `ps -eo pid,args | grep "[n]ext-server"` (the bracket keeps
grep from matching itself) and kill that.

---

## A graph node wrapper must not use `functools.wraps`, and BSON cannot store a `date`

Two things found while building A4's audit wrapper (`agent_worker/trace.py`), both verified, not assumed.

**`functools.wraps` hides LangGraph's `runtime` parameter.** LangGraph decides whether to inject the runtime
context by inspecting the node function's signature. `functools.wraps(node)` makes the wrapper report the
*inner* node's signature, which has no `runtime`, so nothing is injected and the call fails with
`TypeError: inner() missing 1 required positional argument: 'runtime'`. The message names the inner function,
not the cause. Declare `runtime: Runtime[WorkerContext]` on the wrapper itself and don't copy metadata onto it.

**`pymongo` cannot encode `datetime.date`.** `bson.encode({"d": datetime.date.today()})` raises
`InvalidDocument`. Anything untyped that reaches a Mongo document (an extraction's `notes` dict) has to go
through `pydantic_core.to_jsonable_python` first (`agent_worker/staging.document_for`). A `datetime.datetime`
is fine; BSON stores it natively.

## MongoDB 8.x will not start on Docker Desktop's current kernel

`make db-wait` reported "timed out after 30s", but the real cause was the mongo container exiting at
startup: `MongoDB cannot start: Linux kernel versions 6.19 and newer has a known incompatibility`
(SERVER-121912). Docker Desktop's VM runs `7.0.12-linuxkit`, so every `mongo:8.0.x` tested exited with this
guard. `docker compose ps -a` and `docker compose logs mongo` show it; the timeout message does not.

`mongo:7.0` (v7.0.45 when tested) starts and answers ping. Pinned in `docker-compose.yml` instead of
`mongo:8`, which departs from A4-D3 in `a4-auditability.md`. Setting `GLIBC_TUNABLES=glibc.pthread.rseq=1`
gets `mongo:8.0` past the guard and it then answers ping, but it bypasses a check MongoDB added for a real
incompatibility, so it was not used. Revisit the pin when Docker Desktop's kernel or a MongoDB 8.x patch
changes.

## Reconcile (A5): where "absent from the page" can go wrong

- **"Not in the validated list" is not "not on the page".** `validation.excluded` and `Finding.show_index` index the RAW
  `state.extraction.shows`, not `validated_extraction.shows` (which has the excluded shows taken out). A listing left out
  for naming no act is still on the page and may be a real show the act splitter missed, so it protects a stored show on its
  date from the soft delete; one left out for an implausible date is not evidence the page reached that far. Validation excludes a show for
  naming no act BEFORE it checks the date, so an implausible-dated placeholder ("Private event", 2028) arrives as a no-act
  exclusion too; `excluded_listing_dates` re-checks plausibility itself. Reading the wrong list protects the wrong dates,
  silently. `reconcile.excluded_listing_dates` is the one place that does it.
- **A reader that returns an empty list is not the same as a reader that failed.** Reconcile treats "nothing stored" as
  "insert everything". The read therefore raises, and the run stops, rather than falling back to an empty calendar
  (`trace.read_calendar`; test_an_unreadable_calendar_stops_the_run_with_no_reconcile_row).
- **`None == None` is `True` in Python and not in SQL.** The null-time pairing is where this bites (a naive
  `listing.time == stored.start_time` pairs two different untimed shows but not an untimed one with a timed one).
- **Venue ids in DB tests are not 1, 2, 3.** Sequences don't reset when a test's transaction rolls back, so a test that
  needs a venue reads the seeded ids (`load_venues`) rather than hard-coding them.

---

## Component tests: five things that cost time, found while setting up B5

All verified, not assumed (`docs/dev/implementations/b5-frontend-testing.md`, "Checked").

**A `.test.tsx` file fails to parse: `Unexpected JSX expression`.** The app's tsconfig sets `"jsx": "preserve"`
(Next compiles JSX itself), Vite 8 transforms with Oxc and honours that, so JSX reaches Node untouched.
`vitest.config.ts` needs `oxc: { jsx: { runtime: "automatic" } }`. The next error, `document is not defined`,
just means the file is still in the node environment (the extension picks it: `.tsx` is jsdom).

**jsdom 30 needs a newer Node than the cloud sandbox has.** Its range is `^22.22.2 || ^24.15.0 || >=26.0.0`;
the sandbox runs 22.22.0. `jsdom@^29` (`^20.19.0 || ^22.13.0 || >=24.0.0`) runs everywhere we do. A
Dependabot bump to 30 will probably pass CI (`node-version: 24` takes the newest 24.x) and fail a cloud
session or a laptop on an older 24.x. `@testing-library/dom` is a *peer* of `@testing-library/react` 16 and
must be installed explicitly.

**`fireEvent.click` never opens Base UI's combobox.** No option appears, even after waiting. `userEvent` does,
and after an awaited `user.click` the option is already in the DOM. Mock `useRouter` with `vi.hoisted`: a
`vi.mock` factory that reads a top-level `const` eagerly fails with `Cannot access 'push' before
initialization`; with no mock at all the component dies with `invariant expected app router to be mounted`.

**jest-dom's matchers refuse elements from a `DOMParser` document.** `toHaveAttribute` on a script parsed with
`new DOMParser().parseFromString(...)` fails with `received value must be an HTMLElement`, because that
document has no `defaultView`. Use `getAttribute` there. (That parse is needed to test JSON-LD: a Testing
Library `render` sets the script text through `innerHTML`, which never treats `</script>` as an end tag, so
a client-render test stays green even for an unescaped `JSON.stringify`.)

**jsdom is not a browser, and Base UI knows it.** Base UI sets `env.jsdom` from the user agent and takes
different paths under it (it returns early around `getBoundingClientRect`, and skips part of its virtual-click
detection). Tests of the filter header therefore prove URLs, names and presence, not positioning or pointer
behaviour; a test that depends on those belongs in a real browser (Playwright).

**To compare a streamed page before/after a refactor, use a real browser.** Raw server HTML differs between
runs even when the page is identical (Suspense chunks arrive in whatever order the parallel API calls
return), and jsdom with scripts enabled never runs Next's `$RC` swap, so it "agrees" on two skeletons. Dump
`<main>` from headless Chromium instead (`--headless=new --no-sandbox --virtual-time-budget=8000 --dump-dom`),
strip `<script>`, and print the article and skeleton counts beside the verdict so a pair of skeletons can't
pass. Also: a bundle grep for `jsdom` always hits Base UI's own user-agent sniffing; grep for
`testing-library` and `user-event` instead.

## Two clocks in the end-to-end job, deliberately nine days apart (C2)

**Since C2 the API's window follows a real clock, and the browser suite pins both.** The routes start the default
window at the metro's local "today" (`app/clock.py`, `metro_today`, from the injected `get_now`). Until C2 the sample API
ignored the clock (its window was the constant `START`, September 28), and the Next server's `metroToday` (`lib/dates.ts`)
was the only real clock in the app. Now the end-to-end job pins both (`apps/calendar/e2e/support/clock.ts`): Next to
October 7 (`E2E_NOW`, so the "Today" row is in the middle of the window) and the API to noon on September 28
(`E2E_API_NOW`, so the served window is September 28 - October 25, which `lib/fixtures` and the specs expect). They differ
on purpose; production has one clock. `clock.test.ts` fails if either pin stops agreeing with the fixture's window, and the
Python tests (`test_routers.py`, `test_clock.py`) cover the real single clock, including the UTC-vs-Minneapolis date and the
year and daylight-saving turns.

**The API's pin is a dependency override in a module production never imports** (`app/testing/e2e_app.py`), not an
environment variable the real app obeys. `test_no_testing_imports.py` enforces that nothing in production imports
`app.testing`.

The old version of this section said the home page could empty on October 26 because the window rolls with the clock. That
was wrong for the sample API (found while planning B6) and became true in C2, once the routes read the metro's real date; a
hosted database with no recent worker run shows an empty calendar (`alpha-deployment-plan.md`, Dep-D12).

**Freeze the clock by patching `Date.now` and nothing else.** `globalThis.Date = class extends Date { … }` crashes the
Next server at import (`TypeError: Date.UTC is not a function`, thrown while the Temporal polyfill loads), and the whole
app 500s. The Temporal polyfill reads `Date.now()` for `Temporal.Now`, so `Date.now = () => FROZEN` in a
`NODE_OPTIONS=--import` preload is enough (`e2e/support/fake-now.mjs`). Playwright's `page.clock` fakes only the browser's
clock; a Server Component never sees it.

## Playwright and the end-to-end suite (B6)

**`next build` type-checks `e2e/`.** The calendar's tsconfig includes `**/*.ts`, so a type error in a Playwright spec fails
the production build (and so a Vercel build), not just `pnpm check-types`. A throwaway probe file left in `e2e/` does it
too: delete probes before you build.

**Playwright's default `testMatch` also collects `*.test.ts`.** Those are Vitest files here, which import `vitest` and
cannot load under Playwright (it lists 0 tests). `playwright.config.ts` sets `testMatch: "**/*.spec.ts"`; keep specs
`*.spec.ts` and unit tests of the support code `*.test.ts`.

**Playwright's `getByRole` has no `current` option** (Testing Library's does). Find "today's row" by the "Today" badge and
assert `aria-current="date"` on it.

**A real browser's accessible name differs from jsdom's.** The "…, show details" suffix is a visually hidden block, so
Chromium reports `9:00 PM – 11:30 PM , show details` (a space before the comma); jsdom, with no layout, gave B5
`…PM, show details`. Match such names with `\s*`.

**While a combobox popup is open, the whole page behind it is `aria-hidden`** (Base UI marks everything outside the popup;
finding B6-F2), so `getByRole` finds nothing there and a screen reader cannot read it. A multi-select's popup stays open
after a pick: press Escape before asserting on the page.
Cause (B6 Step 8): Base UI 1.7.0 forces the popup modal when the combobox's input is outside it (`focusManagerModal =
!inputInsidePopup || modal`), so the `modal` prop does nothing for our layout, and its focus manager `aria-hidden`s everything
else while the popup is open. Tab is not trapped: focus moves on into the page and the popup stays open. The only way to
remove the flag is the "input inside the popup" pattern, a different control.

**A test that ends mid-prefetch makes Next log `⨯ Error: The destination stream closed early.`** A production page
prefetches the pages its links point to as streamed responses; closing the browser on one makes React abort that render
and log it. Harmless, but alarming. `e2e/support/test.ts` waits for the page's in-flight requests before the browser closes.

**eslint-plugin-react-hooks mistakes Playwright's fixture callback `use` for React's `use()` hook.** The rule is switched
off for `e2e/**/*.ts` in `eslint.config.js`. Also, `eslint-plugin-turbo` (with `--max-warnings 0`) rejects any
`process.env.X` it has not been told about: `turbo.json` declares the e2e ones under `globalPassThroughEnv`.

**The sandbox cannot download Playwright's browser** and ships an older Chromium (`/opt/pw-browsers/chromium`) than
Playwright 1.64 expects; it works. `scripts/cloud-setup.sh` exports `E2E_CHROMIUM_PATH` for it.

**A `focus` handler that scrolls runs for a mouse press or a tap too, and swallows the click.** Chromium focuses a link on
mouse-down; if the handler moves the page (or a scroller) before the mouse-up, the release lands on something else and
nothing navigates. Guard such handlers with `target.matches(":focus-visible")` (keyboard focus only). `ScrollRow` does; its
pointer journey is `e2e/venue-row-pointer.spec.ts`. Test it with raw `page.mouse` / `page.touchscreen` coordinates on the
VISIBLE part of a partly visible control, and with a viewport tall enough that the control is on screen (a press below the
fold reaches nothing and the test fails for the wrong reason).

Browser tests (B6, C2) pin both clocks to dates that agree with the sample window. **Whenever `testing/sample_data.py` changes, move
the pinned dates in the same change** (`clock.test.ts` fails if you don't). See `alpha-build-plan.md`, B6, "Standing rule: the test clock".

---

## With asyncpg, only integrity violations are an `IntegrityError`; an overflow is a plain `DBAPIError`, and a dropped connection has `sqlstate = None`

**Symptom (found in A6 plan review, before any code):** a handler that caught `(IntegrityError, DataError)` to mean "the
database refused this row" did not catch a `Numeric(10, 2)` overflow, and a `getattr(err.orig, "sqlstate", "")[:2]` raised
`TypeError` on a real lost connection.

**Cause:** SQLAlchemy's asyncpg dialect maps `asyncpg.exceptions.IntegrityConstraintViolationError` to `IntegrityError` and every
other server error to the generic `Error` (`dialects/postgresql/asyncpg.py`, `_asyncpg_error_translate`), so `DataError`
never occurs, and a SQLSTATE class 22 error (a data exception: overflow, a NUL byte, a bad enum text) is a plain
`DBAPIError`. The dialect always SETS `orig.sqlstate`, to `None` for a client-side error, so a dropped connection (an
`InterfaceError`, `connection_invalidated = True`) has an attribute that exists and is `None`: a `getattr` default is never used.

**Fix / lesson:** classify by the SQLSTATE class the database reports (`calendar_writer.is_decision_error`: 22 or 23 is about the
row, anything else is about the connection or us), and read it as `getattr(err.orig, "sqlstate", None) or ""`. Measured on
SQLAlchemy 2.0.52 / asyncpg 0.32.0. `tests/fakes.py` builds the real shapes.

---

## In the DB tests a second session's "separate" commit is not separate: it nests inside the first session's savepoint

The test factories bind every session to one connection in `create_savepoint` mode, so a session opened while another is mid-
transaction creates a savepoint INSIDE the first's, and rolling the outer one back undoes the inner one's "committed" work. A test
that asserts "a rolled-back write left no audit row" cannot tell a writer that used one transaction from one that wrote the audit
row through a second session (the A6-M2 mutation). Only counting the sessions catches that (`test_a_write_uses_exactly_one_session`),
or a test on a real engine instead of savepoint mode. A failure raised AFTER the rows were produced
(`test_audit_rows_roll_back_with_the_write`) catches a different mistake, a `commit()` before the rows are added, and passes a
writer that used a second session.

---

## Inside a test transaction `now()` never moves, so `updated_at` assertions need a literal past value

`TimestampMixin.updated_at` is `server_default=now()` / `onupdate=func.now()`, and `now()` is the start of the OUTER test transaction.
Two readings of it are equal, so "did this row get rewritten" cannot compare before with after (the same trap as `finished_at`, A4-CR1-5).
Seed the rows with a literal past `updated_at` and assert the value against that literal.

---

## pytest imports every file its `python_files` globs match, tests or not, and `--collect-only` won't show it

pytest's default `python_files` is `test_*.py` and `*_test.py`. `agent_worker/local_test.py` (a manual script: real Postgres, MongoDB and
Ollama) matches the second glob, so any `testpaths` that includes `agent_worker/` makes pytest **import it on every run**. It was invisible
while `testpaths` listed only `agent_worker/tests`, and it stays invisible in `pytest --collect-only`, whose tree lists only modules that yield
test items: a module that is imported but defines no tests doesn't appear (A7 measured this with a top-level `print("PROBE")` and `-s`).
Today the import has no side effect because the work sits under `if __name__ == "__main__"`; a module-level call added later would run on every
pytest.

**Fix / lesson:** `python_files = ["test_*.py"]` in `pyproject.toml`, so only `test_*.py` is ever a test module, and
`app/tests/test_pytest_config.py` fails if the glob or `testpaths` regress (it walks the whole tree, not just `testpaths`, so it is red on a
config that only widens `testpaths`). To check whether pytest imports a file: add a top-level `print` and run `pytest --collect-only -s -q`.

---

## Dependabot alerts: a cloud session can't read them, and the count overstates the work

**Symptom:** the Security tab showed 117 open alerts; `gh api repos/.../dependabot/alerts` in a cloud session returned `403 Resource not
accessible by integration`.

**Root cause:** the session's token lacks the `vulnerability_alerts: read` permission (the 403's `X-Accepted-Github-Permissions` header names
it), and GraphQL and the global `/advisories` API are blocked for sessions. An export run on Ari's own machine, where `gh` is logged in as the
owner, works. A third-party "export alerts" Action is not worth it: it would be handed a token that reads the unpatched-vulnerability list,
and on this public repo an uploaded CSV artifact is downloadable by other signed-in users.

**Fix / lesson:** the count is misleading in two ways. Dependabot raises one alert per advisory per manifest, so `next` pinned in three
places turned 9 advisories into 27 alerts. And its `runtime` / `development` label follows `dependencies` vs `devDependencies`, so the
`shadcn` CLI (a build-time scaffolding tool) made ~48 alerts read "runtime"; 116 of 118 did. Triage by root cause (which direct dependency
drags the vulnerable one in), not by the flat list or the label. `.claude/skills/dependabot-triage/` (`/dependabot-triage`) does this:
`triage.py fetch` tries `gh` and exits 3 on a 403/401, at which point the skill stops and tells Ari to re-run it in a local session (no paste
step), then `triage.py summarize`, then `pnpm audit` / `pip-audit` and `triage.py chains` to find the levers. The 403 is a GitHub App token
(GitHub's "integration") without `vulnerability_alerts: read`, not a limit on `gh` itself: PRs, check runs and the dependency-graph SBOM all
work from a cloud session. Measured on the
2026-10-21 export: 118 alerts reduced to about six fixes, and the lockfile audits reconstructed 114 of them.

---

## A `viewonly`, `lazy="raise"` relationship fails in the first test, not in production (C2)

SQLAlchemy's default relationship loading is lazy: touching `show.venue` runs a query. Under asyncio that is a
`MissingGreenlet` error, and only on the code path that touched it. The models' relationships are `viewonly=True,
lazy="raise"` (C2-D4), so touching one that the query did not load raises immediately with the attribute's name, and every
query names what it loads (`app/queries.py`, `_show_loads`). Load a to-one side with `joinedload`, the to-many lineup with
`selectinload`: a `joinedload` on the lineup fails with "The unique() method must be invoked on this Result", because the
join repeats each show once per act. `test_the_statement_count_does_not_grow_with_the_number_of_shows` pins the count.

---

## A route test that loads rows and reads them back in one session never sees the column types (C2)

The route tests write the sample world with a session and the route reads through the same one, so without
`session.expunge_all()` between them the route is handed the loader's in-memory objects: `Decimal('10')` where Postgres
stores `Decimal('10.00')`. The `sample_client` fixture expunges after loading (C2-PR1-2). Any test that edits a row and then
calls a route needs the same `await session.flush(); session.expunge_all()` (`_settle` in `test_routers.py`).

---

## Postgres collation is not a rule a test can state, so lists are sorted in Python (C2)

`ORDER BY name` follows the database's collation, which differs between a laptop's Docker image, the cloud sandbox
(Postgres 16), CI (18) and Neon, and none is verified to sort like Python. `app/queries.py` sorts venues and artists by
`(name.casefold(), id)` and shows by `_ordering`, in Python, on bounded row counts. This departs from the style guide's
"SQL-first, Pydantic-second" on purpose.

---

## A seed that only inserts never removes a venue (C2)

`make seed` adds venues missing from `app/db/seed.py`'s list and leaves the rest. A database seeded before C2 keeps the
Midway Saloon and Zhora Darling after the list dropped them, and the worker keeps fetching them. `make db-reset` is how a
local database gets the current list; a hosted one needs the rows deleted by hand.
