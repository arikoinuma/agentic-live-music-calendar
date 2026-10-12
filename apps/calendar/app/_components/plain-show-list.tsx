import Link from "next/link";
import type { ShowSummary } from "@/lib/types";

/**
 * A deliberately PLAIN list of shows, shared by `/` and `/day/[date]`.
 *
 * B2 proves the data reaches the page; B3 replaces this with the real
 * calendar layout and show block, and B3 deletes this file. So it's the
 * smallest thing that renders every field a reader would need to trust
 * the plumbing: when, where, who, and what it costs.
 *
 * Everything here is a string straight from the API (api-contract.md §4):
 * times are "20:00:00", money is "15.00". They're printed as received —
 * no `new Date()` (it would shift the day) and no `parseFloat` (it would
 * round money). Proper Temporal-based formatting is B3's job.
 */
export function PlainShowList({ shows }: { shows: ShowSummary[] }) {
  return (
    <ul className="mt-4 space-y-3">
      {shows.map((show) => (
        <li key={show.id} className="border-b pb-3">
          <div>
            {/* The date is the heading above each group (or the page title
                on /day/[date]), so it isn't repeated per row.

                `start_time` is `string | null | undefined`: the API
                serialises it as null when the venue's page gave no time.
                "Not stated" is a real answer and is shown as one, never
                as a made-up midnight (api-contract.md §4). */}
            <span className="text-muted-foreground">
              {show.start_time ?? "time not listed"}
            </span>
          </div>
          <div className="font-medium">
            <Link className="underline" href={`/venue/${show.venue.id}`}>
              {show.venue.name}
            </Link>
          </div>
          <div>
            {show.lineup.map((entry, index) => (
              <span key={entry.artist.id}>
                {index > 0 && ", "}
                <Link className="underline" href={`/artist/${entry.artist.id}`}>
                  {entry.artist.name}
                </Link>
              </span>
            ))}
          </div>
          <Admission show={show} />
        </li>
      ))}
    </ul>
  );
}

// All three admission fields null means "the listing didn't say" — NOT
// free. `free_admission` is true only when the listing says so
// (api-contract.md §4), so an unpriced show prints nothing here.
function Admission({ show }: { show: ShowSummary }) {
  if (show.free_admission) return <div>Free</div>;
  const parts = [
    show.admission_advance != null && `$${show.admission_advance} advance`,
    show.admission_day != null && `$${show.admission_day} day of show`,
  ].filter(Boolean);
  return parts.length > 0 ? <div>{parts.join(" / ")}</div> : null;
}
