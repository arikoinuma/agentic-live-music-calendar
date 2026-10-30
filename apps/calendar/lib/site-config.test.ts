/**
 * The proxy's configuration reader (C4-T3 input rows: unset and malformed defaults, C4-PR1-4).
 */

import { describe, expect, it } from "vitest";
import { readSiteConfig } from "./site-config";

describe("readSiteConfig", () => {
  it("defaults to msp, no zone and no password when nothing is set", () => {
    // Proves (C4-D2, C4-PR1-4): the e2e stack, `make dev` and a pre-domain deployment need no new variable.
    expect(readSiteConfig({})).toEqual({ zone: null, defaultSlug: "msp", defaultSlugValid: true, gatePassword: null });
  });

  it("normalises the zone and keeps a valid override of the default slug", () => {
    // Proves: a zone typed with capitals and a dot behaves as the plain zone, and a second metro's slug can be the default.
    const config = readSiteConfig({ SITE_ZONE: "Staging.Example.com.", DEFAULT_METRO_SLUG: "chi" });
    expect(config.zone).toBe("staging.example.com");
    expect(config.defaultSlug).toBe("chi");
    expect(config.defaultSlugValid).toBe(true);
  });

  it.each(["Bad_Slug", "ab", "www", "staging"])("reports a set but unusable default slug %j as invalid", (value) => {
    // Proves (C4-PR1-4): a typo (or a reserved word) in the variable is reported, not replaced by `msp`, so the
    // proxy can refuse to serve instead of guessing which metro was meant.
    const config = readSiteConfig({ DEFAULT_METRO_SLUG: value });
    expect(config.defaultSlug).toBe(value);
    expect(config.defaultSlugValid).toBe(false);
  });

  it("treats a blank password as unset and keeps a real one exactly as typed", () => {
    // Proves: an empty variable in a dashboard does not become a gate that accepts the empty password.
    expect(readSiteConfig({ SITE_GATE_PASSWORD: "   " }).gatePassword).toBeNull();
    expect(readSiteConfig({ SITE_GATE_PASSWORD: "" }).gatePassword).toBeNull();
    expect(readSiteConfig({ SITE_GATE_PASSWORD: " s3cret " }).gatePassword).toBe(" s3cret ");
  });
});
