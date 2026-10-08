import Link from "next/link";

// Placeholder home page. B2 turns this into the four-week calendar
// (requirements-initial.md "Calendar (Including Home Page)").
//
// Note what's NOT here compared with the old page: no `force-dynamic`.
// That export existed because the page called FastAPI at render time and
// couldn't be prerendered. This page does no I/O, so Next.js prerenders it
// to static HTML at build — the default, and the cheapest.
export default function Home() {
  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">
        Live music, next four weeks
      </h1>
      <p className="mt-2 text-muted-foreground">
        The calendar is coming. See the{" "}
        <Link className="underline" href="/health">
          status page
        </Link>{" "}
        for whether the API is reachable.
      </p>
    </section>
  );
}
