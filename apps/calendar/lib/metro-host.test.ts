/**
 * Host to metro, as tables (C4-T1, C4-T2).
 *
 * Where the expected values come from: alpha-deployment-plan.md §4.2 (hostnames) and Dep-D2/Dep-D3 (zones, slug
 * shape, reserved words), written out below as literals. They are not computed by the code under test, so a parser
 * that is wrong cannot agree with its own tests.
 *
 * The rows that exercise the zone-stripping (`apex`, `metro`, `bad`, and an "outside" host that is *near* a zone,
 * such as `xdev.example.com`) are the C4-K1 key point; the no-zone rows cover the pre-domain state.
 */

import { describe, expect, it } from "vitest";
import reserved from "./reserved-slugs.json";
import { isReservedSlug, isValidSlug, normalizeHost, normalizeZone, parseHost } from "./metro-host";

const outside = { kind: "outside" } as const;
const apex = { kind: "apex" } as const;
const bad = { kind: "bad" } as const;
const metro = (slug: string) => ({ kind: "metro", slug }) as const;

describe("parseHost in a zone", () => {
  // [zone, host, expected]
  const rows = [
    // The slug is the one label before the zone.
    ["dev.example.com", "msp.dev.example.com", metro("msp")],
    ["staging.example.com", "msp.staging.example.com", metro("msp")],
    ["example.com", "msp.example.com", metro("msp")],
    // Case, port and a trailing dot do not change the answer.
    ["dev.example.com", "MSP.Dev.Example.com:443", metro("msp")],
    ["dev.example.com", "msp.dev.example.com.", metro("msp")],
    // The zone as typed in a dashboard is normalised (C4-PR1-14).
    ["Staging.Example.com.", "msp.staging.example.com", metro("msp")],
    // The apex is the bare zone.
    ["dev.example.com", "dev.example.com", apex],
    ["example.com", "example.com", apex],
    // A LABEL boundary: `xdev.example.com` is not in the `dev.example.com` zone, and neither is a lookalike.
    ["dev.example.com", "xdev.example.com", outside],
    ["dev.example.com", "msp.evildev.example.com", outside],
    ["dev.example.com", "example.com", outside],
    // Several labels, a reserved word and a bad shape are "bad", not metros.
    ["dev.example.com", "a.b.dev.example.com", bad],
    ["dev.example.com", "www.dev.example.com", bad],
    ["dev.example.com", "staging.dev.example.com", bad],
    ["dev.example.com", "m.dev.example.com", bad],
    ["dev.example.com", "-ab.dev.example.com", bad],
    // A staging-zone host seen by the production zone is two labels, so it is bad (not a metro called "msp.staging").
    ["example.com", "msp.staging.example.com", bad],
    // Hosts that belong to no zone: previews, localhost, the e2e stack, an IP, an IPv6 literal.
    ["staging.example.com", "foo-abc.vercel.app", outside],
    ["staging.example.com", "localhost:3000", outside],
    ["staging.example.com", "localhost:3100", outside],
    ["staging.example.com", "127.0.0.1:3100", outside],
    ["staging.example.com", "[::1]:3000", outside],
  ] as const;

  it.each(rows)("zone %s, host %s", (zone, host, expected) => {
    // Proves: the parser strips exactly the environment's zone on a label boundary and leaves every other host
    // alone, so previews and localhost keep working while a lookalike domain never parses as a metro.
    expect(parseHost(host, zone)).toEqual(expected);
  });
});

describe("parseHost with no zone configured", () => {
  it.each(["msp.dev.example.com", "localhost:3000", "foo-abc.vercel.app", "example.com", ""])(
    "%j is outside",
    (host) => {
      // Proves (C4-D2): before a domain exists, nothing is a metro host, apex or bad host, so the pre-domain
      // deployments on *.vercel.app behave exactly as they did before C4.
      expect(parseHost(host, null)).toEqual(outside);
      expect(parseHost(host, undefined)).toEqual(outside);
      expect(parseHost(host, "")).toEqual(outside);
    },
  );
});

describe("slug rules (C4-T2)", () => {
  it.each(["msp", "chi", "tyo", "chicago", "new-york", `a${"b".repeat(30)}c`])("accepts %s", (slug) => {
    // Proves: Dep-D3's codes and a longer alias fit the shape rule, including both length edges (3 and 32).
    expect(isValidSlug(slug)).toBe(true);
  });

  it.each(["ab", "1abc", "-abc", "abc-", "Abc", "ab_c", "a.b", "ms p", "a".repeat(33), ""])("refuses %j", (slug) => {
    // Proves: each way a label can be unfit to be a host name is refused (too short, leading digit or hyphen,
    // trailing hyphen, uppercase, underscore, a dot, a space, too long, empty).
    expect(isValidSlug(slug)).toBe(false);
  });

  it("refuses every reserved word, and the file holds the words the environments use", () => {
    // Proves: the list the parser consults is the shared file, and `dev` and `staging` are in it: the zone apex
    // `staging.<domain>` must never parse as a metro of the production zone (Dep-D3).
    for (const word of reserved) expect(isReservedSlug(word)).toBe(true);
    for (const word of ["www", "api", "admin", "dev", "staging"]) expect(reserved).toContain(word);
    expect(isReservedSlug("msp")).toBe(false);
  });
});

describe("the normalisers", () => {
  it("normalizeHost lowercases and strips a port and a trailing dot, and keeps an IPv6 literal whole", () => {
    // Proves: the parts of a Host header that vary without changing the address are removed, and the colons in an
    // IPv6 literal are not mistaken for a port separator.
    expect(normalizeHost("MSP.Example.com:8080")).toBe("msp.example.com");
    expect(normalizeHost("msp.example.com.")).toBe("msp.example.com");
    expect(normalizeHost("[::1]:3000")).toBe("[::1]");
  });

  it("normalizeZone lowercases, strips dots at both ends and turns blank into null", () => {
    // Proves (C4-PR1-14): a zone typed with capitals or a stray dot behaves as the plain zone; blank means none.
    expect(normalizeZone("Staging.Example.com.")).toBe("staging.example.com");
    expect(normalizeZone(".example.com")).toBe("example.com");
    expect(normalizeZone("  ")).toBeNull();
    expect(normalizeZone(undefined)).toBeNull();
  });
});
