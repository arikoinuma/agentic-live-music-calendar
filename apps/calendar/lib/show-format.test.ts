import { describe, expect, it } from "vitest";
import { formatAdmission, formatPrice, orderedLineup } from "./show-format";
import type { LineupEntry } from "./types";

// Expected values come from api-contract.md §4 (money is a string; all
// three admission fields null means "not stated", never free) and from
// requirements-initial.md "Agent Extraction: Fields" (an unlabelled price
// is the day-of-show price; an online ticket price is the advance price).

describe("formatPrice", () => {
  it("drops the cents when they are zero", () => {
    // Proves: "18.00" reads "$18". String handling only — no parseFloat
    // on money (api-contract.md §4).
    expect(formatPrice("18.00")).toBe("$18");
  });

  it("keeps real cents", () => {
    // Proves: "8.50" is not rounded to "$8" or shortened to "$8.5".
    expect(formatPrice("8.50")).toBe("$8.50");
  });
});

describe("formatAdmission", () => {
  const none = { admission_advance: null, admission_day: null, free_admission: null };

  it("says Free when the listing said so", () => {
    // Proves: free_admission true is shown.
    expect(formatAdmission({ ...none, free_admission: true })).toBe("Free");
  });

  it("shows both prices", () => {
    // Proves: advance and day-of are labelled differently.
    expect(
      formatAdmission({ ...none, admission_advance: "18.00", admission_day: "22.00" }),
    ).toBe("$18 adv / $22 door");
  });

  it("shows a lone day price unlabelled", () => {
    // Proves: a single unlabelled price is stored as the day price, so the
    // block doesn't claim "door" for something the venue never called that.
    expect(formatAdmission({ ...none, admission_day: "10.00" })).toBe("$10");
  });

  it("labels a lone advance price", () => {
    // Proves: an online ticket price is shown as advance.
    expect(formatAdmission({ ...none, admission_advance: "15.00" })).toBe("$15 adv");
  });

  it("is null, not Free, when nothing was stated", () => {
    // Proves: the case api-contract.md §4 calls out — an unpriced show
    // must not be rendered as free, because a reader acts on it.
    expect(formatAdmission(none)).toBeNull();
  });

  it("is null for free_admission false with no prices", () => {
    // Proves: `false` is not "Free" and not a price either.
    expect(formatAdmission({ ...none, free_admission: false })).toBeNull();
  });
});

describe("orderedLineup", () => {
  const entry = (id: number, sequence_number: number | null): LineupEntry => ({
    artist: { id, name: `Artist ${id}` },
    sequence_number,
  });

  it("orders by sequence number", () => {
    // Proves: the performance order, not the API's array order, decides.
    const ids = orderedLineup([entry(1, 2), entry(2, 1), entry(3, 3)]).map((e) => e.artist.id);
    expect(ids).toEqual([2, 1, 3]);
  });

  it("puts unnumbered acts after numbered ones, in the API's order", () => {
    // Proves: a null sequence number neither crashes nor jumps to the
    // front, and the unnumbered acts keep the order the API gave (a stable sort).
    const ids = orderedLineup([entry(1, null), entry(2, 2), entry(3, null), entry(4, 1)]).map(
      (e) => e.artist.id,
    );
    expect(ids).toEqual([4, 2, 1, 3]);
  });

  it("does not mutate its input", () => {
    // Proves: a Server Component can pass props straight in.
    const lineup = [entry(1, 2), entry(2, 1)];
    orderedLineup(lineup);
    expect(lineup.map((e) => e.artist.id)).toEqual([1, 2]);
  });
});
