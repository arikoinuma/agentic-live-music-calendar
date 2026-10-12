import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getArtist } from "@/lib/api";
import { parseIdParam } from "@/lib/params";

export const metadata: Metadata = { title: "Artist" };

// Metadata only in B2. The artist's upcoming-shows calendar is B4.
//
// This page is the complete version of the flow `/venue/[id]` teaches
// (param -> validate -> fetch -> 404 or render); read that one's comments.
export default async function ArtistPage(props: PageProps<"/artist/[id]">) {
  // In Next 16 `params` is a Promise — there is no synchronous fallback.
  const { id: rawId } = await props.params;

  // `notFound()` THROWS; the code after it never runs. That's also why it
  // must never sit inside a try/catch that swallows errors.
  const id = parseIdParam(rawId);
  if (id === null) notFound();

  const artist = await getArtist(id);
  if (artist === null) notFound();

  // Optional fields from the generated types are `T | null | undefined`
  // (api-contract.md §7): FastAPI always sends them, as null when unknown,
  // but the schema marks them optional because they have defaults. A bare
  // truthiness check handles both, and a field the API doesn't have
  // renders nothing — not a labelled blank (api-contract.md §6).
  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">{artist.name}</h1>
      <dl className="mt-4 grid max-w-xl grid-cols-[auto_1fr] gap-x-6 gap-y-2">
        {artist.hometown && (
          <>
            <dt className="text-muted-foreground">Hometown</dt>
            <dd>{artist.hometown}</dd>
          </>
        )}
        {artist.format && (
          <>
            <dt className="text-muted-foreground">Format</dt>
            <dd>{artist.format}</dd>
          </>
        )}
        {artist.repertoire && (
          <>
            <dt className="text-muted-foreground">Repertoire</dt>
            <dd>{artist.repertoire}</dd>
          </>
        )}
        {artist.website && (
          <>
            <dt className="text-muted-foreground">Website</dt>
            <dd>
              <a className="underline" href={artist.website}>
                {artist.website}
              </a>
            </dd>
          </>
        )}
      </dl>
    </section>
  );
}
