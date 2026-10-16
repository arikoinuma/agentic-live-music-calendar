/**
 * Setup for the `components` Vitest project (jsdom): runs once before each
 * `*.test.tsx` file. Registered in vitest.config.ts.
 *
 * It does two things, each of which is easy to forget and confusing when
 * missing.
 */

// 1. jest-dom's matchers: `toBeInTheDocument()`, `toHaveAttribute()`,
//    `toHaveTextContent()`. Their failure messages print the element and its
//    actual attributes (B5-D4), which a bare `getAttribute()` check
//    doesn't. The `/vitest` entry registers them on Vitest's `expect` and
//    brings their TypeScript types along, so `tsc` accepts them in tests.
import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// 2. Unmount whatever a test rendered. Testing Library normally registers
//    this itself, but only when `afterEach` exists as a global, and this repo
//    doesn't turn on Vitest's globals. Without it every `render()` stacks
//    onto the previous test's DOM, and a query like `getByText("one")`
//    finds two matches in the second test (B5 plan, "Checked", fact 5).
afterEach(() => cleanup());
