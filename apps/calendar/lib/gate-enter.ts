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

/** A small plain-text answer, for the cases where there is no page to show (misconfigured, not found, failed). */
function plain(status: number, body: string): Response {
  return new Response(`${body}\n`, { status, headers: { "content-type": "text/plain; charset=utf-8" } });
}

/** What went wrong, as text for a log line: an Error's message, or whatever else was thrown. */
function reason(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/**
 * Handle one login attempt, `POST /gate/enter`. The form on /gate posts two fields: `password`, and `next` (the page the
 * visitor was trying to reach, so they land there after logging in).
 *
 * Three situations it meets, followed through the steps below as A, B and C (the same three as everywhere else in C4):
 *   A. a laptop         POST http://localhost:3000/gate/enter                    APP_ENV=local: there is no gate.
 *   B. staging, right   POST https://foo-abc.vercel.app/gate/enter  password=<correct>  next=/venue/3
 *   C. staging, wrong   POST https://msp.staging.pebblebeats.com/gate/enter  password=<a guess>
 */
export async function handleGateEnter(request: Request, env: Env = process.env): Promise<Response> {
  // Step 1: which environment is this? `getAppEnv()` refuses a missing or inconsistent APP_ENV, and a gate that cannot
  // tell what it guards must not hand out cookies, so that is a 503 (fail closed), logged for whoever runs the site.
  let appEnv: AppEnv;
  try {
    appEnv = getAppEnv(env);
  } catch (err) {
    console.error(`[gate] APP_ENV check failed: ${reason(err)}`);
    return plain(503, "Service unavailable");
  }

  // Step 2: only staging and dev have a gate. Where there is none, this endpoint should not exist, so it answers 404
  // and a local stack or production cannot be talked into issuing a gate cookie.
  //   A: APP_ENV=local -> 404 here.   B and C: staging -> carry on.
  if (!gateApplies(appEnv)) return plain(404, "Not found");

  // Step 3: is there a password to check against? A gated environment with SITE_GATE_PASSWORD unset is misconfigured:
  // 503, never an open door.
  const { gatePassword } = readSiteConfig(env);
  if (gatePassword === null) {
    console.error("[gate] SITE_GATE_PASSWORD is not set");
    return plain(503, "Service unavailable");
  }

  // Step 4: read the form. A body that is not a form (a probe, a broken client, a different content type) cannot be read,
  // and that is treated as an empty password, which never matches, so the visitor is sent back to the form like any
  // other wrong guess. It is logged, so a client that keeps failing is visible; the log line says why it failed but
  // never includes the body, which could hold a password. `next` goes through `safeNextPath`, the one place that decides
  // whether a redirect target stays on this site, because the form field is just text the visitor controls.
  //   B: password="<correct>", next="/venue/3".   C: password="<a guess>", next="/".
  let submitted = "";
  let next = "/";
  try {
    const form = await request.formData();
    submitted = String(form.get("password") ?? "");
    next = safeNextPath(String(form.get("next") ?? ""));
  } catch (err) {
    console.error(`[gate] could not read the login form: ${reason(err)}`);
  }

  // Step 5: check the password. `passwordMatches` derives a key from each side with scrypt and compares them in constant
  // time; it is the one step that can fail for a reason that is not the visitor's (scrypt running out of memory, say).
  // That is a server error, not a wrong password: answer 500, log it, and issue no cookie. Treating a failed check as
  // "no match" would hide the fault behind a login form that can never succeed.
  let matches: boolean;
  try {
    matches = await passwordMatches(submitted, gatePassword);
  } catch (err) {
    console.error(`[gate] password check failed: ${reason(err)}`);
    return plain(500, "Server error");
  }

  // Step 6: a wrong password goes back to the form with an error flag (and `next`, so the visitor does not lose where they
  // were going). No cookie is set. 303, relative: see the file header.
  //   C: 303 -> /gate?error=1
  if (!matches) {
    const back = new URLSearchParams({ error: "1" });
    if (next !== "/") back.set("next", next);
    return see(`${GATE_PATH}?${back.toString()}`);
  }

  // Step 7: the right password. Send the visitor on to `next` and set the cookie that proves they logged in. The cookie
  // is an HMAC keyed by the password (`gateCookieValue`), so it cannot be forged without it, and changing the password
  // logs everyone out. `__Host-` plus Secure and Path=/ and NO Domain makes it host-only, enforced by the browser:
  // staging's cookie is never sent to another host. HttpOnly keeps scripts away from it; SameSite=Lax keeps it off
  // cross-site subrequests; Max-Age is 30 days.
  //   B: 303 -> /venue/3, Set-Cookie: __Host-gate=<hmac>; Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=2592000
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
