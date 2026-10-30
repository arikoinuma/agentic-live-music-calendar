/**
 * Next.js 16's `proxy.ts`: a file Next looks for BY NAME, and runs for you, before any page is built.
 *
 * What "proxy" means here, since the word is used for several things. This is a Next.js file convention: a function
 * Next calls on each incoming request, on the Node runtime, that may let the request through, redirect it, or answer it
 * itself. Next renamed it from `middleware.ts` in version 16 to stress that it sits at the front of the app; it is NOT
 * a reverse proxy server we run, NOT an outbound HTTP proxy, and unrelated to the e2e stack's `delay-proxy.mjs` (a test
 * helper that slows API calls). Per Next's docs it runs after `next.config.js` headers and redirects and BEFORE the
 * pages and route handlers:
 *
 *   browser -> Vercel -> [ proxy.ts ] -> a page (app/**) or a route handler -> the API (server to server)
 *                          |
 *                          +-> may answer by itself: redirect to /gate, redirect to the default metro's host, 401, 503
 *
 * What it does for C4: resolves the metro from the request's host, sends the apex and bad hosts to the default
 * metro, puts the non-production gate in front of staging, and marks every non-production response `noindex`
 * (alpha-deployment-plan.md C4, Dep-D2, Dep-D4). The work is in `lib/proxy-handler.ts` (reads the request, builds the
 * response) and `lib/request-plan.ts` (decides); this file only wires them to Next, because a proxy file may export
 * nothing else but its function and `config`.
 *
 * Three requests, as the proxy sees them (the same three as `parseHost` and `decideRequest`):
 *   A. a laptop           http://localhost:3000/venue/3                -> served as the default metro (no gate locally)
 *   B. a Vercel URL       https://foo-abc.vercel.app/venue/3           -> staging: the password form, then the page
 *   C. a real host        https://msp.staging.pebblebeats.com/venue/3  -> staging: the password form, then the page
 *
 * `config.matcher` SKIPS only the static build output, the image optimizer and the favicon, and covers every page,
 * `/health` included (the style guide: a proxy with no matcher runs on every asset request, including
 * `_next/static`). docs/dev/implementations/c4-metro-hosts.md: C4-D1, C4-D6.
 */

import type { NextRequest } from "next/server";
import { handleRequest } from "@/lib/proxy-handler";

export default function proxy(request: NextRequest) {
  return handleRequest(request);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
