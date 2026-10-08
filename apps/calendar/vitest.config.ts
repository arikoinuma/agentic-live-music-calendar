import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

// Node environment on purpose: B1's tests cover plain functions only.
// jsdom + @testing-library/react arrive in B5 with the first component
// tests (v1-build-plan.md B5). Adding them now would be setup with no
// consumer — the same deferral rule the rest of this repo follows.
export default defineConfig({
  resolve: {
    // Mirrors tsconfig's "paths": { "@/*": ["./*"] } so tests import the
    // same way app code does. Vitest doesn't read tsconfig paths itself.
    alias: { "@": fileURLToPath(new URL("./", import.meta.url)) },
  },
  test: {
    include: ["**/*.test.ts", "**/*.test.tsx"],
    exclude: ["node_modules", ".next"],
  },
});
