/**
 * The typed client for the FastAPI read API — the one place the Next.js
 * app talks to the backend.
 *
 * Server Components call the exported getters (`getVenues()`, …) and get
 * back the generated types from `lib/types.ts`; nothing else in the app
 * should call `fetch` against the API. Keeping it in one file is what
 * lets the rules below hold everywhere:
 *
 *  - `import "server-only"`: this module reads `API_BASE_URL`, which has
 *    no NEXT_PUBLIC_ prefix and must never reach a browser bundle. The
 *    import turns an accidental import from a Client Component into a
 *    BUILD error instead of a silent leak (nextjs-style-guide.md,
 *    "Preventing data leaks"). The browser never talks to FastAPI.
 *  - Every request is `cache: "no-store"` (decision D1 in
 *    docs/dev/implementations/b2-routes-and-data-loading.md). Persistent
 *    caching is deliberately deferred (arch-initial.md §11); this is the
 *    one place to change when it arrives.
 *  - Every request has a timeout, so a hung API can't hold a page open.
 *
 * Shape of the file: `createApiClient({ baseUrl, fetchImpl })` builds the
 * six getters over an injectable `fetch` — that's what api.test.ts drives
 * with fake responses. The exported functions at the bottom bind the real
 * `fetch` and the real env var, and are what pages import.
 */

import "server-only";
import { cache } from "react";
// `unstable_rethrow` is Next's documented way to let its internal
// control-flow errors pass through a catch block. See `send()` for why
// this file can't work without it.
import { unstable_rethrow } from "next/navigation";
import { apiUrl } from "./api-url";
import type { ShowsQuery } from "./params";
import type {
  ArtistDetail,
  ArtistListResponse,
  MetroSummary,
  ShowListResponse,
  VenueDetail,
  VenueListResponse,
} from "./types";

// How long to wait for the API, headers and body together. Longer than
// the /health page's 3s (that page exists to report slowness quickly);
// short enough that a hung API shows the error page rather than a spinner.
const TIMEOUT_MS = 5000;

/**
 * Every way an API call can fail that isn't "that record doesn't exist".
 *
 * `status` is the HTTP status when the API answered, `null` when it never
 * did (unreachable, timed out, unparseable). `path` is the API path (not
 * the full URL — the base URL is deployment config and has no business in
 * an error message). The message is for the server log; pages must not
 * render it (`app/error.tsx` shows a generic message).
 */
export class ApiError extends Error {
  readonly path: string;
  readonly status: number | null;

  constructor(
    message: string,
    opts: { path: string; status?: number; cause?: unknown },
  ) {
    super(message, { cause: opts.cause });
    this.name = "ApiError";
    this.path = opts.path;
    this.status = opts.status ?? null;
  }
}

export interface ApiClient {
  getMetro(): Promise<MetroSummary>;
  getShows(query?: Partial<ShowsQuery>): Promise<ShowListResponse>;
  getVenues(): Promise<VenueListResponse>;
  /** `null` means the API answered 404 — the caller decides that's a 404 page. */
  getVenue(id: number): Promise<VenueDetail | null>;
  getArtists(): Promise<ArtistListResponse>;
  /** `null` means the API answered 404. */
  getArtist(id: number): Promise<ArtistDetail | null>;
}

function isTimeout(err: unknown): boolean {
  // AbortSignal.timeout() aborts with a DOMException named "TimeoutError".
  return err instanceof DOMException && err.name === "TimeoutError";
}

/**
 * Builds the client. `baseUrl` is allowed to be undefined so that a
 * missing env var surfaces as a clear error from the first CALL (naming
 * API_BASE_URL) rather than a crash at import time — module-load-time
 * checks make tests and `next build` depend on import order.
 */
