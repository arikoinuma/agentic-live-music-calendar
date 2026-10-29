/**
 * The site's own address, built from configuration and never from the request's `Host` header (C4-D8).
 *
 * A canonical URL, `metadataBase` and the JSON-LD `url` all say "this is the official address of this page". The
 * `Host` header is sent by the client and can be forged, so echoing it into those places would let any request
 * make our pages point at another site. The origin here is `https://<slug>.<SITE_ZONE>`, built from a zone we
 * configured and a slug the proxy already checked. With no zone configured (the pre-domain state, and Production
 * until C11) there is no origin and so no canonical and no `url`: nothing is emitted rather than something wrong.
 *
 * `siteMetadata` is the one place the layout's SEO-related metadata is decided, so it can be tested without
 * rendering a layout: the canonical is only set when an origin exists (Next fails the build on a relative metadata
 * URL with no `metadataBase`, C4-PR1-16), and `robots` is `noindex` everywhere but production (C4-D7).
 *
 * docs/dev/implementations/c4-metro-hosts.md: C4-D7, C4-D8.
 */

import type { Metadata } from "next";
import type { AppEnv } from "./app-env";
import { normalizeZone } from "./metro-host";

/** `https://<slug>.<zone>`, or null when no zone is configured. */
export function siteOrigin(zone: string | null | undefined, slug: string): string | null {
  const z = normalizeZone(zone);
  return z === null ? null : `https://${slug}.${z}`;
}

/** Is a response from this environment kept out of search engines? Everything but production, and an unreadable environment. */
export function isNoindex(env: AppEnv | null): boolean {
  return env !== "prod";
}

/**
 * The slice of root-layout metadata that depends on where the site is: `metadataBase`, a per-route canonical and
 * `robots`. `env` is null when `getAppEnv()` threw: that is treated as non-production, so a misconfigured site is
 * never indexed (C4-PR1-16).
 */
export function siteMetadata(input: { env: AppEnv | null; origin: string | null }): Metadata {
  const metadata: Metadata = {};
  if (input.origin !== null) {
    metadata.metadataBase = new URL(input.origin);
    // "./" resolves against metadataBase and the current route's pathname, so each page names itself.
    metadata.alternates = { canonical: "./" };
  }
  if (isNoindex(input.env)) metadata.robots = { index: false, follow: false };
  return metadata;
}
