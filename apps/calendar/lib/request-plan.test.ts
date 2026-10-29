/**
 * The proxy's decision order, as a table (C4-T3).
 *
 * Expected actions are written in each test from the rules in c4-metro-hosts.md (C4-D1, C4-D4 to C4-D7 and the
 * C4-K2 key point), never computed by the code under test. `isLiveSlug` is a fake that records its calls, because
 * "was the database consulted" is part of what some rows prove.
 *
 * C4-K2 turns the order-dependent rows green (the gate before the liveness check, redirects before the gate, the
 * fail-closed rows). The scaffold's placeholder serves everything as the default metro, so the prod and local rows
 * pass from it.
 */

import { describe, expect, it, vi } from "vitest";
import type { HostClass } from "./metro-host";
import { decideRequest, type RequestInput } from "./request-plan";

const outside: HostClass = { kind: "outside" };
const apex: HostClass = { kind: "apex" };
const bad: HostClass = { kind: "bad" };
const metro = (slug: string): HostClass => ({ kind: "metro", slug });

/** A request with sensible defaults (staging, default host, no cookie) that each test overrides. */
function plan(overrides: Partial<RequestInput> & { live?: boolean | null }) {
  const { live = true, ...rest } = overrides;
  const isLiveSlug = vi.fn(async () => live);
  const input: RequestInput = {
    env: "staging",
    defaultSlug: "msp",
    defaultSlugValid: true,
    passwordConfigured: true,
    host: metro("msp"),
    method: "GET",
    path: "/venue/3",
    cookieValid: false,
    isLiveSlug,
    ...rest,
  };
  return { result: decideRequest(input), isLiveSlug };
}

describe("production and local", () => {
  it("serves production pages with no noindex and no gate", async () => {
    // Proves (C4-D1): production is open; the gate and noindex are for non-production only.
    for (const host of [outside, metro("msp")]) {
      const { result } = plan({ env: "prod", host });
      expect(await result).toEqual({ action: "next", slug: "msp", noindex: false });
    }
  });

  it("serves local with noindex and no gate", async () => {
    // Proves (C4-D1, C4-D7): a laptop and the e2e stack are not worth a password, but are still kept out of search.
    const { result } = plan({ env: "local", host: outside, passwordConfigured: false });
    expect(await result).toEqual({ action: "next", slug: "msp", noindex: true });
  });
});

describe("the gate", () => {
  it("sends a page request without the cookie to the password form, with noindex", async () => {
    // Proves (C4-D6): an unauthenticated visitor to staging meets the gate, not the page.
    const { result } = plan({ host: outside });
    expect(await result).toEqual({ action: "redirect-gate", noindex: true });
  });

  it("lets a request with a valid cookie through as the default metro", async () => {
    const { result, isLiveSlug } = plan({ cookieValid: true });
    expect(await result).toEqual({ action: "next", slug: "msp", noindex: true });
    // Proves (C4-D4): the default slug is accepted from configuration without asking the API.
    expect(isLiveSlug).not.toHaveBeenCalled();
  });

  it.each(["/gate", "/gate/enter"])("lets %s through without a cookie, or nobody could log in", async (path) => {
    // Proves (C4-K2): the gate's own pages pass the gate.
    const { result } = plan({ path, method: path === "/gate" ? "GET" : "POST" });
    expect(await result).toEqual({ action: "next", slug: "msp", noindex: true });
  });

  it("denies a POST without the cookie and redirects a HEAD", async () => {
    // Proves (C4-D6): only GET and HEAD are sent to the form; a form post to a page route is refused outright.
    expect(await plan({ method: "POST" }).result).toEqual({ action: "deny", noindex: true });
    expect(await plan({ method: "HEAD" }).result).toEqual({ action: "redirect-gate", noindex: true });
  });
});

describe("redirects that reveal nothing from the database", () => {
  it.each([
    ["the apex", apex],
    ["a bad host", bad],
  ])("sends %s to the default metro's host without a login", async (_name, host) => {
    // Proves (C4-PR1-10): these hosts are classified from the host string and configuration alone, so redirecting
    // them before the gate leaks nothing and spares a stranger a login on a host that redirects anyway.
    const { result } = plan({ host });
    expect(await result).toEqual({ action: "redirect-metro", slug: "msp", noindex: true });
  });
});

describe("an unknown slug (C4-D4)", () => {
  it("gets the gate before anything is asked of the API", async () => {
    // Proves (C4-K2): without a cookie a stranger meets the gate on ANY in-zone slug, and the liveness check is
    // never made, so the redirect-versus-gate difference cannot be used to learn which metros exist.
    const { result, isLiveSlug } = plan({ host: metro("foo") });
    expect(await result).toEqual({ action: "redirect-gate", noindex: true });
    expect(isLiveSlug).not.toHaveBeenCalled();
  });

  it("is redirected to the default metro's host once logged in, when the API says it is not a metro", async () => {
    const { result, isLiveSlug } = plan({ host: metro("foo"), cookieValid: true, live: false });
    expect(await result).toEqual({ action: "redirect-metro", slug: "msp", noindex: true });
    expect(isLiveSlug).toHaveBeenCalledWith("foo");
  });

  it("is served as that metro when the API says it is live", async () => {
    // Proves: a second live metro would be reachable on its own host.
    const { result } = plan({ host: metro("chi"), cookieValid: true, live: true });
    expect(await result).toEqual({ action: "next", slug: "chi", noindex: true });
  });

  it("is served as the DEFAULT metro, not as the claimed one, when the API cannot answer", async () => {
    // Proves (C4-D4, C4-PR1-15): an outage fails open (no redirect storm), and the unverified slug never reaches
    // the page's canonical URLs or, later, the feature flags.
    const { result } = plan({ host: metro("foo"), cookieValid: true, live: null });
    expect(await result).toEqual({ action: "next", slug: "msp", noindex: true });
  });

  it("is served as the default metro on the gate's own pages, with no liveness check", async () => {
    // Proves: logging in on `foo.<zone>` works, and costs no API call.
    const { result, isLiveSlug } = plan({ host: metro("foo"), path: "/gate" });
    expect(await result).toEqual({ action: "next", slug: "msp", noindex: true });
    expect(isLiveSlug).not.toHaveBeenCalled();
  });
});

describe("fail closed (C4-D1, C4-D6, C4-PR1-13, C4-PR1-4)", () => {
  it("answers unavailable, with noindex, when APP_ENV cannot be read", async () => {
    // Proves: a gate that cannot tell what it guards must not open, and the 503 itself is kept out of search results.
    expect(await plan({ env: null }).result).toEqual({ action: "unavailable", noindex: true });
  });

  it.each(["staging", "dev"] as const)("answers unavailable in %s when no password is configured", async (env) => {
    // Proves: a missing variable is visible (503), never an open site.
    expect(await plan({ env, passwordConfigured: false }).result).toEqual({ action: "unavailable", noindex: true });
  });

  it("answers unavailable, in any environment, when DEFAULT_METRO_SLUG is set but malformed", async () => {
    // Proves (C4-PR1-4): a typo does not silently fall back to msp.
    for (const env of ["prod", "staging", "local"] as const) {
      expect(await plan({ env, defaultSlugValid: false }).result).toEqual({ action: "unavailable", noindex: true });
    }
  });

  it("does not need a password in production or local", async () => {
    // Proves: only gated environments require the variable.
    expect((await plan({ env: "prod", passwordConfigured: false }).result).action).toBe("next");
    expect((await plan({ env: "local", passwordConfigured: false }).result).action).toBe("next");
  });
});
