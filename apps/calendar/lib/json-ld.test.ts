import { describe, expect, it, vi } from "vitest";
import showDetail from "./fixtures/show-detail.json";
import venueDetail from "./fixtures/venue-detail.json";
import {
  eventDateTime,
  eventEndDateTime,
  jsonLdScriptContent,
  showJsonLd,
} from "./json-ld";
import type { ShowDetail, ShowSummary, VenueDetail } from "./types";

// Where the expected values come from.
//  - UTC offsets are US daylight-saving rules for America/Chicago, worked
//    out by hand: CDT (-05:00) until 2:00 AM on Sunday 2026-11-01, then CST
//    (-06:00); the next spring-forward is 2:00 AM on 2027-03-14, when
//    02:00-02:59 does not exist.
//  - "After midnight" is Ari's rule (requirements-initial.md, "Show",
//    October 11): a time before 5:00 AM belongs to the night it is listed
//    under but happens on the NEXT calendar day.
//  - The show is lib/fixtures/show-detail.json (id 2: Zhora Darling,
//    2026-09-30, 21:00-23:30, Nooky Jones then Beasthead, $18 advance /
//    $22 day, a poster); the venue is venue-detail.json (Zhora Darling, with
//    an address).
// None are read back from json-ld.ts.

const CHICAGO = "America/Chicago";
const show = showDetail as ShowDetail;
const venue = venueDetail as VenueDetail;
const ctx = { venue, timeZone: CHICAGO };
// The tests below that are about something OTHER than the UTC offset (what
// is offered, what the event is named, which image is allowed) run with no
// zone, so they don't depend on Gap A (the line that attaches the zone) and
// stay green while it is open — each still proves only its own rule. Tests
// that assert an offset use `ctx`.
const noZone = { venue, timeZone: null };

// --- eventDateTime (Gap A) ---------------------------------------------------------------

describe("eventDateTime", () => {
  it.each([
    ["2026-10-07", "20:00:00", "2026-10-07T20:00:00-05:00", "CDT"],
    ["2026-12-05", "20:00:00", "2026-12-05T20:00:00-06:00", "CST — the offset comes from the date, not a constant"],
    ["2026-10-07", "01:00:00", "2026-10-08T01:00:00-05:00", "after midnight: Wednesday night's show, Thursday morning's instant"],
    ["2026-10-31", "01:30:00", "2026-11-01T01:30:00-05:00", "01:30 on Nov 1 happens twice (fall back); the earlier, CDT, one"],
    ["2027-03-13", "02:30:00", "2027-03-14T03:30:00-05:00", "after midnight lands in the spring-forward gap; the clock moves forward an hour"],
  ])("%s %s -> %s (%s)", (date, time, expected) => {
    // Proves: startDate names a real instant. A show's date and time are
    // wall-clock values with no zone (right for display); JSON-LD needs the
    // venue's UTC offset, which depends on the DATE, and the after-midnight
    // rule moves the calendar date before the zone is attached. This is
    // the second and last place the metro's timezone matters (the first is
    // "today", dates.ts).
    expect(eventDateTime(date, time, CHICAGO)).toBe(expected);
  });

  it("is a bare date when the listing gave no time", () => {
    // Proves: "not stated" stays not stated — a bare date is valid
    // schema.org, and an invented midnight would be a wrong answer someone
    // acts on (api-contract.md §4).
    expect(eventDateTime("2026-10-07", null, CHICAGO)).toBe("2026-10-07");
    expect(eventDateTime("2026-10-07", undefined, CHICAGO)).toBe("2026-10-07");
  });

  it("falls back to local time with no offset when the zone is unknown", () => {
    // Proves: a missing metro or a typo'd zone costs the offset, not the
    // page — better than guessing a zone or failing. The after-midnight
    // date shift still applies.
    const quiet = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(eventDateTime("2026-10-07", "20:00:00", null)).toBe("2026-10-07T20:00:00");
    expect(eventDateTime("2026-10-07", "20:00:00", "Not/A_Zone")).toBe("2026-10-07T20:00:00");
    expect(eventDateTime("2026-10-07", "01:00:00", null)).toBe("2026-10-08T01:00:00");
    quiet.mockRestore();
  });
});

