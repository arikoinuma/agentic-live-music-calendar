import { describe, expect, it } from "vitest";
import { buildCalendarHref, withIds, type CalendarFilters } from "./calendar-href";

// buildCalendarHref's own behaviour is pinned by params.test.ts (it moved
// here from params.ts in B3 and is re-exported there). These tests cover
// only what is new: `withIds`.

const base: CalendarFilters = { venueIds: [], artistIds: [7], month: "2026-10" };

describe("withIds", () => {
  it("de-duplicates and sorts numerically", () => {
    // Proves: a combobox reports ids in the order they were picked; the
    // URL needs the canonical form (one filter set, one URL), and the sort
    // must be numeric — `[10, 9].sort()` is lexicographic and gives [10, 9].
    expect(withIds(base, "venueIds", [3, 10, 1, 3, 9]).venueIds).toEqual([1, 3, 9, 10]);
  });

  it("leaves the other keys untouched", () => {
    // Proves: changing venues doesn't reset artists or the month.
    const next = withIds(base, "venueIds", [1]);
    expect(next.artistIds).toEqual([7]);
    expect(next.month).toBe("2026-10");
  });

  it("does not mutate its input", () => {
    // Proves: the filter header holds the previous state in React; a
    // mutation would corrupt it.
    withIds(base, "venueIds", [1]);
    expect(base.venueIds).toEqual([]);
  });

  it("yields the one canonical href whatever order the ids were picked in", () => {
    // Proves: picking venue 3 then 1 and picking 1 then 3 share a URL —
    // what makes a filtered calendar bookmarkable (arch-initial.md §4).
    expect(buildCalendarHref(withIds(base, "venueIds", [3, 1]))).toBe(
      buildCalendarHref(withIds(base, "venueIds", [1, 3])),
    );
  });
});
