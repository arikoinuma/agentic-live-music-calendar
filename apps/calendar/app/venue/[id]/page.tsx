import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { CalendarGrid } from "@/app/_components/calendar-grid";
import { DetailRow } from "@/app/_components/detail-row";
import { JsonLd } from "@/app/_components/json-ld";
import { RemoteImage } from "@/app/_components/remote-image";
import { WindowNav } from "@/app/_components/window-nav";
import { getShows, getVenue } from "@/lib/api";
import { groupCalendar } from "@/lib/calendar";
import { buildCalendarHref } from "@/lib/calendar-href";
import { metroTodayOrNull } from "@/lib/dates";
import {
  AGE_LABELS,
  alcoholLabel,
  httpUrlOrNull,
  mapsUrl,
  SEATING_LABELS,
  SETTING_LABELS,
  VENUE_TYPE_LABELS,
} from "@/lib/detail-format";
import { showJsonLd } from "@/lib/json-ld";
import { getMetroOrNull } from "@/lib/metro";
import { parseFromParam, parseIdParam } from "@/lib/params";

// The tab title and description come from the venue itself, because these
// pages exist for search and sharing (arch-initial.md §4). `getVenue` is
// wrapped in React `cache()` (lib/api.ts), so asking for the same venue here
// and in the page below is ONE API request. A bad id gets the generic title;
// the page itself answers it with notFound().
export async function generateMetadata(props: PageProps<"/venue/[id]">): Promise<Metadata> {
  const { id: rawId } = await props.params;
  const id = parseIdParam(rawId);
  if (id === null) return { title: "Venue" };
  const venue = await getVenue(id);
  if (venue === null) return { title: "Venue" };
  return {
    title: venue.name,
    description: `Live music at ${venue.name}${venue.address ? `, ${venue.address}` : ""}`,
  };
}

// A venue: its metadata, then "the default calendar … filtered to the venue"
// (requirements-initial.md, "Venue"): B3's calendar grid, unchanged, over
// the shows this venue has in the window. THE RSC LESSON is in the older
// pages and in B2's plan: this is an `async` component that awaits its
// data on the server, with no `useEffect`, no loading state and no client
// data library.
//
// Paging: `?from=YYYY-MM-DD` moves the window (lib/calendar-window.ts). We
// send the API only a `start`; the server chooses the window's length and
// tells us what it served, and every link and heading below comes from that
// echo, so this page never does date arithmetic of its own.
//
// NO <Suspense> here, on purpose: a boundary above `notFound()` would turn
// a missing venue into a soft 404 (a 200). That is why this page, like the
// other detail routes, answers an API outage with the bare 500 (B3 D4).
export default async function VenuePage(props: PageProps<"/venue/[id]">) {
  const [{ id: rawId }, search] = await Promise.all([props.params, props.searchParams]);

  const id = parseIdParam(rawId);
  if (id === null) notFound();
  const from = parseFromParam(search.from);

  // Three independent requests, started together (the same no-waterfall
  // reasoning as `CalendarBody` in app/page.tsx). The 404 check comes AFTER:
  // a missing venue costs one harmless, empty shows request, and
  // `notFound()` throws, so it must not sit inside a try/catch or a
  // promise chain.
  const [venue, { start, end, shows }, metro] = await Promise.all([
    getVenue(id),
    getShows({ venueIds: [id], start: from ?? undefined }),
    getMetroOrNull(),
  ]);
  if (venue === null) notFound();

  // "Today" is the metro's date (lib/dates.ts); none if the zone is unusable.
  const today = (metro && metroTodayOrNull(metro.timezone)?.toString()) ?? null;
  // Every external URL is data a model scraped from a web page, so each goes
  // through the one http(s)-only rule; a rejected one renders no row.
  const website = httpUrlOrNull(venue.website);
  const calendarUrl = httpUrlOrNull(venue.calendar_url);

  // Optional fields from the generated types are `T | null | undefined`
  // (api-contract.md §7): a truthiness check handles both. `serves_alcohol`
  // is a boolean where `false` is an ANSWER, so it is compared with `!= null`.
  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">{venue.name}</h1>
      <div className="mt-4 flex flex-wrap items-start gap-6">
        <RemoteImage src={venue.photo_url} alt={`Photo of ${venue.name}`} />
        <dl className="grid max-w-xl grid-cols-[auto_1fr] gap-x-6 gap-y-2">
          {venue.address && (
            <DetailRow label="Address">
              <a className="underline" href={mapsUrl(venue.address)}>
                {venue.address}
              </a>
            </DetailRow>
          )}
          {venue.venue_type && (
            <DetailRow label="Type">{VENUE_TYPE_LABELS[venue.venue_type]}</DetailRow>
          )}
          {venue.age_restriction && (
            <DetailRow label="Ages">{AGE_LABELS[venue.age_restriction]}</DetailRow>
          )}
          {venue.serves_alcohol != null && (
            <DetailRow label="Alcohol">{alcoholLabel(venue.serves_alcohol)}</DetailRow>
          )}
          {venue.setting && <DetailRow label="Setting">{SETTING_LABELS[venue.setting]}</DetailRow>}
          {venue.seating && <DetailRow label="Seating">{SEATING_LABELS[venue.seating]}</DetailRow>}
          {venue.phone_numbers && venue.phone_numbers.length > 0 && (
            <DetailRow label="Phone">
              {venue.phone_numbers.map((phone, i) => (
                <span key={phone}>
                  {i > 0 && ", "}
                  <a className="underline" href={`tel:${phone}`}>
                    {phone}
                  </a>
                </span>
              ))}
            </DetailRow>
          )}
          {venue.emails && venue.emails.length > 0 && (
            <DetailRow label="Email">
              {venue.emails.map((email, i) => (
                <span key={email}>
                  {i > 0 && ", "}
                  <a className="underline" href={`mailto:${email}`}>
                    {email}
                  </a>
                </span>
              ))}
            </DetailRow>
          )}
          {website && (
            <DetailRow label="Website">
              <a className="underline" href={website}>
                {website}
              </a>
            </DetailRow>
          )}
          {calendarUrl && (
            <DetailRow label="Calendar">
              <a className="underline" href={calendarUrl}>
                {calendarUrl}
              </a>
            </DetailRow>
          )}
        </dl>
      </div>

      <h2 className="mt-10 text-xl font-semibold tracking-tight">Shows</h2>
      <WindowNav path={`/venue/${id}`} start={start} end={end} isDefault={from === null} />
      <p className="mt-2 text-sm">
        {/* The requirement: anything beyond paging this exact calendar means
            going to the calendar page (filters live there, not here). */}
        <Link
          className="underline"
          href={buildCalendarHref({ venueIds: [id], artistIds: [], month: null })}
        >
          Open in the calendar
        </Link>
      </p>

      {shows.length === 0 ? (
        <p className="mt-6">No shows listed for these dates.</p>
      ) : (
        <>
          <CalendarGrid rows={groupCalendar({ start, end, shows, today })} />
          {/* The events in the window on display, each located at this
              venue's address. Nothing at all when there are none. */}
          <JsonLd
            data={shows.map((show) =>
              showJsonLd(show, { venue, timeZone: metro?.timezone ?? null }),
            )}
          />
        </>
      )}
    </section>
  );
}
