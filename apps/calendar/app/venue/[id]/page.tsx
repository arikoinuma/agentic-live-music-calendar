import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getVenue } from "@/lib/api";
import { parseIdParam } from "@/lib/params"

export const metadata: Metadata = { title: "Venue" };

// Metadata only in B2. The venue's embedded calendar is B4.
//
// THE RSC LESSON, once, here (the other pages just repeat it):
// this component is an `async` function that `await`s its data directly.
// It runs on the SERVER, before any HTML is sent, so there is no
// `useEffect`, no loading state, no client-side data library and no
// loading flash — the browser receives finished markup. The API client
// (lib/api.ts) is `server-only`, so it couldn't be used from a Client
// Component here even by accident.
export default async function VenuePage(props: PageProps<"/venue/[id]">) {
  // (Ari) — Gap D. Lesson: in Next 16 `params` (and `searchParams`) are
  //   Promises with no synchronous fallback (nextjs-style-guide.md, Routing
  //   conventions and the Anti-patterns table). The route's whole
  //   filesystem-routing story — folder `[id]` becomes a parameter — only
  //   becomes real when the value arrives in the component.
  // Code:
  //   const { id: rawId } = await props.params;
  //   (then delete the `todo` line below; `props` is typed by the
  //   generated PageProps<"/venue/[id]">)
  // Check: `pnpm check-types` (runs `next typegen`) — using `props.params`
  //   without `await` is a type error. That is Gap D's own check. A curl
  //   check needs Gaps C AND E filled too: while Gap C (lib/metro.ts) is
  //   open, the layout throws and EVERY route 500s, `/health` included.
  //   Likeliest mistake: destructuring without `await`.
  const { id: rawId } = await props.params;

  // (Ari) — Gap E. Lesson: the RSC idea. `await getVenue(id)` sits
  //   directly in the component and runs on the server before any HTML is
  //   sent. A miss is signalled with `notFound()`, which THROWS, producing
  //   a real HTTP 404; returning "not found" markup instead gives a 200
  //   (a soft 404, which search engines index).
  // Code (add `import { notFound } from "next/navigation"`, and
  //   `getVenue` from "@/lib/api", `parseIdParam` from "@/lib/params";
  //   then delete the `todo` line below):
  //   const id = parseIdParam(rawId);
  //   if (id === null) notFound();
  //   const venue = await getVenue(id);
  //   if (venue === null) notFound();
  // Check (fill Gap C in lib/metro.ts first, or every URL 500s):
  //   `curl -s -o /dev/null -w "%{http_code}" localhost:3000/venue/1`
  //   → 200, `/venue/9999` → 404, `/venue/abc` → 404. Likeliest
  //   mistakes: `return <p>Not found</p>` (a 200), or calling `notFound()`
  //   inside a try/catch that swallows it.
  const id = parseIdParam(rawId);
  if (id === null) notFound();
  const venue = await getVenue(id);
  if (venue === null) notFound();

  // Optional fields from the generated types are `T | null | undefined`
  // (api-contract.md §7): FastAPI always sends them, as null when unknown,
  // but the schema marks them optional because they have defaults. A
  // truthiness check handles both, and a field the contract doesn't have
  // (socials, map_url) isn't rendered at all — not a labelled blank
  // (api-contract.md §6). `serves_alcohol` is a boolean where `false` is
  // an answer, so it's compared with `!= null`, not tested for truthiness.
  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">{venue.name}</h1>
      <dl className="mt-4 grid max-w-xl grid-cols-[auto_1fr] gap-x-6 gap-y-2">
        {venue.address && (
          <>
            <dt className="text-muted-foreground">Address</dt>
            <dd>{venue.address}</dd>
          </>
        )}
        {venue.venue_type && (
          <>
            <dt className="text-muted-foreground">Type</dt>
            <dd>{venue.venue_type}</dd>
          </>
        )}
        {venue.age_restriction && (
          <>
            <dt className="text-muted-foreground">Ages</dt>
            <dd>{venue.age_restriction}</dd>
          </>
        )}
        {venue.serves_alcohol != null && (
          <>
            <dt className="text-muted-foreground">Alcohol</dt>
            <dd>{venue.serves_alcohol ? "served" : "not served"}</dd>
          </>
        )}
        {venue.setting && (
          <>
            <dt className="text-muted-foreground">Setting</dt>
            <dd>{venue.setting}</dd>
          </>
        )}
        {venue.seating && (
          <>
            <dt className="text-muted-foreground">Seating</dt>
            <dd>{venue.seating}</dd>
          </>
        )}
        {venue.phone_numbers && venue.phone_numbers.length > 0 && (
          <>
            <dt className="text-muted-foreground">Phone</dt>
            <dd>{venue.phone_numbers.join(", ")}</dd>
          </>
        )}
        {venue.emails && venue.emails.length > 0 && (
          <>
            <dt className="text-muted-foreground">Email</dt>
            <dd>{venue.emails.join(", ")}</dd>
          </>
        )}
        {venue.website && (
          <>
            <dt className="text-muted-foreground">Website</dt>
            <dd>
              <a className="underline" href={venue.website}>
                {venue.website}
              </a>
            </dd>
          </>
        )}
        <dt className="text-muted-foreground">Calendar</dt>
        <dd>
          <a className="underline" href={venue.calendar_url}>
            {venue.calendar_url}
          </a>
        </dd>
      </dl>
    </section>
  );
}