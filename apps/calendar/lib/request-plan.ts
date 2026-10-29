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
 * The ORDER of the checks is the design (`C4-K2`); it is the one fill-in gap in this file.
 *
 * docs/dev/implementations/c4-metro-hosts.md: C4-D1, C4-D4, C4-D5, C4-D6, C4-D7, C4-K2.
 */

import type { AppEnv } from "./app-env";
// The next two are used by the C4-K2 block below; the scaffold does not call them yet.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
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

export async function decideRequest(input: RequestInput): Promise<RequestPlan> {
  // TODO(Ari) — Key point of interest (C4-K2): the ORDER of the checks is the design, not any one of them
  //   (C4-D4, C4-D6, plan review C4-PR1-10). (1) An unreadable environment, a malformed default slug, or a gated
  //   environment with no password is "unavailable" before anything else, and carries noindex: fail closed.
  //   (2) Host handling that reveals NOTHING from the database comes next and needs no login: the apex and bad
  //   hosts redirect straight to the default metro's host (a pure function of the host string and configuration).
  //   (3) Then the gate, with the gate's own pages passing without a cookie (or nobody could log in).
  //   (4) Only AFTER the gate, the liveness check of a non-default slug: it is the one step whose answer depends on
  //   the database, so a stranger must not be able to reach it (a redirect-versus-gate difference would tell them
  //   which metros exist). It fails open on "unknown" (null), and the default slug is accepted without asking.
  //   (5) noindex is a property of the environment, attached to whatever action results.
  // To align: copy the Code lines below by hand in place of the placeholder `return`, then run the Check.
  // Code:
  //   if (input.env === null || !input.defaultSlugValid || (gateApplies(input.env) && !input.passwordConfigured))
  //     return { action: "unavailable", noindex: true };
  //   const noindex = isNoindex(input.env);
  //   if (input.host.kind === "apex" || input.host.kind === "bad")
  //     return { action: "redirect-metro", slug: input.defaultSlug, noindex };
  //   if (gateApplies(input.env) && !isGatePath(input.path) && !input.cookieValid)
  //     return { action: input.method === "GET" || input.method === "HEAD" ? "redirect-gate" : "deny", noindex };
  //   if (input.host.kind === "metro" && input.host.slug !== input.defaultSlug && !isGatePath(input.path)) {
  //     const live = await input.isLiveSlug(input.host.slug); // true | false | null (outage)
  //     if (live === false) return { action: "redirect-metro", slug: input.defaultSlug, noindex };
  //     return { action: "next", slug: live === true ? input.host.slug : input.defaultSlug, noindex };
  //   }
  //   return { action: "next", slug: input.defaultSlug, noindex };
  // Check: `pnpm --filter calendar test lib/request-plan.test.ts` (C4-T3). The likeliest mistake: running the
  //   liveness check before the gate (the "unknown slug without a cookie gets the gate and the fake is not called"
  //   row goes red), calling `isLiveSlug` for the default slug (the "no call" assertion), treating an outage (null)
  //   as "not live" (the fail-open row), or returning "unavailable" without noindex.
  //
  // Placeholder, NOT the C4-K2 `throw` convention (same departure as C3-PR1-3): the proxy calls this on every
  // request, so a raising placeholder would turn the whole app, the e2e job included, into 500s. This one serves
  // every page as the default metro with the environment's noindex, so only the order-dependent rows stay red.
  return { action: "next", slug: input.defaultSlug, noindex: isNoindex(input.env) };
}
