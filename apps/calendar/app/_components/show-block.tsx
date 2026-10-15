import Link from "next/link";
import { formatClockTime, formatShowTime } from "@/lib/dates";
import { formatAdmission, orderedLineup } from "@/lib/show-format";
import type { ShowSummary } from "@/lib/types";

/**
 * One show as a block: the calendar grid's cell, and the unit `/day/[date]`
 * lists. A Server Component — nothing in it is interactive.
 *
 * The focus is the venue and the artist names (requirements-initial.md,
 * "Calendar"); the time and price are supporting lines. `withVenue` is
 * false inside the grid, where the column header already names the venue,
 * and true where the block stands alone.
 *
 * The time line is the link to the show's own page (`/show/[id]`, B4-D3):
 * the venue and artist links below can't nest inside a block-wide link, and
 * the time is the one line that is about the show itself. A show with no
 * start time has no time to link, so its line stays plain text and a
 * separate "Details" link follows it — "Time not listed, show details" is a
 * statement, not a destination (plan review #6).
 *
 * Deliberately NOT here:
 *  - The poster (`image_url`). The block's focus is names, and 25 remote
 *    images on `/` would be 25 requests to third-party hosts. The show page
 *    renders the poster (`RemoteImage`, B4-D4).
 *
 * Optional fields from the generated types are `T | null | undefined`
 * (api-contract.md §7) — truthiness checks handle both.
 */
export function ShowBlock({ show, withVenue }: { show: ShowSummary; withVenue: boolean }) {
  const start = formatShowTime(show.date, show.start_time);
  const end = show.end_time ? formatClockTime(show.end_time) : null;
  const admission = formatAdmission(show);
  const lineup = orderedLineup(show.lineup);

  return (
    <article className="rounded-lg border bg-card p-3 text-sm text-card-foreground">
      {/* "Not stated" is shown as such, never as a made-up midnight
          (api-contract.md §4). An end time without a start is shown as
          what it is. */}
      {start !== null ? (
        <p className="text-muted-foreground">
          {/* `inline-block py-1`: a taller tap target for the one link in
              the block that is about the show, without moving the layout
              much. The visually hidden suffix gives the link a name that
              says where it goes.

              `relative` is NOT decoration. `.sr-only` is position:absolute,
              and a scroll container does not clip an absolutely positioned
              descendant whose containing block lies OUTSIDE it. Without a
              positioned ancestor this suffix's containing block is the page,
              so on a row scrolled sideways (this block lives in the
              calendar's per-date scroller) the hidden text sits far to the
              right and makes the whole PAGE scroll sideways — measured:
              scrollWidth 889 at 375px on `/`. Making the link the containing
              block keeps the suffix inside the row. (Same family as the
              calendar row's scroller in calendar-grid.tsx; recorded in
              docs/dev/notes.md.) */}
          <Link className="relative inline-block py-1 underline" href={`/show/${show.id}`}>
            {start}
            {end && ` – ${end}`}
            <span className="sr-only">, show details</span>
          </Link>
        </p>
      ) : (
        <p className="text-muted-foreground">
          {end ? `Start time not listed – ${end}` : "Time not listed"}
          {" · "}
          <Link className="inline-block py-1 underline" href={`/show/${show.id}`}>
            Details
          </Link>
        </p>
      )}

      {withVenue && (
        <p className="mt-1 font-medium">
          <Link className="underline" href={`/venue/${show.venue.id}`}>
            {show.venue.name}
          </Link>
        </p>
      )}

      <ul className="mt-1 space-y-0.5">
        {lineup.map((entry) => (
          <li key={entry.artist.id} className="font-medium">
            <Link className="underline" href={`/artist/${entry.artist.id}`}>
              {entry.artist.name}
            </Link>
            {/* A per-act time only means something on a multi-act bill. */}
            {entry.start_time && lineup.length > 1 && (
              <span className="ml-1 font-normal text-muted-foreground">
                {formatClockTime(entry.start_time)}
              </span>
            )}
          </li>
        ))}
      </ul>

      {/* Nothing at all when the listing didn't say what it costs — which
          is NOT the same as free (formatAdmission). */}
      {admission && <p className="mt-1 text-muted-foreground">{admission}</p>}
    </article>
  );
}
