/**
 * Keyboard-only use of the calendar (B6 plan, Step 6): WCAG 2.1.1 Keyboard, 2.1.2 No
 * Keyboard Trap, 2.4.3 Focus Order, 2.4.11 Focus Not Obscured and 3.2.1 On Focus.
 *
 * Every key press here is a real key press in a real browser. What these tests cannot
 * say is whether the experience is GOOD (is the order sensible, is the focus ring easy to
 * find); that is Ari's manual keyboard pass (plan, Verification 7). They catch the
 * mechanical failures: a control a keyboard cannot reach, a trap, focus hidden behind
 * something.
 */
import { expectMatchesBaseline } from "./support/a11y";
import { isFocusObscured } from "./support/focus";
import { TAB_STOP_PAGES, TAB_STOP_WIDTHS, tabStopsLabel } from "./support/labels";
import { SCREENS } from "./support/screens";
import { expect, test } from "./support/test";

// ---------------------------------------------------------------------------
// Focus is never hidden behind the sticky date headings (2.4.11)
// ---------------------------------------------------------------------------

// The pages and widths are in labels.ts, shared with the baseline's orphan check. Both pages
// render the calendar grid and its sticky date headings; 1280 is a desktop, 375 a phone
// (where the sticky heading takes the most room).
const MAX_STOPS = 300; // the home page has about 160; this only stops a runaway loop

for (const width of TAB_STOP_WIDTHS) {
  for (const path of TAB_STOP_PAGES) {
    // Proves: tabbing from the top of the page to the end never lands on a control that is
    // hidden at its centre behind something else (WCAG 2.4.11; the requirement says
    // visible focus "not covered by sticky headers"). The calendar has sticky date
    // headings, so a link scrolled to the top edge could sit under one. The visited
    // order is attached to the report as the evidence for 2.4.3 (Focus Order), and the page
    // URL is checked at the end because merely FOCUSING about 160 controls must change
    // nothing (3.2.1, On Focus). Any stop that IS hidden is held to the ratchet baseline BY
    // NAME, each stop its own finding. The baseline holds none today (B6-F7, a link half cut off
    // by its venue row's scroll container at 375px, was the one it held; `ScrollRow` fixed it),
    // so any hidden stop, including one under a sticky heading, fails.
    test(`no Tab stop is newly hidden, under a sticky heading or anything else, on ${path} @${width}`, async ({
      page,
    }) => {
      const screen = SCREENS.find((s) => s.path === path)!;
      await page.setViewportSize({ width, height: 700 });
      await page.goto(path);
      await screen.ready(page);

      const visited: string[] = [];
      const hidden: string[] = [];
      for (let stop = 0; stop < MAX_STOPS; stop++) {
        await page.keyboard.press("Tab");
        const name = await page.evaluate(() => {
          const el = document.activeElement as HTMLElement | null;
          if (!el || el === document.body) return null; // focus left the page
          return (el.getAttribute("aria-label") ?? el.textContent ?? "").trim().slice(0, 50) || el.tagName;
        });
        if (name === null) break;
        visited.push(name);
        if (await isFocusObscured(page)) hidden.push(name);
      }

      await test.info().attach(`tab order: ${path} @${width}`, { body: visited.join("\n"), contentType: "text/plain" });
      expect(visited.length, "the page has far more than ten Tab stops").toBeGreaterThan(10);
      await test.info().attach(`hidden tab stops: ${path} @${width}`, { body: hidden.join("\n"), contentType: "text/plain" });
      await expect(page, "focusing controls must not navigate (WCAG 3.2.1)").toHaveURL(path);

      // One finding per hidden stop NAME (and how many times that name was hidden), so the
      // baseline says WHICH stop is known, not just how many.
      const label = tabStopsLabel(path, width);
      const byName = new Map<string, number>();
      for (const name of hidden) byName.set(name, (byName.get(name) ?? 0) + 1);
      expectMatchesBaseline(
        label,
        [...byName].map(([name, nodes]) => ({ page: label, ruleId: `b6-focus-obscured: ${name}`, nodes })),
      );
    });
  }
}

// ---------------------------------------------------------------------------
// A venue row scrolls so the focused control is fully in view (B6-F7)
// ---------------------------------------------------------------------------

