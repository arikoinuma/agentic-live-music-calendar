import Link from "next/link";
import { windowHref, windowNavLinks } from "@/lib/calendar-window";
import { formatDayHeadingWithYear } from "@/lib/dates";

/**
 * Earlier / Later links around a window of dates, for the venue page's
 * embedded calendar ("go back and forth to past or future with that exact
 * calendar", requirements-initial.md, "Venue"; B4-D1).
 *
 * A Server Component of plain links: paging is a navigation, and the server
 * renders the new window from `?from=`. Every link is computed from the
 * range the SERVER served (`start`/`end`) by lib/calendar-window.ts, so
 * nothing here knows how long a window is or what today is
 * (api-contract.md §3, "the server owns now").
 *
 * The range is printed WITH its years: a window that crosses New Year must
 * not be ambiguous (plan review #4). `rel="nofollow"` on Earlier/Later
 * keeps crawlers from walking an unbounded chain of ever-emptier windows.
 * "Back to upcoming dates" names no length, since the length is the
 * server's to decide.
 */
export function WindowNav({
  path,
  start,
  end,
  isDefault,
}: {
  path: string;
  start: string;
  end: string;
  isDefault: boolean;
}) {
  const { earlier, later } = windowNavLinks(path, start, end);
  return (
    <nav
      aria-label="Shows by date range"
      className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm"
    >
      {earlier && (
        <Link className="underline" href={earlier} rel="nofollow">
          ← Earlier
        </Link>
      )}
      <span className="text-muted-foreground">
        {formatDayHeadingWithYear(start)} – {formatDayHeadingWithYear(end)}
      </span>
      {later && (
        <Link className="underline" href={later} rel="nofollow">
          Later →
        </Link>
      )}
      {!isDefault && (
        <Link className="underline" href={windowHref(path, null)}>
          Back to upcoming dates
        </Link>
      )}
    </nav>
  );
}
