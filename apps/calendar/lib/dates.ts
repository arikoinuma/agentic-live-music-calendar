/**
 * Dates and times for the calendar, all through Temporal.
 *
 * WHAT NEEDS THE METRO'S TIMEZONE, AND WHAT DOESN'T. A show's date and
 * time reach us as wall-clock strings in the METRO's zone ("2026-10-12",
 * "20:00:00" — requirements-initial.md, "Metro": what a listing says is
 * stored as written). They become `Temporal.PlainDate` / `PlainTime`,
 * which have no zone at all, so formatting them cannot shift a day: the
 * same string prints the same text on a server in UTC or a laptop in
 * Honolulu. (dates.test.ts pins this by running under zones either side
 * of UTC.) The one place the metro's zone matters is "TODAY" — see
 * `metroToday`.
 *
 * The trap that remains is `new Date("2026-10-12")`: UTC midnight, which
 * is the 11th west of Greenwich. There is no `Date` in this file, and
 * there should be none in anything that renders a show.
 *
 * Server-side in practice: this module pulls in the Temporal polyfill
 * (~129 KB, 36 KB gzipped). Client Components must not import it — the
 * filter header gets its labels pre-formatted as props and its hrefs from
 * lib/calendar-href.ts, which is Temporal-free. (It isn't marked
 * `server-only`, because nothing secret is in it and the tests import it;
 * the bundle grep in the B3 plan's Verification 3 is the guard.)
 */

// Explicit import: Node 24 has no global Temporal, so the polyfill is the
// implementation.
import { Temporal } from "@js-temporal/polyfill";

// Ari, October 11, 2026 (requirements-initial.md, "Show"): a time before
// 5:00 AM is after midnight of the night the venue lists the show under.
const NIGHT_CUTOFF = Temporal.PlainTime.from("05:00");

// Sort keys are minutes into the night: the evening is 0..1439, a time
// after midnight is pushed a day later (1440..), untimed goes last. A
// finite number, not Infinity — `Infinity - Infinity` is NaN, which
// would make a comparator return garbage for two untimed shows.
const MINUTES_PER_DAY = 24 * 60;
const UNTIMED_KEY = 2 * MINUTES_PER_DAY;

// --- today -------------------------------------------------------------------

/**
 * The date it is RIGHT NOW in the metro's timezone.
 *
 * (Ari) — Gap A. Lesson: "today" is a question about a place. This code
 *   runs on the Next server, whose zone is UTC on Vercel, so any
 *   zone-less "now" is TOMORROW from early evening Central time on (7 PM
 *   in summer, 6 PM in winter). Ask for the date in the metro's IANA zone
 *   (`MetroSummary.timezone`, requirements-initial.md "Metro"). A show's
 *   own date needs no zone (it is a wall-clock PlainDate); this is the one
 *   place the metro's zone is needed. `now` is a parameter so tests can
 *   fix the clock.
 * Code:
 *   return now.toZonedDateTimeISO(timeZone).toPlainDate();
 *   (and delete `import { todo } from "./todo"` once no gap in this file still
 *   calls it — Gap B does too, so the second one filled removes it)
 * Check: `pnpm --filter calendar test dates` — "is the metro's date when
 *   UTC has already rolled to the next day" and its three siblings (the
 *   DST and east-of-UTC cases). Likeliest mistakes:
 *   `Temporal.Now.plainDateISO()` with no zone argument (the SERVER's
 *   zone — and it ignores `now`, so every case fails), or
 *   `new Date().toISOString().slice(0, 10)` (UTC).
 */
export function metroToday(
  timeZone: string,
  now: Temporal.Instant = Temporal.Now.instant(),
): Temporal.PlainDate {
  return now.toZonedDateTimeISO(timeZone).toPlainDate();
}

/**
 * `metroToday`, but an invalid zone costs the "Today" label instead of
 * the page. The metro's timezone is free text in the database, and
 * `toZonedDateTimeISO` throws a RangeError for an id it doesn't know;
 * "Today" is cosmetic, so a typo in a metro row shouldn't be a 500
 * (B3 plan review #9). Only RangeError is caught — anything else
 * (including an open gap's TODO error) is a real bug and passes through.
 */
export function metroTodayOrNull(
  timeZone: string,
  now?: Temporal.Instant,
): Temporal.PlainDate | null {
  try {
    return metroToday(timeZone, now);
  } catch (err) {
    if (!(err instanceof RangeError)) throw err;
    console.error(`[calendar] unusable metro timezone ${JSON.stringify(timeZone)}:`, err);
    return null;
  }
}

// --- the night ----------------------------------------------------------------

