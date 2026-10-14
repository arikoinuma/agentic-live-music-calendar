import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ShowBlock } from "@/app/_components/show-block";
import { getShows } from "@/lib/api";
import { formatDayHeading, nightSortKey } from "@/lib/dates";
import { parseDateParam } from "@/lib/params";

export const metadata: Metadata = { title: "Day" };

// One day's shows. B4 adds the three sort modes (by time, by venue, by
// artist); B3 swapped the plain list for the real show block, so the day
// view and the calendar render a show the same way.
export default async function DayPage(props: PageProps<"/day/[date]">) {
  const { date: rawDate } = await props.params;

  // A bad date is a 404, not an error page: the URL doesn't name a day.
  // parseDateParam is strict (no "20261008", no timestamps), so each day
  // has exactly one URL.
  const date = parseDateParam(rawDate);
  if (date === null) notFound();

  // `start` and `end` are both the one day; the API's range is inclusive.
  // The string is what we send — the client never builds a JavaScript Date.
  const day = date.toString();
  const { shows } = await getShows({ start: day, end: day });

  // The API orders a day by clock time, which puts a 1:00 AM show FIRST.
  // That show belongs to the END of this night (requirements-initial.md,
  // "Times after midnight"), so re-sort by night. `sort` is stable, so
  // shows with equal keys keep the API's venue-name order.
  const ordered = [...shows].sort((a, b) => nightSortKey(a.start_time) - nightSortKey(b.start_time));

  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">
        {formatDayHeading(day)}, {date.year}
      </h1>
      {ordered.length === 0 ? (
        <p className="mt-4 text-muted-foreground">No shows listed for this day.</p>
      ) : (
        <ul className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {ordered.map((show) => (
            <li key={show.id}>
              <ShowBlock show={show} withVenue />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
