/**
 * schema.org Event JSON-LD for show and venue pages (B4 plan, "JSON-LD
 * dates carry the metro's offset" and arch-initial.md §4: detail pages
 * "carry `schema.org` Event JSON-LD").
 *
 * WHAT THIS IS FOR. Search engines and AI read this block to understand a
 * page beyond its visible text: who is playing, where, when, and what it
 * costs. It is the reason every show gets a server-rendered page of its
 * own. It must say only what the data says.
 *
 * THE TWO PLACES THIS FILE IS CAREFUL.
 *  1. Dates. A show's date and time are wall-clock values with NO zone
 *     (right for display), but JSON-LD `startDate` names a real instant,
 *     so it needs the venue's UTC offset, which depends on the date
 *     (-05:00 in October, -06:00 in December) and so can only come from
 *     the metro's IANA zone. It is the second and last place that zone
 *     matters (the first is "today", lib/dates.ts). Ari's after-midnight
 *     rule moves the calendar date first: a 1:00 AM show listed under
 *     Wednesday happens on Thursday.
 *  2. "Not stated" stays not stated. All-null admission (api-contract.md
 *     §4) produces NO `offers` key, never a price of 0; no start time
 *     produces a bare date, never an invented midnight.
 *
 * Plus one safety rule: names are model-extracted from arbitrary web
 * pages and printed inside a <script> tag, so `jsonLdScriptContent`
 * escapes `<` (Next's JSON-LD guide: JSON.stringify does not sanitise).
 *
 * `url` is omitted on purpose: there is no site URL until the hosted
 * phase. Server-side in practice (Temporal polyfill, like lib/dates.ts).
 */

import { Temporal } from "@js-temporal/polyfill";
import { isAfterMidnight, nightSortKey } from "./dates";
import { httpUrlOrNull } from "./detail-format";
import { orderedLineup } from "./show-format";
import type { ShowSummary, VenueDetail } from "./types";

type JsonLdOffer = {
  "@type": "Offer";
  name?: string;
  price: string;
  priceCurrency: "USD";
};

/** The slice of schema.org MusicEvent this app emits. */
export type JsonLdEvent = {
  "@context": "https://schema.org";
  "@type": "MusicEvent";
  name: string;
  startDate: string;
  endDate?: string;
  eventStatus: string;
  eventAttendanceMode: string;
  location: { "@type": "MusicVenue"; name: string; address?: string };
  performer?: { "@type": "MusicGroup"; name: string }[];
  image?: string;
  offers?: JsonLdOffer[];
};

// --- dates -----------------------------------------------------------------------

/**
 * The calendar day a listed time actually happens on: the listed date, or
 * the NEXT day for a time before 5:00 AM (requirements-initial.md, "Times
 * after midnight"). The rule's one home is `isAfterMidnight`; this is its
 * use on a date, and both the zoned path and the no-offset fallback need it.
 */
function instantDay(date: string, t: Temporal.PlainTime): Temporal.PlainDate {
  return Temporal.PlainDate.from(date).add({ days: isAfterMidnight(t) ? 1 : 0 });
}

/**
 * A wall-clock day and time, in the metro's zone, as an ISO string WITH
 * its UTC offset ("2026-10-07T20:00:00-05:00").
 *
 * A wall-clock time becomes an INSTANT only when a zone is attached, and the
 * offset depends on the date (CDT -05:00 until the first Sunday of November,
 * then CST -06:00), so it can't be a constant and has to come from the
 * metro's IANA zone. This is the second and last place that zone matters (the
 * first is "today", lib/dates.ts `metroToday`). `toString({ timeZoneName:
 * "never" })` prints the offset WITHOUT the "[America/Chicago]" suffix that
 * schema.org doesn't expect. A wall time that doesn't exist (the spring-forward
 * gap) or exists twice (fall back) is resolved by Temporal's default rather
 * than thrown on. `day` is already shifted past midnight by `instantDay`; an
 * unknown zone id throws RangeError, which the caller (`eventDateTime`)
 * handles, not this function.
 */
function withOffset(day: Temporal.PlainDate, t: Temporal.PlainTime, timeZone: string): string {
  return day.toZonedDateTime({ timeZone, plainTime: t }).toString({ timeZoneName: "never" });
}

/**
 * `startDate` for a show: date + time + offset, a bare date when the
 * listing gave no time, or local time without an offset when the metro's
 * zone is missing or unusable (a typo in the metro row must cost the
 * offset, not the page — better than guessing a zone).
 */
export function eventDateTime(
  date: string,
  time: string | null | undefined,
  timeZone: string | null,
): string {
  // "Not stated" stays not stated: a bare date is valid schema.org, and an
  // invented midnight would be a wrong answer someone acts on.
  if (!time) return date;
  const t = Temporal.PlainTime.from(time);
  const day = instantDay(date, t);
  if (timeZone !== null) {
    try {
      return withOffset(day, t, timeZone);
    } catch (err) {
      // Only an unknown zone is ours to absorb; anything else is a real bug
      // and passes through.
      if (!(err instanceof RangeError)) throw err;
      console.error(`[json-ld] unusable metro timezone ${JSON.stringify(timeZone)}:`, err);
    }
  }
  return day.toPlainDateTime(t).toString();
}

