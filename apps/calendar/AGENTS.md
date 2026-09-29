<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

---

<!--
Everything below is hand-written and sits OUTSIDE the managed block above.
`next dev` rewrites only the region between its BEGIN/END markers, so content
here survives. Don't move it above the END marker.
-->

# apps/calendar — the public Next.js app

**Read `docs/references/nextjs-style-guide.md` before non-trivial work here.** It's written
against Next.js 16.3 / React 19.2 / Tailwind 4, all of which changed recently enough that
training-data defaults are frequently wrong. Its Anti-patterns table is the review checklist.
The block above says the same thing about `node_modules/next/dist/docs/`, and means it.

## Commands

From the repo root: `make dev` (with the API) or `make web` (alone). Port 3000.

```
pnpm --filter calendar dev
pnpm lint            # eslint directly — `next lint` was REMOVED in 16, don't add it back
pnpm check-types     # next typegen && tsc --noEmit
```

Run `pnpm check-types` after adding or renaming a dynamic route segment — `next typegen`
regenerates the `PageProps`/`LayoutProps` helpers.

## The API contract

`lib/api-types.ts` is **generated** from FastAPI's OpenAPI schema. Never edit it. Run
`make types` from the repo root after the backend's models change; `make contract-check`
fails if it's stale.

Import from `lib/types.ts`, which aliases the generated shapes to readable names. Three
things about them:

- Dates and times are `string`. Parse with `Temporal.PlainDate`/`PlainTime`, never
  `new Date("2026-09-28")` — that parses as UTC midnight and renders as the 27th anywhere
  west of Greenwich.
- `Decimal` is `string` ("15.00"), not a number. Format it; don't `parseFloat` it.
- Fields with Python-side defaults generate as optional, so they're `T | null | undefined`.

`lib/fixtures/*.json` exists for tests that shouldn't need a running backend. Prefer real
HTTP against the API for anything else — the routes exist and serve the same data.

## Rules that bite most often here

- **Server Components by default.** `"use client"` goes on the smallest interactive leaf,
  never on a page or layout to make one widget work.
- **No `useEffect` + `fetch` for initial data.** Fetch in the Server Component and pass it
  down. That's the single most common stale-training-data pattern.
- **`params` and `searchParams` are Promises.** `const { slug } = await props.params`.
  No synchronous fallback exists in 16.
- **`fetch` is not cached by default** (since 15). Opt in: `{ cache: "force-cache",
  next: { revalidate, tags } }`. This repo is on the **default** caching model —
  `"use cache"` is a Cache Components feature and errors without the flag.
- **Filter and view state goes in URL search params**, not component state
  (`arch-initial.md` §4). It's what makes a filtered calendar shareable and
  server-renderable.
- **`proxy.ts`, not `middleware.ts`** — renamed in 16.
- **Generate shadcn components** with `pnpm dlx shadcn@latest add <name>`; don't hand-roll
  something that has to match the CVA setup `components.json` expects. Shared primitives go
  in `packages/ui` and import as `@repo/ui/components/<name>`.

## Known state and open cleanups

This app is still largely the `create-turbo` template with a health check attached.
Milestone B1 in `docs/dev/v1-build-plan.md` strips it. Until then, expect:

- CSS Modules (`page.module.css`) and Tailwind both active — B1 picks Tailwind.
- Three competing button components — B1 keeps the shadcn one in `packages/ui`.
- `metadata.title` still reads "Create Next App".

**Not done, and the style guide asks for it:** the `server-only` package on any module
touching `process.env` beyond `NEXT_PUBLIC_*` — `API_BASE_URL` is server-only and nothing
enforces that at build time yet. Add it in B2 along with the API client, not before; it
needs a consumer.
