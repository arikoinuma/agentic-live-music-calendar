# Next.js Best Practices for AI Agents

A machine-readable companion to the FastAPI guide (see
[fastapi-style-guide.md](./fastapi-style-guide.md)) for AI coding agents working in this
repo's Next.js apps (`apps/calendar`, `apps/admin`). Same rules, restructured for fast
pattern matching: version pins, Do/Don't blocks, anti-patterns, and a quick-reference table.

No single canonical "Next.js style guide" exists the way FastAPI's does — this file was
assembled from the official Next.js/Vercel docs (App Router, Cache Components, Data
Security guide) as of Next.js 16.3, cross-checked against this repo's actual
`package.json`/`next.config.js`/`components.json` files, and re-verified against the live 16.3.6
docs on 2026-09-28. Treat the linked docs pages (or the copies bundled in `node_modules/next/dist/docs/`)
as the source of truth if something here goes stale.

> **Next.js 16 is a large departure from the "classic" App Router advice you may know from
> training data (2023–2024 era blog posts, tutorials).** `fetch` is no longer cached by default,
> an opt-in Cache Components model (`"use cache"`) sits alongside the older `fetch`/`unstable_cache`
> one, `params`/`searchParams`/`cookies()`/`headers()` are always async, `middleware.ts` is now
> `proxy.ts`, and Turbopack + the React Compiler are stable. If you're unsure whether a pattern
> still applies, check the compatibility matrix and breaking-changes notes below before writing code.

> **Version-matched docs are on disk.** Next.js 16.2+ ships its own docs at
> `node_modules/next/dist/docs/` (resolve from the app directory, not the monorepo root — `next` is
> installed under `apps/*`). Read those before writing code you're unsure about; they beat both this
> file and training data. `npx @next/codemod@canary agents-md` wires an `AGENTS.md` block that points
> agents at them.

## Compatibility Matrix

Pin to these versions or newer — matches this repo's `apps/calendar/package.json` and
`apps/admin/package.json`. Examples in this file assume them.

| Dependency    | Minimum   | Notes                                                              |
|---------------|-----------|---------------------------------------------------------------------|
| Node.js       | 20.9      | Next.js 16 minimum (Node 18 is no longer supported)                |
| Next.js       | 16.3      | Turbopack default, Cache Components, `proxy.ts`, `next lint` removed |
| React         | 19.2      | View Transitions, `useEffectEvent`, `<Activity />`                 |
| TypeScript    | 5.9       | Next.js 16 minimum is 5.1                                           |
| Tailwind CSS  | 4.3       | CSS-first config via `@theme`, no `tailwind.config.js` needed       |
| pnpm          | 9         | Workspace-managed monorepo (`pnpm-workspace.yaml`)                  |
| Turborepo     | 2.10      | Task graph in `turbo.json`; `apps/*` depend on `packages/*`         |
| shadcn        | 4.x       | `components.json` style `base-nova`, icons via `lucide-react`       |

Browser floor also moved in 16: Chrome/Edge/Firefox 111+, Safari 16.4+.

> The root `package.json` still declares `engines.node: ">=18"`, which contradicts the Next.js 16
> floor of 20.9. Bump it to `>=20.9` rather than trusting it.

## Project Structure

This is a pnpm/Turborepo monorepo. Apps consume shared packages — don't duplicate UI,
ESLint, or TS config across apps.

```
apps/
├── calendar/            # Public-facing Next.js app (port 3000)
│   ├── app/              # App Router root — routes, layouts, route handlers
│   ├── components/       # App-local components (shadcn output lands in components/ui)
│   ├── lib/               # App-local utilities (lib/utils.ts — cn() helper, etc.)
│   ├── components.json    # shadcn config — aliases point at @/components, @repo/ui
│   └── next.config.js
├── admin/                # Internal admin app (port 3001), same shape as calendar
└── api/                  # FastAPI backend — see fastapi-style-guide.md
packages/
├── ui/                   # @repo/ui — shared shadcn/base component library
│   └── src/               # components/ -> @repo/ui/components/<name> (one file per component)
├── eslint-config/         # @repo/eslint-config — base.js, next.js, react-internal.js
└── typescript-config/     # @repo/typescript-config — base/nextjs/react-library tsconfig
```

### Route-segment (colocation) structure

Inside `apps/{calendar,admin}/app`, Next.js only treats `page.tsx`, `layout.tsx`,
`route.ts`, and the other special filenames as routable — everything else can be
colocated safely.

```
app/
├── layout.tsx            # Root layout — Server Component by default
├── page.tsx
├── globals.css
├── (marketing)/           # Route group — organizes URLs without adding a path segment
│   └── about/page.tsx
├── venues/
│   ├── page.tsx
│   ├── [slug]/
│   │   ├── page.tsx        # params: Promise<{ slug: string }>
│   │   └── _components/     # Private folder (underscore-prefixed) — not routable
│   └── loading.tsx          # Suspense boundary shown while the segment streams in
├── api/
│   └── health/route.ts     # Route Handler — GET/POST/etc. exports
└── proxy.ts               # Formerly middleware.ts (see Routing below)
```

