/**
 * The gate's pure parts (C4-T4): who it applies to, the cookie, the comparisons and the safe redirect.
 *
 * Expected values come from the rules in docs/dev/implementations/c4-metro-hosts.md (C4-D1, C4-D6) and from the
 * WHATWG URL rules the redirect check depends on, written out below. Nothing here reads an answer from the code under
 * test, except where a test asserts that two outputs differ or agree with each other.
 */

import { timingSafeEqual } from "node:crypto";
import { describe, expect, it, vi } from "vitest";
import {
  GATE_COOKIE,
  gateApplies,
  gateCookieValue,
  isGateCookieValid,
  isGatePath,
  passwordMatches,
  safeNextPath,
} from "./gate";

// A pass-through spy on node:crypto's timingSafeEqual (`vi.spyOn` on an ESM namespace does not work), so a test can
// assert that the comparisons really go through it rather than through `===` (C4-PR1-6).
vi.mock("node:crypto", async (importOriginal) => {
  const actual = await importOriginal<typeof import("node:crypto")>();
  return { ...actual, timingSafeEqual: vi.fn(actual.timingSafeEqual) };
});

describe("who the gate applies to (C4-D1)", () => {
  it("covers staging and dev, and not prod or local", () => {
    // Proves: production is open (public at C11), and a laptop or the e2e stack is not worth a password.
    expect(gateApplies("staging")).toBe(true);
    expect(gateApplies("dev")).toBe(true);
    expect(gateApplies("prod")).toBe(false);
    expect(gateApplies("local")).toBe(false);
  });

  it("treats /gate and everything under it as the gate's own pages, and nothing that merely starts with it", () => {
    // Proves: the form and its POST pass without a cookie (or nobody could log in), while /gateway does not.
    expect(isGatePath("/gate")).toBe(true);
    expect(isGatePath("/gate/enter")).toBe(true);
    expect(isGatePath("/gateway")).toBe(false);
    expect(isGatePath("/venue/3")).toBe(false);
  });
});

describe("the cookie", () => {
  it("is named with the __Host- prefix, which makes the browser enforce host-only", () => {
    // Proves: the name is the one that forces Secure, Path=/ and no Domain (Dep plan §4.2: cookies are host-only).
    expect(GATE_COOKIE).toBe("__Host-gate");
  });

  it("is deterministic for a password and environment, and differs across both", () => {
    // Proves: the same inputs issue the same cookie (so it can be verified without a store), and a different
    // password or a different environment issues a different one (a staging cookie is no use against dev).
    const a = gateCookieValue("correct horse", "staging");
    expect(gateCookieValue("correct horse", "staging")).toBe(a);
    expect(gateCookieValue("another password", "staging")).not.toBe(a);
    expect(gateCookieValue("correct horse", "dev")).not.toBe(a);
  });

  it("validates its own value and refuses a missing, tampered, other-environment or wrong-length cookie", () => {
    // Proves: only the cookie this password issues in this environment passes; a cookie of any other length is
    // simply invalid and never throws (timingSafeEqual would throw on unequal buffers if the values were compared
    // directly, which would turn a guess into a 500, C4-PR1-6).
    const good = gateCookieValue("correct horse", "staging");
    expect(isGateCookieValid(good, "correct horse", "staging")).toBe(true);
    expect(isGateCookieValid(undefined, "correct horse", "staging")).toBe(false);
    expect(isGateCookieValid("", "correct horse", "staging")).toBe(false);
    expect(isGateCookieValid(`${good}0`, "correct horse", "staging")).toBe(false);
    expect(isGateCookieValid(good.slice(0, -1), "correct horse", "staging")).toBe(false);
    expect(isGateCookieValid(`${good.slice(0, -1)}${good.endsWith("0") ? "1" : "0"}`, "correct horse", "staging")).toBe(false);
    expect(isGateCookieValid(good, "correct horse", "dev")).toBe(false);
    expect(isGateCookieValid(good, "rotated password", "staging")).toBe(false);
  });
});

describe("the password comparison", () => {
  it("accepts the exact password and refuses everything else, including a different length, without throwing", () => {
    // Proves (C4-PR1-6): equality of the whole value, not a prefix; a longer, shorter or empty guess is a plain
    // "no" (the digest step makes the compared buffers equal in length).
    expect(passwordMatches("correct horse", "correct horse")).toBe(true);
    expect(passwordMatches("correct hors", "correct horse")).toBe(false);
    expect(passwordMatches("correct horse!", "correct horse")).toBe(false);
    expect(passwordMatches("", "correct horse")).toBe(false);
    expect(passwordMatches("correct horse", "")).toBe(false);
  });
});

describe("constant-time comparison", () => {
  it("compares the password and the cookie through timingSafeEqual, on buffers of equal length", () => {
    // Proves (C4-PR1-6): both comparisons call node's timingSafeEqual (a `===` would not), and always on equal-length
    // buffers (the digests), which is why a guess of any length cannot make it throw. Catches the mutation "compare
    // with ===", which no behavioural test can see because `===` returns the same booleans.
    const spy = vi.mocked(timingSafeEqual);
    spy.mockClear();
    passwordMatches("a", "a much longer configured password");
    isGateCookieValid("short", "pw", "staging");
    expect(spy).toHaveBeenCalledTimes(2);
    for (const [a, b] of spy.mock.calls) expect((a as Buffer).length).toBe((b as Buffer).length);
  });
});

describe("safeNextPath (C4-PR1-8)", () => {
  it.each([
    ["/", "/"],
    ["/venue/3?x=1", "/venue/3?x=1"],
    ["/day/2026-10-07?sort=artist", "/day/2026-10-07?sort=artist"],
  ])("keeps the same-site path %s", (input, expected) => {
    // Proves: an ordinary page, with its query, survives the login redirect.
    expect(safeNextPath(input)).toBe(expected);
  });

  it.each([
    "//evil.com",
    "/\\evil.com",
    "\\\\evil.com",
    "https://evil.com/x",
    "javascript:alert(1)",
    "/\t/evil.com",
    "/\n/evil.com",
    "",
    null,
    undefined,
  ])("sends %j to the front page", (input) => {
    // Proves: anything that reaches for another site (a protocol-relative URL, an absolute one, a backslash trick,
    // a script URL, and the tab and newline variants the WHATWG parser deletes before it resolves the host) lands on
    // `/`, never on the other site. A string-prefix check passes `/\t/evil.com`; a parse-based one does not.
    expect(safeNextPath(input)).toBe("/");
  });

  it("keeps a percent-encoded tab as plain path text on this site, and never produces a host", () => {
    // Proves: `/%09/evil.com` is an ordinary path (the tab is encoded, so the parser does not delete it), and the
    // result resolves on our own origin: the property that matters is "cannot name another host", not "is refused".
    const result = safeNextPath("/%09/evil.com");
    expect(new URL(result, "https://gate.invalid").origin).toBe("https://gate.invalid");
  });

  it("never sends the visitor back to the gate", () => {
    // Proves: logging in cannot loop on the form; the front page is the destination.
    expect(safeNextPath("/gate")).toBe("/");
    expect(safeNextPath("/gate/enter?x=1")).toBe("/");
  });
});
