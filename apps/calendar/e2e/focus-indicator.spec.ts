/**
 * How visible is keyboard focus, and how visible are the controls' own borders?
 * (WCAG 2.2 success criterion 1.4.11, Non-text Contrast; B6 plan, Step 6 and findings
 * B6-F3 and B6-F6.)
 *
 * axe has no rule for either, so this measures what the browser actually PAINTS, from
 * screenshots, and reports a finding through the same ratchet baseline as the axe scans.
 * The first describe block proves the measuring method itself on pages built to be
 * right and wrong; the second applies it to the app.
 */
import { contrastRatio } from "./support/contrast";
import { expectMatchesBaseline } from "./support/a11y";
import { measureControlBorder, measureFocusIndicator } from "./support/focus";
import { expect, test } from "./support/test";

test.describe("the measuring method, on pages built for the purpose", () => {
  // A white page with one button whose focus style is the variable under test.
  const withFocusStyle = (css: string) =>
    `<body style="margin:0;background:#fff;padding:24px"><button id="b" style="margin:12px;padding:6px 12px">Button</button>
     <style>#b:focus{${css}}</style></body>`;

  // Proves: a strong indicator is measured as strong. A 3px black outline on white is the
  // maximum contrast there is; if the method reported anything near 3:1 or less for it,
  // every measurement below would be untrustworthy. Expected value: black on white is
  // 21:1 by the WCAG definition, and the anti-aliased edge may take it a hair under.
  test("reads a black outline as maximum contrast", async ({ page }) => {
    await page.setContent(withFocusStyle("outline:3px solid #000;outline-offset:2px"));
    const { changedPixels, ratio } = await measureFocusIndicator(page, page.locator("#b"));

    expect(changedPixels).toBeGreaterThan(0);
    expect(ratio).toBeGreaterThan(20);
  });

  // Proves: a control with NO focus style is measured as having no indicator at all: zero
  // changed pixels, ratio 1. The failure mode a design can fall into is invisible focus,
  // and this is how it shows up.
  test("reads a control with no focus style as nothing", async ({ page }) => {
    await page.setContent(withFocusStyle("outline:none"));
    const { changedPixels, ratio } = await measureFocusIndicator(page, page.locator("#b"));

    expect(changedPixels).toBe(0);
    expect(ratio).toBe(1);
  });

  // Proves: a faint indicator is measured as faint, below the 3:1 line. Expected value:
  // #ccc on white is 1.6:1 by the WCAG formula (luminance of #ccc is about 0.60).
  test("reads a pale grey outline as low contrast", async ({ page }) => {
    await page.setContent(withFocusStyle("outline:3px solid #ccc;outline-offset:2px"));
    const { ratio } = await measureFocusIndicator(page, page.locator("#b"));

    expect(ratio).toBeCloseTo(1.6, 1);
    expect(ratio).toBeLessThan(3);
  });

  // Proves: the control-border measurement sees a border and reports its contrast. Expected
  // value: a #767676 border on white is 4.54:1 (the published lightest passing grey).
  test("reads an unfocused control's border", async ({ page }) => {
    await page.setContent(
      `<body style="margin:0;background:#fff;padding:24px"><button id="b" style="margin:12px;padding:6px 12px;border:2px solid #767676;background:#fff">Button</button></body>`,
    );

    expect(await measureControlBorder(page, page.locator("#b"))).toBeCloseTo(contrastRatio([0x76, 0x76, 0x76], [255, 255, 255]), 1);
  });
});

test.describe("the app's focus indicators and control borders", () => {
  // WCAG 1.4.11 asks 3:1 of the visual information that identifies a focused component and
  // of a control's boundary. Each target is something a keyboard user lands on.
  const MIN = 3;

  // Proves: the painted focus indicator of every kind of focusable control in the app, and
  // the borders of its two form controls, are held to the baseline. Today several fall
  // below 3:1 (findings B6-F3 and B6-F6); the baseline records how many, so a NEW control
  // with a faint ring, or a fix that is not yet recorded, fails here. Values are printed so
  // the implementation log can quote them.
  test("measured focus indicators and borders match the baseline", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/");
    await expect(page.getByRole("article")).toHaveCount(25);

    const indicators: [string, () => Promise<{ changedPixels: number; ratio: number }>][] = [
      ["artist link", () => measureFocusIndicator(page, page.getByRole("article").first().getByRole("link", { name: "Charlie Parr" }))],
      ["nav link", () => measureFocusIndicator(page, page.getByRole("link", { name: "Venues", exact: true }).first())],
      ["date heading link", () => measureFocusIndicator(page, page.getByRole("link", { name: "Mon, Sep 28" }))],
      [
        "Venues combobox",
        // The ring is drawn by the box around the input, while the input holds focus.
        () => measureFocusIndicator(page, page.getByLabel("Venues"), page.getByLabel("Venues").locator("xpath=..")),
      ],
      ["Month select", () => measureFocusIndicator(page, page.getByLabel("Month"))],
    ];
    const measured: { name: string; ratio: number; changedPixels: number }[] = [];
    for (const [name, measure] of indicators) measured.push({ name, ...(await measure()) });

    // "Clear filters" exists only on a filtered page.
    await page.goto("/?venue=1");
    await expect(page.getByRole("link", { name: "Clear filters" })).toBeVisible();
    measured.push({
      name: "Clear filters link",
      ...(await measureFocusIndicator(page, page.getByRole("link", { name: "Clear filters" }))),
    });

    await page.goto("/");
    await expect(page.getByRole("article")).toHaveCount(25);
    const borders = [
      { name: "Venues box border", ratio: await measureControlBorder(page, page.getByLabel("Venues").locator("xpath=..")) },
      { name: "Month select border", ratio: await measureControlBorder(page, page.getByLabel("Month")) },
    ];

    for (const m of measured) console.log(`FOCUS ${m.name}: ${m.ratio.toFixed(2)}:1 (${m.changedPixels} pixels changed)`);
    for (const b of borders) console.log(`BORDER ${b.name}: ${b.ratio.toFixed(2)}:1`);
    await test.info().attach("focus and border measurements", {
      body: JSON.stringify({ focus: measured, borders }, null, 2),
      contentType: "application/json",
    });

    // A focus indicator that paints nothing at all is its own failure, whatever the ratio.
    for (const m of measured) expect(m.changedPixels, `${m.name} paints no focus indicator`).toBeGreaterThan(0);

    const label = "focus indicators and borders @1280";
    expectMatchesBaseline(label, [
      { page: label, ruleId: "b6-focus-indicator-3to1", nodes: measured.filter((m) => m.ratio < MIN).length },
      { page: label, ruleId: "b6-control-border-3to1", nodes: borders.filter((b) => b.ratio < MIN).length },
    ].filter((f) => f.nodes > 0));
  });
});
