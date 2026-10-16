import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CalendarFilters } from "@/lib/calendar-href";
import artistsFixture from "@/lib/fixtures/artists.json";
import venuesFixture from "@/lib/fixtures/venues.json";
import { FilterHeader } from "./filter-header";

// What this file tests (B5, section 1 of the plan): the calendar's filter
// header, the one Client Component in the calendar. It holds no results.
// A pick calls `router.push` with the new URL and the server page renders
// the answer (arch-initial.md §4: filter state lives in the URL), so the
// header's whole behaviour is "which URL does this interaction ask for?".
// That is why almost every test below ends in an assertion on the URL
// handed to `push`.
//
// What it does NOT test: that a real `router.push` re-renders the page, and
// the "Updating…" / aria-busy state while it does. Those depend on Next's
// router keeping a React transition open, which a mocked router can't do
// (B5 plan, fact 12); they are Playwright's.
//
// Where the expected values come from:
//  - Venue and artist names and ids come from lib/fixtures/venues.json and
//    artists.json, mapped to `{ id, name }`, the shape the home page passes.
//    The ids used below: venues 1 The White Squirrel Bar, 2 The Midway
//    Saloon, 3 Zhora Darling, 4 The Terminal Bar; artist 1 Charlie Parr,
//    artist 7 Humbird.
//  - Every expected URL is written out BY HAND from `buildCalendarHref`'s
//    documented shape (lib/calendar-href.ts): `/` when nothing is chosen,
//    otherwise `/?venue=…&artist=…&month=…` in that key order, ids
//    ascending. It is never produced by calling `buildCalendarHref`, which
//    would agree with itself whatever it did.

// --- the router, mocked at the framework's edge (B5-K1) ---------------------

// TODO(Ari) — Lesson: FilterHeader's only contact with Next is `useRouter().push`
//   (B3-K4: a pick changes the URL and the server page re-renders). Outside a running
//   Next app there is no app router, so the unmocked component throws
//   `invariant expected app router to be mounted`. Replace exactly that edge, not
//   Base UI and not `next/link`, and assert on what `push` received: the URL IS the
//   filter state (arch-initial.md §4), so the pushed URL is the behaviour.
//   `vi.mock` is hoisted above the imports, so anything its factory reads must come
//   from `vi.hoisted`.
// Code:
//   const { push } = vi.hoisted(() => ({ push: vi.fn() }));
//   vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
// (The placeholder below is typed only so `tsc` accepts `push` in the other tests while
//   it is open; replace the WHOLE statement with the Code: lines and nothing is left over.)
// Check: `pnpm --filter calendar test filter-header` — while this is open the whole
//   file fails to load (one failed suite, zero tests); filled, every test runs.
//   Likeliest mistakes: a top-level `const push = vi.fn()` read eagerly inside the
//   factory ("Cannot access 'push' before initialization"), or mocking more than the
//   router (a faked combobox passes while proving nothing about it).
const { push } = vi.hoisted((): { push: ReturnType<typeof vi.fn> } => {
  throw new Error("TODO(Ari)");
});

// --- fixtures and helpers ---------------------------------------------------

const venues = venuesFixture.venues.map(({ id, name }) => ({ id, name }));
const artists = artistsFixture.artists.map(({ id, name }) => ({ id, name }));

// The month dropdown's options as the page builds them (`monthOptions`):
// only months the server says have shows. Two are enough to tell "the
// server's order" from "alphabetical".
const months = [
  { value: "2026-10", label: "October 2026" },
  { value: "2026-11", label: "November 2026" },
];

const noFilters: CalendarFilters = { venueIds: [], artistIds: [], month: null };

// Renders the header with the props the home page would pass.
function renderHeader(filters: CalendarFilters) {
  return render(<FilterHeader filters={filters} venues={venues} artists={artists} months={months} />);
}

// `push` is shared by every test in the file; without this a call made in
// one test would be counted in the next.
beforeEach(() => push.mockClear());

// --- labels and chips -------------------------------------------------------

