/**
 * How the detail pages turn the API's raw values into display text and
 * safe links. Pure and Temporal-free.
 *
 * Three jobs, all about not trusting or exposing raw data:
 *
 *  1. `httpUrlOrNull` — the ONE rule for every URL the pages render from
 *     scraped data (website, calendar URL, "Source", images, the JSON-LD
 *     `image`). These strings are extracted by a model from arbitrary web
 *     pages, so they're untrusted text. React 19 already refuses a
 *     `javascript:` href, but nothing stops `data:` or `file:` URLs, and
 *     nothing guards a URL a search engine will fetch from JSON-LD. One
 *     rule applied everywhere is simpler than reasoning per sink.
 *  2. `mapsUrl` — the Google Maps link (arch-initial.md §4: a constructed
 *     search URL, no geocoding API, no embed, no billing).
 *  3. Label maps — enum values (`twenty_one_plus`) never reach a page raw.
 *     Each map is a `Record<Enum, string>`, so a new enum value arriving
 *     from `make types` is a COMPILE error here rather than a blank label
 *     in production.
 */

import type {
  AgeRestriction,
  ArtistFormat,
  ArtistRepertoire,
  Seating,
  Setting,
  VenueType,
} from "./types";

/**
 * The URL itself if it is an absolute http(s) URL, otherwise `null`
 * (render no link / no image). Never rewrites: `https://x/a` comes back
 * as written, so tests and markup stay predictable.
 */
export function httpUrlOrNull(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const { protocol } = new URL(url);
    return protocol === "http:" || protocol === "https:" ? url : null;
  } catch {
    // Not absolute ("garbage", "//host/x"): `new URL` needs a scheme.
    return null;
  }
}

/**
 * A Google Maps search link for an address (arch-initial.md §4).
 * `encodeURIComponent` is what keeps an `&` or `#` in a scraped address
 * from ending the query parameter or starting a fragment.
 */
export function mapsUrl(address: string): string {
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(address)}`;
}

// --- labels ---------------------------------------------------------------------
// Wording follows requirements-initial.md's field lists; keys are the
// enum values in apps/api/app/enums.py (via the generated types).

export const AGE_LABELS: Record<AgeRestriction, string> = {
  all_ages: "All ages",
  twenty_one_plus: "21+",
};

export const SETTING_LABELS: Record<Setting, string> = {
  indoor: "Indoor",
  outdoor: "Outdoor",
  both: "Indoor and outdoor",
};

export const SEATING_LABELS: Record<Seating, string> = {
  standing: "Standing",
  seated: "Seated",
  both: "Standing or seated",
};

export const VENUE_TYPE_LABELS: Record<VenueType, string> = {
  bar: "Bar",
  club: "Club",
  theater: "Theater",
  coffeehouse: "Coffeehouse",
  arena: "Arena",
  park: "Park",
  other: "Other",
};

export const ARTIST_FORMAT_LABELS: Record<ArtistFormat, string> = {
  solo: "Solo",
  duo: "Duo",
  trio: "Trio",
  band: "Band",
};

export const REPERTOIRE_LABELS: Record<ArtistRepertoire, string> = {
  original: "Original",
  cover: "Covers",
  both_other: "Original and covers",
};

/** `serves_alcohol` is a boolean where `false` is an ANSWER, not an absence. */
export function alcoholLabel(served: boolean): string {
  return served ? "Served" : "Not served";
}
