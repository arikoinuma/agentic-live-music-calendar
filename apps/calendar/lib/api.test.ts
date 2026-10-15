import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, createApiClient } from "./api";
import artistDetail from "./fixtures/artist-detail.json";
import artists from "./fixtures/artists.json";
import calendarMonths from "./fixtures/calendar-months.json";
import metro from "./fixtures/metro.json";
import showDetail from "./fixtures/show-detail.json";
import shows from "./fixtures/shows.json";
import venueDetail from "./fixtures/venue-detail.json";
import venues from "./fixtures/venues.json";

// The client takes `fetchImpl` and `baseUrl` as parameters (as getApiHealth
// does), so none of these tests touch the network. Fixtures are served as
// JSON response bodies and the tests assert the client hands them back
// unchanged. That does NOT prove the fixtures match the generated types
// (JSON imports widen enum fields to `string`; plan review #6) — that
// guarantee is `make contract-check`, since generate_fixtures.py dumps the
// fixtures from the same Pydantic models the types come from.

const BASE = "http://api.test";

const respondWith = (body: unknown, status = 200) =>
  vi.fn(
    async () =>
      new Response(typeof body === "string" ? body : JSON.stringify(body), {
        status,
      }),
  );

const clientFor = (fetchImpl: typeof fetch) =>
  createApiClient({ baseUrl: BASE, fetchImpl });

// The URL string the most recent call was made with.
const calledUrl = (fetchImpl: ReturnType<typeof vi.fn>) =>
  String(fetchImpl.mock.calls.at(-1)?.[0]);

// What Next's `no-store` fetch throws during `next build` to mark a route
// dynamic. Next recognises it by this `digest` string alone.
const dynamicUsageError = () =>
  Object.assign(new Error("Dynamic server usage: no-store fetch"), {
    digest: "DYNAMIC_SERVER_USAGE",
  });

// The client logs one line per API call (see "request log" below), through
// console.log. Silence it for every test, so test output stays readable;
// the "request log" tests read the spy to assert on the lines.
let log: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  log = vi.spyOn(console, "log").mockImplementation(() => {});
});
afterEach(() => vi.restoreAllMocks());

// The lines the client has logged so far, as plain strings.
const loggedLines = () => log.mock.calls.map((args: unknown[]) => String(args[0]));

// --- the happy paths -------------------------------------------------------

describe("typed getters", () => {
  it.each([
    ["getMetro", "/metro", metro, (c: ReturnType<typeof clientFor>) => c.getMetro()],
    ["getVenues", "/venues", venues, (c: ReturnType<typeof clientFor>) => c.getVenues()],
    ["getArtists", "/artists", artists, (c: ReturnType<typeof clientFor>) => c.getArtists()],
    ["getCalendarMonths", "/calendar/months", calendarMonths, (c: ReturnType<typeof clientFor>) => c.getCalendarMonths()],
  ])("%s calls %s and returns the body unchanged", async (_name, path, body, call) => {
    // Proves: each list/reference getter hits the right URL and returns
    // the parsed JSON as-is (no reshaping layer to drift from the contract).
    const fetchImpl = respondWith(body);
    expect(await call(clientFor(fetchImpl))).toEqual(body);
    expect(calledUrl(fetchImpl)).toBe(`${BASE}${path}`);
  });

  it("getVenue / getArtist request /venues/{id} and /artists/{id} and return the record", async () => {
    // Proves: the detail getters build `/venues/{id}` / `/artists/{id}` and return the record unchanged.
    const venueFetch = respondWith(venueDetail);
    expect(await clientFor(venueFetch).getVenue(3)).toEqual(venueDetail);
    expect(calledUrl(venueFetch)).toBe(`${BASE}/venues/3`);

    const artistFetch = respondWith(artistDetail);
    expect(await clientFor(artistFetch).getArtist(1)).toEqual(artistDetail);
    expect(calledUrl(artistFetch)).toBe(`${BASE}/artists/1`);
  });
});

