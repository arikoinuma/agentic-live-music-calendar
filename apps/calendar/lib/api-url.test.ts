import { describe, expect, it } from "vitest";
import { apiUrl } from "./api-url";

// Expected URLs are written out by hand, not derived from apiUrl.

describe("apiUrl", () => {
  it("joins base and path", () => {
    // Proves: the base URL and path join with exactly one slash, the baseline all the other cases vary.
    expect(apiUrl("http://h", "/shows")).toBe("http://h/shows");
  });

  it.each([["http://h/"], ["http://h///"]])(
    "strips trailing slashes from the base (%s)",
    (base) => {
      // Proves: pasting "https://api.example.com/" into API_BASE_URL
      // can't produce "//shows", which FastAPI answers 404 — the same
      // trap lib/health.ts was written to avoid.
      expect(apiUrl(base, "/shows")).toBe("http://h/shows");
    },
  );

  it("preserves repeated query keys, in order", () => {
    // Proves: a multi-select filter becomes venue_id=1&venue_id=3, the
    // repeated-key form FastAPI's list[int] Query() parameter reads.
    expect(apiUrl("http://h", "/shows", { venue_id: [1, 3] })).toBe(
      "http://h/shows?venue_id=1&venue_id=3",
    );
  });

  it("omits undefined values and empty lists, and adds no '?' when nothing is left", () => {
    // Proves: unset filters vanish from the URL instead of becoming `venue_id=undefined`, so the server applies
    // its defaults (api-contract.md §3); and an all-empty query gives "/shows", not "/shows?".
    expect(
      apiUrl("http://h", "/shows", {
        start: undefined,
        venue_id: [],
        artist_id: undefined,
      }),
    ).toBe("http://h/shows");
    expect(apiUrl("http://h", "/shows", { start: "2026-10-01", end: undefined })).toBe(
      "http://h/shows?start=2026-10-01",
    );
  });

  it("URL-encodes values", () => {
    // Proves: a value containing `&` or `=` can't smuggle in an extra parameter or break the query.
    expect(apiUrl("http://h", "/shows", { q: "a&b=c" })).toBe(
      "http://h/shows?q=a%26b%3Dc",
    );
  });

  it("keeps the caller's key order", () => {
    // Proves: keys come out in the order given, so the client's URLs are stable and its tests can compare strings.
    expect(apiUrl("http://h", "/shows", { start: "a", end: "b", venue_id: [2] })).toBe(
      "http://h/shows?start=a&end=b&venue_id=2",
    );
  });
});
