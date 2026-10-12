import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

// Node environment on purpose: the tests cover plain functions only.
// jsdom + @testing-library/react arrive in B5 with the first component
// tests (v1-build-plan.md B5). Adding them now would be setup with no
// consumer — the same deferral rule the rest of this repo follows.
export default defineConfig({
  resolve: {
    alias: {
      // Mirrors tsconfig's "paths": { "@/*": ["./*"] } so tests import the
      // same way app code does. Vitest doesn't read tsconfig paths itself.
      "@": fileURLToPath(new URL("./", import.meta.url)),
      // `import "server-only"` throws outside Next's react-server
      // condition, which is what Vitest is (B2 plan, "Known gotcha").
      // Map it to an empty module so server-only files can be unit
      // tested. Next's build never reads this config, so the real guard
      // in the app is unaffected.
      "server-only": fileURLToPath(
        new URL("./test/server-only-stub.ts", import.meta.url),
      ),
    },
  },
  test: {
    include: ["**/*.test.ts", "**/*.test.tsx"],
    exclude: ["node_modules", ".next"],
  },
});
