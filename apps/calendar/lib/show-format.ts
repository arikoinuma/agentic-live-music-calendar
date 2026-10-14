/**
 * How a show's data becomes display text. Pure string functions: money is
 * a string end to end (api-contract.md §4 — "15.00", never parseFloat),
 * and "not stated" stays distinguishable from "free".
 */

import type { LineupEntry, ShowSummary } from "./types";

/**
 * "18.00" -> "$18"; "8.50" -> "$8.50". String handling only — `parseFloat`
 * on money is the mistake the contract warns about, and the API always
 * sends two decimal places.
 */
export function formatPrice(price: string): string {
  const [whole, cents = ""] = price.split(".");
  return /^0*$/.test(cents) ? `$${whole}` : `$${whole}.${cents}`;
}

/**
 * The admission line for a show block, or `null` when there is nothing to
 * say.
 *
 * All three fields null means the listing didn't say what it costs — NOT
 * free (api-contract.md §4; requirements-initial.md "Show": Free
 * Admission is true only when the listing says so). So that case returns
 * `null` and the block prints nothing, rather than "Free".
 *
 * A lone price is the day-of-show price when unlabelled (requirements,
 * "Agent Extraction: Fields"), so it is shown plain; only a price that is
 * known to be the advance/online one is labelled "adv".
 */
export function formatAdmission(
  show: Pick<ShowSummary, "admission_advance" | "admission_day" | "free_admission">,
): string | null {
  if (show.free_admission) return "Free";
  const { admission_advance: advance, admission_day: day } = show;
  if (advance && day) return `${formatPrice(advance)} adv / ${formatPrice(day)} door`;
  if (advance) return `${formatPrice(advance)} adv`;
  if (day) return formatPrice(day);
  return null;
}

/**
 * A lineup in performance order. Acts with a sequence number come first,
 * by number; acts without one keep the order the API gave, after them
 * (`sort` is stable). Returns a new array — props must not be mutated.
 */
export function orderedLineup(lineup: LineupEntry[]): LineupEntry[] {
  const key = (e: LineupEntry) => e.sequence_number ?? Number.POSITIVE_INFINITY;
  // Compare rather than subtract: Infinity - Infinity is NaN.
  return [...lineup].sort((a, b) => (key(a) === key(b) ? 0 : key(a) < key(b) ? -1 : 1));
}
