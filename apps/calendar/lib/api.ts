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
 *  - Every request is `cache: "no-store"` (decision B2-D1 in
 *    docs/dev/implementations/b2-routes-and-data-loading.md). Persistent
 *    caching is deliberately deferred (arch-initial.md §11); this is the
 *    one place to change when it arrives.
 *  - Every request has a timeout, so a hung API can't hold a page open.
 *  - Every request is LOGGED, one line each, to the Next.js server's
 *    terminal:  `[api] GET /shows?venue_id=3 -> 200 in 41ms`  (or
 *    `-> failed (timed out) in 5003ms`). The browser's Network tab can't
 *    show these calls — they go server to server — so this is the place to
 *    see what the app asked the API for. It writes
 *    the path and query only, never the base URL (deployment config).
 *  - Every 2xx response body gets a one-line SUMMARY, naming its request
 *    (parallel calls interleave in the terminal):
 *      `[api] GET /shows?venue_id=3 body (2.0 KB): 6 shows (…); 1 without start_time; …`
 *    With `LOG_API_BODIES=1` (never in production) the full JSON follows
 *    on one line, cut at 4000 characters. What goes in those lines is
 *    decided in lib/api-log.ts.
 *
 * Shape of the file: `createApiClient({ baseUrl, fetchImpl })` builds the
 * getters over an injectable `fetch` — that's what api.test.ts drives
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
import { bodyLoggingEnabled, compactJson, describeSize, summarizeBody } from "./api-log";
import type { ShowsQuery } from "./params";
import type {
  ArtistDetail,
  ArtistListResponse,
  CalendarMonthsResponse,
  MetroSummary,
  ShowDetail,
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
  /** `null` means the API answered 404. */
  getShow(id: number): Promise<ShowDetail | null>;
  getVenues(): Promise<VenueListResponse>;
  /** `null` means the API answered 404 — the caller decides that's a 404 page. */
  getVenue(id: number): Promise<VenueDetail | null>;
  getCalendarMonths(): Promise<CalendarMonthsResponse>;
  getArtists(): Promise<ArtistListResponse>;
  /** `null` means the API answered 404. */
  getArtist(id: number): Promise<ArtistDetail | null>;
}

function isTimeout(err: unknown): boolean {
  // AbortSignal.timeout() aborts with a DOMException named "TimeoutError".
  return err instanceof DOMException && err.name === "TimeoutError";
}

/**
 * The "path?query" an API call is logged under — the full URL minus the
 * base URL (deployment config, which stays out of logs).
 *
 * A logger must never be able to fail the request it is describing, nor
 * print nonsense. A malformed API_BASE_URL (no scheme, a typo) either
 * makes `new URL` throw — inside the error path, where a throw would
 * replace the ApiError the pages handle with a raw TypeError — or, for
 * something like "localhost:8000", parse "successfully" as a URL whose
 * scheme is "localhost:" and whose path is "8000/venues". So trust the
 * parse only if it came out http(s); otherwise fall back to the bare path.
 */
function targetOf(url: string, path: string): string {
  try {
    const parsed = new URL(url);
    if (parsed.protocol === "http:" || parsed.protocol === "https:") {
      return `${parsed.pathname}${parsed.search}`;
    }
  } catch {
    // fall through to the bare path
  }
  return path;
}

/**
 * Writes the status line described at the top of this file. The "in Nms"
 * is the time until the API's response HEADERS arrived — reading the body
 * comes after, and is covered by the same timeout. Every call this client
 * makes is a GET, so the method is a constant, not a parameter.
 */
function logRequest(target: string, outcome: string, startedAt: number): void {
  const ms = Math.round(performance.now() - startedAt);
  console.log(`[api] GET ${target} -> ${outcome} in ${ms}ms`);
}

/**
 * Writes the body summary line, and the full body when `full` is set.
 * Never throws: it runs after the response was parsed successfully, and a
 * logging problem must not turn good data into an error.
 *
 * Each line starts with the same "GET <path+query>" as the status line,
 * because the page's calls run in parallel and their lines interleave.
 * `route` is the path without its query, for api-log.ts to pick a summary.
 */
