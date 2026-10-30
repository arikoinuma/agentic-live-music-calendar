/**
 * The gate's login: `POST /gate/enter`.
 *
 * A route handler's file may export only handlers, so the body lives here and `app/gate/enter/route.ts` calls it.
 * It checks the submitted password against `SITE_GATE_PASSWORD` in constant time on fixed-length digests
 * (`passwordMatches`), and on success sets `__Host-gate` and sends the visitor to a SAFE path (`safeNextPath`).
 *
 * Both redirects are 303 See Other, not the 307 `NextResponse.redirect` defaults to: 307 keeps the method, so the
 * browser would re-POST the password form to the page it was sent to, and a refresh would resubmit it (C4-PR1-7).
 * The cookie is host-only by construction: `__Host-` prefix, `Secure`, `Path=/`, and no `Domain` attribute.
 * The redirects carry a RELATIVE `Location` (`/venue/3`, which RFC 9110 allows): `request.url` is the server's own
 * address, not necessarily the one the visitor typed, so an absolute URL built from it can name the wrong host (seen
 * against `next start`, where it came out as localhost); a relative one always stays on the host the visitor used.
 *
 * Fails closed: an unreadable `APP_ENV` or a missing password is a 503, and an environment with no gate (prod,
 * local) answers 404, so the endpoint does not exist where there is nothing to log in to.
 *
 * docs/dev/implementations/c4-metro-hosts.md: C4-D6.
 */

import { NextResponse } from "next/server";
import { getAppEnv, type AppEnv } from "./app-env";
import {
  GATE_COOKIE,
  GATE_COOKIE_MAX_AGE_SECONDS,
  GATE_PATH,
  gateApplies,
  gateCookieValue,
  passwordMatches,
  safeNextPath,
} from "./gate";
import { readSiteConfig } from "./site-config";

type Env = Record<string, string | undefined>;

/** A 303 See Other to a path on the same host (see the file header for why it is relative). */
function see(path: string): NextResponse {
  return new NextResponse(null, { status: 303, headers: { location: path } });
}

function plain(status: number, body: string): Response {
  return new Response(`${body}\n`, { status, headers: { "content-type": "text/plain; charset=utf-8" } });
}

export async function handleGateEnter(request: Request, env: Env = process.env): Promise<Response> {
  let appEnv: AppEnv;
  try {
    appEnv = getAppEnv(env);
  } catch (err) {
    console.error(`[gate] APP_ENV check failed: ${err instanceof Error ? err.message : String(err)}`);
    return plain(503, "Service unavailable");
  }
  if (!gateApplies(appEnv)) return plain(404, "Not found");

  const { gatePassword } = readSiteConfig(env);
  if (gatePassword === null) {
    console.error("[gate] SITE_GATE_PASSWORD is not set");
    return plain(503, "Service unavailable");
  }

  let submitted = "";
  let next = "/";
  try {
    const form = await request.formData();
    submitted = String(form.get("password") ?? "");
    next = safeNextPath(String(form.get("next") ?? ""));
  } catch {
    // Not a form post: treated as an empty password, which never matches.
  }

  if (!(await passwordMatches(submitted, gatePassword))) {
    const back = new URLSearchParams({ error: "1" });
    if (next !== "/") back.set("next", next);
    return see(`${GATE_PATH}?${back.toString()}`);
  }

  const response = see(next);
  response.cookies.set({
    name: GATE_COOKIE,
    value: gateCookieValue(gatePassword, appEnv),
    httpOnly: true,
    secure: true,
    sameSite: "lax",
    path: "/",
    maxAge: GATE_COOKIE_MAX_AGE_SECONDS,
    // No `domain`: the cookie stays on this host only (Dep plan §4.2).
  });
  return response;
}