describe("getShow", () => {
  it("requests /shows/{id} and returns the record unchanged", async () => {
    // Proves: the show page's getter builds `/shows/{id}` and hands the
    // body back as-is (show-detail.json is a ShowDetail dumped from the
    // Pydantic model).
    const fetchImpl = respondWith(showDetail);
    expect(await clientFor(fetchImpl).getShow(2)).toEqual(showDetail);
    expect(calledUrl(fetchImpl)).toBe(`${BASE}/shows/2`);
  });

  it("returns null on 404 so the page can call notFound()", async () => {
    // Proves: same contract as getVenue/getArtist — a miss is data.
    expect(await clientFor(respondWith({ detail: "x" }, 404)).getShow(9999)).toBeNull();
  });
});

describe("getShows", () => {
  it("sends start, end and repeated venue_id / artist_id", async () => {
    // Proves: the ShowsQuery -> API-parameter mapping, including the
    // renaming (venueIds -> venue_id) and the repeated-key form
    // (api-contract.md §2).
    const fetchImpl = respondWith(shows);
    const result = await clientFor(fetchImpl).getShows({
      start: "2026-10-01",
      end: "2026-10-31",
      venueIds: [1, 3],
      artistIds: [7],
    });
    expect(result).toEqual(shows);
    expect(calledUrl(fetchImpl)).toBe(
      `${BASE}/shows?start=2026-10-01&end=2026-10-31&venue_id=1&venue_id=3&artist_id=7`,
    );
  });

  it("sends only a start for the venue page's paging, never an end", async () => {
    // Proves: paging sends `start` ALONE, so the window length stays the
    // server's decision (the API fills `end` = start + DEFAULT_WINDOW). A
    // later "both or neither" refactor of the query mapping would silently
    // put a client-chosen length back in charge.
    const fetchImpl = respondWith(shows);
    await clientFor(fetchImpl).getShows({ start: "2026-10-26", venueIds: [3], artistIds: [] });
    expect(calledUrl(fetchImpl)).toBe(`${BASE}/shows?start=2026-10-26&venue_id=3`);
  });

  it("sends upcoming=true with no dates for the artist page", async () => {
    // Proves: B4-D2 — "every upcoming show" is the SERVER's question. The
    // client sends the flag and the artist, and no start or end (the API
    // answers 422 to the combination).
    const fetchImpl = respondWith(shows);
    await clientFor(fetchImpl).getShows({ artistIds: [1], venueIds: [], upcoming: true });
    expect(calledUrl(fetchImpl)).toBe(`${BASE}/shows?artist_id=1&upcoming=true`);
  });

  it("omits upcoming when it is false or absent", async () => {
    // Proves: the default URL is unchanged by the new option — a false
    // flag is simply not sent.
    const fetchImpl = respondWith(shows);
    await clientFor(fetchImpl).getShows({ artistIds: [1], venueIds: [], upcoming: false });
    expect(calledUrl(fetchImpl)).toBe(`${BASE}/shows?artist_id=1`);
    await clientFor(fetchImpl).getShows({ artistIds: [1], venueIds: [] });
    expect(calledUrl(fetchImpl)).toBe(`${BASE}/shows?artist_id=1`);
  });

  it("omits absent filters, so the server picks its default window", async () => {
    // Proves: with no filters (empty lists or no argument at all) the client sends a bare `/shows`, so the
    // SERVER chooses the window: "the server owns now" (api-contract.md §3). Sending a client-computed
    // date here would put the browser's clock in charge.
    const fetchImpl = respondWith(shows);
    await clientFor(fetchImpl).getShows({ venueIds: [], artistIds: [] });
    expect(calledUrl(fetchImpl)).toBe(`${BASE}/shows`);
    await clientFor(fetchImpl).getShows();
    expect(calledUrl(fetchImpl)).toBe(`${BASE}/shows`);
  });
});

