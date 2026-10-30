/**
 * Host to metro: which metro, if any, a request's `Host` names.
 *
 * Each metro is its own subdomain of an environment's *zone* (Dep-D2, alpha-deployment-plan.md §4.2): production
 * `msp.<domain>`, staging `msp.staging.<domain>`. The zone is the part of the domain the environment owns
 * (`staging.<domain>`); its *apex* is the bare zone name; the one label in front of it is the metro's *slug*.
 * `parseHost` classifies a host as exactly one of four things, and everything above it (the proxy's decision
 * order, `request-plan.ts`) is written in terms of that answer:
 *
 *   outside   not in the zone, or no zone is configured: `*.vercel.app` previews, `localhost:3000`, the e2e
 *             stack's `localhost:3100`. These keep working and use the default metro (C4-D2).
 *   apex      equals the zone (`staging.<domain>`): redirected to the default metro's host (C4-D5).
 *   metro     exactly one valid, non-reserved label before the zone: that label is the slug.
 *   bad       anything else inside the zone: several labels, an invalid shape, a reserved word. Redirected to the
 *             default metro's host.
 *
 * Reading order: the shape rule and the reserved list; the two normalisers (`normalizeHost`, `normalizeZone`);
 * then `parseHost`, whose zone-stripping is the `C4-K1` fill-in gap.
 *
 * The reserved words are one JSON file shared with the API's tests (`reserved-slugs.json`, C4-D2), because the API's
 * deploy root cannot read a file outside `apps/api`; app/tests/test_metro_slug.py checks the seed against it.
 *
 * docs/dev/implementations/c4-metro-hosts.md: C4-D2, C4-D5, C4-K1.
 */

import reserved from "./reserved-slugs.json";

/**
 * The request header the proxy sets to the metro slug it resolved for this request. The proxy ALWAYS overwrites it
 * (a client-sent value is dropped), and readers validate it again (`lib/site-context.ts`), so it is only ever the
 * default metro or a slug the proxy accepted (C4-D8).
 */
export const METRO_SLUG_HEADER = "x-metro-slug";

/** Words that can never be a metro's slug: they are already something else in the addressing (Dep-D3). */
export const RESERVED_SLUGS: ReadonlySet<string> = new Set(reserved);

// 3 to 32 characters, a letter first, lowercase letters, digits and hyphens, not ending in a hyphen (C4-D2).
// The same rule as the database's CHECK on `metro.slug`; a label with a dot in it fails here, which is what makes
// `a.b.<zone>` "bad" rather than a metro.
const SLUG_SHAPE = /^[a-z][a-z0-9-]{1,30}[a-z0-9]$/;

export function isValidSlug(label: string): boolean {
  return SLUG_SHAPE.test(label);
}

export function isReservedSlug(label: string): boolean {
  return RESERVED_SLUGS.has(label);
}

/** What `parseHost` concludes about a host (see the file header). */
export type HostClass =
  | { kind: "outside" }
  | { kind: "apex" }
  | { kind: "bad" }
  | { kind: "metro"; slug: string };

/**
 * A host as comparable text: lowercased, without a port, without a trailing dot.
 *
 * The port comes off with a pattern, not a split on `:`, because an IPv6 literal (`[::1]:3000`) is full of colons;
 * the bracketed form is kept whole and never matches a zone. Browsers send the `Host` header in whatever case the
 * address was typed, and DNS names are case-insensitive, so lowercasing is not optional.
 */
export function normalizeHost(host: string): string {
  const h = host.trim().toLowerCase();
  if (h.startsWith("[")) return h.slice(0, h.indexOf("]") + 1 || undefined);
  return h.replace(/:\d+$/, "").replace(/\.$/, "");
}

/**
 * The configured zone as comparable text, or `null` when there is none. Normalised once where the configuration is
 * read (C4-PR1-14): a zone typed as `Staging.Example.com.` in a dashboard must behave as `staging.example.com`, or
 * every host would silently become "outside" and the apex and bad-host handling would switch itself off.
 */
export function normalizeZone(zone: string | null | undefined): string | null {
  const z = (zone ?? "").trim().toLowerCase().replace(/^\./, "").replace(/\.$/, "");
  return z === "" ? null : z;
}

/**
 * Classify `host` against the environment's `zone` (see the file header). `zone` is a parameter, not read from the
 * environment here, so tests run the same table for `example.com` and `staging.example.com`.
 */
export function parseHost(host: string, zone: string | null | undefined): HostClass {
  const h = normalizeHost(host);
  const z = normalizeZone(zone);
  // No zone configured (the pre-domain state): nothing to strip, every host is left alone.
  if (z === null) return { kind: "outside" };

  //  Key point of interest (C4-K1): the environment is the *parent zone*, and what is left after
  //   removing it is the slug (Dep-D2, alpha-deployment-plan.md §4.2). The match must be on a LABEL BOUNDARY:
  //   `h.endsWith("." + z)` or equal to the zone, never a bare `endsWith(z)`, or `xdev.example.com` parses as the
  //   dev zone. What is left must be exactly one valid, non-reserved label; anything else inside the zone is
  //   "bad", and anything outside the zone is "outside", left alone. (`h` and `z` are already normalised above.)
  if (h === z) return { kind: "apex" }; // give an example: what scenario does this catch?
  if (!h.endsWith("." + z)) return { kind: "outside" }; // show me an example of which scenario this catches
  const label = h.slice(0, -(z.length + 1));
  if (!isValidSlug(label) || isReservedSlug(label)) return { kind: "bad" };
  return { kind: "metro", slug: label };
}
