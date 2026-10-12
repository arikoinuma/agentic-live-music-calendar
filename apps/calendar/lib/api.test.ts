import { describe, expect, it, vi } from "vitest";
import { ApiError, createApiClient } from "./api";
import artistDetail from "./fixtures/artist-detail.json";
import artists from "./fixtures/artists.json";
import metro from "./fixtures/metro.json";
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

// --- the happy paths -------------------------------------------------------

describe("typed getters", () => {
  it.each([
    ["getMetro", "/metro", metro, (c: ReturnType<typeof clientFor>) => c.getMetro()],
    ["getVenues", "/venues", venues, (c: ReturnType<typeof clientFor>) => c.getVenues()],
    ["getArtists", "/artists", artists, (c: ReturnType<typeof clientFor>) => c.getArtists()],
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
    // Proves: decision D1 (no persistent caching in B2) and that a hung
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