- Prefix implementation-detail folders with `_` (e.g. `_components/`, `_lib/`) so they're
  never mistaken for routes.
- Use route groups `(name)` to organize without affecting the URL, e.g. splitting
  authenticated vs public layouts.
- Cross-package imports go through the workspace alias, not relative paths:
  `import { Button } from "@repo/ui/components/button"`, not
  `../../../packages/ui/src/components/button`.

## Server vs Client Components

### Decision rule

| Component needs...                                             | Use                    |
|------------------------------------------------------------------|-------------------------|
| Data fetching, secrets/env vars, DB access, large deps           | Server Component (default) |
| `useState`, `useEffect`, event handlers (`onClick`), browser APIs | `"use client"`          |
| Both                                                              | Server Component parent + small Client Component leaf, composed via props/children |

**Default to Server Components.** Add `"use client"` only to the smallest leaf that
actually needs interactivity — not to the page, not to a whole layout.

### Do / Don't

```tsx
// DON'T — marks the entire page a Client Component to use one button's onClick
"use client";

export default function VenuePage({ venue }: { venue: Venue }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <h1>{venue.name}</h1>          {/* now ships to the client for no reason */}
      <p>{venue.description}</p>
      <button onClick={() => setOpen(true)}>Details</button>
    </div>
  );
}

// DO — keep the page a Server Component, isolate interactivity in a leaf
// app/venues/[slug]/page.tsx
export default async function VenuePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const venue = await getVenue(slug);
  return (
    <div>
      <h1>{venue.name}</h1>
      <p>{venue.description}</p>
      <DetailsButton />                {/* only this ships JS */}
    </div>
  );
}

// app/venues/[slug]/_components/details-button.tsx
"use client";
export function DetailsButton() {
  const [open, setOpen] = useState(false);
  return <button onClick={() => setOpen(true)}>Details</button>;
}
```

### Composition: pass Server Components as `children`, don't import client into server needlessly

```tsx
// DO — a Client Component that needs client state (e.g. a modal) still renders
// server-fetched content via children/props, without pulling data-fetching into the client
"use client";
export function Modal({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return open ? <div className="modal">{children}</div> : null;
}

// app/page.tsx (Server Component)
import { Modal } from "./_components/modal";
import { EventList } from "./_components/event-list"; // async Server Component

export default function Page() {
  return (
    <Modal>
      <EventList /> {/* fetched on the server, passed through, not re-fetched client-side */}
    </Modal>
  );
}
```

> Everything a `"use client"` file **imports and directly renders** joins the client
> bundle. Server Components passed in as `children`/props do not — they're rendered on
> the server and streamed in as output. This is the lever for keeping bundles small.

## Data Fetching & Caching

Next.js 16 has **two caching models**, and which one applies depends on one config flag. Pick the
wrong one and the code either fails to build or silently doesn't cache.