// --- misses and failures ------------------------------------------------------

describe("getVenue / getArtist on a miss", () => {
  it("returns null on 404 so the page can call notFound()", async () => {
    // Proves: "no such record" is an expected outcome, not an exception.
    // The caller decides it means a 404 page.
    expect(await clientFor(respondWith({ detail: "x" }, 404)).getVenue(9999)).toBeNull();
    expect(await clientFor(respondWith({ detail: "x" }, 404)).getArtist(9999)).toBeNull();
  });
});

describe("errors", () => {
  it.each([500, 422])("throws ApiError carrying status and path on HTTP %i", async (status) => {
    // Proves: real failures are not swallowed as "not found" — the page
    // will show the error boundary, not a misleading 404.
    const error = await clientFor(respondWith({ detail: "boom" }, status))
      .getVenue(3)
      .catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status, path: "/venues/3" });
  });

  it("wraps a network failure in an ApiError with the cause attached", async () => {
    // Proves: an unreachable API becomes an ApiError (status null, path set) whose `cause` is the original
    // error, so the server log keeps the real reason while pages show only a generic message.
    const cause = new TypeError("fetch failed");
    const fetchImpl = vi.fn(async () => {
      throw cause;
    });
    const error = await clientFor(fetchImpl).getVenues().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ path: "/venues", status: null });
    expect((error as ApiError).cause).toBe(cause);
    expect((error as ApiError).message).toMatch(/could not reach/i);
  });

  it("reports a timeout distinctly", async () => {
    // Proves: a timeout is reported as a timeout, not as "could not reach": the two have different fixes
    // (a hung API vs a down one) and the log should say which.
    const fetchImpl = vi.fn(async () => {
      throw new DOMException("The operation timed out", "TimeoutError");
    });
    const error = await clientFor(fetchImpl).getVenues().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toMatch(/timed out/i);
  });

  it("wraps malformed JSON in an ApiError with a different message", async () => {
    // Proves: "API sent an HTML error page with a 200" is distinguishable
    // from "API unreachable" when someone reads the server log.
    const error = await clientFor(respondWith("<html>oops</html>"))
      .getVenues()
      .catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toMatch(/not valid JSON/i);
    expect((error as ApiError).message).not.toMatch(/could not reach/i);
  });

  it("lets Next's dynamic-usage signal through untouched", async () => {
    // Proves: during `next build`, a no-store fetch throws this error ON
    // PURPOSE to mark the route dynamic. If the client wrapped it in an
    // ApiError the build would fail whether or not the API is up, and no
    // other test can see it because Vitest has no patched `fetch`
    // (plan review #1). It must come out as the *same object*.
    const signal = dynamicUsageError();
    const fetchImpl = vi.fn(async () => {
      throw signal;
    });
    await expect(clientFor(fetchImpl).getVenues()).rejects.toBe(signal);
  });

  it("throws an error naming API_BASE_URL when it is unset, without calling fetch", async () => {
    // Proves: the most likely first-run mistake (no .env.local) is
    // diagnosable from the message alone.
    const fetchImpl = respondWith(venues);
    for (const baseUrl of [undefined, ""]) {
      const client = createApiClient({ baseUrl, fetchImpl });
      await expect(client.getVenues()).rejects.toThrow(/API_BASE_URL/);
    }
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});

describe("request options", () => {
  it("never caches and always bounds the wait with a timeout signal", async () => {
    // Proves: decision B2-D1 (no persistent caching in B2) and that a hung
    // API can't hold a page open. Asserted with objectContaining on the
    // specific values, not expect.anything() (B1 review's lesson).
    const fetchImpl = respondWith(venues);
    await clientFor(fetchImpl).getVenues();
    expect(fetchImpl).toHaveBeenCalledWith(
      `${BASE}/venues`,
      expect.objectContaining({
        cache: "no-store",
        signal: expect.any(AbortSignal),
      }),
    );
  });
});

