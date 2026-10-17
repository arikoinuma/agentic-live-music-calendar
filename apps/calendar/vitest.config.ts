import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

// Two Vitest "projects", and THE FILE EXTENSION PICKS THE ENVIRONMENT:
//
//  - `*.test.ts`  -> `unit`: the node environment. The pure functions in
//    lib/ (URL parsing, dates, the API client, ...) need no DOM, and running
//    them without one proves they don't secretly use it.
//  - `*.test.tsx` -> `components`: jsdom plus Testing Library. These render
//    real React components and drive them the way a person would (B5).
//
// A test that needs a DOM but is written as `.ts` fails loudly with
// `document is not defined`; rename it to `.tsx`. There is no per-file
// docblock to forget.
//
// `extends: true` makes each project inherit the root `resolve.alias` and
// `oxc` settings below, so both environments import the way app code does.

// Shared by both projects. `@` mirrors tsconfig's "paths": { "@/*": ["./*"] }
// because Vitest doesn't read tsconfig paths itself.
const alias = {
  "@": fileURLToPath(new URL("./", import.meta.url)),
  // `import "server-only"` throws outside Next's react-server condition,
  // which is what Vitest is (B2 plan, "Known gotcha"). Map it to an empty
  // module so server-only files can be unit tested. Next's build never
  // reads this config, so the real guard in the app is unaffected.
  "server-only": fileURLToPath(new URL("./test/server-only-stub.ts", import.meta.url)),
};

export default defineConfig({
  // WITHOUT THIS A `.tsx` TEST CANNOT EVEN BE PARSED ("Unexpected JSX
  // expression"). The app's tsconfig sets `"jsx": "preserve"` because Next
  // compiles JSX itself and wants it left alone; Vite 8 transforms with Oxc,
  // honours that setting, and so leaves the JSX untouched for Node to choke
  // on. Asking for the automatic runtime makes it compile `<A />` to the
  // React 19 JSX calls, with no `import React` in every file (B5 plan,
  // "Checked", fact 1).
  oxc: { jsx: { runtime: "automatic" } },
  resolve: { alias },
  test: {
    projects: [
      {
        extends: true,
        test: {
          name: "unit",
          environment: "node",
          include: ["**/*.test.ts"],
          exclude: ["node_modules", ".next"],
        },
      },
      {
        extends: true,
        test: {
          name: "components",
          environment: "jsdom",
          include: ["**/*.test.tsx"],
          exclude: ["node_modules", ".next"],
          // jest-dom matchers and the between-tests cleanup: see the file.
          setupFiles: ["./test/setup-dom.ts"],
        },
      },
    ],
  },
});
