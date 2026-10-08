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