|                        | Default — **what this repo is on today**                                                                 | Cache Components (`cacheComponents: true`)                                                     |
|------------------------|-----------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------|
| Reference              | [Caching and Revalidating (Previous Model)](https://nextjs.org/docs/app/guides/caching-without-cache-components) | [Caching](https://nextjs.org/docs/app/getting-started/caching)                                   |
| Opt into caching with  | `fetch(..., { cache: 'force-cache' })`, `unstable_cache`, route segment config                             | `"use cache"` + `cacheLife`                                                                     |
| `"use cache"`          | **unavailable** — it's a Cache Components feature and errors without the flag                             | the primary API                                                                                 |
| Rendering              | `dynamic = 'auto'`: a route prerenders at build until a request-time API or uncached fetch is reached      | Partial Prerendering: every route must produce a static shell; uncached/runtime reads go in `<Suspense>` |

What is **not** true — and is the most common stale-training-data claim — is that "Next.js 16 caches
nothing" or "everything is dynamic." Only `fetch` lost its implicit cache (that happened in 15). In
both models Next.js still prerenders as much of each route as it can at build time.

Enabling `cacheComponents` is not a rename-only change: it turns uncached data outside `<Suspense>`
into a build error and replaces the old PPR flag (`experimental.ppr` and `experimental_ppr` are gone
in 16). Do it deliberately, with the
[migration guide](https://nextjs.org/docs/app/guides/migrating-to-cache-components) — not as a
drive-by change.

```ts
// next.config.ts — top level in 16 (experimental.dynamicIO / experimental.useCache were removed)
const nextConfig = {
  cacheComponents: true,
};
export default nextConfig;
```

### Model A — default (no `cacheComponents`): what to use in this repo today

```tsx
// Cache a fetch: opt in explicitly, tag it for invalidation
const res = await fetch(`${process.env.API_BASE_URL}/venues`, {
  cache: "force-cache",
  next: { revalidate: 3600, tags: ["venues"] },
});

// Cache a non-fetch call (DB/ORM/SDK): unstable_cache — still the supported API in this model
import { unstable_cache } from "next/cache";
export const getVenue = unstable_cache(
  async (slug: string) => db.venues.findBySlug(slug),
  ["venue"],                          // key prefix
  { tags: ["venues"], revalidate: 3600 },
);

// Dedupe within one render pass (no cross-request caching) — for ORM calls fetch() can't memoize
import { cache } from "react";
export const getCurrentUser = cache(async () => decrypt((await cookies()).get("session")?.value));
```

- Route segment config still exists and is the coarse lever: `export const dynamic = 'auto' |
  'force-dynamic' | 'force-static' | 'error'`, `export const revalidate = false | 0 | number`,
  `export const fetchCache = ...`. `revalidate` must be statically analyzable (`600`, not `60 * 10`).
- The lowest `revalidate` across a route's layouts and pages wins for the whole route.
- Prerender dynamic segments with `generateStaticParams`; unlisted params render on demand and are
  then cached (ISR).
- `export const runtime = 'edge'` is deprecated; don't add it to new segments.
- In development, pages always render on demand and are never cached — don't debug cache behavior
  with `next dev`. Use `next build && next start`, and `NEXT_PRIVATE_DEBUG_CACHE=1` for verbose logs.

### Model B — Cache Components (`"use cache"`), if the flag gets enabled

```tsx
// Function level — cache a data fetch
import { cacheLife, cacheTag } from "next/cache";

export async function getVenue(slug: string) {
  "use cache";
  cacheLife("hours");       // built-in profile: seconds/minutes/hours/days/weeks/max
  cacheTag(`venue-${slug}`); // for on-demand invalidation
  const res = await fetch(`${process.env.API_BASE_URL}/venues/${slug}`);
  return res.json();
}
```

- Cached functions/components **must be `async`**.
- Cached scopes **cannot** call `cookies()`, `headers()`, or read `searchParams`/`params` — and the
  restriction follows the call stack, so a helper that reads one fails the same way
  (`next-request-in-use-cache`). On a dynamically rendered route this can pass `next build` and only
  fail under `next start`. Read them in an uncached parent and pass values in as arguments. Two
  escape hatches exist: `"use cache: private"` (gives a lifetime to a scope that *does* read
  cookies/headers; cached in the browser only) and `"use cache: remote"` (durable, shared cache
  handler instead of per-instance memory).
- Arguments **and closed-over variables** become part of the cache key. Args and return values must
  be RSC-serializable: no class instances (so no raw ORM model objects), functions, symbols or `URL`
  instances. `children`/slots pass through untouched and don't affect the entry.
- Always set an explicit `cacheLife` profile at the call site rather than relying on the implicit
  `default` profile (5 min stale / 15 min revalidate / never expires).
- The default handler is **per-instance in-memory**, so on serverless entries often don't survive
  between requests; no cache survives a new deploy (the build ID is in the cache key). Reach for
  `"use cache: remote"` when you need durability.
- File-level `"use cache"` covers every export in that file (all must be async) —
  including `generateMetadata`/`generateStaticParams` if colocated there.
- Uncached or runtime-dependent components must be wrapped in `<Suspense>`, or the route fails
  prerender validation. Non-deterministic calls (`Math.random()`, `Date.now()`,
  `crypto.randomUUID()`) need `await connection()` plus `<Suspense>`, or a cache directive.
- Symptom to recognize: a build that hangs ~50s with "Filling a cache during prerender timed out"
  means a request-time promise (a `cookies()` store, `params`) leaked into a cached scope via props
  or a closure.

### Revalidation: four APIs, four different jobs

| API                                 | Where it's valid                        | Semantics                                                                                                                                   |
|--------------------------------------|------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------|
| `revalidateTag(tag, profile)`        | Server Actions + Route Handlers          | Stale-while-revalidate — the tag is marked stale, the next *request* triggers the refresh, and the action's own response is **not** re-rendered. Second arg (a `cacheLife` profile, usually `'max'`) is required by the types; pass `{ expire: 0 }` to expire immediately (e.g. from a webhook, where `updateTag` isn't available). |
| `updateTag(tag)`                     | Server Actions only                      | Read-your-writes — expires the tag and re-renders the route within the same request, so the actor sees their own change immediately.          |
| `revalidatePath(path)`               | Server Actions + Route Handlers          | Invalidate by URL path instead of tag. Also triggers an immediate re-render from a Server Action.                                             |
| `refresh()`                          | Server Actions only                      | Refetches the current route's RSC payload **without invalidating any cache** — for views that depend on state outside the cache. Throws if called from a Route Handler or Client Component. |

Neither `revalidateTag`, `updateTag`, `revalidatePath` nor `refresh` can be called from Client
Components or `proxy.ts`.

```ts
"use server";
import { updateTag } from "next/cache";

export async function updateVenue(slug: string, data: VenueInput) {
  await db.venues.update(slug, data);
  updateTag(`venue-${slug}`); // the editor sees their change immediately
}
```

> **Don't** call `revalidateTag('tag')` with a single argument — it's deprecated and is a TypeScript
> error under the current types (it behaves like `{ expire: 0 }` if you suppress the error). Pick
> `revalidateTag(tag, 'max')` for eventual consistency, or `updateTag(tag)` inside a Server Action
> when the actor needs to see their own write immediately.

## Server Actions — security

Server Actions are **public HTTP endpoints** the moment they're exported and reachable —
Next.js strips genuinely unused ones from the build, but any action wired into your UI can
be called directly via POST, bypassing your UI entirely. Treat every Server Action like a
Route Handler from a security standpoint.

### Do / Don't

```tsx
// DON'T — page-level auth check does not protect the Server Action
export default async function AdminPage() {
  const session = await auth();
  if (!session?.user?.isAdmin) redirect("/login");

  return (
    <form action={async () => {
      "use server";
      await db.record.deleteMany(); // reachable directly, no re-check
    }}>
      <button>Delete Records</button>
    </form>
  );
}

// DO — re-verify inside the action itself; check ownership, not just login state
"use server";
export async function deletePost(postId: string) {
  const session = await auth();
  if (!session?.user) throw new Error("Unauthorized");

  const post = await db.post.findUnique({ where: { id: postId } });
  if (post.authorId !== session.user.id) throw new Error("Forbidden"); // IDOR check
  await db.post.delete({ where: { id: postId } });
}
```

### Rules
- **Always** re-check authentication *and* authorization (resource ownership) inside the
  action — a page-level redirect only controls what renders, not what the action executes.
- **Validate** all inputs (`FormData`, arguments) inside the action — never trust
  client-supplied `searchParams`, hidden form fields, or IDs for authorization decisions.
- **Return only what the client needs** — don't return raw DB rows; they get serialized to
  the client and may leak internal fields (`passwordHash`, internal flags, etc.).
- Prefer a **Data Access Layer** (`data/*.ts`, marked `import "server-only"`) that owns
  auth checks and DB access; keep `"use server"` action files thin wrappers that call into
  it. This is the same separation of concerns as `service.py` in the FastAPI guide.
- If deploying behind a reverse proxy or CDN domain that differs from the app's own host,
  configure `experimental.serverActions.allowedOrigins` (still under `experimental` in 16) —
  otherwise Next's built-in Origin/Host CSRF check will reject legitimate requests.
- Action request bodies are capped at **1MB**; raise it with
  `experimental.serverActions.bodySizeLimit` or move large uploads to a Route Handler / direct
  upload instead.
- Never trigger mutations (cookie writes, cache revalidation, DB writes) as a side effect
  during **render** — Next.js blocks this. Do it in a Server Action or Route Handler.
- `redirect()` works by **throwing**, so never call it inside a `try`/`catch` that swallows errors,
  and put revalidation calls *before* it — code after `redirect()` does not run.
- Actions dispatch **one at a time per client**; `Promise.all` over several actions from the browser
  does not parallelize them. Do parallel work inside a single action instead.
- Self-hosted or multi-instance deployments must set a stable `NEXT_SERVER_ACTIONS_ENCRYPTION_KEY`
  across instances (inline-action closures are encrypted with it), or clients hit
  "Failed to find Server Action" after a deploy. Prefer rolling deploys.
- With the `authInterrupts` flag you can `throw unauthorized()` / `forbidden()` from
  `next/navigation` and render `unauthorized.tsx` / `forbidden.tsx` instead of hand-rolling error
  states.

## Preventing data leaks — `server-only` and the Data Access Layer

```ts
// data/venues.ts
import "server-only";                 // build error if ever imported into a Client Component
import { cache } from "react";

export const getCurrentUser = cache(async () => {
  const token = (await cookies()).get("AUTH_TOKEN");
  return decryptAndValidate(token);
});

export async function getVenueDTO(slug: string) {
  const row = await db.venues.findBySlug(slug);
  const user = await getCurrentUser();
  // Return a minimal DTO, not the raw row — omit internal-only fields.
  return {
    name: row.name,
    description: row.description,
    contactEmail: canSeeContact(user) ? row.contactEmail : null,
  };
}
```

- Install and use the [`server-only`](https://www.npmjs.com/package/server-only) package
  on any module that touches secrets, `process.env` (beyond `NEXT_PUBLIC_*`), or a DB
  client — it turns an accidental client import into a build-time error instead of a
  silent leak.
- Only env vars prefixed `NEXT_PUBLIC_` are exposed to the client; everything else is
  server-only by default — but a Server Component can still accidentally *pass* server
  data to a Client Component via props. The leak is in the prop, not the env var.
- When passing data from a Server Component to a Client Component, pass a narrow,
  purpose-built object — not the whole ORM row / API response.
- `serverRuntimeConfig`/`publicRuntimeConfig` were **removed** in 16 — use env vars. Values read
  from `process.env` during prerender are baked in at build time; when a value must be read per
  deployment at runtime, `await connection()` (from `next/server`) before reading it.
- For defense in depth, enable the `taint` config and use React's `experimental_taintObjectReference`
  /`experimental_taintUniqueValue` so a tainted row or secret throws if it ever reaches the client.

## Routing conventions (Next.js 16 specifics)

- **`middleware.ts` → `proxy.ts`.** Rename the file and the exported function to `proxy`
  (codemod: `npx @next/codemod@canary middleware-to-proxy .`). It lives at the project root, beside
  `app/`. `proxy.ts` always runs on the Node.js runtime — the `runtime` segment config is not
  available there and **throws** if set; Edge requires staying on the deprecated `middleware.ts`.
  Config flags were renamed too (`skipMiddlewareUrlNormalize` → `skipProxyUrlNormalize`).
  ```ts
  // proxy.ts
  import type { NextRequest } from "next/server";
  export default function proxy(request: NextRequest) {
    // ...
  }
  // Without a matcher, proxy runs on EVERY request — including _next/static, _next/image
  // and public/ assets. Always scope it.
  export const config = {
    matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
  };
  ```
- **Proxy is not an auth boundary.** Server Actions POST to the route that renders them, so a
  matcher change (or moving a form to another route) silently drops proxy coverage. Keep
  auth/authorization checks inside each action and Route Handler. Matchers must also be statically
  analyzable constants, and `_next/data` is always matched regardless of negative patterns.
- **`params` and `searchParams` are always Promises** — in `page.tsx`, `layout.tsx`,
  `route.ts`, `generateMetadata`, image-generation files, and `sitemap.ts`. There is no
  synchronous fallback in 16.
  ```tsx
  export default async function Page(props: PageProps<"/venues/[slug]">) {
    const { slug } = await props.params;
    const query = await props.searchParams;
  }
  ```
  Run `npx next typegen` to get the generated `PageProps`/`LayoutProps`/`RouteContext`
  helpers instead of hand-writing `Promise<{ slug: string }>` everywhere.
- **Parallel route slots require an explicit `default.js`.** A missing `default.js` in a
  `@slot` directory now fails the build (it used to silently fall back).
  ```tsx
  // app/@modal/default.tsx
  export default function Default() { return null; }
  ```
- Cross-domain/cross-app imports inside `packages/ui` should be exported per-component
  (`@repo/ui/components/button`, `@repo/ui/components/card`) — don't add a barrel `index.ts` that re-exports
  everything; it defeats tree-shaking and Turbopack's incremental compilation.

## Streaming, Suspense & error boundaries

Structure matters more in 16 than in earlier App Router versions: the deeper an `await` sits in the
tree, the more of the page can be prerendered and the faster navigation feels.

```tsx
// DON'T — awaiting params/cookies at the top of a layout blocks the whole subtree
export default async function Layout({ params, children }: LayoutProps<"/venues/[slug]">) {
  const { slug } = await params;      // nothing above this can prerender
  return <div><Sidebar /><h1>{slug}</h1>{children}</div>;
}

// DO — keep the shell synchronous and await inside a boundary
export default function Layout({ params, children }: LayoutProps<"/venues/[slug]">) {
  return (
    <div>
      <Sidebar />
      <Suspense fallback={<h1>Loading…</h1>}>
        <SlugHeading params={params} />
      </Suspense>
      {children}
    </div>
  );
}
```

- Wrap request-time or slow reads in `<Suspense>` (or add a `loading.tsx` for the whole segment)
  rather than making the whole route dynamic.
- A Client Component calling `useSearchParams()` must sit under a `<Suspense>` boundary, or the
  prerender of that route bails out.
- Errors: `error.tsx` per segment (a Client Component receiving `error`/`retry` — `retry()` re-fetches and re-renders, stable since 16.3; `reset()` only clears the error state and re-renders without re-fetching, so it can't recover from a failed server fetch),
  `global-error.tsx` for the root layout, `not-found.tsx` + `notFound()` for 404s. An error boundary
  contains failures the same way Suspense contains async work — one per risky subtree, not one at
  the root.
- Bots/crawlers are detected and served a fully dynamic render instead of the static shell, so any
  data your shell relies on must also be reachable at request time.

## Route Handlers, metadata & background work

- Route Handlers (`app/**/route.ts`) are not cached by default; opt in per-handler with
  `export const revalidate`/`dynamic`, or `Cache-Control` headers you set yourself. Under Cache
  Components, `GET` handlers follow the same prerendering model as pages.
- Use Route Handlers for webhooks, cron targets, file uploads and anything a non-browser client
  calls; use Server Actions for mutations driven by your own UI. Don't create a Route Handler just
  for your own Server Components to call — query the data layer directly.
- Metadata: `export const metadata` for static values, `async generateMetadata()` when it depends on
  `params`/data (`generateViewport` for viewport). Don't hand-write `<title>`/`<meta>` in a layout.
- `after()` (from `next/server`) runs work *after* the response streams — logging, analytics,
  cache warming — instead of blocking the render or the action.
- `instrumentation.ts` with `onRequestError` is the hook for server-side error reporting.
- Navigation in 16 prefetches incrementally and dedupes shared layouts automatically; expect more
  but much smaller prefetch requests. Use `<Link>` for internal navigation (`legacyBehavior` is
  gone), `useRouter` only from Client Components, and `redirect()`/`permanentRedirect()` on the
  server.
- Self-hosting/Docker: `output: "standalone"`, and remember `next dev` now writes to `.next/dev`
  while a lockfile prevents two dev/build runs on the same project.

## `next/image`

```tsx
// DON'T — deprecated, and blocks any hostname
export default {
  images: { domains: ["example.com"] },
};

// DO — explicit allow-list, works with Next.js 16's default security restrictions
export default {
  images: {
    remotePatterns: [{ protocol: "https", hostname: "example.com" }],
  },
};
```

- Use `next/image`, never `next/legacy/image` (deprecated).
- `images.domains` is deprecated — use `images.remotePatterns`.
- Local images referenced with a query string (`/logo.png?v=2`) need
  `images.localPatterns[].search` configured, or the build/runtime will reject them
  (anti-enumeration protection added in 16).
- Defaults changed in 16 — all breaking:
  - `minimumCacheTTL`: 4h (was 60s).
  - `qualities`: `[75]` only (was all) — an out-of-list `quality` prop is coerced to the nearest
    configured value, so set `images.qualities` explicitly if you need multiple tiers.
  - `imageSizes`: `16` was dropped from the default array.
  - `maximumRedirects`: 3 (was unlimited).
  - Local/private IP sources are blocked; `images.dangerouslyAllowLocalIP` opts back in (SSRF risk —
    only for a trusted VPC).

## Styling — Tailwind v4 + shadcn/ui

This repo's `components.json` (`style: "base-nova"`, `baseColor: "neutral"`,
`iconLibrary: "lucide"`) governs both apps. Match it rather than hand-rolling variants.

- Tailwind v4 is **CSS-first** — theme tokens live in `app/globals.css` under `@theme`,
  not in a `tailwind.config.js`. Don't create one unless you have a concrete reason;
  `components.json` already points `tailwind.css` at `app/globals.css`.
- Compose class names with `cn()` (`lib/utils.ts`, `clsx` + `tailwind-merge`) rather than
  string-concatenating classes — it resolves Tailwind class conflicts (e.g. conflicting
  `p-2`/`p-4`) predictably.
  ```tsx
  import { cn } from "@/lib/utils";
  <div className={cn("rounded-md p-4", isActive && "bg-accent")} />
  ```
- New shadcn components go through the CLI (`pnpm dlx shadcn@latest add <name>`), landing
  in `components/ui/` per the `aliases` in `components.json` — don't hand-write
  shadcn-style primitives from scratch; it drifts from the generated variants/CVA setup.
- Shared, cross-app components belong in `packages/ui/src` (imported as
  `@repo/ui/<name>`); app-specific ones stay in that app's `components/`.

## Turbopack & React Compiler

- Turbopack is the **default** bundler for both `next dev` and `next build` in 16 — no
  `--turbopack` flag needed. Don't add a custom webpack config unless there's a hard
  requirement; a webpack config now makes `next build` fail outright (must pass
  `--webpack` explicitly to opt out). Note a plugin can introduce one without you writing it.
- Turbopack options are top-level `turbopack: {}` in `next.config.ts` (out of `experimental` in 16);
  filesystem caching for dev and build is on by default. Use `turbopack.resolveAlias` instead of
  webpack's `resolve.fallback`, and drop the Sass `~` prefix in `node_modules` imports —
  Turbopack doesn't support it.
- The React Compiler (`reactCompiler: true` in `next.config.ts`) is stable but **not
  enabled by default** — it auto-memoizes components, removing most hand-written
  `useMemo`/`useCallback`/`React.memo`. If enabling it, expect slower build times (it
  runs via Babel) and don't hand-add memoization afterward — let the compiler do it.

## Linting & Formatting

`next lint` was **removed** in Next.js 16 — this repo already uses ESLint directly
(`"lint": "eslint --max-warnings 0"` in every `package.json`, matching
`packages/eslint-config`'s flat config). Don't suggest `next lint` or add it back.

```shell
pnpm lint          # turbo run lint — fans out to every app/package
pnpm check-types   # turbo run check-types — next typegen && tsc --noEmit
pnpm format        # prettier --write "**/*.{ts,tsx,md}"
```

- ESLint config is Flat Config (`eslint.config.js`), extending
  `@repo/eslint-config/next-js` — includes `@next/eslint-plugin-next`'s
  `core-web-vitals` rules and `eslint-plugin-react-hooks`. Don't add a legacy
  `.eslintrc.*` file.
- Run `next typegen` (wired into `check-types`) after adding/renaming dynamic route
  segments — it regenerates the `PageProps`/`LayoutProps`/`RouteContext` helper types
  used for async `params`/`searchParams`.

## Testing

Next.js's own docs recommend **Vitest** for unit tests and **Playwright** for E2E —
neither app has a test setup yet, so this is the default to reach for, not a rip-and-replace.

| Layer                                             | Tool                          |
|-----------------------------------------------------|---------------------------------|
| Pure functions, Zod schemas, small sync components  | Vitest + React Testing Library |
| Data Access Layer / Route Handlers (mockable DB)     | Vitest (integration-style)     |
| Async Server Components, full user flows, auth       | Playwright — the Next.js docs recommend E2E over unit tests for `async` components |

- Don't try to unit-test an `async function Page()` Server Component directly through
  Vitest/RTL — tooling support for async components is still incomplete, and the Next.js testing
  guide explicitly recommends E2E for them. Push that coverage to Playwright instead.
- Test Server Actions by importing and calling the exported function directly in Vitest
  (they're just async functions) rather than driving them through a rendered form.

## Anti-patterns — common AI-agent mistakes

| Anti-pattern | Why it's wrong | Fix |
|---|---|---|
| `"use client"` at the top of a whole page/layout for one interactive widget | Ships the entire subtree's JS to the browser | Isolate the interactive piece in its own small Client Component; keep the page/layout a Server Component |
| `useEffect(() => { fetch(...) }, [])` in a Client Component to load initial data | Client-server waterfall, loading spinner on first paint, no server caching | Fetch in the Server Component parent and pass data down as props, or stream with `use()` |
| Assuming a `fetch()` call is cached by default | `fetch` has been uncached by default since 15 | Pass `{ cache: 'force-cache', next: { revalidate, tags } }`, or `"use cache"` + `cacheLife(...)` under Cache Components |
| Writing `"use cache"` without `cacheComponents: true` in `next.config` | It's a Cache Components feature and errors without the flag (not enabled in this repo) | Use `fetch` cache options / `unstable_cache`, or enable the flag deliberately via the migration guide |
| Claiming "nothing is cached / everything is dynamic in 16" | Routes are still prerendered at build up to the first request-time API; with Cache Components PPR is the default | Reason about the model in use, not a blanket rule |
| `revalidateTag('tag')` with one argument | Deprecated single-arg form, type error | `revalidateTag('tag', 'max')` for SWR, or `updateTag('tag')` in a Server Action for read-your-writes |
| Trusting a page-level `redirect()`/auth check to protect a Server Action defined on that page | Actions are independently reachable via direct POST | Re-check `auth()`/ownership inside the action itself |
| Returning a raw DB row from a Server Action or passing it as a Client Component prop | Leaks internal fields (hashes, flags, other users' data) to the browser | Return/pass a narrow DTO with only the fields the UI needs |
| `middleware.ts` / `export function middleware()` in new code | Deprecated name in Next.js 16 | `proxy.ts` / `export default function proxy()` (unless Edge runtime is required) |
| `const { slug } = params` without `await` | `params`/`searchParams`/`cookies()`/`headers()` are always Promises now | `const { slug } = await params` |
| `images: { domains: [...] }` in `next.config` | Deprecated, less secure (no protocol/path scoping) | `images: { remotePatterns: [...] }` |
| Calling `cookies()`/`headers()` inside a `"use cache"` scope | Error (`next-request-in-use-cache`) — cached code can't read per-request data, and a dynamic route may only fail at runtime, not at build | Read them in an uncached parent and pass the value in as an argument, or use `"use cache: private"` |
| Passing an ORM model / class instance as an argument to a cached function | Cached args must be RSC-serializable; class instances and `URL`s throw | Pass primitives or plain objects |
| `redirect()` inside `try`/`catch`, or code placed after it | `redirect()` throws a control-flow error — the catch swallows the navigation and later lines never run | Call it outside the `try`, after any `revalidate*` calls |
| A `proxy.ts` with no `config.matcher` | Runs on every request including `_next/static`, `_next/image` and `public/` assets | Add a negative-lookahead matcher; keep auth checks in the actions/handlers too |
| Relying on `proxy.ts` to authorize Server Actions | Actions POST to the invoking route and can fall outside the matcher | Re-check auth inside each action |
| A Client Component using `useSearchParams()` with no `<Suspense>` above it | Bails the route out of prerendering | Wrap it in `<Suspense>` |
| `serverRuntimeConfig`/`publicRuntimeConfig`, or `export const runtime = 'edge'` in new code | Removed / deprecated in 16 | Env vars (+ `await connection()` for runtime reads); Node runtime |
| Hand-rolling a shadcn-style component instead of `pnpm dlx shadcn add` | Drifts from the CVA/variant setup `components.json` expects | Generate via the shadcn CLI, then customize |
| Adding a parallel route slot (`@modal`) without `default.js` | Next.js 16 fails the build on missing `default.js` | Add `default.js` that calls `notFound()` or returns `null` |
| `next lint` in scripts/CI | Removed in Next.js 16 | `eslint` directly (already wired in this repo's `package.json`) |

## Quick reference

| Scenario                                    | Solution                                                    |
|-----------------------------------------------|-----------------------------------------------------------------|
| Fetch data for a page                         | `async function Page()` Server Component, `await fetch(...)` directly |
| Add interactivity (click, form state)         | Small leaf `"use client"` component, composed via props/children |
| Cache an expensive fetch (this repo, today)   | `fetch(url, { cache: 'force-cache', next: { revalidate, tags } })` |
| Cache an expensive DB/ORM query (today)       | `unstable_cache(fn, [key], { tags, revalidate })`               |
| Dedupe a query within one render              | `cache()` from `react`                                          |
| Cache an expensive fetch/query (Cache Components) | `"use cache"` + `cacheLife('hours' \| 'days' \| ...)`      |
| Tag a cache entry for later invalidation      | `cacheTag('name')` (or `next: { tags: [...] }` on `fetch`)      |
| Invalidate with eventual consistency          | `revalidateTag('name', 'max')`                                  |
| Invalidate from a webhook/Route Handler       | `revalidateTag('name', { expire: 0 })` or `revalidatePath('/x')` |
| Invalidate with read-your-writes (in an action) | `updateTag('name')`                                            |
| Re-render the current route after an action, without invalidating caches | `refresh()`                          |
| Keep a slow read off the critical path        | `<Suspense>` (or `loading.tsx`) around the async component      |
| Run work after the response is sent           | `after()` from `next/server`                                    |
| Handle a form submission / mutation           | Server Action (`"use server"`), re-verify auth inside it        |
| Keep secrets/DB access off the client         | `import "server-only"` in the module, DTOs at the boundary      |
| Intercept/redirect requests                   | `proxy.ts` (`export default function proxy(request)`) + `config.matcher` |
| Async dynamic route params                    | `const { slug } = await params` (generate types via `next typegen`) |
| Allow-list remote images                      | `images.remotePatterns` in `next.config.ts`                     |
| Add a new shared UI component                 | `pnpm dlx shadcn@latest add <name>` inside the target app       |
| Unit test business logic                      | Vitest + React Testing Library                                  |
| Test a full user flow / async Server Component | Playwright                                                      |
| Lint + format                                 | `pnpm lint` (ESLint flat config) + `pnpm format` (Prettier)      |
| Type-check incl. route param types            | `pnpm check-types` (`next typegen && tsc --noEmit`)              |

## Sources

- [Next.js 16 release notes](https://nextjs.org/blog/next-16)
- [Upgrading to version 16](https://nextjs.org/docs/app/guides/upgrading/version-16)
- [`"use cache"` directive](https://nextjs.org/docs/app/api-reference/directives/use-cache)
- [How to think about data security in Next.js](https://nextjs.org/docs/app/guides/data-security)
- [Server and Client Components](https://nextjs.org/docs/app/getting-started/server-and-client-components)
- [Project structure](https://nextjs.org/docs/app/getting-started/project-structure)
- [Testing guide](https://nextjs.org/docs/app/guides/testing)
- [Caching and Revalidating (Previous Model)](https://nextjs.org/docs/app/guides/caching-without-cache-components) — the model this repo is on
- [Migrating to Cache Components](https://nextjs.org/docs/app/guides/migrating-to-cache-components)
- [Server Actions and Mutations](https://nextjs.org/docs/app/guides/server-actions)
- [`proxy.js` reference](https://nextjs.org/docs/app/api-reference/file-conventions/proxy)
- [`revalidateTag`](https://nextjs.org/docs/app/api-reference/functions/revalidateTag) · [`updateTag`](https://nextjs.org/docs/app/api-reference/functions/updateTag) · [`refresh`](https://nextjs.org/docs/app/api-reference/functions/refresh)
- [AI coding agents guide](https://nextjs.org/docs/app/guides/ai-agents) — bundled docs + `AGENTS.md` setup
