import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ShowBlock } from "@/app/_components/show-block";
import { getShows } from "@/lib/api";
import { formatDayHeadingWithYear, formatShowTime } from "@/lib/dates";
import { parseDateParam } from "@/lib/params";
import {
  artistRows,
  dayHref,
  parseDaySort,
  timeOrder,
  venueOrder,
  type DaySort,
} from "@/lib/show-order";

// The title is the date itself, so no API call is needed. A bad date gets
// the generic title; the page answers it with notFound().
export async function generateMetadata(props: PageProps<"/day/[date]">): Promise<Metadata> {
  const { date: rawDate } = await props.params;
  const date = parseDateParam(rawDate);
  return { title: date === null ? "Day" : formatDayHeadingWithYear(date.toString()) };
}

// The three ways to view one night (requirements-initial.md, "/Day view").
const MODES: { sort: DaySort; label: string }[] = [
  { sort: "venue", label: "By venue" },
  { sort: "time", label: "By time" },
  { sort: "artist", label: "By artist" },
];

// One day's shows, in the order the reader chose. The mode lives in the URL
// (`?sort=time`, `?sort=artist`; the default is the bare URL — B4 plan, D6),
// like every other view state (arch-initial.md §4): shareable, bookmarkable,
// and the server renders the right result directly from it. The switch is
// three plain links, not a Client Component — changing the view is a
// navigation, so no JavaScript is needed to do it.
export default async function DayPage(props: PageProps<"/day/[date]">) {
  const [{ date: rawDate }, search] = await Promise.all([props.params, props.searchParams]);

  // A bad date is a 404, not an error page: the URL doesn't name a day.
  // parseDateParam is strict (no "20261008", no timestamps), so each day
  // has exactly one URL. An unknown `?sort=` is NOT a 404: it is just the
  // default view (a search param isn't part of the resource's identity).
  const date = parseDateParam(rawDate);
  if (date === null) notFound();
  const sort = parseDaySort(search.sort);

  // `start` and `end` are both the one day; the API's range is inclusive.
  // The string is what we send — the client never builds a JavaScript Date.
  const day = date.toString();
  const { shows } = await getShows({ start: day, end: day });

  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">{formatDayHeadingWithYear(day)}</h1>

      <nav aria-label="Order shows" className="mt-3 flex gap-4 text-sm">
        {MODES.map((mode) =>
          mode.sort === sort ? (
            <span key={mode.sort} aria-current="page" className="font-semibold">
              {mode.label}
            </span>
          ) : (
            <Link key={mode.sort} className="underline" href={dayHref(day, mode.sort)}>
              {mode.label}
            </Link>
          ),
        )}
      </nav>

      {shows.length === 0 ? (
        <p className="mt-4 text-muted-foreground">No shows listed for this day.</p>
      ) : sort === "artist" ? (
        <ul className="mt-4 space-y-2">
          {artistRows(shows).map((row) => {
            // formatShowTime names the NEXT day for a time after midnight
            // ("1:00 AM Thu"); null means the listing gave no time.
            const time = formatShowTime(row.date, row.time);
            return (
              <li key={`${row.showId}-${row.artist.id}`}>
                <Link className="font-medium underline" href={`/artist/${row.artist.id}`}>
                  {row.artist.name}
                </Link>
                {" · "}
                <Link className="underline" href={`/venue/${row.venue.id}`}>
                  {row.venue.name}
                </Link>
                {" · "}
                {time !== null ? (
                  <Link className="inline-block py-1 underline" href={`/show/${row.showId}`}>
                    {time}
                    <span className="sr-only">, show details</span>
                  </Link>
                ) : (
                  <>
                    <span className="text-muted-foreground">Time not listed</span>
                    {" · "}
                    <Link className="inline-block py-1 underline" href={`/show/${row.showId}`}>
                      Details
                    </Link>
                  </>
                )}
              </li>
            );
          })}
        </ul>
      ) : (
        <ul className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {[...shows].sort(sort === "time" ? timeOrder : venueOrder).map((show) => (
            <li key={show.id}>
              <ShowBlock show={show} withVenue />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
