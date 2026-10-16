import { jsonLdScriptContent } from "@/lib/json-ld";

/**
 * Renders structured data for search engines and AI as a
 * `<script type="application/ld+json">` (arch-initial.md §4: detail pages
 * "carry `schema.org` Event JSON-LD").
 *
 * A native `<script>`, not `next/script`: Next's JSON-LD guide says so —
 * `next/script` is for loading and running JavaScript, and this is data.
 * `data` is a ready-made object or array from lib/json-ld.ts.
 *
 * THE ONLY `dangerouslySetInnerHTML` IN THE APP, and it is safe because of
 * the one thing `jsonLdScriptContent` does: it escapes `<`, so text scraped
 * from a venue's website (a show name containing `</script>`) can't close
 * the tag. That property is pinned by lib/json-ld.test.ts ("never emits a
 * '<'"). Don't build this string any other way.
 */
export function JsonLd({ data }: { data: unknown }) {
  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: jsonLdScriptContent(data) }}
    />
  );
}
