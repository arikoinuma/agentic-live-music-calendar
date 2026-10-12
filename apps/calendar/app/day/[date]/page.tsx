import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { PlainShowList } from "@/app/_components/plain-show-list";
import { getShows } from "@/lib/api";
import { parseDateParam } from "@/lib/params";

export const metadata: Metadata = { title: "Day" };

// One day's shows. B4 adds the three sort modes (by time, by venue, by
// artist); B2 proves the route, the validation and the fetch.
export default async function DayPage(props: PageProps<"/day/[date]">) {
  const { date: rawDate } = await props.params;

  // A bad date is a 404, not an error page: the URL doesn't name a day.
  // parseDateParam is strict (no "20261008", no timestamps), so each day
  // has exactly one URL.
  const date = parseDateParam(rawDate);
  if (date === null) notFound();

  // `start` and `end` are both the one day; the API's range is inclusive.
  // The string is what we send and print — the client never builds a
  // JavaScript Date.
  const day = date.toString();
  const { shows } = await getShows({ start: day, end: day });

  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">{day}</h1>
      {shows.length === 0 ? (
        <p className="mt-4 text-muted-foreground">No shows listed for this day.</p>
      ) : (
        <PlainShowList shows={shows} />
      )}
    </section>
  );
}
