/**
 * The gate's login handler (C4-T6): the cookie it sets and the redirects it makes.
 *
 * Expected values come from c4-metro-hosts.md (C4-D6) and the cookie rules the `__Host-` prefix imposes (RFC 6265bis:
 * Secure, Path=/, no Domain). The environment is a plain object.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { gateCookieValue, passwordMatches } from "./gate";
import { handleGateEnter } from "./gate-enter";

// A pass-through wrapper, so one test can make the password comparison fail (a real scrypt failure, for example out
// of memory, cannot be provoked from outside) while every other test uses the real function.
vi.mock("./gate", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./gate")>();
  return { ...actual, passwordMatches: vi.fn(actual.passwordMatches) };
});

afterEach(() => {
  vi.restoreAllMocks();
});

const STAGING = {
  APP_ENV: "staging",
  VERCEL_ENV: "preview",
  VERCEL_GIT_COMMIT_REF: "main",
  SITE_GATE_PASSWORD: "correct horse",
};

function post(fields: Record<string, string>) {
  return new Request("https://msp.staging.example.com/gate/enter", {
    method: "POST",
    body: new URLSearchParams(fields),
  });
}

describe("a correct password", () => {
  it("sets a host-only, secure, HttpOnly cookie and redirects with 303 to a safe next", async () => {
    // Proves (C4-D6, C4-PR1-7): the cookie carries the name that forces host-only in the browser, Secure,
    // HttpOnly, SameSite=Lax, Path=/, a Max-Age, and NO Domain; the value is the one the proxy verifies; the
    // redirect is 303 so the browser follows with a GET.
    const response = await handleGateEnter(post({ password: "correct horse", next: "/venue/3?x=1" }), STAGING);
    expect(response.status).toBe(303);
    // A relative Location, so it stays on whatever host the visitor used (see gate-enter.ts).
    expect(response.headers.get("location")).toBe("/venue/3?x=1");
    const cookie = response.headers.get("set-cookie") ?? "";
    expect(cookie).toContain(`__Host-gate=${gateCookieValue("correct horse", "staging")}`);
    for (const attribute of ["Secure", "HttpOnly", "SameSite=lax", "Path=/", "Max-Age=2592000"]) {
      expect(cookie.toLowerCase()).toContain(attribute.toLowerCase());
    }
    expect(cookie.toLowerCase()).not.toContain("domain=");
  });

  it("sends an unsafe next to the front page", async () => {
    // Proves (C4-PR1-8): the redirect cannot leave the site, whatever the form carried.
    for (const next of ["//evil.com", "https://evil.com", "/\t/evil.com", "/.//evil.com", "/x/..//evil.com"]) {
      const response = await handleGateEnter(post({ password: "correct horse", next }), STAGING);
      expect(response.headers.get("location")).toBe("/");
    }
  });
});

describe("a wrong password", () => {
  it.each(["wrong", "correct hors", "correct horse!", ""])("%j is refused with 303 back to the form and no cookie", async (password) => {
    // Proves (C4-PR1-6, C4-PR1-7): any wrong guess, including ones of a different length, is a redirect with an
    // error flag and no Set-Cookie, never a 500.
    const response = await handleGateEnter(post({ password, next: "/venue/3" }), STAGING);
    expect(response.status).toBe(303);
    const location = new URL(response.headers.get("location") ?? "", "https://same-host.invalid");
    expect(location.origin).toBe("https://same-host.invalid"); // relative: no host of its own
    expect(location.pathname).toBe("/gate");
    expect(location.searchParams.get("error")).toBe("1");
    expect(location.searchParams.get("next")).toBe("/venue/3");
    expect(response.headers.get("set-cookie")).toBeNull();
  });

  it("treats a request that is not a form post as an empty password, and says so in the server log", async () => {
    // Proves (C4-D6, PR review): a body that cannot be read as a form is a refusal (a 303 back to the form, no cookie),
    // never an exception, AND it leaves a line in the server log so a broken client or a probe is visible instead of
    // swallowed. The line carries the reason but never the body, which could hold a password.
    const log = vi.spyOn(console, "error").mockImplementation(() => {});
    const response = await handleGateEnter(
      new Request("https://msp.staging.example.com/gate/enter", { method: "POST", body: "not a form" }),
      STAGING,
    );
    expect(response.status).toBe(303);
    expect(response.headers.get("set-cookie")).toBeNull();
    expect(log).toHaveBeenCalledTimes(1);
    const line = String(log.mock.calls[0]?.[0]);
    expect(line).toContain("[gate] could not read the login form");
    expect(line).not.toContain("not a form");
  });

  it("answers 500, logs it, and sets no cookie when the password check itself fails", async () => {
    // Proves (PR review, "no error handling here?"): if deriving or comparing the password throws (the scrypt step
    // failing is the realistic case), the handler answers a plain 500 with a log line instead of letting the exception
    // escape, and it never issues a cookie. Catches a handler that treats a failed check as success or crashes.
    const log = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.mocked(passwordMatches).mockRejectedValueOnce(new Error("scrypt out of memory"));
    const response = await handleGateEnter(post({ password: "correct horse", next: "/" }), STAGING);
    expect(response.status).toBe(500);
    expect(response.headers.get("set-cookie")).toBeNull();
    expect(String(log.mock.calls[0]?.[0])).toContain("[gate] password check failed: scrypt out of memory");
  });
});

describe("where there is nothing to log in to", () => {
  it("answers 503 when the password is unset, fail closed", async () => {
    // Proves (C4-D6): a gated environment with no password is unavailable, not open.
    const response = await handleGateEnter(post({ password: "x" }), { ...STAGING, SITE_GATE_PASSWORD: "" });
    expect(response.status).toBe(503);
  });

  it("answers 503 when APP_ENV is unreadable", async () => {
    // Proves (C4-D1): an environment the gate cannot identify is unavailable, not open.
    const response = await handleGateEnter(post({ password: "x" }), { ...STAGING, APP_ENV: "nope" });
    expect(response.status).toBe(503);
  });

  it("answers 404 in production and local, which have no gate", async () => {
    // Proves (C4-D1): the endpoint does not exist where there is no gate.
    const prod = await handleGateEnter(post({ password: "x" }), { APP_ENV: "prod", VERCEL_ENV: "production", SITE_GATE_PASSWORD: "x" });
    const local = await handleGateEnter(post({ password: "x" }), { APP_ENV: "local", SITE_GATE_PASSWORD: "x" });
    expect([prod.status, local.status]).toEqual([404, 404]);
  });
});
