/**
 * The non-production gate's pure parts: who it applies to, the cookie it sets, and the redirect it follows.
 *
 * The gate is one shared password in front of the website's pages in staging (Dep-D4, C4-D6). It is a courtesy, not
 * security: the Railway API stays public until C10, and there is no rate limit and no per-user identity. What it
 * must get right is small and testable, and it all lives here:
 *
 *   - `gateApplies`: staging and dev (and nothing else; C4-D1). `prod` is open, `local` is not worth a password.
 *   - the cookie: `__Host-gate`, whose value is an HMAC of a constant keyed by the password and the environment,
 *     so it cannot be forged without the password, needs no session store, and changing the password invalidates
 *     every cookie. The `__Host-` prefix makes the browser itself insist on Secure, Path=/ and NO Domain, so the
 *     cookie is host-only and the environments cannot read each other's (alpha-deployment-plan.md §4.2).
 *   - comparisons: both sides are hashed to the same length first, then compared with `timingSafeEqual`, which
 *     throws on different lengths; a wrong-length guess or cookie must be a refusal, not a 500 (C4-PR1-6).
 *   - `safeNextPath`: where to send the visitor after logging in, parsed with the WHATWG URL parser rather than
 *     checked by string prefix, because the parser deletes tabs and newlines, so `/\t/evil.com` becomes
 *     `//evil.com` after a string check has already passed it (C4-PR1-8).
 *
 * Node's `node:crypto`: the proxy runs on the Node runtime in Next.js 16, and so does the route handler.
 *
 * docs/dev/implementations/c4-metro-hosts.md: C4-D1, C4-D6.
 */

import { createHash, createHmac, timingSafeEqual } from "node:crypto";
import type { AppEnv } from "./app-env";

export const GATE_COOKIE = "__Host-gate";
/** 30 days. Enforced by the browser; the HMAC carries no expiry (C4-D6: a courtesy gate, not a session system). */
export const GATE_COOKIE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60;

/** Where the password form lives and where it posts. Both must pass the gate without a cookie. */
export const GATE_PATH = "/gate";

/** Environments that sit behind the password: staging, and dev if it is ever set up (C4-D1). */
export function gateApplies(env: AppEnv): boolean {
  return env === "staging" || env === "dev";
}

/** True for the gate's own pages, which must be reachable without a cookie or nobody could log in. */
export function isGatePath(pathname: string): boolean {
  return pathname === GATE_PATH || pathname.startsWith(`${GATE_PATH}/`);
}

/** The cookie value for this password in this environment: an HMAC (key: the password) of a constant. */
export function gateCookieValue(password: string, env: AppEnv): string {
  return createHmac("sha256", password).update(`gate-v1:${env}`).digest("hex");
}

/** SHA-256 of a string: the fixed-length form both sides of a comparison are reduced to. */
function digest(value: string): Buffer {
  return createHash("sha256").update(value).digest();
}

/** Constant-time equality of two strings of any lengths (C4-PR1-6). */
function safeEqual(a: string, b: string): boolean {
  return timingSafeEqual(digest(a), digest(b));
}

/** Does the submitted password equal the configured one? A different length is simply "no". */
export function passwordMatches(submitted: string, configured: string): boolean {
  return safeEqual(submitted, configured);
}

/** Is this cookie the one this password issues in this environment? Missing, tampered or other-environment: no. */
export function isGateCookieValid(
  cookie: string | undefined | null,
  password: string,
  env: AppEnv,
): boolean {
  if (!cookie) return false;
  return safeEqual(cookie, gateCookieValue(password, env));
}

/**
 * The path to send a visitor to after the gate, or `/` for anything that is not a same-site path.
 *
 * "Same-site" is decided by parsing against a placeholder origin: if the parsed URL's origin is not the
 * placeholder, the input reached for another site (`//evil.com`, `https://evil.com`, and the tab, newline and
 * backslash variants the parser normalises into one of those). The redirect then uses only `pathname + search`,
 * so nothing the visitor controls can name a host. Never trusts `next` as sent (C4-PR1-8).
 */
export function safeNextPath(next: string | null | undefined): string {
  if (!next) return "/";
  const base = "https://gate.invalid";
  let parsed: URL;
  try {
    parsed = new URL(next, base);
  } catch {
    return "/";
  }
  if (parsed.origin !== base) return "/";
  // A path that is the gate itself would loop: after logging in, go to the front page instead.
  if (isGatePath(parsed.pathname)) return "/";
  return `${parsed.pathname}${parsed.search}`;
}
