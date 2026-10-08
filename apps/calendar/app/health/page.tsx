import type { Metadata } from "next";
import { getApiHealth } from "@/lib/health";

export const metadata: Metadata = { title: "Status" };

// Why `force-dynamic` lives here and not on the home page any more:
// this page's whole value is reporting the API's state *right now*.
// Without it, Next.js would try to prerender the page at build time — which
// would (a) require the FastAPI backend to be reachable from Vercel's build
// servers on every deploy, and (b) freeze a build-time "up" into the static
// output so every visitor sees a stale answer. force-dynamic renders it per
// request instead.
export const dynamic = "force-dynamic";

// A Server Component with a top-level `await`: the fetch happens on the
// server, before any HTML is sent. There's no useEffect, no loading state,
// and no client-side data library — the browser just receives finished
// markup. This is the pattern B2 repeats for real calendar data.
//
// `API_BASE_URL` has no NEXT_PUBLIC_ prefix, so it exists only on the
// server. It can't leak into the browser bundle, which also means this
// check reports whether the *server* can reach the API — the thing that
// matters, since the browser never talks to FastAPI directly.
//
// This page is linked from every footer, so strangers can see it. The
// detailed `reason` (env var names, file paths, raw error text) is for
// the person running the app, not for visitors: it goes to the server log
// always, and onto the page only in development, where the person
// reading the page *is* the developer (the unset-API_BASE_URL first-run
// mistake is easiest to spot right here).
export default async function HealthPage() {
  const health = await getApiHealth(process.env.API_BASE_URL);
  if (!health.ok) console.error(`[health] API check failed: ${health.reason}`);
  const showDetail = process.env.NODE_ENV !== "production";

  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">Status</h1>
      <dl className="mt-4 grid max-w-md grid-cols-[auto_1fr] gap-x-6 gap-y-2">
        <dt className="text-muted-foreground">API</dt>
        <dd>
          {health.ok ? (
            <span>up ({health.message})</span>
          ) : (
            <span className="text-destructive">
              down
              {showDetail && <> — {health.reason}</>}
            </span>
          )}
        </dd>
      </dl>
    </section>
  );
}
