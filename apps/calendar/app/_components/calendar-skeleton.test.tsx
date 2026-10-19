/**
 * The loading skeleton's accessibility (B6 plan, decision D8; finding B6-F5).
 *
 * The grey bars are decoration and stay hidden from assistive technology. Before B6
 * they were ALL it had: no text, so a screen-reader user got nothing while the
 * calendar loaded, and a browser test had no role-based handle to find the skeleton
 * by (the project's rule is role, name or label, never a class).
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CalendarSkeleton } from "./calendar-skeleton";

describe("CalendarSkeleton", () => {
  // Proves: the skeleton says it is loading, in text, as a status. This is what a
  // screen-reader user can find while the calendar streams in, and what the browser
  // test (skeleton.spec.ts) locates it by. Fails if the status text is removed or
  // the whole component goes back to being aria-hidden.
  it("announces that shows are loading", () => {
    render(<CalendarSkeleton />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading shows");
  });

  // Proves: the grey bars themselves stay hidden from assistive technology, so the
  // status text is the only thing a screen reader meets: ten silent bars with no
  // text would be noise. Fails if the decorative container loses `aria-hidden`.
  it("keeps the decorative bars out of the accessibility tree", () => {
    const { container } = render(<CalendarSkeleton />);

    const bars = container.querySelector(".animate-pulse");
    expect(bars).not.toBeNull();
    expect(bars).toHaveAttribute("aria-hidden", "true");
  });
});
