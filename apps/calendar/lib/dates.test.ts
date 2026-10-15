import { Temporal } from "@js-temporal/polyfill";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  formatClockTime,
  formatDayHeading,
  formatMonthLabel,
  formatShowTime,
  isAfterMidnight,
  metroToday,
  metroTodayOrNull,
  nightSortKey,
} from "./dates";

// Where the expected values come from: none of them is read back from the
// code under test. Weekdays and dates are worked out from a calendar
// (2026-10-12 is a Monday, so the 9th is a Friday and the 7th a Wednesday;
// 2028-02-29 is a Tuesday), clock times from the rule in
// requirements-initial.md ("Show": a time before 5:00 AM is after midnight
// of the night it is listed under), and UTC offsets from the US rules
// (Central is UTC-5 in daylight time until 07:00Z on 2026-11-01, UTC-6
// after).

afterEach(() => vi.restoreAllMocks());

// --- metroToday (Gap A) -----------------------------------------------------

describe("metroToday", () => {
  const at = (iso: string) => Temporal.Instant.from(iso);

  it("is the metro's date when UTC has already rolled to the next day", () => {
    // Proves: "today" is a question about a PLACE. 02:30Z on the 13th is
    // 21:30 CDT on the 12th. The Next server runs in UTC on Vercel, so a
    // zone-less "now" says the 13th from 7 PM Central on — the row marked
    // "Today" would be tomorrow's.
    expect(metroToday("America/Chicago", at("2026-10-13T02:30:00Z")).toString()).toBe("2026-10-12");
  });

  it("is the same date in the afternoon", () => {
    // Proves: the common case isn't broken by the fix (17:00Z is 12:00 CDT).
    expect(metroToday("America/Chicago", at("2026-10-12T17:00:00Z")).toString()).toBe("2026-10-12");
  });

  it("uses the winter offset after the fall-back change", () => {
    // Proves: the zone's rules are applied, not a fixed offset. DST ended
    // at 07:00Z on 2026-11-01, so 05:30Z on the 2nd is 23:30 CST (UTC-6)
    // on the 1st. A hard-coded -5 would say 00:30 on the 2nd.
    expect(metroToday("America/Chicago", at("2026-11-02T05:30:00Z")).toString()).toBe("2026-11-01");
  });

  it("is ahead of UTC for a zone east of it", () => {
    // Proves: it works in both directions. 12:00Z on the 12th is 01:00 on
    // the 13th in Auckland (UTC+13 in October).
    expect(metroToday("Pacific/Auckland", at("2026-10-12T12:00:00Z")).toString()).toBe("2026-10-13");
  });
});

describe("metroTodayOrNull", () => {
  it("matches metroToday for a valid zone", () => {
    // Proves: the safe wrapper is transparent when the zone is fine.
    const now = Temporal.Instant.from("2026-10-13T02:30:00Z");
    expect(metroTodayOrNull("America/Chicago", now)?.toString()).toBe("2026-10-12");
  });

  it("returns null, and logs, for an unknown zone instead of throwing", () => {
    // Proves: the metro's timezone is free text in the database, and the
    // "Today" label is cosmetic. A typo must cost the label, not the whole
    // calendar page (plan review #9).
    const log = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(metroTodayOrNull("Not/A_Zone")).toBeNull();
    expect(log).toHaveBeenCalled();
  });
});

// --- the after-midnight rule (Gap B) ---------------------------------------

describe("isAfterMidnight", () => {
  it.each(["00:00:00", "01:00:00", "04:59:00"])("is true at %s", (t) => {
    // Proves: anything before the 5:00 AM cut-off belongs to the previous night.
    expect(isAfterMidnight(Temporal.PlainTime.from(t))).toBe(true);
  });

  it.each(["05:00:00", "12:00:00", "20:00:00", "23:59:00"])("is false at %s", (t) => {
    // Proves: 5:00 AM itself is NOT after midnight (the cut-off is
    // exclusive: "before 5:00 AM"), so a morning show isn't pushed to the
    // previous night.
    expect(isAfterMidnight(Temporal.PlainTime.from(t))).toBe(false);
  });
});