// --- eventEndDateTime ----------------------------------------------------------------------

describe("eventEndDateTime", () => {
  it.each([
    { date: "2026-10-07", start: "22:00:00", end: "00:30:00", expected: "2026-10-08T00:30:00-05:00", why: "ends after midnight" },
    { date: "2026-10-07", start: "18:00:00", end: "23:00:00", expected: "2026-10-07T23:00:00-05:00", why: "same night" },
    { date: "2026-10-07", start: "21:00:00", end: "06:00:00", expected: "2026-10-08T06:00:00-05:00", why: "earlier than its start, not after midnight: the next morning" },
    { date: "2026-10-07", start: "01:00:00", end: "03:00:00", expected: "2026-10-08T03:00:00-05:00", why: "both after midnight" },
    { date: "2026-10-07", start: "01:00:00", end: "06:00:00", expected: "2026-10-08T06:00:00-05:00", why: "starts after midnight, ends mid-morning: still the 8th, not the 9th" },
    { date: "2026-10-07", start: null, end: "00:30:00", expected: "2026-10-08T00:30:00-05:00", why: "no start: only the after-midnight rule" },
    { date: "2026-10-07", start: null, end: "23:00:00", expected: "2026-10-07T23:00:00-05:00", why: "no start, evening end" },
  ])("$date $start to $end -> $expected ($why)", ({ date, start, end, expected }) => {
    // Proves: requirements-initial.md's rule ("An end time earlier than its
    // start is the next morning") on top of the after-midnight rule, with
    // no throw and no 'undefined' in the string when the start is missing.
    expect(eventEndDateTime(date, start, end, CHICAGO)).toBe(expected);
  });

  it("is null when there is no end time", () => {
    // Proves: the caller omits the key rather than printing a made-up end.
    expect(eventEndDateTime("2026-10-07", "20:00:00", null, CHICAGO)).toBeNull();
    expect(eventEndDateTime("2026-10-07", "20:00:00", undefined, CHICAGO)).toBeNull();
  });
});

// --- showJsonLd ------------------------------------------------------------------------------

