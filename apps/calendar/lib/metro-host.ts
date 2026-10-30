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
 * then `parseHost`, whose zone-stripping is the `C4-K1` key point (filled by Ari).
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
 * `host` is whatever the browser put in the `Host` header: the address you typed, in the case you typed it, with a
 * `:port` when the port is not the default. What comes back is the form `parseHost` can compare with a zone.
 *
 *   "localhost:3000"                   -> "localhost"                     (a laptop: port removed)
 *   "foo-abc.vercel.app"               -> "foo-abc.vercel.app"            (a Vercel preview: already plain)
 *   "MSP.Staging.PebbleBeats.com:443"  -> "msp.staging.pebblebeats.com"   (a real host: lowercased, port removed)
 *   "msp.staging.pebblebeats.com."     -> "msp.staging.pebblebeats.com"   (a fully-qualified name's trailing dot)
 *   "[::1]:3000"                       -> "[::1]"                         (an IPv6 literal: kept whole, see below)
 *
 * The port comes off with a pattern, not a split on `:`, because an IPv6 literal (`[::1]:3000`) is full of colons;
 * the bracketed form is kept whole and never matches a zone. Browsers send the `Host` header in whatever case the
 * address was typed, and DNS names are case-insensitive, so lowercasing is not optional.
 */
export function normalizeHost(host: string): string {
  // "  MSP.Staging.PebbleBeats.com:443 " -> "msp.staging.pebblebeats.com:443"
  const h = host.trim().toLowerCase();
  // "[::1]:3000" -> "[::1]": keep everything up to the closing bracket (indexOf is -1 if it is missing, so the
  // `|| undefined` makes slice take the whole string rather than cut off its last character).
  if (h.startsWith("[")) return h.slice(0, h.indexOf("]") + 1 || undefined);
  // "localhost:3000" -> "localhost";  "msp.staging.pebblebeats.com." -> "msp.staging.pebblebeats.com"
  return h.replace(/:\d+$/, "").replace(/\.$/, "");
}

/**
 * The configured zone as comparable text, or `null` when there is none. The zone is the part of the domain an
 * environment owns, and it comes from the `SITE_ZONE` variable (lib/site-config.ts). Normalised once where the
 * configuration is read (C4-PR1-14), so a zone typed with capitals or a stray dot in a dashboard still behaves:
 * otherwise every host would silently become "outside" and the apex and bad-host handling would switch itself off.
 *
 *   undefined / null / "" / "  "          -> null                        (no domain yet: a laptop, or a preview
 *                                                                         before any domain is attached)
 *   "staging.pebblebeats.com"             -> "staging.pebblebeats.com"   (staging, as it should be typed)
 *   "Staging.PebbleBeats.com."            -> "staging.pebblebeats.com"   (capitals and a trailing dot removed)
 *   ".pebblebeats.com"                    -> "pebblebeats.com"           (a leading dot removed; this is production's
 *                                                                         zone, set at C11)
 */
export function normalizeZone(zone: string | null | undefined): string | null {
  // undefined / null -> "";  "  Staging.PebbleBeats.com. " -> "staging.pebblebeats.com"
  const z = (zone ?? "").trim().toLowerCase().replace(/^\./, "").replace(/\.$/, "");
  // Nothing left after trimming means no zone was configured.
  return z === "" ? null : z;
}

/**
 * Classify `host` against the environment's `zone` (see the file header). `zone` is a parameter, not read from the
 * environment here, so tests run the same table for `pebblebeats.com` and `staging.pebblebeats.com`.
 *
 * Why the zone is the parent and the slug is what is left: Dep-D2 and alpha-deployment-plan.md §4.2 give every
 * environment its own zone and every metro one label in front of it (`msp.staging.pebblebeats.com` is the metro
 * `msp` in the zone `staging.pebblebeats.com`). A wildcard certificate covers exactly one label, which is why the
 * environment is the parent and the metro is the child.
 *
 * Three situations the app really meets, followed through each line below as A, B and C:
 *
 *   A. a laptop       host "localhost:3000"                       zone null (SITE_ZONE is not set locally)
 *   B. a Vercel URL   host "foo-abc.vercel.app"                   zone "staging.pebblebeats.com" once staging has a
 *                                                                 domain (null before)
 *   C. a real host    host "MSP.Staging.PebbleBeats.com:443"      zone "Staging.PebbleBeats.com." (as typed)
 *
 * Other hosts in the same staging zone, for the lines that tell them apart:
 *   "staging.pebblebeats.com"        -> apex     (the bare zone: someone typed the zone with nothing in front)
 *   "www.staging.pebblebeats.com"    -> bad      (one label, but `www` is reserved)
 *   "a.b.staging.pebblebeats.com"    -> bad      (two labels in front; "a.b" is not a slug)
 *   "xstaging.pebblebeats.com"       -> outside  (looks like the zone, but is a different domain: see the `endsWith` line below)
 */
export function parseHost(host: string, zone: string | null | undefined): HostClass {
  // A: "localhost:3000" -> "localhost".   B: "foo-abc.vercel.app" (unchanged).   C: "msp.staging.pebblebeats.com".
  const h = normalizeHost(host);
  // A: null -> null.   B: "staging.pebblebeats.com" (or null).   C: "Staging.PebbleBeats.com." -> "staging.pebblebeats.com".
  const z = normalizeZone(zone);
  // No zone configured (the pre-domain state): nothing to strip, every host is left alone.
  // A: zone is null, so a laptop stops here -> outside (the default metro, no redirect).
  // B before a domain exists: also stops here -> outside.   C cannot happen without a zone.
  if (z === null) return { kind: "outside" };

  // From here on there IS a zone, so B and C are being compared with "staging.pebblebeats.com".
  //
  // The host IS the zone, with nothing in front: the apex. This is what someone gets by typing the bare environment
  // name. It is redirected to the default metro's host (C4-D5) because there is no slug to serve.
  //   "staging.pebblebeats.com" === "staging.pebblebeats.com" -> apex.
  //   A, B and C never match here (C has "msp." in front).
  if (h === z) return { kind: "apex" };
  // Not under the zone: leave it alone. The test is on a LABEL BOUNDARY, so it asks for ".staging.pebblebeats.com",
  // with the dot, not for a bare "staging.pebblebeats.com" at the end. Without the dot, "xstaging.pebblebeats.com"
  // (someone else's domain that merely ends with the same letters) would be taken for part of our zone.
  //   A: "localhost" does not end with ".staging.pebblebeats.com"           -> outside.
  //   B: "foo-abc.vercel.app" does not end with it either                    -> outside (a preview keeps working).
  //   "xstaging.pebblebeats.com" ends with "staging.pebblebeats.com" but not with ".staging.pebblebeats.com" -> outside.
  //   C: "msp.staging.pebblebeats.com" does end with it                       -> carry on.
  if (!h.endsWith("." + z)) return { kind: "outside" };
  // Cut the zone, and the dot in front of it, off the end. What is left is everything in front of the zone: the
  // candidate slug. (The `+ 1` is that dot.)
  //   C: "msp.staging.pebblebeats.com" is 27 characters and ".staging.pebblebeats.com" is 24, so this keeps 3: "msp".
  //   "a.b.staging.pebblebeats.com" leaves "a.b"; "www.staging.pebblebeats.com" leaves "www".
  const label = h.slice(0, -(z.length + 1));
  // The candidate must be exactly one valid slug (3 to 32 characters, a letter first, lowercase letters, digits and
  // hyphens, not ending in a hyphen) and not a reserved word. Anything else inside our own zone is "bad": it is ours,
  // so it is redirected to the default metro rather than served.
  //   "a.b" has a dot, so it is not a valid slug -> bad.   "www" is reserved -> bad.   "m" is too short -> bad.
  if (!isValidSlug(label) || isReservedSlug(label)) return { kind: "bad" };
  // C: "msp" is valid and not reserved -> the metro "msp". The proxy serves it as that metro.
  return { kind: "metro", slug: label };
}
