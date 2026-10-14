/**
 * Paging a calendar window without a client clock (B4 plan, "Paging an
 * embedded calendar").
 *
 * The venue page shows a window of dates and lets the reader go "back and
 * forth to past or future with that exact calendar" (requirements-initial.md,
 * "Venue"). The window's length and its first day are the SERVER's
 * decisions (api-contract.md §3, "the server owns now"): the page sends
 * only a `start` (`?from=`) and the API answers with the `start`/`end` it
 * actually served. Every link here is computed from that echoed range, so
 * this module needs no clock and no constant "28".
 *
 * Pure, Temporal-based, server-side in practice (it imports lib/params.ts,
 * which pulls in the polyfill) — Client Components must not import it.
 */

import { parseFromParam } from "./params";
import { todo } from "./todo";

/**
 * The first day of the previous window and of the next one, given the
 * range just served (both ISO dates, `end` inclusive).
 *
 * TODO(Ari) — Gap B. Lesson: the paging links come from the range the
 *   SERVER echoed, never from a clock or a hard-coded 28 (api-contract.md
 *   §3). The window's length is `start.until(end).days + 1` — INCLUSIVE,
 *   hence the `+ 1`. The next window starts the day after `end`; the
 *   previous one starts one whole window before `start`. Temporal does the
 *   month, year and leap-day arithmetic.
 * Code (add `import { Temporal } from "@js-temporal/polyfill"` — Node 24 has
 *   no global Temporal — replace the `todo` line below, and delete
 *   `import { todo } from "./todo"`):
 *   const s = Temporal.PlainDate.from(start);
 *   const e = Temporal.PlainDate.from(end);
 *   const length = s.until(e).days + 1;
 *   return { earlier: s.subtract({ days: length }).toString(), later: e.add({ days: 1 }).toString() };
 * Check: `pnpm --filter calendar test calendar-window` — the default-window
 *   and one-day cases. Likeliest mistakes: forgetting the `+ 1` (earlier
 *   overlaps the current window by a day: 2026-09-01 instead of
 *   2026-08-31), or passing `largestUnit: "month"` to `until` (then `.days`
 *   is the remainder, not the total — the default unit is days, so pass
 *   nothing).
 */
export function windowLinks(start: string, end: string): { earlier: string; later: string } {
  return todo(start, end);
}

/** `path` with the window's first day, or the bare `path` for `null` (the server's default window). */
export function windowHref(path: string, from: string | null): string {
  return from === null ? path : `${path}?from=${from}`;
}

/**
 * The two hrefs the pager renders, each `null` when its date would not
 * survive `parseFromParam`. The URL parser is the single bound rule (years
 * 1..9998): a link whose date it would reject would silently land on the
 * DEFAULT window instead of paging, so such a link is simply not shown
 * (plan review #5). Practically unreachable, and cheap to get right.
 */
export function windowNavLinks(
  path: string,
  start: string,
  end: string,
): { earlier: string | null; later: string | null } {
  const { earlier, later } = windowLinks(start, end);
  const link = (from: string) => (parseFromParam(from) === null ? null : windowHref(path, from));
  return { earlier: link(earlier), later: link(later) };
}
