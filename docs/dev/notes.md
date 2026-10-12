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

**Fix / lesson:** don't trust the dashboard's raw editor as a source of truth.
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

**Symptom (predicted, not yet hit):** the first calendar page that imports
`@repo/ui/components/button` will compile, type-check and render, but without the
button's classes (`bg-primary`, `h-8`, …). A B1 review confirmed the calendar's built
CSS contains none of them.

**Root cause:** Tailwind v4 generates only the utilities it finds by scanning source
files, and its automatic detection starts from the app's own directory. Class names that
live in `../../packages/ui/src` are outside it, so those utilities are never emitted.

**Fix, when the first shared component is used in `apps/calendar`:** add
`@source "../../packages/ui/src";` to `apps/calendar/app/globals.css` (path is relative to
the CSS file). Deliberately not added in B1 — nothing in calendar imports `@repo/ui` yet.
`apps/admin` has no Tailwind at all, which is why its shared button renders unstyled.

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
first, but then `notFound()` returns 200 (a soft 404) — a trade-off recorded as D4 in the B2 plan.
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
slipped past because nobody compared act counts across labels. Lesson for schema changes: when a
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
  work around (A2.1 plan, D3).
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
