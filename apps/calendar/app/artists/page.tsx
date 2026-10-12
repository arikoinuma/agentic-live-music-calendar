import type { Metadata } from "next";
import Link from "next/link";
import { getArtists } from "@/lib/api";

export const metadata: Metadata = { title: "Artists" };

// Same shape as /venues: fetch on the server, render a plain list. The API
// returns artists already alphabetical.
export default async function ArtistsPage() {
  const { artists } = await getArtists();

  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">Artists</h1>
      <ul className="mt-4 space-y-1">
        {artists.map((artist) => (
          <li key={artist.id}>
            <Link className="underline" href={`/artist/${artist.id}`}>
              {artist.name}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
