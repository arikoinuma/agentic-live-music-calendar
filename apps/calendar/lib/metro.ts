/**
 * The metro name for the root layout, with a safety net.
 *
 * Every page renders the root layout, so the layout asking the API for the
 * metro name makes the whole site depend on one more API call. This file
 * is what keeps that dependency from being fatal: if the call fails, the
 * layout falls back to a generic description and a plain footer instead of
 * failing every route (G24, alpha-build-plan.md B2).
 *
 * The fetcher is a parameter (defaulting to the real client's `getMetro`,
 * like `getApiHealth` takes `fetch`), so tests pass a fake and never touch
 * the network.
 */

import { unstable_rethrow } from "next/navigation";
import { getMetro } from "./api";
import type { MetroSummary } from "./types";

// Used when the metro can't be fetched. Exported so the build check can
// grep the built HTML for it: a static page with this text baked in would
// mean the metro fetch got cached at build time, which is exactly what
// decision D1 (no persistent caching in B2) exists to prevent
// (plan Verification 3, review #7).
export const FALLBACK_DESCRIPTION =
  "Live music, gathered from venue calendars.";

/** The page `<meta description>`: names the metro when we have it. */
export function siteDescription(metro: MetroSummary | null): string {
  return metro === null
    ? FALLBACK_DESCRIPTION
    : `Live music in ${metro.name}, gathered from venue calendars.`;
}

/**
 * Runs `fetcher` (the API client's `getMetro`) and returns its result, or
 * `null` if the API is unavailable.
 *
 * (Ari) — Gap C. Lesson: every page renders the root layout, so a
 *   failed metro call must not fail the shell — but a blanket `catch`
 *   also swallows Next's internal control-flow errors (the dynamic-usage
 *   signal `fetch` throws during prerender), which turns a working build
 *   into a failing one. `unstable_rethrow` first, then handle.
 * Code:
 *   try {
 *     return await fetcher();
 *   } catch (err) {
 *     unstable_rethrow(err);
 *     console.error("[metro] unavailable:", err);
 *     return null;
 *   }
 * Check: `pnpm --filter calendar test metro` — the "rethrows Next's
 *   dynamic-usage signal" case. Likeliest mistake: `catch { return null }`,
 *   which passes the other two cases and then fails `next build`.
 */
export async function getMetroOrNull(
  fetcher: () => Promise<MetroSummary> = getMetro,
): Promise<MetroSummary | null> {
  // Referenced so the scaffold type-checks and lints before the gap is
  // filled; the filled version uses both.
  try {
      return await fetcher();
    } catch (err) {
      unstable_rethrow(err);
      console.error("[metro] unavailable:", err);
      return null;
    }
}
