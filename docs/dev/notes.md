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
