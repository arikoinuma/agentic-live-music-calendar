/**
 * Journey J7 (B6 plan): URLs that lead nowhere get the real 404 page.
 */
import { expect, test } from "./support/test";

// One test per URL, so a failure names the URL. What each is:
//   /venue/9999     a well-formed id the API says does not exist (404 from the API)
//   /venue/abc      not an id at all (rejected before any API call)
//   /day/2026-02-30 a date that does not exist
//   /nope           no such route
const MISSING = ["/venue/9999", "/venue/abc", "/day/2026-02-30", "/nope"];

for (const url of MISSING) {
  // Proves: the response is a genuine HTTP 404, not a 200 that merely says "not
  // found" (a "soft 404", which search engines index; B2: `notFound()` must THROW),
  // and the visitor lands on the app's own page with a way back. Valid while the detail
  // routes are not behind a streaming boundary (B2-D4): once a response streams, the
  // status line is already sent.
  test(`${url} is a 404 with a way back`, async ({ page }) => {
    const response = await page.goto(url);

    expect(response?.status()).toBe(404);
    await expect(page.getByRole("heading", { level: 1, name: "Not found" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Back to the calendar" })).toHaveAttribute("href", "/");
  });
}