describe("nightSortKey", () => {
  it("orders the evening, then after-midnight shows, then untimed", () => {
    // Proves: a show listed under Friday at 1:00 AM sorts AFTER Friday's
    // 8 PM show (it is later that night), and an untimed show goes last —
    // "not stated" isn't "first thing in the morning" (the API's own
    // ordering puts untimed last for the same reason).
    const times = ["20:00:00", "01:00:00", null, "18:00:00"];
    const sorted = [...times].sort((a, b) => nightSortKey(a) - nightSortKey(b));
    expect(sorted).toEqual(["18:00:00", "20:00:00", "01:00:00", null]);
  });

  it("treats undefined like null", () => {
    // Proves: the generated type is `string | null | undefined`.
    expect(nightSortKey(undefined)).toBe(nightSortKey(null));
  });
});

// --- formatting --------------------------------------------------------------

describe("formatDayHeading", () => {
  it("formats a date as weekday, month and day", () => {
    // Proves: the heading text. 2026-10-12 is a Monday.
    expect(formatDayHeading("2026-10-12")).toBe("Mon, Oct 12");
  });

  it("knows a leap day", () => {
    // Proves: calendar arithmetic is Temporal's, not ours. 2028 is a leap
    // year and 2028-02-29 a Tuesday.
    expect(formatDayHeading("2028-02-29")).toBe("Tue, Feb 29");
  });

  // These tests change the process's timezone on purpose — that is the
  // property under test — so turbo's "declare your env vars" rule (which
  // exists to keep build caches correct) doesn't apply to them.
  /* eslint-disable turbo/no-undeclared-env-vars */
  describe("whatever the server's own timezone is", () => {
    const original = process.env.TZ;
    afterEach(() => {
      // Assigning `undefined` would set the STRING "undefined".
      if (original === undefined) delete process.env.TZ;
      else process.env.TZ = original;
    });

    it.each(["Pacific/Pago_Pago", "Pacific/Kiritimati"])("is the same in %s", (zone) => {
      // Proves: formatting a show's date doesn't depend on the machine's
      // zone. A PlainDate has no zone, so it can't shift. The western zone
      // (UTC-11) is the one that catches the classic bug —
      // `new Date("2026-10-12")` is UTC midnight, which is the 11th there;
      // the eastern one (UTC+14) catches the mirror (building a local-time
      // Date and reading it back in UTC). Plan review #5.
      process.env.TZ = zone;
      expect(formatDayHeading("2026-10-12")).toBe("Mon, Oct 12");
    });
  });
  /* eslint-enable turbo/no-undeclared-env-vars */
});

describe("formatShowTime", () => {
  it("formats an evening time", () => {
    // Proves: 12-hour clock with minutes, as venues print it.
    expect(formatShowTime("2026-10-09", "20:00:00")).toBe("8:00 PM");
    expect(formatShowTime("2026-10-09", "19:30:00")).toBe("7:30 PM");
  });

  it("names the next day for a time after midnight", () => {
    // Proves: requirements-initial.md "Times after midnight" — a show
    // listed under Friday the 9th at 1:00 AM is Friday night's show,
    // displayed with the next day: "1:00 AM Sat".
    expect(formatShowTime("2026-10-09", "01:00:00")).toBe("1:00 AM Sat");
  });

  it("treats midnight itself as after midnight", () => {
    // Proves: 12:00 AM is also the next day, not the start of Friday.
    expect(formatShowTime("2026-10-09", "00:00:00")).toBe("12:00 AM Sat");
  });

  it("gives no day suffix at the 5:00 AM cut-off", () => {
    // Proves: the cut-off is exclusive (see isAfterMidnight).
    expect(formatShowTime("2026-10-09", "05:00:00")).toBe("5:00 AM");
  });

  it("is null when the listing gave no time", () => {
    // Proves: "not stated" stays visible to the caller, which prints
    // "Time not listed" — never a made-up midnight (api-contract.md §4).
    expect(formatShowTime("2026-10-09", null)).toBeNull();
    expect(formatShowTime("2026-10-09", undefined)).toBeNull();
  });
});

describe("formatClockTime", () => {
  it("formats without any day suffix", () => {
    // Proves: end times and per-act times don't repeat the "Sat" — the
    // block shows the day once, on the start time. 00:30 is 12:30 AM.
    expect(formatClockTime("00:30:00")).toBe("12:30 AM");
    expect(formatClockTime("23:15:00")).toBe("11:15 PM");
  });
});

describe("formatMonthLabel", () => {
  it("formats a year and month", () => {
    // Proves: the dropdown labels. (Goes through a PlainDate on purpose:
    // PlainYearMonth.toLocaleString("en-US") throws — see notes.md.)
    expect(formatMonthLabel(2026, 10)).toBe("October 2026");
    expect(formatMonthLabel(2027, 1)).toBe("January 2027");
  });
});
