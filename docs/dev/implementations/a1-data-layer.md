# A1 — the data layer (models, migration, seed)

**Status:** Implemented — `make check` green (61 API tests, DB suite required)
**Date:** October 8, 2026
**Author model:** Claude Sonnet 5.5
**Reviewer model:** Round 1: Claude Opus (Agent tool, read-only). Round 2: a second reviewer model, run by the user — findings recorded under [Review](#review)
**Spec:** `docs/dev/alpha-build-plan.md` §5 A1, `docs/arch/data-model-initial.md` §1–4

## Context

`alpha-build-plan.md` §5 A1 is the foundation for all of Track A: there are no SQLAlchemy
models (v0.1-G11), no seed data (v0.1-G13), and Alembic's `target_metadata` is `None`, so autogenerate
can't work. Today the only schema is a hand-written migration (`db2aedec0bb9`) creating bare
`metro` and `venue`. A1 delivers the shared `app/db/` package, models for the core calendar plus
audit tables, a reviewed migration, a seed script, and removal of the dead `FIXTURES_DIR` (v0.1-G1).

Decisions made with the user:

- **Tests first, against real Postgres.** A separate `calendar_test` DB, schema built by running
  `alembic upgrade head`, so the migration itself is under test. A `postgres` service is added to
  the CI python job. DB tests skip with a clear message if Postgres isn't reachable.
- **Routers are out of scope.** They keep serving `app/sample_data.py`; swapping them for queries
  is a follow-up. A1 only moves `main.py` onto the shared engine.

Per the Oct 8 note in the build plan: dense why-comments throughout; fill-in items get
scaffolded with guiding comments and the implementation is written, then walked through.

## Test approach (written first, watched fail, then made green)

Tests-first caveat: `test_db_metadata.py` imports `app.db`, which doesn't exist yet, so the first
red run is a *collection error* that interrupts the whole run, not a tidy assertion failure. That is
expected; the useful red state is reached once empty `app/db` stubs exist.

Three layers, in `apps/api/app/tests/`:

1. **`test_db_metadata.py` — no DB needed, runs everywhere.** Pure assertions on `Base.metadata`:
   - expected tables exist (`metro, venue, event, show, artist, show_artist, agent_run, audit_log`);
     deferred tables (`contributor, flag, genre, …`) do *not*;
   - the set of Postgres enum type names equals the **13** in `app/enums.py` mapped to the names in
     `data-model-initial.md` §4 (derived from `enums.py`, not a hard-coded count), and each column's
     enum labels equal the `enums.py` **values** (guards the pitfall that SQLAlchemy persists member
     *names* unless `values_callable` is set);
   - naming convention applied to PK / FK / CK / IX names (no UQ — A1 has no unique constraints);
   - `show` has the CHECK named `free_admission` (rendered `show_free_admission_check`); `show_artist`
     has the composite PK;
   - defaults are **`server_default`**, not Python-side `default`, so raw SQL and the worker get them
     too: `show.status`, `venue.fetch_strategy`, `audit_log.attempt_number`, `agent_run.started_at`,
     the timestamp columns;
   - (The `StepType` / `NodeNames` agreement test is **not** in A1: it would make `app/` import
     `agent_worker`, which `apps/api/AGENTS.md` forbids. It belongs with A4/A7 when worker tests are
     collected.)
2. **`test_db_schema.py` — real Postgres, migration under test.**
   - **Fixture design (the part that must be right):**
     1. *Fresh database every session.* After the safety guard below passes, the session fixture
        connects to the maintenance DB and runs `DROP DATABASE IF EXISTS calendar_test WITH (FORCE)`
        then `CREATE DATABASE calendar_test`. A leftover schema or `alembic_version` row from an
        older draft of the migration therefore can't break setup ("Can't locate revision", or the new
        `downgrade()` run against an old schema).
     2. *Round trip on every run, CI included.* On the fresh DB: `upgrade head` → `downgrade base` →
        assert only `alembic_version` remains and no `typtype = 'e'` types exist → `upgrade head`.
        This is what actually exercises the hand-written `downgrade()` (13 enum drops, venue column
        drops); `downgrade base` on an empty CI database would otherwise do nothing.
     3. *Injection mechanism.* The engine is async, but Alembic's `command.*` is sync and `env.py` skips
        its `asyncio.run` path when a connection is injected. So:
        `await conn.run_sync(lambda sc: (cfg.attributes.__setitem__("connection", sc), command.upgrade(cfg, "head")))`
        — an `AsyncConnection` can't go in `config.attributes`; the `run_sync` sync connection can.
        The `Config` is built from `Path(__file__)`, not the cwd; engine from `TEST_DATABASE_URL`,
        `NullPool`.
     4. *Transaction trap.* If the connection is already in a transaction when Alembic configures,
        Alembic's `begin_transaction()` degrades to `nullcontext()` and never commits, so the migrated
        schema stays invisible to other connections (`alembic/runtime/migration.py` `_in_external_transaction`).
        The `current_database()` guard therefore runs on a **separate** connection, and the fixture
        `await conn.commit()`s after each Alembic command. A why-comment says so. `migrations/env.py` is changed to honour the injected connection
     (see step 2) — otherwise it would overwrite the URL with `settings.database_url` and the
     downgrade would run against `calendar_dev`.
   - **Safety guard (runs before anything destructive, on its own connection):**
     `SELECT current_database() = 'calendar_test'` **and** the host is in
     `{localhost, 127.0.0.1, ::1}` whenever `TEST_DATABASE_URL` is *derived* from `DATABASE_URL`
     rather than set explicitly — `notes.md` records `DATABASE_URL` once being pointed at the
     production Neon database from this machine, and a name-only guard would happily create and wipe
     `calendar_test` there. The same guard is also covered by a plain test.
   - **Drift check:** `compare_metadata` with `compare_server_default=True` returns no diff. Stated
     limits: it compares enum types by name only, ignores CHECK constraints, and ignores index
     method. So the drift check is paired with **catalog assertions**: `pg_enum` labels per type, in
     order, equal `enums.py` values; the set of enum `pg_type` names (filtered to `typtype = 'e'` — `pg_type`
     also holds an array type `_<name>` per enum) equals the expected 13 (also catches orphans after
     the round trip); `pg_indexes.indexdef` contains `USING gin` for both
     `extra_metadata` indexes; `pg_constraint` contains `show_free_admission_check`.
   - **Constraint behaviour, asserting the specific constraint** (`exc.orig.sqlstate` 23514/23503/23505
     from SQLAlchemy's asyncpg adapter, and `constraint_name` from the native asyncpg exception at
     `exc.orig.__cause__` — not bare `IntegrityError`, so an unrelated NOT NULL failure can't satisfy
     it). **Tests use Core `insert` / `delete` statements, not ORM objects:** A1 declares **no ORM
     `relationship()`s** (no consumer yet), but even so, an ORM delete of a venue would null
     `show.venue_id` first (23502, not the FK error) and two same-PK `ShowArtist` objects fail in the
     identity map before any SQL runs:
     `free_admission=True` + a price → `show_free_admission_check`; delete a venue that has shows →
     `show_venue_id_fkey`; duplicate `show_artist` pair → `show_artist_pkey`. **Positive cases:**
     `free_admission=False` + price, and `NULL` + price, both insert (guards a CHECK written
     backwards or with COALESCE).
   - JSONB and `text[]` columns round-trip.
