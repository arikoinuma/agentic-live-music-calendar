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
];
