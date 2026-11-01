/**
 * The proxy's glue: gather the facts about a request, ask `decideRequest` what to do, and do it.
 *
 * `proxy.ts` (Next.js 16's name for `middleware.ts`) must export only the function and its `config`, so the
 * testable body lives here, with its inputs (the environment and the liveness question) as parameters. All the
 * policy is in `request-plan.ts`; this file is the part that touches `NextRequest` and builds `NextResponse`s:
 *
 *   - It reads `APP_ENV` through `getAppEnv()` (C3-D7) and turns its refusal into `null`, which the plan treats
 *     as "unavailable" (fail closed). It never throws.
 *   - It sets `X-Robots-Tag: noindex, nofollow` on every response when the plan says `noindex`, redirects and the
 *     503 included (C4-D7).
 *   - On `next` it forwards the request with `x-metro-slug` set to the slug the plan chose, after DELETING whatever
 *     the client sent under that name, so the header can be trusted downstream (C4-D8).
 *   - Redirects to a metro's host are built from the configured zone (`siteOrigin`), never from the request's own
 *     `Host`, for the same reason the canonical URLs are (C4-D8).
 *
 * The proxy is a courtesy gate, not an auth boundary (docs/references/nextjs-style-guide.md, Routing): the Railway
 * API stays public until C10, and a Server Action POSTs to the page that renders it, so nothing here authorizes
 * anything that matters.
 *
 * docs/dev/implementations/c4-metro-hosts.md: C4-D1, C4-D5, C4-D6, C4-D7, C4-D8.
 */

import { NextResponse, type NextRequest } from "next/server";
import { getAppEnv, type AppEnv } from "./app-env";
import { GATE_COOKIE, GATE_PATH, isGateCookieValid } from "./gate";
import { getMetroOrNull } from "./metro";
import { METRO_SLUG_HEADER, parseHost } from "./metro-host";
import { decideRequest, type RequestPlan } from "./request-plan";
import { readSiteConfig } from "./site-config";
import { siteOrigin } from "./site-url";

type Env = Record<string, string | undefined>;

export type ProxyDeps = {
  /** The environment variables to read; tests pass a plain object. */
  env?: Env;
  /** Is this slug the live metro (true/false), or null when the API cannot answer. */
  isLiveSlug?: (slug: string) => Promise<boolean | null>;
};

/**
 * Ask the API which metro is live (`GET /metro`) and compare. `getMetroOrNull` never throws, so an outage is
 * `null`, which the plan treats as "unknown" and fails open (C4-D4). Only called for a non-default slug, after the
 * gate, so the hot path (the default metro) makes no extra API call.
 */
async function liveMetroIs(slug: string): Promise<boolean | null> {
  const metro = await getMetroOrNull();
  return metro === null ? null : metro.slug === slug;
}

export async function handleRequest(request: NextRequest, deps: ProxyDeps = {}): Promise<NextResponse> {
  const env = deps.env ?? process.env;

  let appEnv: AppEnv | null = null;
  try {
    appEnv = getAppEnv(env);
  } catch (err) {
    console.error(`[proxy] APP_ENV check failed: ${err instanceof Error ? err.message : String(err)}`);
  }

  const config = readSiteConfig(env);
  const host = parseHost(request.headers.get("host") ?? "", config.zone);
  const cookieValid =
    appEnv !== null &&
    config.gatePassword !== null &&
    isGateCookieValid(request.cookies.get(GATE_COOKIE)?.value, config.gatePassword, appEnv);

  const plan = await decideRequest({
    env: appEnv,
    defaultSlug: config.defaultSlug,
    defaultSlugValid: config.defaultSlugValid,
    passwordConfigured: config.gatePassword !== null,
    host,
    method: request.method,
    path: request.nextUrl.pathname,
    cookieValid,
    isLiveSlug: deps.isLiveSlug ?? liveMetroIs,
  });

  if (plan.action === "unavailable") {
    console.error(
      `[proxy] unavailable: app_env=${appEnv ?? "unreadable"} default_slug_valid=${config.defaultSlugValid} password_configured=${config.gatePassword !== null}`,
    );
  }
  return withRobots(plan, perform(plan, request, config.zone));
}

/** Attach `X-Robots-Tag` when the plan asks for noindex (everything but production, C4-D7). */
function withRobots(plan: RequestPlan, response: NextResponse): NextResponse {
  if (plan.noindex) response.headers.set("X-Robots-Tag", "noindex, nofollow");
  return response;
}

/** Turn a plan into a response. */
function perform(plan: RequestPlan, request: NextRequest, zone: string | null): NextResponse {
  switch (plan.action) {
    case "unavailable":
      return new NextResponse("Service unavailable: this deployment is misconfigured. See the server log.\n", {
        status: 503,
        headers: { "content-type": "text/plain; charset=utf-8" },
      });
    case "deny":
      return new NextResponse("Unauthorized\n", {
        status: 401,
        headers: { "content-type": "text/plain; charset=utf-8" },
      });
    case "redirect-gate": {
      // The visitor's own path and query ride along as `next`; the form posts it back and the server re-checks it
      // (`safeNextPath`) before redirecting, so this value is never trusted.
      const url = request.nextUrl.clone();
      const next = `${request.nextUrl.pathname}${request.nextUrl.search}`;
      url.pathname = GATE_PATH;
      url.search = "";
      url.searchParams.set("next", next);
      return NextResponse.redirect(url);
    }
    case "redirect-metro": {
      const origin = siteOrigin(zone, plan.slug);
      // A redirect to a metro host only arises for hosts inside a zone, so there is a zone; without one, serve.
      if (origin === null) return forward(request, plan.slug);
      return NextResponse.redirect(new URL(`${request.nextUrl.pathname}${request.nextUrl.search}`, origin));
    }
    case "next":
      return forward(request, plan.slug);
  }
}

/** Serve the request, as the metro `slug`, with any client-sent `x-metro-slug` dropped first. */
function forward(request: NextRequest, slug: string): NextResponse {
  const headers = new Headers(request.headers);
  headers.delete(METRO_SLUG_HEADER);
  headers.set(METRO_SLUG_HEADER, slug);
  return NextResponse.next({ request: { headers } });
}
