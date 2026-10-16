import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { DetailRow } from "@/app/_components/detail-row";
import { JsonLd } from "@/app/_components/json-ld";
import { RemoteImage } from "@/app/_components/remote-image";
import { getShow, getVenue } from "@/lib/api";
import { formatClockTime, formatDayHeadingWithYear, formatShowTime } from "@/lib/dates";
import {
  AGE_LABELS,
  alcoholLabel,
  httpUrlOrNull,
  mapsUrl,
  SEATING_LABELS,
  SETTING_LABELS,
} from "@/lib/detail-format";
import { showJsonLd } from "@/lib/json-ld";
import { getMetroOrNull } from "@/lib/metro";
import { parseIdParam } from "@/lib/params";
import { formatAdmission, orderedLineup } from "@/lib/show-format";

// "Nooky Jones, Beasthead at Zhora Darling, Wed, Sep 30, 2026". The cached
// `getShow` makes this and the page one API request.
export async function generateMetadata(props: PageProps<"/show/[id]">): Promise<Metadata> {
  const { id: rawId } = await props.params;
  const id = parseIdParam(rawId);
  if (id === null) return { title: "Show" };
  const show = await getShow(id);
  if (show === null) return { title: "Show" };
  const names = orderedLineup(show.lineup).map((entry) => entry.artist.name).join(", ");
  return { title: `${names || "Live music"} at ${show.venue.name}, ${formatDayHeadingWithYear(show.date)}` };
}

// One show's own page (B4-D3): the thing every show block's time line
// links to, and the reason each show is indexable and shareable
// (arch-initial.md §4: "every event … has its own server-rendered detail
// page"). It carries the schema.org Event JSON-LD.
//
// The flow is the venue page's. One request IS dependent: the show tells us
// its venue's id, so the venue (for the address) can only be fetched after
// it — a real dependency, not the needless waterfall the venue page avoids.
// The metro (for the offset in the JSON-LD dates) is independent, so it
// starts with the show.
export default async function ShowPage(props: PageProps<"/show/[id]">) {
  const { id: rawId } = await props.params;
  const id = parseIdParam(rawId);
  if (id === null) notFound();

  const [show, metro] = await Promise.all([getShow(id), getMetroOrNull()]);
  if (show === null) notFound();
  // A venue deleted between the two calls renders the page without an
  // address; it is not a reason to 404 a show we do have.
  const venue = await getVenue(show.venue.id);

  const lineup = orderedLineup(show.lineup);
  const names = lineup.map((entry) => entry.artist.name).join(", ");
  const start = formatShowTime(show.date, show.start_time);
  const end = show.end_time ? formatClockTime(show.end_time) : null;
  const admission = formatAdmission(show);
  const source = httpUrlOrNull(show.original_url);

  // Optional fields from the generated types are `T | null | undefined`
  // (api-contract.md §7). The four inherited fields are the RESOLVED values
  // (api-contract.md §5): whether they came from the show or its venue is
  // not said, and nothing here depends on it. `serves_alcohol` is a boolean
  // where `false` is an answer, hence `!= null`.
  return (
    <article>
      <p className="text-muted-foreground">
        <Link className="underline" href={`/day/${show.date}`}>
          {formatDayHeadingWithYear(show.date)}
        </Link>
      </p>
      <h1 className="mt-1 text-2xl font-semibold tracking-tight">{names || "Live music"}</h1>

      <p className="mt-3">
        {/* "Not stated" is shown as such, never as a made-up midnight. */}
        {start ?? (end ? "Start time not listed" : "Time not listed")}
        {end && ` – ${end}`}
      </p>
      <p className="mt-1">
        <Link className="font-medium underline" href={`/venue/${show.venue.id}`}>
          {show.venue.name}
        </Link>
        {venue?.address && (
          <>
            {" · "}
            <a className="underline" href={mapsUrl(venue.address)}>
              {venue.address}
            </a>
          </>
        )}
      </p>

      <RemoteImage
        className="mt-4"
        src={show.image_url}
        alt={`Poster for ${names || show.venue.name}`}
      />

      {lineup.length > 0 && (
        <>
          <h2 className="mt-8 text-xl font-semibold tracking-tight">Lineup</h2>
          <ol className="mt-2 space-y-1">
            {lineup.map((entry) => (
              <li key={entry.artist.id}>
                <Link className="font-medium underline" href={`/artist/${entry.artist.id}`}>
                  {entry.artist.name}
                </Link>
                {/* A per-act time only means something on a multi-act bill. */}
                {entry.start_time && lineup.length > 1 && (
                  <span className="ml-2 text-muted-foreground">
                    {formatClockTime(entry.start_time)}
                  </span>
                )}
              </li>
            ))}
          </ol>
        </>
      )}

      <dl className="mt-8 grid max-w-xl grid-cols-[auto_1fr] gap-x-6 gap-y-2">
        {/* Nothing at all when the listing didn't say what it costs — which
            is NOT the same as free (formatAdmission). */}
        {admission && <DetailRow label="Admission">{admission}</DetailRow>}
        {show.age_restriction && (
          <DetailRow label="Ages">{AGE_LABELS[show.age_restriction]}</DetailRow>
        )}
        {show.serves_alcohol != null && (
          <DetailRow label="Alcohol">{alcoholLabel(show.serves_alcohol)}</DetailRow>
        )}
        {show.setting && <DetailRow label="Setting">{SETTING_LABELS[show.setting]}</DetailRow>}
        {show.seating && <DetailRow label="Seating">{SEATING_LABELS[show.seating]}</DetailRow>}
        {/* No event page yet (requirements: "perhaps v2"), so plain text. */}
        {show.event && <DetailRow label="Event">{show.event.name}</DetailRow>}
        {/* Where this listing came from: part of making the agent's work
            visible to the reader, not only to the audit trail. */}
        {source && (
          <DetailRow label="Source">
            <a className="underline" href={source}>
              {new URL(source).hostname}
            </a>
          </DetailRow>
        )}
      </dl>

      <JsonLd data={showJsonLd(show, { venue, timeZone: metro?.timezone ?? null })} />
    </article>
  );
}
