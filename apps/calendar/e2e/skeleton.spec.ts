/**
 * Journey J9 (B6 plan): the loading skeleton, replaced by the calendar.
 */
import { expect, test } from "./support/test";

// Proves: `/` streams. With the API slowed to 1.5 s, the shell and the heading paint
// FIRST and the skeleton ("Loading shows") stands in, with no show on screen; then the
// real calendar replaces it and the skeleton is gone (B3-D4: a <Suspense> inside the
// page, not a root loading.tsx). jsdom cannot show streaming and a fast API hides it,
// so the delay proxy slows the API between Next and FastAPI. The status text is asserted
// by its TEXT, not by a status role disappearing: the filter header always renders its
// own (empty) status element once the calendar is there. Expected values: 25 shows in
// the window (sample data).
test("the skeleton is replaced by the calendar", async ({ page, stack }) => {
  await stack.delay(1500);

  // "commit" resolves as soon as the response starts, so the page is still loading.
  await page.goto("/", { waitUntil: "commit" });

  await expect(page.getByRole("heading", { level: 1, name: "Live music" })).toBeVisible();
  await expect(page.getByText("Loading shows")).toHaveCount(1);
  await expect(page.getByRole("article")).toHaveCount(0);

  await expect(page.getByRole("article")).toHaveCount(25);
  await expect(page.getByText("Loading shows")).toHaveCount(0);
});