describe("FilterHeader controls", () => {
  it("gives each control an accessible label", () => {
    // Proves: the <label htmlFor> / id pairing for the three controls. It is
    // what makes each one announceable ("Venues, combobox") and what lets
    // every other test find it by its label instead of a selector.
    renderHeader(noFilters);

    expect(screen.getByLabelText("Venues")).toBeInTheDocument();
    expect(screen.getByLabelText("Artists")).toBeInTheDocument();
    expect(screen.getByLabelText("Month")).toBeInTheDocument();
  });

  it("shows selected venues as chips carrying their names, not their ids", () => {
    // Proves: the chip shows a name while the URL carries the id (the
    // component's own comment). Venues 1 and 3 are selected here.
    renderHeader({ ...noFilters, venueIds: [1, 3] });

    expect(screen.getByText("The White Squirrel Bar")).toBeInTheDocument();
    expect(screen.getByText("Zhora Darling")).toBeInTheDocument();
  });

  it("shows the chosen month on the month control, or 'Next four weeks' when there is none", () => {
    // Proves: the select displays the LABEL for its current value
    // ("October 2026", not "2026-10"), and that no month filter reads as the
    // server's default window. `toHaveTextContent` matches a substring on
    // purpose: the trigger's text also carries its chevron glyph.
    const { unmount } = renderHeader({ ...noFilters, month: "2026-10" });
    expect(screen.getByLabelText("Month")).toHaveTextContent("October 2026");
    unmount();

    renderHeader(noFilters);
    expect(screen.getByLabelText("Month")).toHaveTextContent("Next four weeks");
  });
});

// --- navigation: every pick is a URL (B5-K2) --------------------------------

describe("FilterHeader navigation", () => {
  it("picking a venue keeps the other filters and writes the one canonical URL", async () => {
    // Proves: the header's central job. A pick is ONE navigation to the URL
    // that means "this filter set", and the URL is canonical: ids ascending
    // (1 before 3 though 3 was already chosen), keys in the fixed order venue,
    // artist, month. The other filters are preselected so a header that
    // forgot them (mutation B5-M2) or dropped `{ scroll: false }` (B5-M1) fails.
    // This is what makes a filtered calendar shareable and bookmarkable.

    // TODO(Ari) — Lesson: drive the combobox the way a person does, and assert the
    //   WHOLE outcome. (1) Find things by role and accessible name, not by class or
    //   data-slot. (2) Use `userEvent`: the combobox opens on the pointer-and-focus
    //   sequence a real click produces, and `fireEvent.click` sends one bare event
    //   after which the list never opens. (3) Assert the entire pushed URL, with the
    //   other filters preselected so a header that forgets them fails, and write the
    //   expected string BY HAND from buildCalendarHref's documented key order rather
    //   than calling buildCalendarHref (it would agree with itself whatever it did).
    // Code:
    //   const user = userEvent.setup();
    //   renderHeader({ venueIds: [3], artistIds: [7], month: "2026-10" });
    //   await user.click(screen.getByLabelText("Venues"));
    //   await user.click(await screen.findByRole("option", { name: "The White Squirrel Bar" }));
    //   expect(push).toHaveBeenCalledExactlyOnceWith("/?venue=1&venue=3&artist=7&month=2026-10", { scroll: false });
    // Check: `pnpm --filter calendar test filter-header` — green on the real header,
    //   RED when filter-header.tsx is mutated so a pick drops the other filters (B5-M2)
    //   or loses `{ scroll: false }` (B5-M1). Likeliest mistakes: `fireEvent.click`
    //   (waits forever for the option), building the expected URL with
    //   buildCalendarHref, or `expect(push).toHaveBeenCalled()` with no argument
    //   (passes under both mutations). `toHaveBeenCalledWith` alone is a weaker miss:
    //   it ignores a second navigation, which `toHaveBeenCalledExactlyOnceWith` catches.
    throw new Error("TODO(Ari)");
  });

  it("clicking an already-selected venue removes it", async () => {
    // Proves: the list toggles. With venues 1 and 3 chosen, clicking Zhora
    // Darling (3) again leaves only 1. The same option is how a keyboard user
    // un-picks without reaching a chip.
    const user = userEvent.setup();
    renderHeader({ ...noFilters, venueIds: [1, 3] });

    await user.click(screen.getByLabelText("Venues"));
    await user.click(await screen.findByRole("option", { name: "Zhora Darling" }));

    expect(push).toHaveBeenCalledExactlyOnceWith("/?venue=1", { scroll: false });
  });

  it("the Artists box writes artist= and keeps the other filters", async () => {
    // Proves: the two pickers are not wired to each other's key (Charlie Parr
    // is artist 1; a header that sent it as a venue would write another
    // `venue=1`), AND the artist picker, like the venue one, keeps what was
    // already chosen. A venue and a month are preselected so an `onChange`
    // that rebuilt the filters from scratch (mutation B5-M15) loses them and
    // fails: a calendar that forgets your venue when you add an artist is not
    // shareable as intended.
    const user = userEvent.setup();
    renderHeader({ venueIds: [2], artistIds: [], month: "2026-10" });

    await user.click(screen.getByLabelText("Artists"));
    await user.click(await screen.findByRole("option", { name: "Charlie Parr" }));

    expect(push).toHaveBeenCalledExactlyOnceWith("/?venue=2&artist=1&month=2026-10", {
      scroll: false,
    });
  });

  it("choosing a month writes month=YYYY-MM", async () => {
    // Proves: the select sends the machine value ("2026-11") while the
    // person picked the label ("November 2026").
    const user = userEvent.setup();
    renderHeader(noFilters);

    await user.click(screen.getByLabelText("Month"));
    await user.click(await screen.findByRole("option", { name: "November 2026" }));

    expect(push).toHaveBeenCalledExactlyOnceWith("/?month=2026-11", { scroll: false });
  });

  it("choosing 'Next four weeks' clears only the month", async () => {
    // Proves: "no month" is a real choice that removes `month` from the URL
    // and leaves the venue filter alone, and that the select's sentinel value
    // ("next-four-weeks") never leaks into a URL (mutation B5-M3).
    const user = userEvent.setup();
    renderHeader({ ...noFilters, venueIds: [1], month: "2026-10" });

    await user.click(screen.getByLabelText("Month"));
    await user.click(await screen.findByRole("option", { name: "Next four weeks" }));

    expect(push).toHaveBeenCalledExactlyOnceWith("/?venue=1", { scroll: false });
  });

  it("removes a venue from its own chip's button", async () => {
    // Proves (B5-D3): the control that un-picks a filter has an accessible
    // name, "Remove <venue>". Before B5-D3 it was an icon-only button with no
    // name at all — a screen reader said just "button" — which is also why a
    // role-and-name query could not even find it.
    const user = userEvent.setup();
    renderHeader({ ...noFilters, venueIds: [1, 3] });

    await user.click(screen.getByRole("button", { name: "Remove Zhora Darling" }));

    expect(push).toHaveBeenCalledExactlyOnceWith("/?venue=1", { scroll: false });
  });
});

