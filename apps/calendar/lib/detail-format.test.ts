import { describe, expect, it } from "vitest";
import {
  AGE_LABELS,
  alcoholLabel,
  ARTIST_FORMAT_LABELS,
  httpUrlOrNull,
  mapsUrl,
  REPERTOIRE_LABELS,
  SEATING_LABELS,
  SETTING_LABELS,
  VENUE_TYPE_LABELS,
} from "./detail-format";

// Where the expected values come from: the Maps URL format is
// arch-initial.md §4 verbatim ("https://www.google.com/maps/search/?api=1&query="
// plus the encoded address); the percent-encodings are the standard ones
// (space %20, comma %2C, ampersand %26, hash %23); the labels are the
// wording of requirements-initial.md's Venue/Artist/Show field lists and
// the enum values in apps/api/app/enums.py.

// --- mapsUrl -----------------------------------------------------------------

describe("mapsUrl", () => {
  it("builds the Google Maps search URL from the address", () => {
    // Proves: the venue page's address link has the exact format
    // arch-initial.md §4 specifies, using the sample data's real address.
    expect(mapsUrl("1010 Washington Ave N, Minneapolis, MN 55401")).toBe(
      "https://www.google.com/maps/search/?api=1&query=1010%20Washington%20Ave%20N%2C%20Minneapolis%2C%20MN%2055401",
    );
  });

  it("encodes characters that would otherwise end the query parameter", () => {
    // Proves: an `&` or `#` in a scraped address can't truncate the query
    // or start a fragment — the address is data, not URL syntax.
    expect(mapsUrl("Tom & Jerry's #1")).toBe(
      "https://www.google.com/maps/search/?api=1&query=Tom%20%26%20Jerry's%20%231",
    );
  });
});

// --- httpUrlOrNull -------------------------------------------------------------

describe("httpUrlOrNull", () => {
  it.each(["https://x.example/a", "http://x.example", "https://x.example/p?q=1#top"])(
    "lets the http(s) URL %s through unchanged",
    (url) => {
      // Proves: ordinary links and images are untouched (the helper
      // decides WHETHER to render, never rewrites).
      expect(httpUrlOrNull(url)).toBe(url);
    },
  );

  it.each([
    ["javascript:alert(1)", "script URL (React 19 blocks it in href, but not in JSON-LD)"],
    ["data:image/png;base64,AAAA", "inline data"],
    ["file:///etc/passwd", "local file"],
    ["//evil.example/x", "protocol-relative — not absolute, so not parseable"],
    ["garbage", "not a URL at all"],
    ["", "empty"],
  ])("rejects %s (%s)", (url) => {
    // Proves: every URL the detail pages render from scraped data is
    // checked by ONE rule — http(s) only — so a hostile or mangled value
    // becomes "no link / no image" instead of reaching an href, an <img>
    // or the JSON-LD `image`. The values are model-extracted text from
    // venue websites: untrusted by the same reasoning as the JSON-LD
    // escaping (json-ld.test.ts).
    expect(httpUrlOrNull(url)).toBeNull();
  });

  it("treats null and undefined as 'no URL'", () => {
    // Proves: the generated types make these fields `string | null |
    // undefined` (api-contract.md §7); both mean "not stated".
    expect(httpUrlOrNull(null)).toBeNull();
    expect(httpUrlOrNull(undefined)).toBeNull();
  });
});

// --- labels --------------------------------------------------------------------

describe("enum labels", () => {
  it("spot-checks one label per map", () => {
    // Proves: raw enum values (`twenty_one_plus`) never reach the page.
    // Completeness is a COMPILE-time guarantee instead: each map is a
    // Record<Enum, string>, so a new enum value from `make types` is a
    // type error here, not a missing label in production.
    expect(AGE_LABELS.twenty_one_plus).toBe("21+");
    expect(AGE_LABELS.all_ages).toBe("All ages");
    expect(SETTING_LABELS.both).toBe("Indoor and outdoor");
    expect(SEATING_LABELS.both).toBe("Standing or seated");
    expect(VENUE_TYPE_LABELS.coffeehouse).toBe("Coffeehouse");
    expect(ARTIST_FORMAT_LABELS.duo).toBe("Duo");
    expect(REPERTOIRE_LABELS.both_other).toBe("Original and covers");
  });

  it("says whether alcohol is served in words", () => {
    // Proves: a boolean becomes a label; `false` is an answer ("Not
    // served"), not an absence (the page tests `!= null` before calling).
    expect(alcoholLabel(true)).toBe("Served");
    expect(alcoholLabel(false)).toBe("Not served");
  });
});