function logBody(
  target: string,
  route: string,
  text: string,
  body: unknown,
  full: boolean,
): void {
  try {
    const size = describeSize(new TextEncoder().encode(text).length);
    console.log(`[api] GET ${target} body (${size}): ${summarizeBody(route, body)}`);
    if (full) console.log(`[api] GET ${target} body JSON: ${compactJson(body)}`);
  } catch {
    // A log line is not worth a failed request.
  }
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
  // Also log each response body in full (LOG_API_BODIES; see api-log.ts).
  // Off by default: the one-line summary is always logged, the JSON is for
  // chasing one specific problem.
  logBodies?: boolean;
}): ApiClient {
  const { baseUrl, fetchImpl = fetch, logBodies = false } = opts;

  /**
   * The one place a request is made. Returns the raw Response once the
   * API has answered with ANY status; status handling is the caller's
   * (a 404 is data for getVenue and an error for getVenues). `target` is
   * the "path?query" the request is logged under, carried along so the
   * body summary can name its request.
   */
  async function send(
    path: string,
    query?: Parameters<typeof apiUrl>[2],
  ): Promise<{ response: Response; target: string }> {
    if (!baseUrl) {
      throw new ApiError(
        "API_BASE_URL is not set (see apps/calendar/.env.local)",
        { path },
      );
    }
    const url = apiUrl(baseUrl, path, query);
    const target = targetOf(url, path);
    const startedAt = performance.now();
    try {
      const response = await fetchImpl(url, {
        // B2-D1: never cached. Explicit at the call site, as in lib/health.ts.
        cache: "no-store",
        signal: AbortSignal.timeout(TIMEOUT_MS),
      });
      // Logged whatever the status: a 404 here is "no such venue", which
      // the caller turns into data — but the log reports what the API said.
      logRequest(target, String(response.status), startedAt);
      return { response, target };
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
      // Only now, so that Next's control-flow error (above) is never
      // logged as an API failure — it would print a false alarm on every
      // `next build`.
      logRequest(
        target,
        `failed (${isTimeout(err) ? "timed out" : "could not reach the API"})`,
        startedAt,
      );
      throw new ApiError(
        isTimeout(err)
          ? `API request timed out after ${TIMEOUT_MS}ms`
          : "Could not reach the API",
        { path, cause: err },
      );
    }
  }

  /** Non-2xx -> ApiError; 2xx -> the parsed JSON body, trusted as `T`. */
  async function readJson<T>(
    response: Response,
    path: string,
    target: string,
  ): Promise<T> {
    if (!response.ok) {
      throw new ApiError(`API answered HTTP ${response.status}`, {
        path,
        status: response.status,
      });
    }
    let text: string;
    let body: unknown;
    try {
      // Read as text and parse, rather than `response.json()`, so the
      // body's size can be logged. Same failure modes: a stalled body
      // rejects here, malformed JSON in JSON.parse.
      text = await response.text();
      body = JSON.parse(text);
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
    // After the try, not inside it: a logging problem must not be reported
    // as "not valid JSON". logBody never throws.
    logBody(target, path, text, body, logBodies);
    // `as T` is a trust boundary, not a check: the generated types say
    // what the API SHOULD send. Runtime validation (zod) is deferred
    // until the edit forms need it (api-contract.md §7).
    return body as T;
  }

  async function get<T>(
    path: string,
    query?: Parameters<typeof apiUrl>[2],
  ): Promise<T> {
    const { response, target } = await send(path, query);
    return readJson<T>(response, path, target);
  }

  // Detail endpoints: a 404 is an expected answer ("no such venue"), so
  // it's `null`, not an exception. Anything else non-2xx still throws.
  async function getOrNull<T>(path: string): Promise<T | null> {
    const { response, target } = await send(path);
    if (response.status === 404) return null;
    return readJson<T>(response, path, target);
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
        // "Every show from the server's today on" (B4, D2): sent as the
        // string "true" (QueryValue has no boolean) or not at all, so a
        // false flag leaves the default URL unchanged. The API refuses it
        // with `start`/`end` — that rule lives on the server.
        upcoming: query.upcoming ? "true" : undefined,
      }),
    getShow: (id) => getOrNull<ShowDetail>(`/shows/${id}`),
    // The month dropdown's options (B3): future-facing months that have
    // shows. The server decides both; the client never derives them.
    getCalendarMonths: () => get<CalendarMonthsResponse>("/calendar/months"),
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
const live = () =>
  createApiClient({
    baseUrl: process.env.API_BASE_URL,
    // LOG_API_BODIES=1 in apps/calendar/.env.local (restart `next dev`)
    // logs full response bodies; ignored in production (api-log.ts).
    logBodies: bodyLoggingEnabled(process.env),
  });

// React's `cache()` de-duplicates calls within ONE server render. It is
// applied to the getters whose arguments are PRIMITIVES, because `cache()`
// compares arguments with Object.is: `getMetro()` (no arguments), and
// `getVenue(id)`, `getArtist(id)` and `getShow(id)` (a number compares by
// value). The reason is `generateMetadata` (B4, D7): a detail page needs
// its record twice per render, once for the tab title and once for the
// body, and this makes that one API request. The root layout's footer and
// `generateMetadata` share the metro the same way. `getShows` takes an
// object, which `cache()` would compare by identity and never hit, and
// it is called once per page. (Next's own fetch memoization is not an
// option: it is switched off whenever a `signal` is passed.)
// Measured in B2: one /metro request per page that renders, but TWO when a
// page calls `notFound()` — Next renders the not-found tree as a second
// render, and `cache()` is scoped to one render (B2 code review #5). The
// same applies to a detail page's record.
export const getMetro = cache(() => live().getMetro());

export const getShows = (query?: Partial<ShowsQuery>) => live().getShows(query);
export const getCalendarMonths = () => live().getCalendarMonths();
export const getVenues = () => live().getVenues();
export const getVenue = cache((id: number) => live().getVenue(id));
export const getArtists = () => live().getArtists();
export const getArtist = cache((id: number) => live().getArtist(id));
export const getShow = cache((id: number) => live().getShow(id));
