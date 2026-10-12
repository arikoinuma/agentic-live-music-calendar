import Link from "next/link";
import { PlainShowList } from "@/app/_components/plain-show-list";
import { getShows, getVenues } from "@/lib/api";
import {
  buildCalendarHref,
  parseCalendarFilters,
  toShowsQuery,
} from "@/lib/params";
import type { ShowSummary } from "@/lib/types";

// The home calendar, B2 edition: filters parsed from the URL, the matching
// shows from the API, rendered as a plain list. The real calendar layout,
// filter header and show blocks are B3 — this page proves the plumbing
// (URL -> filters -> API query -> data) that B3 builds on.
//
// DYNAMIC, and that's correct. Reading `searchParams` is a request-time
// API, so this page renders per request by definition (Next docs,
// page.md) — don't "fix" that with `export const dynamic = ...`, it's
// already what's happening. (Every other route is dynamic too in B2, for a
// different reason: the root layout fetches the metro with `no-store`.
// That's the accepted cost of decision D1, no persistent caching yet.
// B1's placeholder was static; this page is not.)
export default async function Home({ searchParams }: PageProps<"/">) {
  // The URL is the filter state (arch-initial.md §4). `searchParams` is a
  // Promise in Next 16, like `params`. parseCalendarFilters never throws:
  // junk in the URL is ignored, so `/?venue=abc` is just the calendar.
  const filters = parseCalendarFilters(await searchParams);

  // Two independent requests, so run them together instead of one after
  // the other. `getVenues` is here only for the demo filter links below.
  const [{ start, end, shows }, { venues }] = await Promise.all([
    getShows(toShowsQuery(filters)),
    getVenues(),
  ]);

  const isFiltered =
    filters.venueIds.length > 0 ||
    filters.artistIds.length > 0 ||
    filters.month !== null;

  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">Live music</h1>

      {/* The range the SERVER says it served, not one computed here: "the
          next four weeks" is a question about the metro's clock, not the
          browser's (api-contract.md §3, "the server owns now"). With the
          sample-data API this is a pinned 2026-09-28 to 2026-10-25
          whatever today is; the real endpoint reads the metro's local
          date. Not a bug to chase. */}
      <p className="mt-2 text-muted-foreground">
        Showing {start} to {end}
      </p>

      {/* SCAFFOLDING, deleted by B3 (which brings the real filter header):
          one link per venue, built by buildCalendarHref, to prove that
          filters round-trip through the URL and to give B3 a working
          target. Plain <Link>s — no filter component, no "use client". */}
      <nav aria-label="Filter by venue" className="mt-4 flex flex-wrap gap-x-4 gap-y-1">
        {venues.map((venue) => (
          <Link
            key={venue.id}
            className="underline"
            href={buildCalendarHref({ ...filters, venueIds: [venue.id] })}
          >
            {venue.name}
          </Link>
        ))}
        {isFiltered && (
          <Link className="underline" href="/">
            Clear filters
          </Link>
        )}
      </nav>

      {shows.length === 0 ? (
        // The real empty state is B3's.
        <p className="mt-6">
          No shows match these filters.{" "}
          <Link className="underline" href="/">
            Show everything
          </Link>
        </p>
      ) : (
        groupByDate(shows).map(([date, dayShows]) => (
          <div key={date} className="mt-6">
            <h2 className="text-lg font-semibold">
              <Link className="underline" href={`/day/${date}`}>
                {date}
              </Link>
            </h2>
            <PlainShowList shows={dayShows} />
          </div>
        ))
      )}
    </section>
  );
}

// The API returns shows already ordered by date, then time, so grouping is
// just collecting runs by the date string — no date parsing at all. A Map
// keeps insertion order, which preserves the server's ordering.
function groupByDate(shows: ShowSummary[]): [string, ShowSummary[]][] {
  const groups = new Map<string, ShowSummary[]>();
  for (const show of shows) {
    groups.set(show.date, [...(groups.get(show.date) ?? []), show]);
  }
  return [...groups];
}
