/**
 * What the proxy does with a request, decided as a pure function.
 *
 * `proxy.ts` is thin glue: it reads the request and the configuration, asks `decideRequest` what to do, and does
 * it. All the policy lives here so it can be tested as a table (C4-T3) without a server. The inputs are facts the
 * glue has already gathered (the environment, the host's classification, whether the gate cookie is valid, the
 * method and path) plus one injected question, `isLiveSlug`, so the tests never touch the network.
 *
 * The result is one of five actions, each carrying `noindex` so the glue can attach `X-Robots-Tag` to whatever it
 * sends (C4-D7):
 *
 *   unavailable      503: the environment cannot be read, the default metro is malformed, or a gated environment
 *                    has no password. Fail closed (C4-D1, C4-D6).
 *   redirect-gate    send a GET or HEAD to the password form.
 *   deny             401 for any other method without the cookie.
 *   redirect-metro   307 to the default metro's host (the apex, a bad host, or a slug that is not a live metro).
 *   next             serve the page, as the metro named in `slug`.
 *
 * The ORDER of the checks is the design (`C4-K2`, filled by Ari); the walk-through above `decideRequest` follows
 * three concrete requests through it.
 *
 * docs/dev/implementations/c4-metro-hosts.md: C4-D1, C4-D4, C4-D5, C4-D6, C4-D7, C4-K2.
 */

import type { AppEnv } from "./app-env";
import { gateApplies, isGatePath } from "./gate";
import type { HostClass } from "./metro-host";
import { isNoindex } from "./site-url";

export type RequestInput = {
  /** The environment, or null when `getAppEnv()` threw (a missing or inconsistent `APP_ENV`). */
  env: AppEnv | null;
  defaultSlug: string;
  /** False when `DEFAULT_METRO_SLUG` is set to something that cannot be a slug (C4-PR1-4). */
  defaultSlugValid: boolean;
  passwordConfigured: boolean;
  host: HostClass;
  method: string;
  path: string;
  /** Does the request carry the cookie this environment's password issues? */
  cookieValid: boolean;
  /** Is this slug the live metro? true / false, or null when the API could not answer (an outage). */
  isLiveSlug: (slug: string) => Promise<boolean | null>;
};

export type RequestPlan =
  | { action: "unavailable"; noindex: true }
  | { action: "redirect-gate"; noindex: boolean }
  | { action: "deny"; noindex: boolean }
  | { action: "redirect-metro"; slug: string; noindex: boolean }
  | { action: "next"; slug: string; noindex: boolean };

/**
 * Decide what to do with one request. The ORDER of the checks below is the design, not any one of them (C4-K2, with
 * C4-D4, C4-D6 and plan review C4-PR1-10); the first check that applies decides, so each is only reached by requests
 * that passed every check above it.
 *
 * Three requests, followed through (the same three situations as `parseHost`, now as whole requests):
 *
 *   A. a laptop           GET http://localhost:3000/venue/3
 *        env "local", host "outside" (no zone), no password needed.
 *        Check 1 passes, 2 and 3 do not apply (local has no gate, the host is not an apex), 4 does not apply
 *        (not a metro host) -> next, slug "msp", noindex true.
 *
 *   B. a Vercel URL       GET https://foo-abc.vercel.app/venue/3      (a PR preview or staging before it has a domain)
 *        env "staging" (every Preview is staging, C3-D11), host "outside", password configured.
 *        Check 1 passes; 2 does not apply; 3: staging is gated and there is no cookie -> redirect-gate.
 *        With the cookie: 3 passes, 4 does not apply (outside, not a metro host) -> next, slug "msp".
 *
 *   C. a real staging host GET https://msp.staging.pebblebeats.com/venue/3
 *        env "staging", host { metro, "msp" }, which is the default slug.
 *        No cookie: 3 -> redirect-gate.  With the cookie: 3 passes; 4 sees the default slug and accepts it WITHOUT
 *        asking the API -> next, slug "msp".
 *        Variations on C:
 *          https://staging.pebblebeats.com/venue/3         the apex -> check 2: redirect-metro to msp.staging...
 *                                                           (no login first: nothing from the database is revealed)
 *          https://www.staging.pebblebeats.com/            a bad host -> check 2: redirect-metro, same reason
 *          https://chi.staging.pebblebeats.com/            an unknown slug, no cookie -> check 3: redirect-gate, and
 *                                                           the API is NOT asked (a stranger must not learn which metros
 *                                                           exist). With the cookie -> check 4 asks the API: "not a
 *                                                           metro" -> redirect-metro; "yes" -> next as chi; API down
 *                                                           -> next as msp (fails open).
 *          https://msp.pebblebeats.com/venue/3             production at C11: env "prod", no gate, noindex false.
 */
