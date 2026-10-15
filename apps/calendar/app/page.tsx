import Link from "next/link";
import { Suspense } from "react";
import { CalendarGrid } from "@/app/_components/calendar-grid";
import { CalendarSkeleton } from "@/app/_components/calendar-skeleton";
import { FilterHeader } from "@/app/_components/filter-header";
import { getArtists, getCalendarMonths, getShows, getVenues } from "@/lib/api";
import { groupCalendar, monthOptions } from "@/lib/calendar";
import { formatDayHeading, metroTodayOrNull } from "@/lib/dates";
import { getMetroOrNull } from "@/lib/metro";
import { parseCalendarFilters, toShowsQuery, type CalendarFilters } from "@/lib/params";

// The home calendar (B3): filters parsed from the URL, the matching shows
// from the API, laid out as dates -> venue columns -> show blocks.
//
// DYNAMIC, and that's correct. Reading `searchParams` is a request-time
// API, so this page renders per request by definition (Next docs,
// page.md) — don't "fix" that with `export const dynamic = ...`. (Every
// other route is dynamic too, for a different reason: the root layout
// fetches the metro with `no-store`. That's the accepted cost of B2's
// decision B2-D1, no persistent caching yet.)
export default async function Home({ searchParams }: PageProps<"/">) {
  // The URL is the filter state (arch-initial.md §4). `searchParams` is a
  // Promise in Next 16, like `params`. parseCalendarFilters never throws:
  // junk in the URL is ignored, so `/?venue=abc` is just the calendar.
  const filters = parseCalendarFilters(await searchParams);

  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">Live music</h1>

      {/* WHY THE <Suspense> IS HERE and not a root `loading.tsx` (plan B3-D4).
          Everything that needs the API — the shows, the filter options, the
          month list — is below this boundary, so the header, footer and
          this heading stream first and a skeleton stands in meanwhile; and
          if the API is down the shell still renders and `error.tsx` takes
          over this region after hydration. A root `loading.tsx` would do
          the same for EVERY page, but once a response streams, `notFound()`
          can no longer set HTTP 404 (Next docs, not-found.md): every bad
          `/venue/abc` would become a soft 404 (a 200). This page never
          calls `notFound()`, so the boundary costs nothing here.
          Consequence, accepted: with the API down `/` answers 200 with the
          shell, where the detail pages still answer B2's bare 500.

          No `key` on the boundary: on a filter change the navigation
          transition keeps the current calendar on screen (the header shows
          "Updating…") instead of flashing this skeleton. */}
      <Suspense fallback={<CalendarSkeleton />}>
        <CalendarBody filters={filters} />
      </Suspense>
    </section>
  );
}

// Everything that waits on the API. Five independent requests, run
// together rather than one after another. `getMetroOrNull` is the same
// call the layout's footer makes, shared through React's `cache()`.
async function CalendarBody({ filters }: { filters: CalendarFilters }) {
  const [{ start, end, shows }, { venues }, { artists }, { months }, metro] = await Promise.all([
    getShows(toShowsQuery(filters)),
    getVenues(),
    getArtists(),
    getCalendarMonths(),
    getMetroOrNull(),
  ]);

  // "Today" is the metro's date, not the server's (lib/dates.ts, B3-Gap-A).
  // With no metro, or a timezone we can't use, no row is marked — better
  // than guessing a zone.
  const today = (metro && metroTodayOrNull(metro.timezone)?.toString()) ?? null;

  const isFiltered =
    filters.venueIds.length > 0 || filters.artistIds.length > 0 || filters.month !== null;

  return (
    <>
      <FilterHeader
        filters={filters}
        venues={venues}
        artists={artists}
        months={monthOptions(months, filters.month)}
      />

      {/* The range the SERVER says it served, not one computed here: "the
          next four weeks" is a question about the metro's clock, not the
          browser's (api-contract.md §3, "the server owns now"). With the
          sample-data API this is a pinned 2026-09-28 to 2026-10-25
          whatever today is; the real endpoint reads the metro's local
          date. Not a bug to chase. */}
      <p className="mt-3 text-sm text-muted-foreground">
        Showing {formatDayHeading(start)} – {formatDayHeading(end)}
      </p>

      {shows.length === 0 ? (
        isFiltered ? (
          // The empty state the requirements call for: filters matched
          // nothing, so say so and offer the way out.
          <p className="mt-6">
            No matches found.{" "}
            <Link className="underline" href="/">
              Reset filters
            </Link>
          </p>
        ) : (
          // Nothing to reset: the window itself is empty.
          <p className="mt-6">No shows listed for these dates.</p>
        )
      ) : (
        <CalendarGrid rows={groupCalendar({ start, end, shows, today })} />
      )}
    </>
  );
}
