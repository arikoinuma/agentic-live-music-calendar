import type { ReactNode } from "react";

/**
 * One label/value pair inside a `<dl className="grid grid-cols-[auto_1fr] …">`
 * (the venue, artist and show pages). A fragment, so the <dt>/<dd> pair
 * sits directly in the grid. Callers decide WHETHER to render a row —
 * `{venue.address && <DetailRow …/>}` — because a field the API doesn't
 * have renders nothing at all, not a labelled blank (api-contract.md §6).
 */
export function DetailRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      {/* `min-w-0` + `overflow-wrap:anywhere`: a grid item's automatic
          minimum width is its longest unbreakable word, and these values
          are URLs and email addresses scraped from the web. Without this a
          calendar URL on a 375px phone widens the whole grid past the
          screen (measured: the page scrolled sideways by 9px). Same family
          of bug as B3's Gap E. */}
      <dd className="min-w-0 [overflow-wrap:anywhere]">{children}</dd>
    </>
  );
}
