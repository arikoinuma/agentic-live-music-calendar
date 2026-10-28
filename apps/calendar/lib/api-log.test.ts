import { describe, expect, it } from "vitest";
import {
  bodyLoggingEnabled,
  compactJson,
  describeSize,
  summarizeBody,
} from "./api-log";
import artists from "./fixtures/artists.json";
import calendarMonths from "./fixtures/calendar-months.json";
import metro from "./fixtures/metro.json";
import shows from "./fixtures/shows.json";
import venues from "./fixtures/venues.json";

// Where the expected values come from: the numbers in the /shows summary are
// counted BY HAND from apps/api/app/testing/sample_data.py's _SHOW_ROWS (25 rows
// after B3), not read back from the code under test:
//  - without a start time: Midway (offset 2), White Squirrel (offset 10),
//    Midway (offset 23) -> 3
//  - empty lineup: none -> 0
//  - no admission info at all (advance, day and free all null): White
//    Squirrel at offset 10, and White Squirrel 18:00 on offset 9 -> 2
//  - range: sample_data.START (2026-09-28) plus 27 days -> 2026-10-25
// Sizes are the compact JSON lengths measured with `len(json.dumps(...,
// separators=(",", ":")))` on the fixtures (venues.json: 156 bytes).

// --- the on/off rule ----------------------------------------------------------

describe("bodyLoggingEnabled", () => {
  it("is on when asked for, outside production", () => {
    // Proves: the switch works in dev (and in tests, whose NODE_ENV is "test").
    expect(bodyLoggingEnabled({ LOG_API_BODIES: "1", NODE_ENV: "development" })).toBe(true);
    expect(bodyLoggingEnabled({ LOG_API_BODIES: "true", NODE_ENV: "test" })).toBe(true);
  });

  it("is off unless asked for", () => {
    // Proves: the default is the summary only. Anything but "1"/"true" —
    // including a typo or "0" — leaves full bodies off.
    expect(bodyLoggingEnabled({ NODE_ENV: "development" })).toBe(false);
    expect(bodyLoggingEnabled({ LOG_API_BODIES: "0", NODE_ENV: "development" })).toBe(false);
    expect(bodyLoggingEnabled({ LOG_API_BODIES: "yes", NODE_ENV: "development" })).toBe(false);
  });

  it("is never on in production, whatever the flag says", () => {
    // Proves: a stray env var on Vercel can't make the server write whole
    // API responses into hosted logs (large lines, and data nobody chose
    // to retain).
    expect(bodyLoggingEnabled({ LOG_API_BODIES: "1", NODE_ENV: "production" })).toBe(false);
  });
});

// --- sizes and truncation -------------------------------------------------------

describe("describeSize", () => {
  it.each([
    [0, "0 B"],
    [156, "156 B"],
    [1023, "1023 B"],
    [1024, "1.0 KB"],
    [8288, "8.1 KB"],
    [1048576, "1.0 MB"],
  ])("%i bytes -> %s", (bytes, expected) => {
    // Proves: sizes read at a glance. 8288 / 1024 = 8.09 -> "8.1 KB".
    expect(describeSize(bytes)).toBe(expected);
  });
});

describe("compactJson", () => {
  it("returns a short body whole, on one line", () => {
    // Proves: one log line per body — no pretty-printing, which would
    // split it across lines that a log search can't tie together.
    expect(compactJson({ a: 1, b: ["x"] }, 100)).toBe('{"a":1,"b":["x"]}');
  });

  it("cuts a long body and says how much was cut", () => {
    // Proves: a huge response can't flood the log, and the marker says the
    // line is incomplete rather than letting a cut look like the whole.
    // {"s":"aaaaaaaaaa"} is 18 characters; the first 10 are `{"s":"` plus
    // four a's, which leaves 8 cut.
    expect(compactJson({ s: "a".repeat(10) }, 10)).toBe('{"s":"aaaa…(+8 chars)');
  });
});

// --- the summaries -----------------------------------------------------------

describe("summarizeBody /shows", () => {
  it("counts shows and the anomalies worth a glance", () => {
    // Proves: the line a developer scans — how many shows, over what range,
    // and how many have the gaps that are most often a sign the extraction
    // missed something (no time, no artists), plus the admission-unknown
    // count (legitimate, but a sudden jump means the agent stopped reading prices).
    expect(summarizeBody("/shows", shows)).toBe(
      "25 shows (2026-09-28..2026-10-25); 3 without start_time; 0 with empty lineup; 2 with no admission info",
    );
  });

  it("handles an empty list", () => {
    // Proves: zero shows is a normal answer (a filter matched nothing), not a crash.
    expect(
      summarizeBody("/shows", { start: "2026-10-01", end: "2026-10-31", shows: [] }),
    ).toBe("0 shows (2026-10-01..2026-10-31); 0 without start_time; 0 with empty lineup; 0 with no admission info");
  });

  it("falls back to the generic summary when the shape isn't a show list", () => {
    // Proves: if the API changes shape, the log says what arrived instead of
    // throwing or printing "undefined shows" — a wrong shape is exactly what
    // this line exists to reveal.
    expect(summarizeBody("/shows", { detail: "Not found" })).toBe('detail="Not found"');
  });
});

describe("summarizeBody (generic)", () => {
  it("counts list items", () => {
    // Proves: list responses read as "venues[4]" — key and count.
    expect(summarizeBody("/venues", venues)).toBe("venues[4]");
    expect(summarizeBody("/artists", artists)).toBe("artists[10]");
    expect(summarizeBody("/calendar/months", calendarMonths)).toBe("months[2]");
  });

  it("shows small scalar values", () => {
    // Proves: a small record is printed outright, so /metro's answer is visible.
    expect(summarizeBody("/metro", metro)).toBe(
      'id=1, name="Minneapolis/St. Paul", timezone="America/Chicago"',
    );
  });

  it("marks arrays and objects by size, and lists the null fields", () => {
    // Proves: a detail record shows its shape at a glance and — the point —
    // which fields came back null, since "this field is unexpectedly null"
    // is the commonest anomaly.
    expect(
      summarizeBody("/venues/7", {
        id: 7,
        name: "X",
        tags: ["a", "b"],
        owner: { id: 1 },
        website: null,
        phone: null,
      }),
    ).toBe('id=7, name="X", tags[2], owner{…}; null: website, phone');
  });

  it("shortens long strings and long summaries", () => {
    // Proves: a summary stays one short line however big the record is.
    const long = summarizeBody("/x", { text: "y".repeat(200) });
    expect(long.length).toBeLessThan(80);
    const many = summarizeBody("/x", Object.fromEntries(Array.from({ length: 40 }, (_, i) => [`key${i}`, i])));
    expect(many.length).toBeLessThanOrEqual(240);
    expect(many.endsWith("…")).toBe(true);
  });

  it("describes bodies that aren't objects", () => {
    // Proves: it never throws, whatever the API returns.
    expect(summarizeBody("/x", [1, 2, 3])).toBe("[3 items]");
    expect(summarizeBody("/x", null)).toBe("null");
    expect(summarizeBody("/x", "hello")).toBe('"hello"');
    expect(summarizeBody("/x", 42)).toBe("42");
  });
});
