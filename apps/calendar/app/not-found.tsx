import Link from "next/link";

// Rendered when a page calls `notFound()` (a bad id or date, or an id the
// API says doesn't exist) and for URLs that match no route at all. Next
// sends the HTTP status 404 with it — which is why pages call
// `notFound()` rather than returning "not found" markup, which would be a
// 200 that search engines index (a "soft 404").
export default function NotFound() {
  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">Not found</h1>
      <p className="mt-2 text-muted-foreground">
        We couldn&apos;t find that page.{" "}
        <Link className="underline" href="/">
          Back to the calendar
        </Link>
        .
      </p>
    </section>
  );
}
