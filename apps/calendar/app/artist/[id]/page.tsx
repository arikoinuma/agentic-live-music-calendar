import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { DetailRow } from "@/app/_components/detail-row";
import { RemoteImage } from "@/app/_components/remote-image";
import { ShowBlock } from "@/app/_components/show-block";
import { getArtist, getShows } from "@/lib/api";
import { formatDayHeadingWithYear } from "@/lib/dates";
import { ARTIST_FORMAT_LABELS, httpUrlOrNull, REPERTOIRE_LABELS } from "@/lib/detail-format";
import { parseIdParam } from "@/lib/params";
import { inNightOrder } from "@/lib/show-order";

// As on the venue page: the title comes from the record, and the cached
// `getArtist` makes asking for it here and in the page one API request.
export async function generateMetadata(props: PageProps<"/artist/[id]">): Promise<Metadata> {
  const { id: rawId } = await props.params;
  const id = parseIdParam(rawId);
  if (id === null) return { title: "Artist" };
  const artist = await getArtist(id);
  return { title: artist?.name ?? "Artist" };
}

// An artist: their metadata, then "the list view of their upcoming shows"
// (requirements-initial.md, "Artist") — EVERY upcoming show, not just the
// next four weeks (B4-D2). We ask the API for
// `upcoming: true`: "from the server's today, no upper limit". The client
// sends no date at all, because the server owns "now" (api-contract.md §3),
// and prints the `start` the server echoes. Unlike the venue page there is
// no `?from=` and no pager: a list that already reaches the end of the
// artist's bookings has nowhere to page to, so this page doesn't read
// `searchParams` and a stray `?from=` is simply ignored.
//
// The flow is the same as the venue page's (param -> validate -> fetch ->
// 404 or render); read the comments there. Two independent requests start
// together. `notFound()` THROWS and so stays outside any try/catch.
export default async function ArtistPage(props: PageProps<"/artist/[id]">) {
  const { id: rawId } = await props.params;
  const id = parseIdParam(rawId);
  if (id === null) notFound();

  const [artist, { start, shows }] = await Promise.all([
    getArtist(id),
    getShows({ artistIds: [id], upcoming: true }),
  ]);
  if (artist === null) notFound();

  const website = httpUrlOrNull(artist.website);

  // Optional fields from the generated types are `T | null | undefined`
  // (api-contract.md §7): FastAPI always sends them, as null when unknown,
  // but the schema marks them optional because they have defaults. A bare
  // truthiness check handles both, and a field the API doesn't have
  // renders nothing — not a labelled blank (api-contract.md §6).
  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">{artist.name}</h1>
      <div className="mt-4 flex flex-wrap items-start gap-6">
        <RemoteImage src={artist.photo_url} alt={`Photo of ${artist.name}`} />
        <dl className="grid max-w-xl grid-cols-[auto_1fr] gap-x-6 gap-y-2">
          {artist.hometown && <DetailRow label="Hometown">{artist.hometown}</DetailRow>}
          {artist.format && (
            <DetailRow label="Format">{ARTIST_FORMAT_LABELS[artist.format]}</DetailRow>
          )}
          {artist.repertoire && (
            <DetailRow label="Repertoire">{REPERTOIRE_LABELS[artist.repertoire]}</DetailRow>
          )}
          {website && (
            <DetailRow label="Website">
              <a className="underline" href={website}>
                {website}
              </a>
            </DetailRow>
          )}
        </dl>
      </div>

      <h2 className="mt-10 text-xl font-semibold tracking-tight">Upcoming shows</h2>
      {shows.length === 0 ? (
        <p className="mt-3">No upcoming shows listed.</p>
      ) : (
        <>
          {/* The SERVER's "today", formatted — "the server owns now" made visible. */}
          <p className="mt-1 text-sm text-muted-foreground">
            Everything listed from {formatDayHeadingWithYear(start)} on
          </p>
          {/* Chronological, with a 1:00 AM show after its evening's (the API
              sorts by clock time, which would put it first). */}
          <ol className="mt-4 space-y-5">
            {inNightOrder(shows).map((show) => (
              <li key={show.id}>
                <h3 className="mb-2 font-medium">
                  <Link className="underline" href={`/day/${show.date}`}>
                    {formatDayHeadingWithYear(show.date)}
                  </Link>
                </h3>
                <div className="max-w-md">
                  <ShowBlock show={show} withVenue />
                </div>
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}
