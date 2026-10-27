import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import fixture from "@/lib/fixtures/shows.json";
import type { ShowListResponse, ShowSummary } from "@/lib/types";
import { ShowBlock } from "./show-block";

// What this file tests (B5, section 4 of the plan; decision B5-D2): the show
// block, the calendar's cell and the unit `/day/[date]` lists. It has the
// densest logic in the render layer — which line is the link to the show,
// what an unstated time or price looks like, and when a per-act time is
// worth printing — and none of it was tested. The formatting helpers it
// calls (`formatShowTime`, `formatAdmission`, ...) have their own pure
// tests; this file pins how the BLOCK uses them.
//
// Where the expected values come from:
//  - The shows are fixture rows from lib/fixtures/shows.json (generated from
//    app/testing/sample_data.py): show 2, Zhora Darling, 2026-09-30, 21:00–23:30,
//    Nooky Jones at 21:00 and Beasthead at 22:30, $18 advance / $22 door;
//    show 22, The White Squirrel Bar, 18:00, one act, no price stated; show
//    25, The Midway Saloon, listed under Wednesday 2026-10-07 at 01:00, free.
//  - The strings ("9:00 PM – 11:30 PM", "1:00 AM Thu", "$18 adv / $22 door")
//    are what the formatters pin in lib/dates.test.ts and
//    lib/show-format.test.ts, and were read off the real component.
//    "1:00 AM Thu" is the after-midnight rule: the show belongs to Wednesday
//    night and happens on Thursday morning (requirements-initial.md,
//    "Times after midnight").
//  - The visually hidden ", show details" ends the time link's accessible
//    name so a screen reader hears where it goes (B4-D3).

const shows = (fixture as ShowListResponse).shows;

// A fixture show by id; the throw makes a renumbered fixture fail here, with
// a clear message, instead of as a confusing "cannot read properties of
// undefined" inside a test.
function fixtureShow(id: number): ShowSummary {
  const found = shows.find((s) => s.id === id);
  if (found === undefined) throw new Error(`fixture has no show ${id}`);
  return found;
}

const timed = fixtureShow(2);
const afterMidnight = fixtureShow(25);
const noPrice = fixtureShow(22);

// --- the time line ----------------------------------------------------------

describe("ShowBlock time line", () => {
  it("makes a timed show's time the link to its own page", () => {
    // Proves: the time line is the one link in the block that is about the
    // show itself (the venue and artist links can't nest in a block-wide
    // link), with the end time folded in and the hidden suffix completing
    // its accessible name (B4-D3).
    render(<ShowBlock show={timed} withVenue={false} />);

    expect(screen.getByRole("link", { name: "9:00 PM – 11:30 PM, show details" })).toHaveAttribute(
      "href",
      "/show/2",
    );
  });

  it("displays an after-midnight show on the next day", () => {
    // Proves: the block passes BOTH the date and the time to the formatter.
    // 01:00 listed under Wednesday must read "Thu"; a block that passed the
    // time alone would print a bare "1:00 AM" and put the show a night early.
    render(<ShowBlock show={afterMidnight} withVenue={false} />);

    expect(screen.getByRole("link", { name: "1:00 AM Thu, show details" })).toHaveAttribute(
      "href",
      "/show/25",
    );
  });

  it("says the time isn't listed, and offers a separate 'Details' link, when there is no start", () => {
    // Proves: "not stated" is shown as such, never a made-up midnight
    // (api-contract.md §4), and with no time to link the block gets a
    // separate "Details" link instead — "Time not listed, show details" is a
    // statement, not a destination (B4-PR1-6).
    render(<ShowBlock show={{ ...noPrice, start_time: null }} withVenue={false} />);

    expect(screen.getByText(/Time not listed/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Details" })).toHaveAttribute("href", "/show/22");
    expect(screen.queryByRole("link", { name: /show details/ })).not.toBeInTheDocument();
  });

  it("shows an end time with no start as what it is", () => {
    // Proves: a listing that gave only "until 11:30 PM" isn't dressed up as a
    // start time.
    render(
      <ShowBlock show={{ ...noPrice, start_time: null, end_time: "23:30:00" }} withVenue={false} />,
    );

    expect(screen.getByText(/Start time not listed – 11:30 PM/)).toBeInTheDocument();
  });
});

// --- venue and lineup -------------------------------------------------------

describe("ShowBlock venue and lineup", () => {
  it("names and links the venue only when asked to", () => {
    // Proves: inside the calendar grid the column header already names the
    // venue, so the block stays quiet (`withVenue={false}`); on the day view
    // it stands alone and links to /venue/<id>.
    const { unmount } = render(<ShowBlock show={timed} withVenue />);
    expect(screen.getByRole("link", { name: "Zhora Darling" })).toHaveAttribute("href", "/venue/3");
    unmount();

    render(<ShowBlock show={timed} withVenue={false} />);
    expect(screen.queryByRole("link", { name: "Zhora Darling" })).not.toBeInTheDocument();
  });

  it("links each act and prints per-act times on a multi-act bill", () => {
    // Proves: every artist links to /artist/<id>, and on a bill with more
    // than one act each act's own start time is printed beside the name.
    render(<ShowBlock show={timed} withVenue={false} />);

    expect(screen.getByRole("link", { name: "Nooky Jones" })).toHaveAttribute("href", "/artist/2");
    expect(screen.getByRole("link", { name: "Beasthead" })).toHaveAttribute("href", "/artist/9");

    const [first, second] = screen.getAllByRole("listitem");
    expect(first).toHaveTextContent(/Nooky Jones\s*9:00 PM/);
    expect(second).toHaveTextContent(/Beasthead\s*10:30 PM/);
  });

  it("prints no per-act time for a single act, even when the act has one", () => {
    // Proves: a per-act time only means something on a multi-act bill. For a
    // lone act it would repeat the show's own time (mutation B5-M10).
    const lone = { ...noPrice, lineup: [{ ...noPrice.lineup[0]!, start_time: "18:00:00" }] };
    render(<ShowBlock show={lone} withVenue={false} />);

    expect(screen.getByRole("listitem").textContent).toBe("Lanue");
  });
});

// --- admission --------------------------------------------------------------

describe("ShowBlock admission", () => {
  it("shows both prices, or 'Free' when the listing said so", () => {
    // Proves: the price line is what formatAdmission returns for the show.
    const { unmount } = render(<ShowBlock show={timed} withVenue={false} />);
    expect(screen.getByText("$18 adv / $22 door")).toBeInTheDocument();
    unmount();

    render(<ShowBlock show={afterMidnight} withVenue={false} />);
    expect(screen.getByText("Free")).toBeInTheDocument();
  });

  it("shows no price line at all when nothing was stated, and in particular not 'Free'", () => {
    // Proves: "not stated" is NOT "free" (api-contract.md §4). A block that
    // fell back to "Free" for a missing price (mutation B5-M9) would send people
    // to a door charge they were told didn't exist.
    render(<ShowBlock show={noPrice} withVenue={false} />);

    expect(screen.queryByText(/Free/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\$/)).not.toBeInTheDocument();
  });
});
