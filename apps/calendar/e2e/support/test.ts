/**
 * The `test` and `expect` every spec imports, from one place.
 *
 * Specs import from here rather than from `@playwright/test` so that fixtures
 * added later (the delay proxy's reset, Step 4 of the B6 plan) reach every test
 * without editing each file. For now it is a plain re-export.
 */
export { expect, test } from "@playwright/test";