3. **`test_seed.py` — real Postgres.** `seed(session)` is called against an injected session. Seed
   once → 1 metro + 4 venues with expected names/URLs/`fetch_strategy` (values settled in step 3, so
   the test can be written first); seed twice → still 1 + 4.
   Never asserts ids (sequences don't roll back). Session fixture is an outer `conn.begin()` that is
   rolled back, with `AsyncSession(bind=conn, join_transaction_mode="create_savepoint")` so the seed
   may call `commit()`.

**Shared fixtures** live in a plugin module `app/testing/db.py`, loaded via `pytest_plugins` from
`apps/api/conftest.py` (rootdir), not in `app/tests/conftest.py` — so A7's `agent_worker/` tests can
reuse them unchanged. They provide: `TEST_DATABASE_URL` (derived from `DATABASE_URL` with db name
`calendar_test`, overridable by env); **creation of `calendar_test` itself** (connect to the `postgres`
maintenance DB via asyncpg, check `pg_database`, `CREATE DATABASE` if missing — no Makefile target, no
`docker compose exec`, so it works whether or not Docker is involved); the migrated-schema fixture;
the rolled-back session fixture. Tests never use `app.db.session.engine`.

**Skip vs fail:** DB tests skip with a clear message when Postgres is unreachable — *unless* `CI` is
set or `REQUIRE_DB=1`, in which case unreachable is a hard failure. Only connection-level errors
(`OSError`, `ConnectionRefusedError`, timeouts) count as "unreachable"; auth failures and a failing
`CREATE DATABASE` always fail the run. The Makefile `test` target runs `REQUIRE_DB=1 uv run pytest`,
so **`make check` — the "done" gate — can't go green with the whole DB suite skipped**; bare
`uv run pytest` stays skippable (with `-rs` so skips are visible). `TEST_DATABASE_URL` and
`REQUIRE_DB` are **shell/CI environment variables only**: not `Settings` fields (the app doesn't
consume them) and not in `.env` — `Settings` is `extra='forbid'`, so a stray `.env` key raises a
`ValidationError` app-wide, and pydantic-settings doesn't export `.env` values to `os.environ`
anyway. The maintenance URL is built with
`make_url(...).set(drivername="postgresql", database="postgres").render_as_string(hide_password=False)`
(plain `str(url)` masks the password; raw asyncpg rejects the `+asyncpg` scheme).

**pytest-asyncio config** (`pyproject.toml`): `asyncio_mode = "auto"`,
`asyncio_default_fixture_loop_scope = "session"`, `asyncio_default_test_loop_scope = "session"`.
asyncpg connections are bound to the loop that created them, and 1.x defaults to a loop per test, so
session scope + `NullPool` avoids "attached to a different loop"; leaving fixture scope unset also
raises a `PytestDeprecationWarning`. Existing `TestClient` route tests are untouched.

## Implementation steps

### 1. `app/db/` — shared package (written)

- `app/db/base.py`: `Base(DeclarativeBase)` with `MetaData(naming_convention=…)` using the
  `ix/uq/ck/fk/pk` templates from `docs/references/fastapi-style-guide.md` (`apps/api/AGENTS.md`
  says add it *now*, with the first models). The existing migration's constraints (`venue_pkey`,
  `venue_metro_id_fkey`) already match these names, so no rename churn.
