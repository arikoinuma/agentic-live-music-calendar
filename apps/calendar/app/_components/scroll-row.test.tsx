/**
 * The calendar's sideways-scrolling venue row, as a component (B6 finding B6-F7).
 *
 * Chromium does not scroll a nested scroller to reveal a focused element that is already
 * partly visible, and `scroll-snap` undoes a small scroll nudge, so keyboard focus could sit
 * half off-screen in a row's second and later columns. `ScrollRow` scrolls the row, on focus,
 * to the focused control's whole COLUMN, whose left edge is a snap point.
 *
 * jsdom has no layout, so every rectangle below is stubbed by hand. These tests prove the
 * DECISION (scroll or not, to where); that the browser really ends up showing the control is
 * proved by the Playwright journey in e2e/keyboard.spec.ts.
 */
import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ScrollRow } from "./scroll-row";

// A rectangle with only the fields the component reads.
const rect = (left: number, right: number) => ({ left, right, top: 0, bottom: 20, width: right - left, height: 20 }) as DOMRect;

// Renders a row holding one column holding one link, with the given geometry, and focuses the
// link. Returns the row's `scrollTo` spy.
function focusLink(geometry: { row: [number, number]; column: [number, number]; link: [number, number]; scrollLeft?: number }) {
  const { container } = render(
    <ScrollRow className="row">
      <section>
        <a href="/x">link</a>
      </section>
    </ScrollRow>,
  );
  const row = container.querySelector(".row") as HTMLElement;
  const column = container.querySelector("section") as HTMLElement;
  const link = container.querySelector("a") as HTMLElement;
  row.getBoundingClientRect = () => rect(...geometry.row);
  column.getBoundingClientRect = () => rect(...geometry.column);
  link.getBoundingClientRect = () => rect(...geometry.link);
  row.scrollLeft = geometry.scrollLeft ?? 0;
  const scrollTo = vi.fn();
  row.scrollTo = scrollTo;
  link.focus();
  return scrollTo;
}

describe("ScrollRow", () => {
  // Proves: focus landing on a link that is only PARTLY inside the row scrolls the row so the
  // link's column starts at the row's left edge. Expected value: the row's left edge is at x=16
  // and the column's at x=284, so the row must scroll 284 - 16 = 268px further (from 0). Fails if
  // the handler is missing, or scrolls to the link instead of the column (the snap point).
  it("scrolls to the focused control's column when the control is partly outside the row", () => {
    const scrollTo = focusLink({ row: [16, 359], column: [284, 540], link: [297, 425] });

    expect(scrollTo).toHaveBeenCalledExactlyOnceWith({ left: 268 });
  });

  // Proves: a control that is already fully inside the row is left alone. Scrolling anyway would
  // make the page jump under every Tab press that stays within the visible columns.
  it("does nothing when the control is fully inside the row", () => {
    const scrollTo = focusLink({ row: [16, 359], column: [16, 272], link: [29, 120] });

    expect(scrollTo).not.toHaveBeenCalled();
  });

  // Proves: the same distance rule when the row is already scrolled and the link is cut off on
  // the RIGHT: scroll position 100, column left edge at x=200, row left edge at x=16: the row
  // goes to 100 + (200 - 16) = 284.
  it("scrolls relative to the row's current position", () => {
    const scrollTo = focusLink({ row: [16, 359], column: [200, 456], link: [213, 400], scrollLeft: 100 });

    expect(scrollTo).toHaveBeenCalledExactlyOnceWith({ left: 284 });
  });
});