export async function decideRequest(input: RequestInput): Promise<RequestPlan> {
  // 1. Misconfiguration comes first, and fails CLOSED: refuse before anything else is decided.
  //    - env null: APP_ENV is missing or does not match where Vercel says this is running.
  //    - defaultSlugValid false: DEFAULT_METRO_SLUG is set to something that cannot be a slug (a typo).
  //    - a gated environment (staging or dev) with no SITE_GATE_PASSWORD: the gate has nothing to check against.
  //    All three become a 503 that carries noindex. Example: staging deployed with the password variable forgotten
  //    answers 503 rather than serving the site to everyone.
  if (input.env === null || !input.defaultSlugValid || (gateApplies(input.env) && !input.passwordConfigured))
    return { action: "unavailable", noindex: true };

  // noindex is a property of the environment, attached to whatever action follows: true for local, dev and staging,
  // false only for prod (C4-D7).
  const noindex = isNoindex(input.env);

  // 2. Hosts we can judge from the address alone, and redirect before any login. The apex ("staging.pebblebeats.com")
  //    and a bad host ("www.staging.pebblebeats.com", "a.b.staging.pebblebeats.com") both go to the default metro's host.
  //    This needs no password: the answer depends only on the host text and the configured default, so redirecting
  //    reveals nothing about the database, and it spares a visitor a login on a host that was going to redirect anyway.
  if (input.host.kind === "apex" || input.host.kind === "bad")
    return { action: "redirect-metro", slug: input.defaultSlug, noindex };

  // 3. The gate. In a gated environment (staging, dev), a visitor with no valid cookie meets the password form.
  //    The gate's own pages (/gate and /gate/enter) are let through, or nobody could ever log in.
  //    A GET or HEAD is sent to the form ("redirect-gate", remembering where they were going); any other method
  //    (a POST to a page, say) is refused outright with a 401 ("deny"), because a form post to a page route should
  //    never have worked without the cookie.
  //    Example: GET https://msp.staging.pebblebeats.com/venue/3 with no cookie -> redirect to /gate?next=/venue/3.
  if (gateApplies(input.env) && !isGatePath(input.path) && !input.cookieValid)
    return { action: input.method === "GET" || input.method === "HEAD" ? "redirect-gate" : "deny", noindex };

  // 4. Only now, and only for a slug that is not the default: is it a real metro? This is the one check whose answer
  //    comes from the database (through the API), so it comes AFTER the gate. Were it before, a stranger could tell a
  //    real metro from an invented one by whether they were redirected or shown the password form. The default slug
  //    ("msp") never reaches this block: it is accepted from configuration without asking, so the common request makes
  //    no API call. The gate's own pages are skipped too, so logging in on any host costs no API call.
  //    Example: https://chi.staging.pebblebeats.com/ with the cookie.
  if (input.host.kind === "metro" && input.host.slug !== input.defaultSlug && !isGatePath(input.path)) {
    const live = await input.isLiveSlug(input.host.slug); // true | false | null (the API could not answer)
    // The API says "no such metro": send the visitor to the default metro's host.
    if (live === false) return { action: "redirect-metro", slug: input.defaultSlug, noindex };
    // true: serve it as that metro. null (the API is down): fail OPEN, serving the default metro rather than a
    // redirect storm, and never passing the unverified slug on to canonical URLs or, later, feature flags.
    return { action: "next", slug: live === true ? input.host.slug : input.defaultSlug, noindex };
  }

  // 5. Everything else is served as the default metro: a laptop, a Vercel URL, the default host, the gate's own
  //    pages, production. The default slug comes from configuration (it is "msp" unless DEFAULT_METRO_SLUG says otherwise).
  return { action: "next", slug: input.defaultSlug, noindex };
}
