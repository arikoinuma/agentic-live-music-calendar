"use client";

import type { FocusEvent, ReactNode } from "react";

/**
 * One date's sideways-scrolling row of venue columns (requirements-initial.md, "Calendar").
 *
 * It is the same `<div>` the calendar grid always rendered, with one behaviour added: when
 * keyboard focus lands on a control that is not fully inside the row, the row scrolls to that
 * control's whole COLUMN (B6 finding B6-F7). It is a Client Component only because it needs an
 * `onFocus` handler; everything inside it is still rendered on the server and passed in.
 *
 * WHY THE BROWSER'S OWN SCROLLING IS NOT ENOUGH. Chromium scrolls a nested scroller to reveal
 * a focused element only when the element is hidden; one that is already PARTLY visible is
 * left where it is. And `scroll-snap` (the row snaps to column starts) undoes a small
 * `scrollIntoView` nudge, pulling the row back to the nearest column start. So tabbing into a
 * row's second and later columns left the focused link half off-screen on a phone (at 320px,
 * 5% visible). Measured in the B6 plan: `focus()` leaves `scrollLeft` at 0 with snapping on or
 * off, and `scrollIntoView` only works with snapping off.
 *
 * WHY THE COLUMN. A column's left edge is a snap point, so scrolling the row to it lands exactly
 * where snapping wants the row to be, and the whole column (and so the focused control) is in
 * view. Scrolling to the control itself would be undone by the snap.
 *
 * Nothing happens when the control is already fully visible (no jump on every Tab) or when
 * focus lands outside a column.
 */
export function ScrollRow({ className, children }: { className: string; children: ReactNode }) {
  return (
    <div className={className} onFocus={revealColumn}>
      {children}
    </div>
  );
}

/** On focus, scroll the row so the focused control's column starts at the row's left edge. */
function revealColumn(event: FocusEvent<HTMLDivElement>) {
  const row = event.currentTarget;
  const target = event.target as HTMLElement;

  const rowBox = row.getBoundingClientRect();
  const targetBox = target.getBoundingClientRect();
  // 1px of slack for sub-pixel layout, so a control flush with the edge does not scroll.
  const fullyVisible = targetBox.left >= rowBox.left - 1 && targetBox.right <= rowBox.right + 1;
  if (fullyVisible) return;

  const column = target.closest("section");
  if (!column) return;
  // How far the column's left edge is from the row's, added to where the row already is.
  row.scrollTo({ left: row.scrollLeft + (column.getBoundingClientRect().left - rowBox.left) });
}
