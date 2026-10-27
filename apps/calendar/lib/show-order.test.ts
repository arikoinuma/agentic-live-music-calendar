import { describe, expect, it } from "vitest";
import fixture from "./fixtures/shows.json";
import {
  artistRows,
  dayHref,
  inNightOrder,
  parseDaySort,
  timeOrder,
  venueOrder,
} from "./show-order";
import type { ShowListResponse, ShowSummary } from "./types";

// Where the expected values come from. The "fixture day" is 2026-10-07 in
// lib/fixtures/shows.json (a Wednesday), whose five shows were built hard
// on purpose (B3-D5) and are listed in apps/api/app/testing/sample_data.py:
//
//   id  venue                    start  lineup (per-act time)
//    8  The Terminal Bar         21:00  Jaedyn James, Tarnation, Beasthead
//   22  The White Squirrel Bar   18:00  Lanue
//   23  The White Squirrel Bar   22:00  Nooky Jones (22:00), Pert Near Sandstone (23:15)
//   24  Zhora Darling            20:00  Charlie Parr
//   25  The Midway Saloon        01:00  Dead Man Winter
//
// Orders below are worked out from that table by hand: venue names
// alphabetically (no "The"-stripping, as the API sorts), clock times by the
// 5:00 AM night rule (requirements-initial.md, "Times after midnight").

const served = fixture as ShowListResponse;
const fixtureDay = served.shows.filter((s) => s.date === "2026-10-07");

const ids = (shows: ShowSummary[]) => shows.map((s) => s.id);

// A hand-built show: only what ordering reads.
const show = (
  id: number,
  venue: { id: number; name: string },
  start_time: string | null,
  date = "2026-10-07",
): ShowSummary => ({ id, date, start_time, venue, lineup: [] });

const squirrel = { id: 1, name: "The White Squirrel Bar" };
const midway = { id: 2, name: "The Midway Saloon" };
const zhora = { id: 3, name: "Zhora Darling" };

it("the fixture day is the five shows this file's expectations assume", () => {
  // Proves: the table above still describes the fixture. If sample data
  // changes and the fixture regenerates, this fails first and says why the
  // order tests below would be comparing against stale numbers.
  expect(ids(fixtureDay).sort((a, b) => a - b)).toEqual([8, 22, 23, 24, 25]);
});

// --- venueOrder / timeOrder (B4-K4) ---------------------------------------------------

describe("venueOrder", () => {
  it("sorts by venue name, then by time within a venue", () => {
    // Proves: the default day view. Midway, Terminal, White Squirrel (18:00
    // before 22:00), Zhora. The 1:00 AM Midway show is simply that venue's
    // only show — the night rule matters in the tie-break below.
    expect(ids([...fixtureDay].sort(venueOrder))).toEqual([25, 8, 22, 23, 24]);
  });

  it("keeps the input order for a tie", () => {
    // Proves: the sort is stable and the comparator returns 0 for a true
    // tie (same venue, same time), so the API's order survives.
    const a = show(1, squirrel, "20:00:00");
    const b = show(2, squirrel, "20:00:00");
    expect(ids([a, b].sort(venueOrder))).toEqual([1, 2]);
    expect(ids([b, a].sort(venueOrder))).toEqual([2, 1]);
  });

  it("puts an untimed show last within its venue", () => {
    // Proves: "time not stated" isn't "first thing in the morning"
    // (nightSortKey), including inside a venue.
    expect(ids([show(1, squirrel, null), show(2, squirrel, "20:00:00")].sort(venueOrder))).toEqual([2, 1]);
  });

  it("puts a 1:00 AM show after the same venue's evening show", () => {
    // Proves: venue mode uses the NIGHT order, not clock order: 01:00
    // belongs to the end of the night. A string compare of start_time would
    // put it first.
    expect(ids([show(1, squirrel, "01:00:00"), show(2, squirrel, "22:00:00")].sort(venueOrder))).toEqual([2, 1]);
  });
});

describe("timeOrder", () => {
  it("sorts by night order, with the 1:00 AM show last", () => {
    // Proves: 18:00, 20:00, 21:00, 22:00, then 01:00 — the show listed
    // under Wednesday at 1:00 AM is the END of Wednesday night. Clock order
    // would put it first, which is the mistake this guards.
    expect(ids([...fixtureDay].sort(timeOrder))).toEqual([22, 24, 8, 23, 25]);
  });

  it("breaks a time tie by venue name", () => {
    // Proves: two 20:00 shows at different venues sort by venue name
    // (Midway before Zhora).
    expect(ids([show(1, zhora, "20:00:00"), show(2, midway, "20:00:00")].sort(timeOrder))).toEqual([2, 1]);
  });

  it("puts untimed shows after everything", () => {
    // Proves: an untimed show is last of ALL, whatever its venue's name.
    expect(ids([show(1, midway, null), show(2, zhora, "20:00:00")].sort(timeOrder))).toEqual([2, 1]);
  });
});

// --- artistRows (B4-K3) ---------------------------------------------------------------

