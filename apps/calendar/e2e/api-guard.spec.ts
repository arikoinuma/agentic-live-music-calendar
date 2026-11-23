/**
 * The shared-secret journey (C10-T17): the API refuses a call without the shared secret, and answers one with it.
 *
 * The stack runs the real FastAPI app with `API_SHARED_SECRET` set (`playwright.config.ts`, C10-D12), so every other
 * spec already proves the calendar renders through the guard. This one speaks to the API DIRECTLY, with Playwright's
 * `request` fixture and no browser, and pins the guard's contract from the outside:
 *   - no header -> 401, and a wrong header -> 401, with the same body (C10-D7: "absent" and "wrong" look alike);
 *   - the right header -> 200 and real data;
 *   - `/health` -> 200 with no header, because Railway's deploy check and the status page call it unauthenticated (C10-D6).
 * It goes to the API itself (`API_URL`), not the delay proxy, so a test cannot be passing on the proxy's behavior.
 */
import { expect, test } from "./support/test";
import { API_URL, E2E_API_SECRET } from "./support/stack";

const REFUSAL = { detail: "Missing or invalid API secret" };

test("a call with no secret is refused", async ({ request }) => {
  // Proves (C10-T17, C10-D6): with a secret configured the API refuses an anonymous read of the calendar. (The stack's API
  // runs `APP_ENV=local` with a secret set; the hosted start-up rule is `test_api_guard.py`'s, C10-T6 and C10-T7.)
  const response = await request.get(`${API_URL}/shows`);

  expect(response.status()).toBe(401);
  expect(await response.json()).toEqual(REFUSAL);
});

test("a call with the wrong secret is refused the same way", async ({ request }) => {
  // Proves (C10-T17, C10-D7): a wrong value is the same status and body as an absent one, so a caller learns nothing
  // from the difference.
  const response = await request.get(`${API_URL}/shows`, { headers: { "X-Api-Secret": "not-the-secret" } });

  expect(response.status()).toBe(401);
  expect(await response.json()).toEqual(REFUSAL);
});

test("a call with the right secret is served", async ({ request }) => {
  // Proves (C10-T17, C10-D6): the guard is not a wall: the right header reaches the route and the sample world comes
  // back (the metro is the same one the calendar's layout asks for).
  const response = await request.get(`${API_URL}/metro`, { headers: { "X-Api-Secret": E2E_API_SECRET } });

  expect(response.status()).toBe(200);
  expect((await response.json()).slug).toBe("msp");
});

test("/health answers with no secret", async ({ request }) => {
  // Proves (C10-T17, C10-D6): the one open route stays open. Railway's deploy check has no way to send a header, and a
  // guarded `/health` would fail every deploy.
  const response = await request.get(`${API_URL}/health`);

  expect(response.status()).toBe(200);
  expect((await response.json()).message).toBe("up");
});
