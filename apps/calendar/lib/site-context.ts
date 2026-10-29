/**
 * What a server render knows about where it is: the environment, the metro's slug and the site's own origin.
 *
 * The proxy resolves the metro from the host and passes the slug down in the `x-metro-slug` request header
 * (`lib/proxy-handler.ts`). This reads it back for the root layout's metadata and the JSON-LD URLs. It validates the
 * header AGAIN (a valid shape, not reserved, else the default slug) rather than trusting that the proxy ran: the
 * proxy is a convenience layer, not a boundary (nextjs-style-guide.md), and a header is only text (C4-D8).
 *
 * The origin comes from configuration (`siteOrigin`: the zone and the slug), never from the `Host` header.
 *
 * docs/dev/implementations/c4-metro-hosts.md: C4-D8.
 */

import "server-only";
import { headers } from "next/headers";
import { getAppEnv, type AppEnv } from "./app-env";
import { isReservedSlug, isValidSlug, METRO_SLUG_HEADER } from "./metro-host";
import { readSiteConfig } from "./site-config";
import { siteOrigin } from "./site-url";

export type SiteContext = {
  /** Null when `APP_ENV` is missing or inconsistent: treated as non-production (C4-PR1-16). */
  env: AppEnv | null;
  slug: string;
  /** `https://<slug>.<zone>`, or null when no zone is configured. */
  origin: string | null;
};

export async function getSiteContext(): Promise<SiteContext> {
  let env: AppEnv | null = null;
  try {
    env = getAppEnv();
  } catch {
    // The status page and the proxy report this; the layout just treats it as non-production.
  }
  const config = readSiteConfig();
  const fromHeader = (await headers()).get(METRO_SLUG_HEADER);
  const slug =
    fromHeader !== null && isValidSlug(fromHeader) && !isReservedSlug(fromHeader) ? fromHeader : config.defaultSlug;
  return { env, slug, origin: siteOrigin(config.zone, slug) };
}
