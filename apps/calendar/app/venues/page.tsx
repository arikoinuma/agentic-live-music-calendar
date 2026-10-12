import type { Metadata } from "next";
import Link from "next/link";
import { getVenues } from "@/lib/api";

export const metadata: Metadata = { title: "Venues" };

// Another Server Component with a top-level `await` (see the first page
// to do this, app/venue/[id]/page.tsx, for why that's enough). The API
// returns venues already alphabetical, so there's no sorting here.
// Plain on purpose: B3/B4 own presentation.
export default async function VenuesPage() {
  const { venues } = await getVenues();

  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">Venues</h1>
      <ul className="mt-4 space-y-1">
        {venues.map((venue) => (
          <li key={venue.id}>
            <Link className="underline" href={`/venue/${venue.id}`}>
              {venue.name}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