describe("artistRows", () => {
  it("makes one row per act, alphabetical by artist", () => {
    // Proves: artist mode is a different SHAPE (one row per act, not per
    // show): five shows become eight rows. Alphabetical: Beasthead, Charlie
    // Parr, Dead Man Winter, Jaedyn James, Lanue, Nooky Jones, Pert Near
    // Sandstone, Tarnation. Each row's time is the act's own when the
    // listing has one (Nooky 22:00, Pert Near Sandstone 23:15 — NOT the
    // show's 22:00), else the show's.
    const rows = artistRows(fixtureDay).map((r) => [r.artist.name, r.venue.name, r.time]);
    expect(rows).toEqual([
      ["Beasthead", "The Terminal Bar", "21:00:00"],
      ["Charlie Parr", "Zhora Darling", "20:00:00"],
      ["Dead Man Winter", "The Midway Saloon", "01:00:00"],
      ["Jaedyn James", "The Terminal Bar", "21:00:00"],
      ["Lanue", "The White Squirrel Bar", "18:00:00"],
      ["Nooky Jones", "The White Squirrel Bar", "22:00:00"],
      ["Pert Near Sandstone", "The White Squirrel Bar", "23:15:00"],
      ["Tarnation", "The Terminal Bar", "21:00:00"],
    ]);
  });

  it("carries the ids the page needs to link all three things", () => {
    // Proves: a row has the artist, the venue, the show id and the date,
    // so the page can link the artist, the venue and (via the date) format
    // an after-midnight time. Nooky Jones is on show 23 at venue 1.
    const nooky = artistRows(fixtureDay).find((r) => r.artist.name === "Nooky Jones");
    expect(nooky).toMatchObject({
      artist: { id: 2 },
      venue: { id: 1 },
      showId: 23,
      date: "2026-10-07",
    });
  });

  it("gives an artist on two bills the same night two rows, in night order", () => {
    // Proves: rows are per ACT per show, and an artist's own rows sort by
    // the night rule (22:00 before 01:00), not the clock.
    const artist = { id: 9, name: "Double Booked" };
    const early: ShowSummary = {
      ...show(1, squirrel, "22:00:00"),
      lineup: [{ artist, start_time: null, sequence_number: 1 }],
    };
    const late: ShowSummary = {
      ...show(2, midway, "01:00:00"),
      lineup: [{ artist, start_time: null, sequence_number: 1 }],
    };
    expect(artistRows([late, early]).map((r) => r.showId)).toEqual([1, 2]);
  });

  it("gives a show with an empty lineup no rows", () => {
    // Proves: the contract's `lineup` is a list and nothing enforces "one
    // or more", so an empty one must not throw or invent a row.
    expect(artistRows([show(1, squirrel, "20:00:00")])).toEqual([]);
  });
});

// --- parseDaySort / dayHref -----------------------------------------------------------------

describe("parseDaySort", () => {
  it.each([
    [undefined, "venue"],
    ["time", "time"],
    ["artist", "artist"],
    ["venue", "venue"],
    ["bogus", "venue"],
    ["", "venue"],
    ["TIME", "venue"],
    [["artist", "time"], "artist"],
    [["bogus", "time"], "time"],
  ] as const)("reads %j as %s", (raw, expected) => {
    // Proves: an unknown or missing value is the default view, never an
    // error (a search param isn't part of the resource's identity), and a
    // repeated key takes the first VALID value, as parseMonthParam does.
    expect(parseDaySort(raw as string | string[] | undefined)).toBe(expected);
  });
});

describe("dayHref", () => {
  it("writes the default view as the bare URL", () => {
    // Proves: one canonical URL per view (B4-D6) — venue order has no query.
    expect(dayHref("2026-10-07", "venue")).toBe("/day/2026-10-07");
    expect(dayHref("2026-10-07", "time")).toBe("/day/2026-10-07?sort=time");
    expect(dayHref("2026-10-07", "artist")).toBe("/day/2026-10-07?sort=artist");
  });

  it("round-trips through parseDaySort", () => {
    // Proves: what the switch writes is what the page reads back — the
    // view really is in the URL, so it is shareable and survives Back.
    for (const mode of ["venue", "time", "artist"] as const) {
      const query = dayHref("2026-10-07", mode).split("?")[1];
      expect(parseDaySort(new URLSearchParams(query).get("sort") ?? undefined)).toBe(mode);
    }
  });
});

// --- inNightOrder ---------------------------------------------------------------------------------

describe("inNightOrder", () => {
  it("orders by date, then by night order within a date", () => {
    // Proves: the artist page's list is chronological whatever order the
    // API sent. Charlie Parr (artist 1) has four shows in the fixture, on
    // 2026-09-28, 10-07, 10-08 and 10-20 (sample_data.py); feeding them in
    // reverse must give them back ascending.
    const parr = served.shows.filter((s) => s.lineup.some((e) => e.artist.id === 1));
    expect(inNightOrder([...parr].reverse()).map((s) => s.date)).toEqual([
      "2026-09-28",
      "2026-10-07",
      "2026-10-08",
      "2026-10-20",
    ]);
  });

  it("puts a 1:00 AM show after the evening show of the same date", () => {
    // Proves: within one date the night rule applies, here to the artist
    // page's list as well.
    expect(
      ids(inNightOrder([show(1, midway, "01:00:00"), show(2, squirrel, "22:00:00")])),
    ).toEqual([2, 1]);
  });
});