/**
 * `endDate`, or `null` when the listing has no end time. An end earlier
 * than its start is the next morning (requirements-initial.md, "Show");
 * that comparison is in NIGHT order (`nightSortKey`), so a 22:00 start
 * with a 00:30 end is the same night's tail, not a day-long show. With no
 * start there is nothing to compare, so only the after-midnight rule applies.
 */
export function eventEndDateTime(
  date: string,
  start: string | null | undefined,
  end: string | null | undefined,
  timeZone: string | null,
): string | null {
  if (!end) return null;
  // A start AND an end both before 5:00 AM, the end earlier than the start
  // (01:00 to 00:30): the listing contradicts itself. Obeying "an earlier end
  // is the next morning" would publish a ~23-hour show, so publish no end
  // (B4 code review #3; pinned in json-ld.test.ts).
  if (
    start &&
    isAfterMidnight(Temporal.PlainTime.from(start)) &&
    isAfterMidnight(Temporal.PlainTime.from(end)) &&
    nightSortKey(end) < nightSortKey(start)
  ) {
    return null;
  }
  const endsNextMorning = !!start && nightSortKey(end) < nightSortKey(start);
  const anchor = endsNextMorning ? Temporal.PlainDate.from(date).add({ days: 1 }).toString() : date;
  return eventDateTime(anchor, end, timeZone);
}

// --- the event ------------------------------------------------------------------------

/**
 * What the show costs, as schema.org offers; an empty list when the listing
 * didn't say. Mirrors `formatAdmission` (lib/show-format.ts) so the page and
 * the JSON-LD never disagree: `free_admission` true -> free; an advance and
 * a day price -> two labelled offers; a lone advance price is labelled
 * "Advance"; a lone price is the unlabelled day price. The prices are the
 * API's STRINGS ("18.00"), passed through — never `parseFloat`.
 */
function offersFor(show: ShowSummary): JsonLdOffer[] {
  if (show.free_admission) {
    return [{ "@type": "Offer", price: "0", priceCurrency: "USD" }];
  }
  const advance = show.admission_advance;
  const day = show.admission_day;
  const offers: JsonLdOffer[] = [];
  if (advance) {
    offers.push({ "@type": "Offer", name: "Advance", price: advance, priceCurrency: "USD" });
  }
  if (day) {
    offers.push({
      "@type": "Offer",
      ...(advance ? { name: "Door" } : {}),
      price: day,
      priceCurrency: "USD",
    });
  }
  return offers;
}

/**
 * One show as a schema.org MusicEvent. `venue` is the venue's detail
 * record when the page has it (for the address), `null` when it doesn't —
 * the location then falls back to the show's own venue name with no
 * address. `timeZone` is the metro's IANA zone, or `null`.
 */
export function showJsonLd(
  show: ShowSummary,
  ctx: { venue: VenueDetail | null; timeZone: string | null },
): JsonLdEvent {
  const lineup = orderedLineup(show.lineup);
  const event: JsonLdEvent = {
    "@context": "https://schema.org",
    "@type": "MusicEvent",
    // The bill, in performance order; a show with no lineup is named after
    // its venue rather than left blank.
    name:
      lineup.length > 0
        ? lineup.map((entry) => entry.artist.name).join(", ")
        : `Live music at ${show.venue.name}`,
    startDate: eventDateTime(show.date, show.start_time, ctx.timeZone),
    eventStatus: "https://schema.org/EventScheduled",
    eventAttendanceMode: "https://schema.org/OfflineEventAttendanceMode",
    location: {
      "@type": "MusicVenue",
      name: show.venue.name,
      ...(ctx.venue?.address ? { address: ctx.venue.address } : {}),
    },
  };

  const endDate = eventEndDateTime(show.date, show.start_time, show.end_time, ctx.timeZone);
  if (endDate !== null) event.endDate = endDate;

  if (lineup.length > 0) {
    event.performer = lineup.map((entry) => ({
      "@type": "MusicGroup",
      name: entry.artist.name,
    }));
  }

  // A search engine will fetch this URL, so it gets the same http(s)-only
  // rule as every link and image on the pages.
  const image = httpUrlOrNull(show.image_url);
  if (image !== null) event.image = image;

  const offers = offersFor(show);
  if (offers.length > 0) event.offers = offers;

  return event;
}

/**
 * The text printed inside `<script type="application/ld+json">`.
 *
 * `JSON.stringify` does not sanitise, and a name scraped from a venue's
 * website could contain `</script>`, which would close the tag and let the
 * rest run as page markup. Replacing `<` with its JSON escape `\u003c` is
 * lossless (JSON.parse gives the original back) and removes every way to
 * write a closing tag. Next's own JSON-LD guide recommends exactly this.
 */
export function jsonLdScriptContent(data: unknown): string {
  return JSON.stringify(data).replace(/</g, "\\u003c");
}
