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
 * Deliberately NOT here:
 *  - The poster (`image_url`). Hosts are arbitrary venue sites:
 *    `next/image` would need an open-ended `images.remotePatterns`, and a
 *    bare <img> trips `@next/next/no-img-element`. The block's focus is
 *    names; the poster belongs on the show page (B4).
 *  - A link to `/show/[id]`: that page is B4, and the venue and artist
 *    links below can't nest inside another link anyway.
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
      <p className="text-muted-foreground">
        {start ?? (end ? "Start time not listed" : "Time not listed")}
        {end && ` – ${end}`}
      </p>

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