export function createApiClient(opts: {
  baseUrl: string | undefined;
  fetchImpl?: typeof fetch;
}): ApiClient {
  const { baseUrl, fetchImpl = fetch } = opts;

  /**
   * The one place a request is made. Returns the raw Response once the
   * API has answered with ANY status; status handling is the caller's
   * (a 404 is data for getVenue and an error for getVenues).
   */
  async function send(
    path: string,
    query?: Parameters<typeof apiUrl>[2],
  ): Promise<Response> {
    if (!baseUrl) {
      throw new ApiError(
        "API_BASE_URL is not set (see apps/calendar/.env.local)",
        { path },
      );
    }
    try {
      return await fetchImpl(apiUrl(baseUrl, path, query), {
        // D1: never cached. Explicit at the call site, as in lib/health.ts.
        cache: "no-store",
        signal: AbortSignal.timeout(TIMEOUT_MS),
      });
    } catch (err) {
      // MUST be first. During `next build`, a `no-store` fetch THROWS a
      // DynamicServerError, on purpose and before any network call, to
      // tell Next "this route is dynamic". Wrapping it in an ApiError
      // would turn that signal into a build failure, whether or not the
      // API is up — and no unit test can see it, because Vitest has no
      // patched `fetch` (plan review #1; pinned by api.test.ts). So give
      // Next its control-flow errors back untouched, then handle the
      // errors that are really ours.
      unstable_rethrow(err);
      throw new ApiError(
        isTimeout(err)
          ? `API request timed out after ${TIMEOUT_MS}ms`
          : "Could not reach the API",
        { path, cause: err },
      );
    }
  }

  /** Non-2xx -> ApiError; 2xx -> the parsed JSON body, trusted as `T`. */
  async function readJson<T>(response: Response, path: string): Promise<T> {
    if (!response.ok) {
      throw new ApiError(`API answered HTTP ${response.status}`, {
        path,
        status: response.status,
      });
    }
    try {
      // `as T` is a trust boundary, not a check: the generated types say
      // what the API SHOULD send. Runtime validation (zod) is deferred
      // until the edit forms need it (api-contract.md §7).
      return (await response.json()) as T;
    } catch (err) {
      unstable_rethrow(err); // same reason as in send()
      // The timeout also covers reading the body, so a stalled body shows
      // up here as a TimeoutError — tell it apart from bad JSON.
      throw new ApiError(
        isTimeout(err)
          ? `API response timed out after ${TIMEOUT_MS}ms`
          : "API response was not valid JSON",
        { path, status: response.status, cause: err },
      );
    }
  }

  async function get<T>(
    path: string,
    query?: Parameters<typeof apiUrl>[2],
  ): Promise<T> {
    return readJson<T>(await send(path, query), path);
  }

  // Detail endpoints: a 404 is an expected answer ("no such venue"), so
  // it's `null`, not an exception. Anything else non-2xx still throws.
  async function getOrNull<T>(path: string): Promise<T | null> {
    const response = await send(path);
    if (response.status === 404) return null;
    return readJson<T>(response, path);
  }

  return {
    getMetro: () => get<MetroSummary>("/metro"),
    getShows: (query = {}) =>
      // ShowsQuery's camelCase names become the API's snake_case,
      // repeated-key parameters (api-contract.md §2). Absent or empty
      // values are omitted by apiUrl, so the server picks its defaults.
      get<ShowListResponse>("/shows", {
        start: query.start,
        end: query.end,
        venue_id: query.venueIds,
        artist_id: query.artistIds,
      }),
    getVenues: () => get<VenueListResponse>("/venues"),
    getVenue: (id) => getOrNull<VenueDetail>(`/venues/${id}`),
    getArtists: () => get<ArtistListResponse>("/artists"),
    getArtist: (id) => getOrNull<ArtistDetail>(`/artists/${id}`),
  };
}

// --- what pages import ------------------------------------------------------------
//
// A fresh client per call, so `process.env.API_BASE_URL` is read when the
// request happens, not when the module loads.
const live = () => createApiClient({ baseUrl: process.env.API_BASE_URL });

// React's `cache()` de-duplicates calls within ONE server render: the
// root layout's footer and `generateMetadata` both ask for the metro, and
// this makes that a single API request. Only getMetro is wrapped because
// only it takes no arguments — `cache()` compares arguments by identity,
// so the other getters' object arguments would never hit, and each of
// them is called once per page anyway. (Next's own fetch memoization is
// not an option here: it is switched off whenever a `signal` is passed.)
// Measured: one /metro request per page that renders, but TWO when a page
// calls `notFound()` — Next renders the not-found tree as a second render,
// and `cache()` is scoped to one render (code review round 1, #5).
export const getMetro = cache(() => live().getMetro());

export const getShows = (query?: Partial<ShowsQuery>) => live().getShows(query);
export const getVenues = () => live().getVenues();
export const getVenue = (id: number) => live().getVenue(id);
export const getArtists = () => live().getArtists();
export const getArtist = (id: number) => live().getArtist(id);