/**
 * True for a clock time that belongs to the early hours AFTER the night
 * it is listed under: 00:00 up to, not including, 05:00.
 *
 * (Ari) — Gap B. Lesson: Ari's after-midnight rule as ONE comparison — and
 *   Temporal refuses `<`: its objects throw on `valueOf()` precisely so
 *   `a < b` can't silently compare strings or NaN. Ordering goes through
 *   `compare`. Both `formatShowTime` (the "Sat" suffix) and `nightSortKey`
 *   (sorts after the evening's shows) call this, so the rule lives in
 *   exactly one line.
 * Code:
 *   return Temporal.PlainTime.compare(time, NIGHT_CUTOFF) < 0;
 *   (and delete the `todo` import if Gap A is already filled)
 * Check: `pnpm --filter calendar test dates` — `isAfterMidnight`'s
 *   04:59 (true) and 05:00 (false); the `formatShowTime` and
 *   `nightSortKey` cases go green with it. Likeliest mistakes:
 *   `time < NIGHT_CUTOFF` (throws a TypeError that tells you to use
 *   `compare`), or `<= 0` (makes 5:00 AM "after midnight").
 */
export function isAfterMidnight(time: Temporal.PlainTime): boolean {
  return Temporal.PlainTime.compare(time, NIGHT_CUTOFF) < 0;
}

/**
 * A number to sort a day's shows by, so a 1:00 AM show comes after the
 * evening's 8:00 PM show on the same night, and an untimed one comes last
 * ("not stated" isn't "first thing in the morning" — the API's own
 * ordering puts untimed last for the same reason, routers/shows.py).
 */
export function nightSortKey(time: string | null | undefined): number {
  if (!time) return UNTIMED_KEY;
  const t = Temporal.PlainTime.from(time);
  const minutes = t.hour * 60 + t.minute;
  return isAfterMidnight(t) ? minutes + MINUTES_PER_DAY : minutes;
}

// --- formatting ---------------------------------------------------------------

// Locale is fixed to en-US: the app has one locale and the output must not
// vary with whatever the server's environment says.
const LOCALE = "en-US";

/** "2026-10-12" -> "Mon, Oct 12". */
export function formatDayHeading(date: string): string {
  return Temporal.PlainDate.from(date).toLocaleString(LOCALE, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

/** "2026-10-12" -> "Mon, Oct 12, 2026": the heading plus its year, for lists that can cross a year. */
export function formatDayHeadingWithYear(date: string): string {
  return `${formatDayHeading(date)}, ${Temporal.PlainDate.from(date).year}`;
}

/**
 * "20:00:00" -> "8:00 PM".
 *
 * Built by hand rather than with `Intl`, as a guard rather than a fix for
 * something measured: on this repo's runtime (Node 24, ICU 78) `Intl`
 * prints a plain space before "PM", but some ICU versions (CLDR 42-era)
 * printed U+202F, a narrow no-break space, and the server's ICU is not
 * ours to pin. Hand-built, the text is the same everywhere and the tests
 * compare plain strings.
 */
export function formatClockTime(time: string): string {
  const t = Temporal.PlainTime.from(time);
  const hour12 = t.hour % 12 === 0 ? 12 : t.hour % 12;
  const minutes = String(t.minute).padStart(2, "0");
  return `${hour12}:${minutes} ${t.hour < 12 ? "AM" : "PM"}`;
}

/**
 * A show's start time as the block displays it: "8:00 PM", or — for a
 * time after midnight — "1:00 AM Sat", naming the NEXT day, because the
 * show belongs to Friday night but happens on Saturday morning
 * (requirements-initial.md, "Times after midnight"). `null` when the
 * listing gave no time: "not stated" is shown as such by the caller, never
 * as a made-up midnight (api-contract.md §4).
 */
export function formatShowTime(
  date: string,
  time: string | null | undefined,
): string | null {
  if (!time) return null;
  const clock = formatClockTime(time);
  if (!isAfterMidnight(Temporal.PlainTime.from(time))) return clock;
  const nextDay = Temporal.PlainDate.from(date)
    .add({ days: 1 })
    .toLocaleString(LOCALE, { weekday: "short" });
  return `${clock} ${nextDay}`;
}

/**
 * (2026, 10) -> "October 2026".
 *
 * Goes through a PlainDate on purpose: `PlainYearMonth.toLocaleString`
 * THROWS for en-US ("cannot format PlainYearMonth with calendar iso8601
 * in locale with calendar gregory" — docs/dev/notes.md).
 */
export function formatMonthLabel(year: number, month: number): string {
  return Temporal.PlainDate.from({ year, month, day: 1 }).toLocaleString(LOCALE, {
    month: "long",
    year: "numeric",
  });
}
