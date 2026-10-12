/**
 * Joins the API base URL, a path and a query into one URL string.
 *
 * Shared by `lib/api.ts` (the typed client) and `lib/health.ts` so that
 * "what happens to a trailing slash in API_BASE_URL" and "how repeated
 * query keys are written" are decided in exactly one place. Pure — no
 * env, no fetch — which is why it lives apart from `api.ts`: that file
 * is `server-only` and reads `process.env`; this one can be unit tested
 * (and reused) without either.
 */

// One query value. A list means "repeat the key" (`venue_id=1&venue_id=3`),
// the form FastAPI's `list[int] = Query()` parameters read
// (api-contract.md §2). `undefined` means "not set": the key is omitted.
export type QueryValue =
  | string
  | number
  | undefined
  | readonly (string | number)[];

export function apiUrl(
  base: string,
  path: string,
  query: Record<string, QueryValue> = {},
): string {
  // Strip trailing slashes: pasting "https://api.example.com/" into an
  // env var is easy, and `${base}/health` would then be "//health" —
  // which FastAPI answers 404, so the page would report "down" while the
  // API is up. (This is the same guard getApiHealth had inline.)
  const root = base.replace(/\/+$/, "");

  // URLSearchParams does the percent-encoding, and `append` (unlike
  // `set`) keeps repeated keys, in the order they were added.
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined) continue;
    for (const item of typeof value === "object" ? value : [value]) {
      params.append(key, String(item));
    }
  }

  // No '?' at all when nothing is left: "/shows?" is a different string
  // than "/shows" for anything comparing URLs, for no benefit.
  const queryString = params.toString();
  return queryString ? `${root}${path}?${queryString}` : `${root}${path}`;
}