// --- the request log ---------------------------------------------------------
// One line per API call, in the Next.js server's terminal: the substitute
// for the browser's Network tab, which can't see server-to-server requests.
// Expected values are the format written in
// lib/api.ts's docstring, not read back from the code.

describe("request log", () => {
  it("logs the method, path, status and elapsed time", async () => {
    // Proves: a successful call leaves a status line, in the documented
    // format — the line a developer greps the terminal for — followed by
    // the body summary (tested under "response body log").
    await clientFor(respondWith(venues)).getVenues();
    expect(loggedLines()).toHaveLength(2);
    expect(loggedLines()[0]).toMatch(/^\[api\] GET \/venues -> 200 in \d+ms$/);
  });

  it("includes the query string, with repeated keys", async () => {
    // Proves: the line shows what was actually asked for (the filters),
    // which is the thing you open the log to check.
    await clientFor(respondWith(shows)).getShows({ venueIds: [1, 3], start: "2026-10-01", end: "2026-10-31" });
    expect(loggedLines()[0]).toContain("/shows?start=2026-10-01&end=2026-10-31&venue_id=1&venue_id=3");
  });

  it("logs the real status of a 404, even though getVenue treats it as data", async () => {
    // Proves: the log reports what the API said, not what the caller made
    // of it; "no such venue" must still be visible as a 404 in the log.
    await clientFor(respondWith({ detail: "Venue not found" }, 404)).getVenue(9999);
    expect(loggedLines()[0]).toMatch(/GET \/venues\/9999 -> 404 in \d+ms$/);
  });

  it("logs a failed call instead of a status", async () => {
    // Proves: an unreachable API shows up in the log with a reason, at the
    // moment it happens.
    const fetchImpl = vi.fn(async () => {
      throw new TypeError("fetch failed");
    });
    await clientFor(fetchImpl as unknown as typeof fetch).getVenues().catch(() => {});
    expect(loggedLines()[0]).toMatch(/GET \/venues -> failed \(could not reach the API\) in \d+ms$/);
  });

  it("says when a call timed out", async () => {
    // Proves: a timeout is told apart from an unreachable host in the log,
    // since the fix differs (a slow API versus a stopped one).
    const fetchImpl = vi.fn(async () => {
      throw new DOMException("timed out", "TimeoutError");
    });
    await clientFor(fetchImpl as unknown as typeof fetch).getVenues().catch(() => {});
    expect(loggedLines()[0]).toMatch(/-> failed \(timed out\) in \d+ms$/);
  });

  it("never prints the base URL", async () => {
    // Proves: deployment config (API_BASE_URL) stays out of logs; only the
    // path and query are written.
    await clientFor(respondWith(venues)).getVenues();
    expect(loggedLines().join("\n")).not.toContain(BASE);
  });

  it("does not log Next's dynamic-usage signal as a failure", async () => {
    // Proves: during `next build` a no-store fetch throws this on purpose
    // to mark the route dynamic. It is control flow, not an API failure,
    // so it must pass through silently (same rule as the ApiError wrapping
    // above) — a "failed" line here would be a false alarm on every build.
    const fetchImpl = vi.fn(async () => {
      throw dynamicUsageError();
    });
    await clientFor(fetchImpl as unknown as typeof fetch).getVenues().catch(() => {});
    expect(loggedLines()).toEqual([]);
  });

  it("cannot break the request it is logging", async () => {
    // Proves: a malformed API_BASE_URL (no scheme, a typo) still surfaces
    // as the ApiError the pages handle, not as a raw TypeError thrown by
    // the log line's own URL parsing. A logger must never be able to fail
    // a request; it falls back to the bare path.
    const fetchImpl = vi.fn(async () => {
      throw new TypeError("Failed to parse URL");
    });
    const client = createApiClient({ baseUrl: "localhost:8000", fetchImpl: fetchImpl as unknown as typeof fetch });
    const error = await client.getVenues().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(loggedLines()[0]).toMatch(/GET \/venues -> failed \(could not reach the API\) in \d+ms$/);
  });
});

