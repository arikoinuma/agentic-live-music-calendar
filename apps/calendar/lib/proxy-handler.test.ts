/**
 * The proxy's glue with real `NextRequest`s (C4-T5): the wiring the pure tests cannot see.
 *
 * `request-plan.test.ts` proves the decisions; this proves that the glue gathers the right facts, performs the
 * decision, and does the two things only the glue can: sets `X-Robots-Tag` on every non-production response, and
 * replaces any client-sent `x-metro-slug`. Environment variables are a plain object, and the API question is a fake.
 *
 * Expected values come from c4-metro-hosts.md (C4-D1 to C4-D8). A forwarded request's headers are read from
 * `x-middleware-request-*`, which is how `NextResponse.next({ request: { headers } })` reports what it will pass on.
 */

import { NextRequest } from "next/server";
import { describe, expect, it, vi } from "vitest";
import { gateCookieValue } from "./gate";
import { handleRequest } from "./proxy-handler";

const STAGING = {
  APP_ENV: "staging",
  VERCEL_ENV: "preview",
  VERCEL_GIT_COMMIT_REF: "main",
  SITE_ZONE: "staging.example.com",
  SITE_GATE_PASSWORD: "correct horse",
};
const PROD = { APP_ENV: "prod", VERCEL_ENV: "production", SITE_ZONE: "example.com" };

function request(host: string, path = "/", init: { cookie?: string; headers?: Record<string, string>; method?: string } = {}) {
  const headers: Record<string, string> = { host, ...(init.headers ?? {}) };
  if (init.cookie) headers.cookie = init.cookie;
  return new NextRequest(`https://${host}${path}`, { method: init.method ?? "GET", headers });
}

const loggedIn = `__Host-gate=${gateCookieValue("correct horse", "staging")}`;
const robots = (response: Response) => response.headers.get("x-robots-tag");

describe("noindex on every non-production response", () => {
  it("is set on a page, a redirect to the gate, a redirect to a metro host and the 503", async () => {
    // Proves (C4-D7): the header is attached by the glue to whatever the plan produced, not only to pages.
    const page = await handleRequest(request("msp.staging.example.com", "/", { cookie: loggedIn }), { env: STAGING });
    const gate = await handleRequest(request("msp.staging.example.com", "/venue/3"), { env: STAGING });
    const apex = await handleRequest(request("staging.example.com", "/venue/3"), { env: STAGING });
    const broken = await handleRequest(request("msp.staging.example.com"), { env: { ...STAGING, SITE_GATE_PASSWORD: "" } });
    for (const response of [page, gate, apex, broken]) expect(robots(response)).toBe("noindex, nofollow");
    expect([page.status, gate.status, apex.status, broken.status]).toEqual([200, 307, 307, 503]);
  });

  it("is absent in production", async () => {
    // Proves: production is indexable once public; its pages carry no X-Robots-Tag.
    const response = await handleRequest(request("msp.example.com", "/venue/3"), { env: PROD });
    expect(response.status).toBe(200);
    expect(robots(response)).toBeNull();
  });
});

describe("the metro slug header", () => {
  it("drops a client-sent x-metro-slug and sets the resolved one", async () => {
    // Proves (C4-D8): a request cannot choose its own slug. The attacker's value is replaced by the proxy's; with
    // the default host it is the default slug.
    const response = await handleRequest(
      request("msp.staging.example.com", "/", { cookie: loggedIn, headers: { "x-metro-slug": "evil" } }),
      { env: STAGING },
    );
    expect(response.headers.get("x-middleware-request-x-metro-slug")).toBe("msp");
  });

  it("is the default slug on a host outside every zone, such as a preview or localhost", async () => {
    // Proves (C4-D2): previews on *.vercel.app and the e2e stack on localhost:3100 resolve to the default metro.
    const response = await handleRequest(request("localhost:3100"), { env: { APP_ENV: "local" } });
    expect(response.headers.get("x-middleware-request-x-metro-slug")).toBe("msp");
  });
});

describe("the gate in the glue", () => {
  it("redirects an unauthenticated page request to /gate with the visitor's path in `next`", async () => {
    // Proves: the Location is the gate on the same host, and `next` carries the path and query for after login.
    const response = await handleRequest(request("msp.staging.example.com", "/venue/3?x=1"), { env: STAGING });
    const location = new URL(response.headers.get("location") ?? "");
    expect(location.host).toBe("msp.staging.example.com");
    expect(location.pathname).toBe("/gate");
    expect(location.searchParams.get("next")).toBe("/venue/3?x=1");
  });

  it("lets the gate's own page through, and accepts a valid cookie", async () => {
    // Proves: /gate needs no cookie, and the cookie the login sets is the one the proxy recognises.
    expect((await handleRequest(request("msp.staging.example.com", "/gate"), { env: STAGING })).status).toBe(200);
    expect((await handleRequest(request("msp.staging.example.com", "/", { cookie: loggedIn }), { env: STAGING })).status).toBe(200);
  });

  it("refuses a cookie for another environment's password", async () => {
    // Proves: a tampered or wrong-password cookie is just 'not logged in'.
    const stale = `__Host-gate=${gateCookieValue("another password", "staging")}`;
    const response = await handleRequest(request("msp.staging.example.com", "/", { cookie: stale }), { env: STAGING });
    expect(response.status).toBe(307);
  });
});

describe("hosts", () => {
  it("redirects the apex, keeping the path, to the default metro's host built from configuration", async () => {
    // Proves (C4-D5, C4-D8): the target is https://<default slug>.<zone><path>, and it is built from the zone we
    // configured, not from the request's Host.
    const response = await handleRequest(request("staging.example.com", "/venue/3?x=1"), { env: STAGING });
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("https://msp.staging.example.com/venue/3?x=1");
  });

  it("asks the API about an unknown slug only after login, and redirects when it is not a metro", async () => {
    // Proves (C4-D4): the liveness question is asked once, for the claimed slug, and 'not live' redirects to the default host.
    const isLiveSlug = vi.fn(async () => false);
    const before = await handleRequest(request("foo.staging.example.com"), { env: STAGING, isLiveSlug });
    expect(before.headers.get("location")).toContain("/gate");
    expect(isLiveSlug).not.toHaveBeenCalled();
    const after = await handleRequest(request("foo.staging.example.com", "/", { cookie: loggedIn }), { env: STAGING, isLiveSlug });
    expect(isLiveSlug).toHaveBeenCalledExactlyOnceWith("foo");
    expect(after.headers.get("location")).toBe("https://msp.staging.example.com/");
  });
});

describe("misconfiguration", () => {
  it("answers 503 when APP_ENV is invalid, and never throws", async () => {
    // Proves (C4-D1): an unreadable environment fails closed.
    const response = await handleRequest(request("msp.staging.example.com"), { env: { ...STAGING, APP_ENV: "prodution" } });
    expect(response.status).toBe(503);
    expect(robots(response)).toBe("noindex, nofollow");
  });

  it("answers 503 when DEFAULT_METRO_SLUG is set but malformed", async () => {
    // Proves (C4-PR1-4): a typo is visible, not a quiet fall back to msp.
    const response = await handleRequest(request("msp.example.com"), { env: { ...PROD, DEFAULT_METRO_SLUG: "Bad_Slug" } });
    expect(response.status).toBe(503);
  });
});
