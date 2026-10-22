import { nextJsConfig } from "@repo/eslint-config/next-js";

/** @type {import("eslint").Linter.Config[]} */
export default [
  ...nextJsConfig,
  {
    // The Playwright support scripts are plain Node (`.mjs`). The shared config gives
    // `.mjs` files only the service-worker globals, so `process` would be `no-undef`.
    files: ["e2e/**/*.mjs"],
    languageOptions: { globals: { process: "readonly" } },
  },
  {
    // Playwright fixtures receive a callback named `use` (`async ({ page }, use) => { ... }`).
    // eslint-plugin-react-hooks takes any function called `use` for React's `use()` hook
    // and objects to it. It is not React code; the rule has nothing to say about e2e/.
    files: ["e2e/**/*.ts"],
    rules: { "react-hooks/rules-of-hooks": "off" },
  },
];