describe("showJsonLd", () => {
  it("describes a show as a schema.org MusicEvent", () => {
    // Proves: the whole object for the fixture show, field by field —
    // type, name from the lineup in performance order, offset dates,
    // performers, venue with address, the poster, and two labelled offers
    // carrying the API's price STRINGS (never parseFloat'd).
    expect(showJsonLd(show, ctx)).toEqual({
      "@context": "https://schema.org",
      "@type": "MusicEvent",
      name: "Nooky Jones, Beasthead",
      startDate: "2026-09-30T21:00:00-05:00",
      endDate: "2026-09-30T23:30:00-05:00",
      eventStatus: "https://schema.org/EventScheduled",
      eventAttendanceMode: "https://schema.org/OfflineEventAttendanceMode",
      location: {
        "@type": "MusicVenue",
        name: "Zhora Darling",
        address: "1010 Washington Ave N, Minneapolis, MN 55401",
      },
      performer: [
        { "@type": "MusicGroup", name: "Nooky Jones" },
        { "@type": "MusicGroup", name: "Beasthead" },
      ],
      image: "https://example.com/posters/nooky.jpg",
      offers: [
        { "@type": "Offer", name: "Advance", price: "18.00", priceCurrency: "USD" },
        { "@type": "Offer", name: "Door", price: "22.00", priceCurrency: "USD" },
      ],
    });
  });

  it("falls back to the show's own venue name, with no address, when the venue detail is missing", () => {
    // Proves: the show page renders without an address when the venue
    // lookup misses (plan review #1c), and the JSON-LD says the same.
    const ld = showJsonLd(show, { venue: null, timeZone: null });
    expect(ld.location).toEqual({ "@type": "MusicVenue", name: "Zhora Darling" });
  });

  describe("offers", () => {
    const priced = (patch: Partial<ShowSummary>): ShowSummary => ({
      ...show,
      admission_advance: null,
      admission_day: null,
      free_admission: null,
      ...patch,
    });

    it("is one zero-price offer for a free show", () => {
      // Proves: free is stated only when the listing says so
      // (`free_admission: true`), and then it is a price of "0".
      expect(showJsonLd(priced({ free_admission: true }), noZone).offers).toEqual([
        { "@type": "Offer", price: "0", priceCurrency: "USD" },
      ]);
    });

    it("is one unlabelled offer for a lone day price", () => {
      // Proves: an unlabelled price is stored as the day price
      // (requirements, "Agent Extraction: Fields"), so it isn't called "Door".
      expect(showJsonLd(priced({ admission_day: "10.00" }), noZone).offers).toEqual([
        { "@type": "Offer", price: "10.00", priceCurrency: "USD" },
      ]);
    });

    it("is one 'Advance' offer for a lone advance price", () => {
      // Proves: the JSON-LD says what formatAdmission says on the page
      // ("$15 adv") — plan review #1a.
      expect(showJsonLd(priced({ admission_advance: "15.00" }), noZone).offers).toEqual([
        { "@type": "Offer", name: "Advance", price: "15.00", priceCurrency: "USD" },
      ]);
    });

    it.each([
      [{}],
      [{ free_admission: false }],
    ])("has NO offers key at all when nothing is stated (%j)", (patch) => {
      // Proves: the contract's rule (api-contract.md §4) reaches the
      // search-engine view: all-null is "not stated", never a price of 0
      // and never "free". Asserted as an absent key, not a falsy value.
      expect(showJsonLd(priced(patch), noZone)).not.toHaveProperty("offers");
    });
  });

  it("names a show with no lineup after its venue and lists no performers", () => {
    // Proves: an empty lineup (nothing enforces "one or more") still gets
    // a name, and no empty `performer` array is emitted.
    const ld = showJsonLd({ ...show, lineup: [] }, noZone);
    expect(ld.name).toBe("Live music at Zhora Darling");
    expect(ld).not.toHaveProperty("performer");
  });

  it("uses a bare date for a show with no start time, and omits endDate without an end", () => {
    // Proves: missing times don't produce 'undefined' text or an invented
    // time anywhere in the object.
    const ld = showJsonLd({ ...show, start_time: null, end_time: null }, noZone);
    expect(ld.startDate).toBe("2026-09-30");
    expect(ld).not.toHaveProperty("endDate");
  });

  it.each([
    ["javascript:alert(1)"],
    ["data:image/png;base64,AAAA"],
    [null],
  ])("omits `image` for %s", (image_url) => {
    // Proves: only an http(s) image URL reaches the JSON-LD `image`, which
    // a search engine will fetch (httpUrlOrNull, detail-format.test.ts).
    expect(showJsonLd({ ...show, image_url }, noZone)).not.toHaveProperty("image");
  });
});

// --- jsonLdScriptContent -----------------------------------------------------------------------

describe("jsonLdScriptContent", () => {
  it("never emits a '<', and decodes back to the original", () => {
    // Proves: text scraped from venue sites can't close the <script> tag it
    // is printed inside. Next's JSON-LD guide warns that JSON.stringify
    // doesn't sanitise; show and artist names here are model-extracted from
    // arbitrary web pages — exactly the untrusted text it means. The
    // escape (< -> <) is lossless: JSON.parse gives the name back.
    const hostile = "</script><script>alert(1)</script>";
    const out = jsonLdScriptContent({ name: hostile });
    expect(out).not.toContain("<");
    expect(JSON.parse(out)).toEqual({ name: hostile });
  });
});
