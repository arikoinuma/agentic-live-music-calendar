import Link from "next/link";
import { groupCalendar } from "@/lib/calendar";
import { hasActiveFilters, type CalendarFilters } from "@/lib/calendar-href";
import type { ShowSummary } from "@/lib/types";
import { CalendarGrid } from "./calendar-grid";

/**
 * What the home page shows once its shows have arrived: the calendar, or one
 * of two empty-state messages.
 *
 * WHY THIS IS ITS OWN COMPONENT (B5-D1). This branch used to sit inside
 * `CalendarBody` in app/page.tsx, an async Server Component that awaits five
 * API calls. Async components can't be unit tested (style guide, Testing),
 * so the "No matches found" requirement had no check. The fetching stays in
 * the page; everything that decides what to DRAW from data already in hand
 * moves here, synchronous and fed only by props, so Testing Library can
 * render it (calendar-results.test.tsx). It changes nothing a visitor sees:
 * the rendered page is byte-identical before and after the move.
 *
 * `start` and `end` are the range the SERVER says it served and `today` is
 * the metro's current date or null (api-contract.md §3, "the server owns
 * now"); this component computes neither.
 */
export function CalendarResults({
  start,
  end,
  shows,
  today,
  filters,
}: {
  start: string;
  end: string;
  shows: ShowSummary[];
  today: string | null;
  filters: CalendarFilters;
}) {
  if (shows.length === 0) {
    return hasActiveFilters(filters) ? (
      // The empty state the requirements call for: filters matched nothing,
      // so say so and offer the way out. A plain link, so it works before
      // any JavaScript has loaded.
      <p className="mt-6">
        No matches found.{" "}
        <Link className="underline" href="/">
          Reset filters
        </Link>
      </p>
    ) : (
      // Nothing to reset: the window itself is empty.
      <p className="mt-6">No shows listed for these dates.</p>
    );
  }
  return <CalendarGrid rows={groupCalendar({ start, end, shows, today })} />;
}
