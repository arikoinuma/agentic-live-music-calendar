import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { CalendarFilters } from "@/lib/calendar-href";
import fixture from "@/lib/fixtures/shows.json";
import type { ShowListResponse } from "@/lib/types";
import { CalendarResults } from "./calendar-results";

// What this file tests (B5, section 3 of the plan; decision B5-D1): the part of
// the home page that decides WHAT to show once the shows have arrived — the
// calendar, or one of two empty-state messages. It used to live inside
// `CalendarBody`, an async Server Component that awaits five API calls and
// so can't be unit tested (style guide, Testing); `CalendarResults` is the
// synchronous half, pulled out so it can be.
//
// Where the expected values come from:
//  - The fixture is lib/fixtures/shows.json, generated from
//    app/testing/sample_data.py: the API's default window 2026-09-28 to 2026-10-25
//    (28 days, inclusive) and 25 shows on 20 of those dates.
//  - 2026-10-07 is a Wednesday and holds five shows (ids 8, 22, 23, 24, 25)
//    at four venues — B4's fixture-day table. Show 25 (The Midway Saloon,
//    01:00) is listed under that Wednesday but happens on Thursday morning,
//    so its block reads "1:00 AM Thu" (requirements-initial.md, "Times after
//    midnight"). 2026-10-04 is a Sunday the sample data leaves empty
//    ("deliberately empty", lib/calendar.test.ts).
//  - The two messages are the ones the requirements call for ("No matches
//    found" with a way to reset) and the component's own wording.

const served = fixture as ShowListResponse;

const noFilters: CalendarFilters = { venueIds: [], artistIds: [], month: null };

// The grid's rows are the direct children of its <ol>; a show block's lineup
// is a <ul> with its own <li>s, so "every listitem" would count those too.
function dateRows(): HTMLElement[] {
  return screen.getAllByRole("listitem").filter((li) => li.parentElement?.tagName === "OL");
}

// --- the calendar, rendered from the fixture --------------------------------

describe("CalendarResults with shows", () => {
  it("renders a row for every served date and puts each show in its own date's row", () => {
    // Proves: the date grouping is wired all the way through to the page.
    // Every date the server served has a row (28, including empty ones),
    // every show is on screen (25), and the busy Wednesday holds its five
    // shows under four venues — one of them the after-midnight Midway show,
    // still under the night it was listed and displayed as Thursday. Only
    // that row is marked as today. `groupCalendar` has its own pure tests;
    // this is the integration they can't give (mutations B5-M6, B5-M7).
    render(
      <CalendarResults
        start={served.start}
        end={served.end}
        shows={served.shows}
        today="2026-10-07"
        filters={noFilters}
      />,
    );

    expect(dateRows()).toHaveLength(28);
    expect(screen.getAllByRole("article")).toHaveLength(25);

    const wednesday = screen.getByRole("link", { name: "Wed, Oct 7" }).closest("li")!;
    expect(within(wednesday).getAllByRole("article")).toHaveLength(5);
    expect(within(wednesday).getAllByRole("heading", { level: 3 })).toHaveLength(4);
    expect(
      within(wednesday).getByRole("link", { name: "1:00 AM Thu, show details" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("listitem", { current: "date" })).toBe(wednesday);

    // A date with no shows still has its row, as a thin line.
    const sunday = screen.getByRole("link", { name: "Sun, Oct 4" }).closest("li")!;
    expect(within(sunday).getByText("Nothing listed")).toBeInTheDocument();
  });

  it("shows neither empty-state message when there are shows, even with filters on", () => {
    // Proves: the empty states are for EMPTY results only. A filtered
    // calendar that has matches (venue 1's eight shows) is just the calendar.
    const venueOne = served.shows.filter((s) => s.venue.id === 1);
    render(
      <CalendarResults
        start={served.start}
        end={served.end}
        shows={venueOne}
        today={null}
        filters={{ ...noFilters, venueIds: [1] }}
      />,
    );

    expect(screen.getAllByRole("article")).toHaveLength(8);
    expect(screen.queryByText(/No matches found/)).not.toBeInTheDocument();
    expect(screen.queryByText(/No shows listed/)).not.toBeInTheDocument();
  });
});

// --- the two empty states (B5-K3) -------------------------------------------

describe("CalendarResults with no shows", () => {
  it("filtered and empty: says no matches and offers a real link to reset", () => {
    // Proves: the requirement ("No matches found" with a link or button to
    // reset the filter) for the case where filters are what emptied the
    // result. The month is one a visitor could have hand-edited into the
    // URL (B2-D2), which is why it counts as a filter: mutation B5-M4 (the
    // predicate forgetting `month`) turns this into the wrong message.
    render(
      <CalendarResults
        start="2027-01-01"
        end="2027-01-31"
        shows={[]}
        today={null}
        filters={{ ...noFilters, month: "2027-01" }}
      />,
    );

    expect(screen.getByText(/No matches found/)).toBeInTheDocument();
    // Nothing to lay out: no calendar rows, no skeleton.
    expect(screen.queryByRole("list")).not.toBeInTheDocument();

    // The way out has to be a real LINK to "/", not just words (B5-K3). The
    // page is server-rendered, so a plain <a href="/"> works before any
    // JavaScript has loaded, and `getByRole("link", { name })` plus
    // `toHaveAttribute("href", "/")` proves it is one (the same reasoning as
    // "Clear filters" in filter-header.tsx; requirements-initial.md,
    // "Calendar"). A text-only check would pass even if the reset were
    // plain text or pointed elsewhere (mutation B5-M14).
    expect(screen.getByRole("link", { name: "Reset filters" })).toHaveAttribute("href", "/");
  });

  it("unfiltered and empty: says nothing is listed and offers no reset", () => {
    // Proves: the quieter half of the same requirement. With nothing filtered
    // there is nothing to reset, so the page must NOT say "No matches" or
    // tell the visitor to reset filters they never set. This branch can't be
    // reached through the sample data (its default window always has shows),
    // so this test is the only check it has (B5 plan, fact 14).
    render(
      <CalendarResults
        start="2027-01-01"
        end="2027-01-28"
        shows={[]}
        today={null}
        filters={noFilters}
      />,
    );

    expect(screen.getByText("No shows listed for these dates.")).toBeInTheDocument();

    // Absence is asserted with `queryBy*` (B5-K3). `getBy*` throws when it
    // finds nothing, so it can't express "must not be there"; the `queryBy*`
    // family returns `null` instead, which `.not.toBeInTheDocument()` accepts.
    // One component, two behaviours, and the bug to catch is the wrong one
    // showing (mutation B5-M5).
    expect(screen.queryByRole("link", { name: "Reset filters" })).not.toBeInTheDocument();
    expect(screen.queryByText(/No matches found/)).not.toBeInTheDocument();
  });
});