// --- the lists --------------------------------------------------------------

describe("FilterHeader lists", () => {
  it("lists 'Next four weeks' first, then the server's months in the order given", async () => {
    // Proves: the month choices are the sentinel for "no month" followed by
    // exactly the months the page passed, in its order (the server decides
    // which months exist, api-contract.md §2).
    const user = userEvent.setup();
    renderHeader(noFilters);

    await user.click(screen.getByLabelText("Month"));

    const options = await screen.findAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual([
      "Next four weeks",
      "October 2026",
      "November 2026",
    ]);
  });

  it("narrows the venue list as you type, and says so when nothing matches", async () => {
    // Proves: the requirement "multi-select list with ability to type and
    // filter down the items" (requirements-initial.md, "Calendar"), including
    // the empty case: a typo shows "No matches" rather than a blank box.
    const user = userEvent.setup();
    renderHeader(noFilters);
    const venueBox = screen.getByLabelText("Venues");

    await user.type(venueBox, "mid");
    expect(screen.getByRole("option", { name: "The Midway Saloon" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Zhora Darling" })).not.toBeInTheDocument();

    await user.clear(venueBox);
    await user.type(venueBox, "zzz");
    expect(await screen.findByText("No matches")).toBeInTheDocument();
  });
});

// --- "Clear filters" --------------------------------------------------------

describe("FilterHeader 'Clear filters'", () => {
  it.each([
    ["a venue", { ...noFilters, venueIds: [1] }],
    ["an artist", { ...noFilters, artistIds: [7] }],
    ["a month", { ...noFilters, month: "2026-10" }],
  ])("offers a plain link home when only %s is chosen", (_label, filters) => {
    // Proves: each kind of filter, ALONE, is enough to offer the way out,
    // and the way out is a real link to "/" (so it works before the page has
    // hydrated). One row per filter kind means a header that forgot one
    // (mutation B5-M4) fails on that row; pointing the link elsewhere (B5-M8) fails
    // all three.
    renderHeader(filters);

    expect(screen.getByRole("link", { name: "Clear filters" })).toHaveAttribute("href", "/");
  });

  it("offers nothing to clear when nothing is chosen", () => {
    // Proves: no filters, no "Clear filters" — not a permanent dead link.
    renderHeader(noFilters);

    expect(screen.queryByRole("link", { name: "Clear filters" })).not.toBeInTheDocument();
  });
});
