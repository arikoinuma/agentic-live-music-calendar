/**
 * The proxy's and the gate's configuration, read from the environment in one place.
 *
 * Three server-only variables, none with a `NEXT_PUBLIC_` prefix, so none can reach a browser bundle:
 *
 *   SITE_ZONE            the environment's own zone (`staging.<domain>`, `<domain>` in production). Unset until a
 *                        domain exists, which makes every host "outside" and every deployment behave as it did
 *                        before C4 (C4-D2). Normalised here, once.
 *   DEFAULT_METRO_SLUG   optional; the code default is `msp` (C4-D2). A value that is SET but malformed or reserved
 *                        is reported as invalid, and the proxy answers 503 rather than quietly falling back, so a
 *                        typo is visible (C4-PR1-4).
 *   SITE_GATE_PASSWORD   the shared password for staging (C4-D6). Blank counts as unset.
 *
 * `env` is a parameter so tests pass a plain object; callers use the default, `process.env`.
 *
 * docs/dev/implementations/c4-metro-hosts.md: C4-D2, C4-D6, C4-PR1-4.
 */

import { isReservedSlug, isValidSlug, normalizeZone } from "./metro-host";

/** The default metro's slug when `DEFAULT_METRO_SLUG` is unset: the one live metro (Dep-D3). */
export const FALLBACK_METRO_SLUG = "msp";

type Env = Record<string, string | undefined>;

export type SiteConfig = {
  /** Normalised zone, or null when none is configured. */
  zone: string | null;
  defaultSlug: string;
  /** False when `DEFAULT_METRO_SLUG` is set to something that cannot be a slug. */
  defaultSlugValid: boolean;
  /** The gate password, or null when unset or blank. */
  gatePassword: string | null;
};

export function readSiteConfig(env: Env = process.env): SiteConfig {
  const rawSlug = env.DEFAULT_METRO_SLUG;
  const defaultSlug = rawSlug === undefined || rawSlug === "" ? FALLBACK_METRO_SLUG : rawSlug;
  const password = env.SITE_GATE_PASSWORD;
  return {
    zone: normalizeZone(env.SITE_ZONE),
    defaultSlug,
    defaultSlugValid: isValidSlug(defaultSlug) && !isReservedSlug(defaultSlug),
    gatePassword: password === undefined || password.trim() === "" ? null : password,
  };
}