for (const width of [1280, 375, 320]) {
  // Proves: while tabbing the home page, every focused control inside a sideways-scrolling
  // venue row is FULLY inside the row's visible area, not just "not entirely hidden"
  // (WCAG 2.4.11's bar, and what the check above asks). Chromium does not scroll a nested
  // scroller for a focused element that is already partly visible, and `scroll-snap` undoes a
  // small `scrollIntoView` nudge, so before B6-F7 was fixed every stop in a row's second and
  // later columns stayed partly or almost wholly off-screen (at 320px a link was 5% visible).
  // Expected value: 100% for every stop; the 1px tolerance is sub-pixel layout.
  test(`tabbing keeps the focused control fully inside its venue row @${width}`, async ({ page }) => {
    const screen = SCREENS.find((s) => s.path === "/")!;
    await page.setViewportSize({ width, height: 700 });
    await page.goto("/");
    await screen.ready(page);

    const partlyOutside: string[] = [];
    for (let stop = 0; stop < MAX_STOPS; stop++) {
      await page.keyboard.press("Tab");
      const result = await page.evaluate(() => {
        const el = document.activeElement as HTMLElement | null;
        if (!el || el === document.body) return null; // focus left the page
        // The sideways scroller the control lives in, if any.
        let row: HTMLElement | null = el.parentElement;
        while (row && getComputedStyle(row).overflowX !== "auto") row = row.parentElement;
        if (!row) return { name: "", outside: false };
        const rect = el.getBoundingClientRect();
        const bounds = row.getBoundingClientRect();
        return {
          name: (el.textContent ?? "").trim().slice(0, 40),
          outside: rect.left < bounds.left - 1 || rect.right > bounds.right + 1,
        };
      });
      if (result === null) break;
      if (result.outside) partlyOutside.push(result.name);
    }

    expect(partlyOutside, "focused controls not fully inside their venue row").toEqual([]);
  });
}

// ---------------------------------------------------------------------------
// The filter header, by keyboard alone (2.1.1, 2.1.2, 3.2.1)
// ---------------------------------------------------------------------------

test.describe("the filter header with a keyboard", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("article")).toHaveCount(25);
  });

  // Proves: the Venues combobox can be reached by Tab alone, opened, filtered by typing,
  // chosen from, closed and left, with no mouse (2.1.1), and never traps focus (2.1.2):
  // Escape closes the popup and keeps focus on the input, and Tab moves on. Also 3.2.1:
  // merely FOCUSING a control (landing on it with Tab) changes nothing; the URL stays
  // `/` until a choice is made. Expected values: typing "Zhora" leaves one option,
  // Zhora Darling, venue 3 (lib/fixtures/venues.json), so the URL is `/?venue=3`.
  test("the Venues combobox can be used and left with the keyboard", async ({ page }) => {
    const venues = page.getByLabel("Venues");

    // Tab from the top of the page to the control, like a visitor does.
    for (let stop = 0; stop < 30 && !(await venues.evaluate((el) => el === document.activeElement)); stop++) {
      await page.keyboard.press("Tab");
    }
    await expect(venues).toBeFocused();
    await expect(page).toHaveURL("/"); // 3.2.1: arriving changed nothing

    await page.keyboard.type("Zhora");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL("/?venue=3");

    await page.keyboard.press("Escape");
    await expect(page.getByRole("listbox")).toHaveCount(0);
    await expect(venues).toBeFocused(); // 2.1.2: the popup closed and focus stayed put

    await page.keyboard.press("Tab");
    await expect(venues).not.toBeFocused(); // focus moves on: no trap
  });

  // Proves: a chosen venue can be removed from the keyboard too: Backspace in the empty
  // input removes the last chip, and the calendar returns to unfiltered.
  test("a chosen venue can be removed with the keyboard", async ({ page }) => {
    const venues = page.getByLabel("Venues");
    await venues.focus();
    await page.keyboard.type("Zhora");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL("/?venue=3");
    await page.keyboard.press("Escape");

    await page.keyboard.press("Backspace");

    await expect(page).toHaveURL("/");
    await expect(page.getByRole("button", { name: "Remove Zhora Darling" })).toHaveCount(0);
  });

  // Proves: the Month select can be opened, chosen from and closed with the keyboard
  // (2.1.1). Expected values: its options are "Next four weeks" then the months that have
  // shows; typing "Oct" picks "October 2026" (calendar-months.json), URL `/?month=2026-10`.
  test("the Month select can be used with the keyboard", async ({ page }) => {
    const month = page.getByLabel("Month");
    await month.focus();

    await page.keyboard.press("Enter");
    await expect(page.getByRole("option").first()).toBeVisible();
    await page.keyboard.type("Oct");
    await page.keyboard.press("Enter");

    await expect(page).toHaveURL("/?month=2026-10");
    await expect(page.getByRole("option")).toHaveCount(0);
  });
});

// Proves: a show's link can be followed with Enter, from the keyboard. The first time
// link on the page is show 1 (Mon, Sep 28); focus it as Tab would and press Enter.
test("a show's time link can be followed with Enter", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("article")).toHaveCount(25);

  const link = page.getByRole("article").first().getByRole("link", { name: /show details/ });
  await link.focus();
  await expect(link).toBeFocused();
  await page.keyboard.press("Enter");

  await expect(page).toHaveURL("/show/1");
});
