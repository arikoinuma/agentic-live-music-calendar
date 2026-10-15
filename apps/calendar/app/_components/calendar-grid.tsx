import Link from "next/link";
import { formatDayHeading } from "@/lib/dates";
import type { CalendarRow } from "@/lib/calendar";
import { ShowBlock } from "./show-block";

/**
 * The calendar: a vertical list of dates, each date a horizontally
 * scrolling row of venue columns, each column holding that venue's shows
 * that day (requirements-initial.md, "Calendar").
 *
 * A Server Component: nothing here is interactive (the sideways scroll is
 * the browser's own), so it ships no JavaScript, and the Temporal
 * formatting stays on the server.
 *
 * Plan D1/D2: a row lists only the venues with a show that date, and every
 * date in the served range gets a row — a date with nothing on it is a thin
 * "Nothing listed" line, not a gap.
 */
export function CalendarGrid({ rows }: { rows: CalendarRow[] }) {
  return (
    <ol className="mt-6 divide-y">
      {rows.map((row) => {
        const heading = formatDayHeading(row.date);
        return (
          // Below `md` the row is plain block flow, above it a two-column
          // grid (date | venues). Block flow on phones is deliberate: a
          // `sticky` element only sticks within its own grid AREA, and in a
          // one-column grid the heading's area is just its own height, so
          // it would never stick. In block flow the <li> is the containing
          // block and the heading stays visible while its row is on screen.
          <li
            key={row.date}
            aria-current={row.isToday ? "date" : undefined}
            className="py-3 md:grid md:grid-cols-[9rem_1fr] md:gap-3"
          >
            <h2 className="sticky top-0 z-10 bg-background py-1 text-base font-semibold md:self-start">
              <Link className="underline" href={`/day/${row.date}`}>
                {heading}
              </Link>
              {row.isToday && (
                <span className="ml-2 rounded bg-primary px-1.5 py-0.5 text-xs font-medium text-primary-foreground">
                  Today
                </span>
              )}
            </h2>

            {row.venues.length === 0 ? (
              <p className="py-1 text-sm text-muted-foreground">Nothing listed</p>
            ) : (
              // THE SCROLLER IS THE <li>'s DIRECT GRID ITEM — do not wrap it
              // in another element. (This matters from `md` up, where the <li>
              // is a grid; below it the row is block flow and a wrapper's
              // width is just its container's, so a wrapper does no harm on
              // a phone.) A grid item's automatic minimum width is
              // its content's min-content width, unless the item is itself a
              // scroll container (whose automatic minimum is 0). Wrap this in
              // a plain <div> and THAT <div>'s minimum becomes the full width
              // of every venue column, the `1fr` track grows to fit it, and
              // the whole PAGE scrolls sideways instead of this row. (If a
              // wrapper is ever needed: `min-w-0` on it.)
              //
              // Deliberately NO `tabIndex`, `role="region"` or `aria-label`
              // here (code review #4; Ari tried it and it was noise). A
              // scrollable area must be keyboard-reachable, but every venue
              // column already starts with a link, so Tab lands inside the row
              // and the browser scrolls the focused link into view. Making the
              // row itself focusable added a tab stop per date (20 on `/`)
              // before that date's first link, and `role="region"` added 20
              // near-identical landmarks to a screen reader's list.
              //
              // The scroller's classes: `overflow-x-auto` makes it a scroll
              // container (which is what lets the `1fr` track stay the page's
              // width); `overscroll-x-contain` stops a swipe that reaches the
              // row's end from chaining into the browser's Back gesture; and
              // scroll-snap keeps columns aligned after a flick.
              <div
                className="flex snap-x snap-mandatory gap-3 overflow-x-auto overscroll-x-contain pb-2"
              >
                {row.venues.map((column) => (
                  <section
                    key={column.venue.id}
                    className="w-[min(80vw,16rem)] shrink-0 snap-start"
                  >
                    <h3 className="mb-2 font-medium">
                      <Link className="underline" href={`/venue/${column.venue.id}`}>
                        {column.venue.name}
                      </Link>
                    </h3>
                    {/* Every show, no cap at two (plan D7): "1-2 shows" in
                        the requirements describes the usual case, and a
                        cap would hide real shows. The column grows taller. */}
                    <div className="space-y-2">
                      {column.shows.map((show) => (
                        <ShowBlock key={show.id} show={show} withVenue={false} />
                      ))}
                    </div>
                  </section>
                ))}
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}
