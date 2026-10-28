import { describe, expect, it, vi } from "vitest";
import { getApiHealth } from "./health";

// getApiHealth takes the fetch implementation as a parameter so these
// tests never touch the network. Each helper builds the smallest fake
// that exercises one failure mode.
const respondWith = (body: BodyInit | null, init?: ResponseInit) =>
  vi.fn(async () => new Response(body, init));

// What `AbortSignal.timeout()` rejects with when it fires.
const timeoutError = () =>
  new DOMException("The operation was aborted due to timeout", "TimeoutError");

const BASE = "http://api.test";

// Narrowing helper: fails the test loudly if the result was ok, and gives
// the assertions below a `reason` string without a conditional in every test.
async function failureReason(
  ...args: Parameters<typeof getApiHealth>
): Promise<string> {
  const result = await getApiHealth(...args);
  if (result.ok) throw new Error(`expected a failure, got ${JSON.stringify(result)}`);
  return result.reason;
}

describe("getApiHealth", () => {
  it("reports ok with the API's message when /health answers 200", async () => {
    const fetchImpl = respondWith(JSON.stringify({ message: "up" }), {
      status: 200,
    });

    expect(await getApiHealth(BASE, fetchImpl)).toEqual({
      ok: true,
      message: "up",
      appEnv: undefined,
    });
  });

  it("returns the API's app_env when it reports one (C3-D6)", async () => {
    // Proves: the page can show which environment the API believes it is in, so a staging frontend pointed at
    // the production API is visible. The value passes through untouched; the page decides how to show it.
    const fetchImpl = respondWith(JSON.stringify({ message: "up", app_env: "staging" }));

    expect(await getApiHealth(BASE, fetchImpl)).toEqual({
      ok: true,
      message: "up",
      appEnv: "staging",
    });
  });

  it("still reports ok, with no environment, when the API predates app_env (C3-D6)", async () => {
    // Proves: during the cutover the new frontend talks to the old production API for a while (plan step 6.4),
    // whose /health has only `message`. That must read as "up, environment unknown", not as a failure.
    const fetchImpl = respondWith(JSON.stringify({ message: "up" }));

    const result = await getApiHealth(BASE, fetchImpl);

    expect(result.ok).toBe(true);
    expect(result.ok && result.appEnv).toBeUndefined();
  });

  it("ignores an app_env that is not a string", async () => {
    // Proves: a malformed field is dropped instead of being rendered or failing the page; `message` is still
    // what decides ok.
    const fetchImpl = respondWith(JSON.stringify({ message: "up", app_env: 7 }));

    const result = await getApiHealth(BASE, fetchImpl);

    expect(result.ok && result.appEnv).toBeUndefined();
  });

  it("never caches, and always bounds the wait with a timeout signal", async () => {
    // A health check that returns a cached "up", or hangs with the API,
    // is worse than none — so pin both options, not just that *some*
    // second argument was passed.
    const fetchImpl = respondWith(JSON.stringify({ message: "up" }));

    await getApiHealth(BASE, fetchImpl);

    expect(fetchImpl).toHaveBeenCalledWith(
      `${BASE}/health`,
      expect.objectContaining({
        cache: "no-store",
        signal: expect.any(AbortSignal),
      }),
    );
  });

  it.each([["http://api.test/"], ["http://api.test///"]])(
    "doesn't double the slash when API_BASE_URL ends with one (%s)",
    async (base) => {
      // `${base}/health` with a trailing slash is "//health", which
      // FastAPI answers 404 — the page would say "down" while the API is up.
      const fetchImpl = respondWith(JSON.stringify({ message: "up" }));

      expect((await getApiHealth(base, fetchImpl)).ok).toBe(true);
      expect(fetchImpl).toHaveBeenCalledWith(
        "http://api.test/health",
        expect.anything(),
      );
    },
  );

  it("reports the status on a non-200 instead of throwing", async () => {
    const fetchImpl = respondWith("nope", { status: 503 });

    expect(await failureReason(BASE, fetchImpl)).toContain("503");
  });

  it("reports the underlying error when the network call fails", async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError("fetch failed");
    });

    expect(await failureReason(BASE, fetchImpl)).toContain("fetch failed");
  });

  it("says 'timed out' when the request times out", async () => {
    const fetchImpl = vi.fn(async () => {
      throw timeoutError();
    });

    expect(await failureReason(BASE, fetchImpl)).toContain("timed out");
  });

  it("says 'timed out' when the headers arrive but the body stalls", async () => {
    // The timeout signal also cancels the body read, so a stalled body
    // surfaces from `.json()`, not from `fetch`. It must not be
    // misreported as bad JSON.
    const fetchImpl = vi.fn(
      async () =>
        ({
          ok: true,
          status: 200,
          json: async () => {
            throw timeoutError();
          },
        }) as unknown as Response,
    );

    const reason = await failureReason(BASE, fetchImpl);

    expect(reason).toContain("timed out");
    expect(reason).not.toContain("JSON");
  });

  it("reports invalid JSON when the body isn't JSON", async () => {
    const fetchImpl = respondWith("<html>bad gateway</html>", { status: 200 });

    expect(await failureReason(BASE, fetchImpl)).toContain("not valid JSON");
  });

  it("reports a missing `message` when the JSON lacks a string one", async () => {
    const fetchImpl = respondWith(JSON.stringify({ message: 42 }), {
      status: 200,
    });

    expect(await failureReason(BASE, fetchImpl)).toContain("message");
  });

  it("names API_BASE_URL when it isn't configured", async () => {
    // An unset env var is the most likely first-run mistake
    // (apps/calendar/.env.local), so it gets its own message.
    const fetchImpl = vi.fn();

    expect(await failureReason(undefined, fetchImpl)).toContain("API_BASE_URL");
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