// --- the response body log -----------------------------------------------------
// After the status line, a one-line SUMMARY of the parsed body (lib/api-log.ts
// decides its content); the full JSON only when the client is told to
// (LOG_API_BODIES -> `logBodies`). Sizes are the compact JSON lengths of
// the fixtures, measured with `json.dumps(..., separators=(",", ":"))`.

describe("response body log", () => {
  const withBodies = (fetchImpl: typeof fetch) =>
    createApiClient({ baseUrl: BASE, fetchImpl, logBodies: true });

  it("logs a summary line after the status line, by default", async () => {
    // Proves: the default leaves a short, searchable line describing what
    // came back — size and shape — so an anomaly (an empty list, a missing
    // field) is visible without reading JSON. venues.json is 156 bytes
    // compact and holds four venues.
    await clientFor(respondWith(venues)).getVenues();
    expect(loggedLines()).toHaveLength(2);
    expect(loggedLines()[1]).toBe("[api] GET /venues body (156 B): venues[4]");
  });

  it("carries its own method and path, because calls interleave", async () => {
    // Proves: the page's five API calls run in parallel, so their lines
    // interleave in the terminal. A summary that said only "25 shows" could
    // not be attributed; this one starts with the same "GET <path+query>"
    // as its status line, so a search for that request finds both.
    await clientFor(respondWith(shows)).getShows({ venueIds: [3] });
    expect(loggedLines()[1]).toMatch(
      /^\[api\] GET \/shows\?venue_id=3 body \(8\.1 KB\): 25 shows \(2026-09-28\.\.2026-10-25\); 3 without start_time/,
    );
  });

  it("does not write the full body unless asked", async () => {
    // Proves: the default never prints the JSON itself (large lines, and
    // data in hosted logs by accident).
    await clientFor(respondWith(venues)).getVenues();
    expect(loggedLines().join("\n")).not.toContain('"venues":[');
  });

  it("writes the full body, on one line, when asked", async () => {
    // Proves: the LOG_API_BODIES switch gives the exact JSON the API sent
    // (re-serialised compactly), for chasing one specific problem.
    await withBodies(respondWith(venues)).getVenues();
    expect(loggedLines()).toHaveLength(3);
    expect(loggedLines()[2]).toBe(`[api] GET /venues body JSON: ${JSON.stringify(venues)}`);
  });

  it("cuts a very large full body", async () => {
    // Proves: even with the switch on, one response can't flood the log:
    // the 8 KB /shows body (compact) is longer than the 4000-character cap
    // and the line says how much was cut.
    await withBodies(respondWith(shows)).getShows();
    expect(loggedLines()[2]).toMatch(/…\(\+\d+ chars\)$/);
  });

  it("logs no body for an error response or one that isn't JSON", async () => {
    // Proves: there is no body line where there is no usable body — the
    // status line alone says what happened — and the pages still get their
    // ApiError.
    const failing = await clientFor(respondWith({ detail: "boom" }, 500)).getVenues().catch((e: unknown) => e);
    expect(failing).toBeInstanceOf(ApiError);
    expect(loggedLines()).toHaveLength(1);

    log.mockClear();
    const garbled = await clientFor(respondWith("<html>not json")).getVenues().catch((e: unknown) => e);
    expect(garbled).toBeInstanceOf(ApiError);
    expect(loggedLines()).toHaveLength(1); // only the "-> 200" status line
  });

  it("returns the same data it logged", async () => {
    // Proves: reading the body as text (to measure it) and parsing it is
    // transparent — the caller gets exactly the API's object.
    expect(await withBodies(respondWith(shows)).getShows()).toEqual(shows);
  });
});
