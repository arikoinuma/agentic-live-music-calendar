/**
 * Journey J8 (C4-T9): the local stack is not gated, resolves its host to the default metro, and stays out of search.
 *
 * The e2e stack is `APP_ENV=local` on `localhost:3100`, a host outside every zone. Three things follow, and this pins
 * them in the real server, where the unit tests (`lib/request-plan.test.ts`, `lib/proxy-handler.test.ts`) cannot:
 *   - no gate: a page loads with no cookie and no redirect (C4-D1: a laptop is not worth a password);
 *   - the default metro: the page renders the one live metro's calendar (C4-D2: hosts outside every zone are the
 *     default metro);
 *   - `noindex`: every non-production response carries `X-Robots-Tag` (C4-D7), here on the page and on a 404.
 * The staging gate itself is proven in the unit tests and by the `next start` matrix in the plan's Verification 4,
 * not here: it would need a second Next server with another environment.
 */
import { expect, test } from "./support/test";

test("the home page loads without a gate, as the default metro, and asks not to be indexed", async ({ page }) => {
  // Proves (C4-D1, C4-D2, C4-D7): the local stack serves the page with no gate redirect, as the default metro (the
  // sample world's venues are on the calendar), and marks the response noindex.
  const response = await page.goto("/");

  expect(response?.status()).toBe(200);
  expect(page.url()).not.toContain("/gate");
  expect(response?.headers()["x-robots-tag"]).toBe("noindex, nofollow");
  await expect(page.getByRole("link", { name: "Zhora Darling" }).first()).toBeVisible();
});

test("a missing page is still a real 404 and still carries noindex", async ({ page }) => {
  // Proves (C4-D7): noindex is attached to every non-production response, a genuine 404 included, and the proxy
  // does not turn the 404 into a 200.
  const response = await page.goto("/nope");

  expect(response?.status()).toBe(404);
  expect(response?.headers()["x-robots-tag"]).toBe("noindex, nofollow");
});

test("the gate's own page exists everywhere but its login does not outside staging", async ({ request }) => {
  // Proves (C4-D1, C4-D6): /gate renders in every environment (the proxy only gates staging and dev), but /gate/enter
  // answers 404 where there is nothing to log in to, so a local stack cannot be talked into issuing a gate cookie.
  expect((await request.get("/gate")).status()).toBe(200);
  expect((await request.post("/gate/enter", { form: { password: "x" } })).status()).toBe(404);
});
