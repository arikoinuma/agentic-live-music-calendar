# Calendar (`apps/calendar`)

The public Next.js app for the Minneapolis/St. Paul live music calendar. It reads shows from the FastAPI service in `apps/api` and renders them.

## Running it

From the repo root, `make dev` starts Postgres, the API and this app together (this app on port 3000). First-time setup is in `docs/dev/env-setup.md`.

## Where to look

- `app/` — routes and pages
- `lib/` — data access, date handling and formatting
- `lib/api-types.ts` — generated from the API schemas. Do not edit by hand; regenerate with `make types`.

`AGENTS.md` describes the repo conventions, and `docs/references/nextjs-style-guide.md` describes the Next.js rules this app follows.
