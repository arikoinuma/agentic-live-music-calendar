/**
 * The site's own address and the layout metadata built from it (C4-T7).
 *
 * Expected values are literals from C4-D8: the origin is `https://<slug>.<zone>`, absent without a zone.
 */

import { describe, expect, it } from "vitest";
import { isNoindex, siteMetadata, siteOrigin } from "./site-url";

describe("siteOrigin", () => {
  it("builds https://<slug>.<zone> from configuration", () => {
    // Proves (C4-D8): the origin comes from the zone we configured and the slug, so a forged Host header cannot
    // change what a canonical URL says. A zone typed with capitals and a dot is normalised first.
    expect(siteOrigin("staging.example.com", "msp")).toBe("https://msp.staging.example.com");
    expect(siteOrigin("Staging.Example.com.", "msp")).toBe("https://msp.staging.example.com");
  });

  it("is null when no zone is configured", () => {
    // Proves: before a domain exists nothing is emitted, rather than a wrong address.
    expect(siteOrigin(null, "msp")).toBeNull();
    expect(siteOrigin(undefined, "msp")).toBeNull();
    expect(siteOrigin("", "msp")).toBeNull();
  });
});

describe("siteMetadata", () => {
  it("sets metadataBase and a relative canonical only when an origin exists", () => {
    // Proves (C4-D8, C4-PR1-16): with an origin the layout names the site and each route canonicalises itself;
    // without one it sets neither, because a relative canonical with no metadataBase fails the Next build.
    const withOrigin = siteMetadata({ env: "prod", origin: "https://msp.example.com" });
    expect(String(withOrigin.metadataBase)).toBe("https://msp.example.com/");
    expect(withOrigin.alternates).toEqual({ canonical: "./" });
    const without = siteMetadata({ env: "prod", origin: null });
    expect(without.metadataBase).toBeUndefined();
    expect(without.alternates).toBeUndefined();
  });

  it.each(["staging", "dev", "local", null] as const)("marks %s as noindex", (env) => {
    // Proves (C4-D7): every environment except production, and an unreadable one, asks to stay out of search results.
    expect(isNoindex(env)).toBe(true);
    expect(siteMetadata({ env, origin: null }).robots).toEqual({ index: false, follow: false });
  });

  it("leaves production indexable", () => {
    // Proves: no robots directive is set for production, so it can be indexed once it is public (C11).
    expect(isNoindex("prod")).toBe(false);
    expect(siteMetadata({ env: "prod", origin: null }).robots).toBeUndefined();
  });
});