- `app/db/session.py`: `engine = create_async_engine(settings.database_url, pool_pre_ping=True)` and
  `SessionFactory = async_sessionmaker(engine, expire_on_commit=False)`. No `get_db` dependency —
  nothing consumes it until the router swap ("don't build what has nothing to consume it"). `main.py`
  and the seed CLI use the engine/factory. **Known consequence, recorded in the build plan under A4:**
  this is an async-only, pooled engine created at import, but the worker's nodes are sync `def`s and
  A4 (before A6) writes `agent_run`/`audit_log` from all six. asyncpg connections are bound to the
  loop that made them, so a per-node `asyncio.run` against the shared engine fails on the second
  node ("attached to a different loop"). A4 must either make the nodes `async def` (LangGraph
  supports it; this pulls the A6 async decision forward) or bridge with a **separate `NullPool`
  engine per `asyncio.run`** — never reuse `app.db.session.engine` across loops. No sync engine is
  added now (no consumer; psycopg isn't a dependency).
- `app/db/types.py`: each Postgres enum type defined **once** as a module-level
  `Enum(E, name=..., values_callable=...)` and reused by every column (`age_restriction`, `setting`,
  `seating` are shared by `venue` and `show`; two inline copies could drift). Names match
  `data-model-initial.md` §4 exactly; a missed `name=` would silently become `artistformat`.
- `app/db/seed.py`: `async def seed(session: AsyncSession) -> None` (the testable logic, inside
  `app/` so mypy covers it); `scripts/seed.py` is only the CLI wrapper around it.
- No ORM `relationship()`s in A1: nothing reads them yet (the seed and tests use Core/explicit FKs).
  Add them with the first consumer (A5/A6 or the router swap), with cascade settings chosen then.
- `app/db/models/` (one module per area, re-exported from `__init__.py` so importing
  `app.db.models` registers every table on `Base.metadata` — required for Alembic):
  `calendar.py` (`Metro, Venue, Event, Show, Artist, ShowArtist`), `audit.py` (`AgentRun, AuditLog`).
- Timestamps: `created_at`/`updated_at` timestamptz, `server_default=func.now()`; `updated_at` also
  `onupdate=func.now()`. `data-model-initial.md` §1 puts these on every table "unless noted".
  Skipped on `show_artist` (pure join), `audit_log` (append-only; `created_at` only, as §3 specifies)
  and `agent_run` (its own `started_at`/`finished_at` are the lifecycle timestamps; a
  `created_at`/`updated_at` pair would duplicate them). Each skip is a recorded departure.
- `import datetime` and `Mapped[datetime.date]` throughout `calendar.py` — `Show.date` shadows the
  `date` name in a class body, the classic SQLAlchemy/mypy annotation trap.
- All defaults are `server_default` (see test approach). **Exception, stated plainly:** `updated_at`'s
  `onupdate=func.now()` is SQLAlchemy-side only — it fires on ORM/Core UPDATEs, not raw SQL. No
  trigger is added (no consumer for that guarantee).
- `show.date` keeps its name despite the `_date`-suffix naming rule in `apps/api/AGENTS.md` /
  the style guide: `data-model-initial.md` §2 and the API contract both call it `date`, and
  matching the spec wins. Recorded as a departure.
- Enum columns: `Enum(E, name="age_restriction", values_callable=lambda e: [m.value for m in e])`
  so labels are the lowercase values matching `app/enums.py` and the doc's §4.
- Column details, all from `data-model-initial.md` §2–3:
  - `venue`: add `photo_url, address (Text), phone_numbers/emails (ARRAY(Text)), website,
    age_restriction, serves_alcohol, venue_type, setting, seating, fetch_strategy (NOT NULL,
    default http), extra_metadata (JSONB) + GIN index`.
  - `artist`: `name, photo_url, website, hometown, format, repertoire, extra_metadata + GIN`.
  - `show`: `admission_advance/day` as `Numeric(10, 2)` (API sends `Decimal` as string, so keep an
    exact money type), CHECK `NOT (free_admission AND (advance IS NOT NULL OR day IS NOT NULL))`
    **with an explicit `name="free_admission"`** (the `ck` template `%(table_name)s_%(constraint_name)s_check`
    raises at definition time on an unnamed CheckConstraint) → `show_free_admission_check`.
    `status` `server_default='active'`. Index on `(venue_id, date)` — the reconcile composite-key
    lookup and calendar range queries both hit it; convention name `show_venue_id_idx` only names the
    first column, which is acceptable.
  - `show_artist`: composite PK `(show_id, artist_id)`, `start_time`, `sequence_number`.
  - `event`: `name, start_date, end_date` (derived, nullable).
  - `agent_run`: `venue_id` FK, `trigger`, `started_at` (NOT NULL, `server_default=now()`),
    `finished_at`. `audit_log`: §3 columns, `attempt_number` `server_default=1`, `entity_id`
    deliberately **not** an FK (the doc says so), `confidence` `Numeric(4, 3)` (the worker uses
    `float`; A4 converts), `snapshot_key` **kept** (nullable; user decision after round 2 — the build plan's A4 already says it "can stay null", and R2 will fill it, so the column is the documented hook; an exception to the omit rule, deliberately), and an
    index on `audit_log(run_id)` — Postgres doesn't index FK columns, and A4's "everything in run N"
    query is its consumer.
  - **Departures from `data-model-initial.md` to record there and in the migration docstring:**
    `agent_run.triggered_by` and `audit_log.contributor_id` are **omitted** — first and decisively
    because their FK target (`contributor`) is deferred, so they can't be created as specified;
    `audit_log.session_hash` is **omitted** because it stays NULL for all of v1 (user edits and the
    MCP admin server are deferred, build plan §8) and an always-empty column is worse than its absence;
    adding a nullable column later is a trivial migration. `audit_log.snapshot_key` is the one
    always-NULL column that is **kept**, by user decision: build plan A4 explicitly expects it to
    exist and stay null until R2 lands. No build-plan edit needed. Also: `Numeric(10, 2)` / `Numeric(4, 3)` precisions, the extra `show` and
    `audit_log` indexes, and no timestamps on `agent_run`.
- `app/main.py`: delete the local `create_async_engine`, import `engine` from `app.db.session`.
  `/health/db` behaviour unchanged. (There is no `/health/db` test — only `/health` is covered — so
  verification step 5 checks it by hand.)

### 2. Alembic (fill-in)

- `migrations/env.py`: `from app.db.base import Base`, `import app.db.models  # noqa: F401`,
  `target_metadata = Base.metadata`. **Honour an injected connection:** if
  `config.attributes.get("connection")` is set, run `do_run_migrations(connection)` directly and
  skip both the `settings.database_url` override and the `asyncio.run` path (the tests need this —
  see test approach); skip `fileConfig()` in that case too, since it would disable existing loggers
  (`caplog`, app loggers) for the rest of the pytest session. Normal CLI use is unchanged. Pass
  `compare_server_default=True` to both `context.configure` calls (off by default, and it's what
  makes autogenerate notice default drift). `compare_type=True` is already Alembic's default since
  1.12, so it is *not* added. Dense comments on why the models import is load-bearing.
- `make migration m="core calendar and audit tables"` → **read the generated file line by line**
  and fix by hand what autogenerate gets wrong:
  - enum types: **Alembic's `add_column` never creates a Postgres enum type** — only `create_table`
    does — so `venue_type` and `fetch_strategy` (used only on the existing `venue` table) would fail
    with `type does not exist`, and `age_restriction`/`setting`/`seating` would work only by luck of
    operation order. Hand-write the fix: at the top of `upgrade()` create all **13** enum types
    explicitly (`postgresql.ENUM(..., name=...).create(op.get_bind())`), reference them in columns with
    `postgresql.ENUM(name=..., create_type=False)`, and drop all 13 at the end of `downgrade()` after
    the tables. (Goes in `notes.md` — it is exactly the kind of thing that bites.)
  - table creation order respects FKs (`metro → venue → event → show → …`);
  - `venue` is an **existing** table: expect `add_column` ops, not `create_table`; the new NOT NULL
    column `fetch_strategy` needs a `server_default` or it fails on non-empty tables;
  - GIN indexes (`postgresql_using="gin"`) and the CHECK constraint name come through correctly;
  - `down_revision = "db2aedec0bb9"`.
  Keep the file's style (docstring explaining scope and the deliberate departures).
- Apply to `calendar_dev` with `make migrate`; confirm with `make db-shell` (`\dT`, `\d show`).

### 3. Seed (written) — `apps/api/scripts/seed.py`, `make seed`

- Logic is `seed(session)` in `app/db/seed.py`; `scripts/seed.py` is a thin CLI wrapper run as
  `uv run python -m scripts.seed` (same `-m` pattern as `dump_openapi`).
- Creates Minneapolis/St. Paul (`America/Chicago`) and the four venues **in the same order as
  `app/sample_data.py`** so ids line up with the frontend fixtures (`api-contract.md` says both
  describe "one world"). URLs are each fixture's `saved from url` / canonical tag:

  | id | Venue | calendar_url |
  |---|---|---|
  | 1 | The White Squirrel Bar | `https://whitesquirrelbar.com/calendar/` |
  | 2 | The Midway Saloon | `https://www.themidwaysaloon.com/events` |
  | 3 | Zhora Darling | `https://www.zhoradarling.com/events` |
  | 4 | The Terminal Bar | `https://terminalbarmn.com/live-music/` |

  `fetch_strategy`, settled from the saved fixtures (`grep` for pagination patterns):

  | Venue | Value | Evidence |
  |---|---|---|
  | The White Squirrel Bar | `http` | The Events Calendar `tribe-events-c-nav` "Next Events" — plain URL pagination |
  | The Midway Saloon | `http` | no "load more" or JS pagination pattern found in the fixture |
  | Zhora Darling | `browser` | Dice widget `<button type="button" class="dice_load-more">Load more</button>` — click-driven, per `data-model-initial.md` §2 / `enums.py` `FetchStrategy.BROWSER` |
  | The Terminal Bar | `http` | no pagination pattern; shows are image-embedded (deferred, build plan §8) |

  Consequence, commented in the seed: only the `http` path is implemented this phase
  (build plan §8), so Zhora extracts only its first page until Playwright lands. Midway's `http` is
  "nothing found", not proof. The seed test asserts these four values.
- Idempotent: look up metro by name and venue by `(metro_id, name)`; insert only if missing. No new
  unique constraint just for the seed.
- Seed contains only metro + venues (build plan A1) — no fake shows/artists; real rows come from the
  agent.

### 4. Cleanup (v0.1-G1)

- `agent_worker/nodes.py`: delete the `FIXTURES_DIR = ...` TODO block. Verified: nothing reads
  `nodes.FIXTURES_DIR`; only `eval/run_eval.py` defines (and uses) its own — `local_test.py` does
  not. (Build plan marks this item [fill-in]; it is a one-line deletion, so it will be done and noted
  rather than scaffolded.)

### 5. Wiring

- `Makefile`: add a `seed` target (+ `.PHONY`), and run `seed` after `migrate` in `setup` and
  `db-reset` so a fresh checkout can run end to end (v0.1-G13's point). The `test` target becomes
  `REQUIRE_DB=1 uv run pytest` (see skip-vs-fail). No test-DB target: the fixtures create
  `calendar_test` themselves, so nothing depends on `docker compose exec`.
- `.github/workflows/ci.yml` python job: add `services: postgres:18` with a health check and
  `ports: ["5432:5432"]` (the job runs on the host, not in a container), set `TEST_DATABASE_URL`
  explicitly (the fixture creates the database itself), update the stale "nothing talks to a real
  database" comment at lines 16-18. `contract` job unchanged.
- `apps/api/.env.example`: a comment-only note that `TEST_DATABASE_URL` / `REQUIRE_DB` are
  shell/CI variables and must **not** be placed in `.env`, with the `extra='forbid'` reason.
  `pyproject.toml`: the three pytest-asyncio settings. New `apps/api/conftest.py` with `pytest_plugins`.
- Docs: tick the A1 boxes in `alpha-build-plan.md`; **add a build-plan item for the router swap** (with
  the `httpx.AsyncClient` test migration) and repoint the stale "A1 swaps the bodies" claims —
  `alpha-build-plan.md` §4, comments in `app/routers/{shows,venues,artists}.py`, `app/sample_data.py`,
  `app/tests/test_routers.py`, `apps/api/AGENTS.md` lines 37 and 50, and `api-contract.md` lines
  33-39 (every route says "A-track, after A1" — now after the router-swap item); correct
  `app/enums.py` lines 15-16 ("SQLAlchemy stores the value rather than the member name" is false
  without `values_callable`) and lines 19-21 (`social_platform` is omitted too, not only
  `submission_status`); add the async-engine/sync-nodes
  note under A4; record the departures in `data-model-initial.md`; add to `docs/dev/notes.md`
  `values_callable`, `add_column` not creating enums, and the env.py/URL-override trap.

## Critical files

- New: `apps/api/app/db/{__init__,base,types,session,seed}.py`, `app/db/models/{__init__,calendar,audit}.py`,
  `apps/api/scripts/seed.py`, `apps/api/conftest.py`, `app/testing/db.py`,
  `app/tests/{test_db_metadata,test_db_schema,test_seed}.py`,
  `migrations/versions/<date>_<rev>_core_calendar_and_audit_tables.py`
- Modified: `apps/api/migrations/env.py`, `apps/api/app/main.py`, `apps/api/agent_worker/nodes.py`,
  `apps/api/pyproject.toml`, `Makefile`, `.github/workflows/ci.yml`, `apps/api/.env.example`, docs above
- Reused as-is: `app/enums.py`, `app/config.py` (`settings.database_url`), `app/sample_data.py`
  (venue order/names), docker-compose Postgres.

## Verification

1. Start Docker Desktop (not running when this was written — `docker ps` failed), `make db-up db-wait`.
2. Tests first: write the three test modules plus empty `app/db` stubs, run
   `cd apps/api && uv run pytest`, confirm they fail for the right reason (no models / no tables),
   then implement until green. Confirm `current_database()` guard passes before the first downgrade.
3. `make migrate` on `calendar_dev`; `make seed` twice; `make db-shell` → `select id,name from venue;`
   shows 4 rows, ids 1–4; `\dT` shows the enum types; `\d show` shows the CHECK and FKs.
4. Migration round trip by hand: `uv run alembic downgrade base && uv run alembic upgrade head`.
5. `make dev`, hit `/health/db` → still `db connection up`, and `/shows` etc. unchanged.
6. `make check` (ruff + eslint, mypy + tsc, pytest + vitest, contract-check) green, with the DB suite
   actually running rather than skipped — contract-check must be a no-op
   since schemas/routers are untouched.

## Review

Reviewer: Claude Opus, read-only, against the cited docs and the code. 24 findings (2 blocker,
14 should-fix, 8 nit). Facts I re-checked myself before accepting them: 13 enums in `enums.py`
(finding 3), `local_test.py` defines no `FIXTURES_DIR` (16), `migrations/env.py:18` overrides the URL
unconditionally (1). Everything else was accepted on the reviewer's cited evidence and will be
confirmed by the tests failing/passing for the stated reason.

| # | Sev | Finding | Resolution |
|---|---|---|---|
| 1 | blocker | env.py always uses `settings.database_url`, so migration tests (incl. `downgrade base`) would hit `calendar_dev` | **Fixed.** env.py honours `config.attributes["connection"]`; fixture injects a `calendar_test` connection; `current_database()` guard test + in-fixture assertion |
| 2 | blocker | `add_column` doesn't create enum types → migration fails | **Fixed.** Explicit create of all 13 types at top of `upgrade()`, `create_type=False` in columns, explicit drop in `downgrade()`; also goes in `notes.md` |
| 3 | should | 13 enum types, not 12 | **Fixed**; test derives the list from `enums.py` |
| 4 | should | `compare_metadata` doesn't compare enum labels, CHECKs, index method, or server defaults | **Fixed.** `compare_server_default=True` + catalog assertions (`pg_enum`, `pg_type`, `pg_indexes`, `pg_constraint`); plan no longer claims drift check covers enums |
| 5 | should | Bare `IntegrityError` assertions can pass for the wrong reason | **Fixed.** Assert sqlstate + constraint name; add positive cases (`False`+price, `NULL`+price) |
| 6 | should | CHECK must be explicitly named under the `ck` template; no UQ in A1 | **Fixed.** `name="free_admission"` → `show_free_admission_check`; UQ dropped from the naming test |
| 7 | should | Alembic's `asyncio.run` + pytest-asyncio loop scoping + stale asyncpg type cache | **Fixed.** Injected connection (no `asyncio.run`), session loop scopes, `NullPool`, never the app engine |
| 8 | should | Session fixture order-dependent; stale schema if left at head | **Fixed.** Fixture does `downgrade base` → assert no enums → `upgrade head`; no `DROP SCHEMA CASCADE` |
| 9 | should | Seed test needs an injectable session and savepoint mode | **Fixed.** `seed(session)` in `app/db/seed.py` (mypy-covered), CLI wrapper in `scripts/`; `create_savepoint` fixture; no id assertions |
| 10 | should | Skip-if-unreachable can hide a broken CI service | **Fixed.** Hard fail when `CI` or `REQUIRE_DB=1` |
| 11 | should | Makefile `docker compose exec` target fails when Docker is off; no `CREATE DATABASE IF NOT EXISTS` | **Fixed.** `conftest` creates `calendar_test` via the maintenance DB; Makefile target dropped; CI uses `POSTGRES_DB` |
| 12 | should | `compare_type=True` is already the default | **Fixed.** Dropped; `compare_server_default=True` added instead |
| 13 | should | Deferring the router swap leaves stale "A1 swaps the bodies" claims | **Fixed.** Build-plan item added; listed comments/docs repointed |
| 14 | should | Async-only engine vs sync worker nodes; A4 precedes A6 | **Accepted as a recorded consequence**, noted in step 1 and under A4; no sync engine added |
| 15 | should | `triggered_by`, `contributor_id`, `session_hash` placeholders violate "no always-empty fields" | **Accepted — omit them**, record as a departure from `data-model-initial.md` §3. This reverses the earlier draft; **flagged to the user as overridable.** `snapshot_key` kept (A4 expects it) |
| 16 | nit | `local_test.py` doesn't define `FIXTURES_DIR` | **Fixed**; also noted the item is [fill-in] but trivial |
| 17 | nit | Shared enum types defined inline twice | **Fixed.** `app/db/types.py`, one object per type |
| 18 | nit | Defaults must be `server_default`; `started_at` / `attempt_number` / `agent_run` timestamps unspecified | **Fixed.** All stated; metadata test checks `server_default` |
| 19 | nit | Unrecorded departures (`Numeric` precision, extra indexes, `confidence` type) | **Fixed.** Recorded; `audit_log(run_id)` index added (A4 consumer) |
| 20 | nit | `Show.date` shadows `datetime.date` | **Fixed.** `import datetime` |
| 21 | nit | `fileConfig()` disables loggers in tests | **Fixed.** Skipped when a connection is injected; Config built from `Path(__file__)` |
| 22 | nit | Fixtures in `app/tests/conftest.py` won't reach A7's `agent_worker/` tests | **Fixed.** Plugin module `app/testing/db.py` via root `conftest.py` |
| 23 | nit | `fetch_strategy='http'` for all four is unverified | **Fixed.** Check each fixture while writing the seed; comment where undeterminable |
| 24 | nit | `seed` in `setup`/`db-reset`; collection-error caveat; StepType/NodeNames test pulled forward | **Fixed.** All three noted/added |

Rejected: none.

### Round 2

Reviewer: a second model, run by the user from a prompt generated for the purpose; checked against
installed package source (alembic 1.19.1, SQLAlchemy 2.0.52, asyncpg 0.31.0, pytest-asyncio 1.4.0,
pydantic-settings). 16 findings: 0 blockers, 9 should-fix, 7 nits. Verdict: proceed after fixes. I
re-checked #8 and #5's Makefile claim myself (the Zhora fixture contains `dice_load-more`;
`Makefile:162-163` `test` runs bare `uv run pytest`).

| # | Sev | Finding | Resolution |
|---|---|---|---|
| 1 | should | Round trip never runs `downgrade()` in CI (empty DB); leftover local schema breaks setup | **Fixed.** Drop/create `calendar_test` per session (`WITH (FORCE)`), then `upgrade` → `downgrade base` → assert clean → `upgrade` |
| 2 | should | Injection needs `run_sync`; transaction trap (`nullcontext`, uncommitted schema) | **Fixed.** Mechanism stated; guard on a separate connection; commit after each command |
| 3 | should | `TEST_DATABASE_URL`/`REQUIRE_DB` in `.env` breaks `Settings` (`extra='forbid'`) and wouldn't reach `os.environ` | **Fixed.** Shell/CI env only; `.env.example` warns; not `Settings` fields |
| 4 | should | Guard checks db name, not host (Neon incident in `notes.md`); maintenance URL pitfalls; error classification | **Fixed.** Host allow-list when derived; `make_url(...).render_as_string(hide_password=False)`; only connection errors skip |
| 5 | should | `make check` can pass with every DB test skipped | **Fixed.** `test` target sets `REQUIRE_DB=1`; bare pytest uses `-rs` |
| 6 | should | ORM delete / identity map hit ORM behaviour, not the DB constraints; relationships undecided | **Fixed.** Core statements; no `relationship()`s in A1; `sqlstate` vs `__cause__.constraint_name` noted |
| 7 | should | A4 "bridge with `asyncio.run`" fails on the shared pooled engine | **Fixed.** Note rewritten: `async def` nodes, or a separate `NullPool` engine per `asyncio.run` |
| 8 | should | `fetch_strategy` left to decide while writing the seed, but tests come first | **Fixed.** Settled now: Zhora `browser` (verified `dice_load-more` button), others `http` |
| 9 | should | Stale refs: `enums.py` comments, `api-contract.md` "after A1" | **Fixed.** Added to the docs list |
| 10 | nit | `StepType`/`NodeNames` test makes `app/` import `agent_worker` | **Accepted.** Removed from A1; belongs to A4/A7 |
| 11 | nit | `onupdate` isn't a server default | **Fixed.** Stated in the model comment; no trigger |
| 12 | nit | Omitted-columns reasoning inconsistent (`snapshot_key`) | **Partly accepted.** FK-target-deferred now leads the rationale for the two FK columns. I proposed omitting `snapshot_key` too; **the user chose to keep it**, so it stays as a documented exception |
| 13 | nit | `show.date` vs `_date` suffix rule | **Fixed.** Recorded as a departure (spec wins) |
| 14 | nit | Enum catalog check must filter array types | **Fixed.** `typtype = 'e'` |
| 15 | nit | CI service needs `ports` | **Fixed.** |
| 16 | nit | `/health/db` has no test; `make check` also runs eslint/tsc/vitest | **Fixed.** Both corrected |

Rejected: none.

## Implementation notes

Built tests-first: the first run was a collection error (no `app.db`), then empty stubs gave 18 real
failures, then the models turned them green. Because everything passed at once, three mutations were
applied to confirm the DB tests have teeth, each failing for the intended reason: `downgrade()` not
dropping enum types (round-trip assertion), `upgrade()` not pre-creating them (`type "artist_format"
does not exist`), and the CHECK constraint renamed (two failures).

Differences from the plan as written:

- **Manual migration round trip on `calendar_dev` was not done** (verification step 4). The test
  fixture does `upgrade → downgrade → upgrade` on `calendar_test` every run, and a manual
  downgrade/upgrade on the dev database would have reset the seeded `fetch_strategy` values (the seed
  is insert-only), for no extra coverage.
- **Seed ids were checked by hand on `calendar_dev`**, as planned: ids 1-4 match `app/sample_data.py`.
- **`pool_pre_ping` comment moved** from `app/main.py` to `app/db/session.py` with the engine it
  documents.
- **ruff in this repo enforces more than the defaults** (e.g. `UP041`); `ruff check --fix` handled the
  auto-fixable ones.
- `test_db_schema.py` imports its expected column/enum tables from `test_db_metadata.py`, so the two
  layers can't disagree about what the spec says.
- A1b (routers onto the database) was added to `alpha-build-plan.md`; stale "A1 swaps the bodies"
  comments and the `api-contract.md` route table now point at A1b.

## Review of the implementation

A third reviewer model (different from the author) reviewed the finished code, ran
`ruff` / `mypy` / `pytest` (61 passed at the time), and probed the test-database guard with
`make_url` and asyncpg's source. 0 blockers, 3 should-fix, 6 nits. Verdict: merge after fixes.
Where a finding was testable, a failing test was written before the fix (#2, #3, #7); #1 was
confirmed with `git check-ignore`.

| # | Sev | Finding | Resolution |
|---|---|---|---|
| 1 | should | `apps/api/.env.example` is gitignored (`.env*`) and was never committed — `make setup` breaks on a fresh clone, and A1's warning never ships | **Fixed.** `!.env.example` in `apps/api/.gitignore`. Contains only local placeholders. *Not committed — that's the user's call* |
| 2 | should | Hand-written `ENUM.create()` defaults to `checkfirst=True`, silently adopting an orphaned type | **Fixed.** `checkfirst=False` on create and drop; new test `test_upgrade_fails_loudly_if_an_enum_type_already_exists` (red first); `notes.md` corrected |
| 3 | should | `onupdate=func.now()` leaves `updated_at` expired after an ORM UPDATE → `MissingGreenlet` under AsyncSession (A6 trap) | **Fixed.** `eager_defaults=True` on `TimestampMixin`; new test `test_updated_at_is_readable_after_an_orm_update` reproduced the crash first |
| 4 | nit | `app/testing/db.py` docstring described the old `env.py` | **Fixed** |
| 5 | nit | Plan claimed bare `pytest` prints skips; no `addopts` | **Fixed.** `addopts = "-rs"` |
| 6 | nit | Fixtures are post-JS DOM captures, so Midway's `http` is unverified | **Fixed.** Comment says so; confirm with a raw `httpx.get` in A3/A4 |
| 7 | nit | Enum-label tests compared against `enums.py`, so a wrong label there would pass | **Fixed.** `EXPECTED_ENUM_LABELS` written out literally from data-model §4; `enums.py`, the models and the DB are all checked against it |
| 8 | nit | `seed()` committed a session it doesn't own | **Fixed.** `seed()` flushes; `scripts/seed.py` commits |
| 9 | nit | `DROP DATABASE ... WITH (FORCE)` kills a concurrent pytest run | **Fixed.** Comment in `app/testing/db.py` and a line in `apps/api/AGENTS.md` |

Rejected: none. Suite after fixes: 64 passed (3 new tests), ruff and mypy clean.

