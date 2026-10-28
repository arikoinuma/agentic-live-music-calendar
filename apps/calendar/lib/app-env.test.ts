import { describe, expect, it, vi } from "vitest";
import { getAppEnv } from "./app-env";

// getAppEnv takes the environment as a parameter (like getApiHealth takes fetch), so no test touches the real
// process.env. Expected values are written out by hand from the plan's rule (c3-environments-and-deploy.md,
// C3-D7), not derived from the function.

const preview = (ref: string) => ({ VERCEL_ENV: "preview", VERCEL_GIT_COMMIT_REF: ref });
const production = { VERCEL_ENV: "production", VERCEL_GIT_COMMIT_REF: "production" };

describe("getAppEnv", () => {
  it.each(["local", "dev", "staging", "prod"] as const)(
    "returns %s when nothing on the platform contradicts it",
    (value) => {
      // Proves (C3-D7): each of the four values is accepted when the platform variables are absent, which is
      // the case on a laptop and on any host that is not Vercel. The cross-check applies only where Vercel has
      // told us where we are.
      expect(getAppEnv({ APP_ENV: value })).toBe(value);
    },
  );

  it.each([[undefined], [""], ["prodution"], ["PROD"], ["production"]])(
    "throws for a missing or invalid APP_ENV (%s)",
    (value) => {
      // Proves (C3-D7): a typo or an unset variable is an error, not a default. A gate that read an unvalidated
      // string would fail open on `prodution`. Note "production" is refused: Vercel's word for it is not ours.
      expect(() => getAppEnv({ APP_ENV: value })).toThrow(/APP_ENV/);
    },
  );

  describe("the platform cross-check", () => {
    it("accepts prod on a production deployment, and refuses it anywhere else", () => {
      // Proves (C3-D7): `prod` is real only on Vercel's Production environment. A `prod` copied onto a preview
      // would skip C4's gate on a copy of staging.
      expect(getAppEnv({ APP_ENV: "prod", ...production })).toBe("prod");
      expect(() => getAppEnv({ APP_ENV: "prod", ...preview("main") })).toThrow(/prod/);
    });

    it.each([["main"], ["c3-env-deploy"], ["staging"]])(
      "accepts staging on a preview of %s",
      (ref) => {
        // Proves (C3-PR1-1): `staging` is any preview that is not the dev lane, `main` and every PR branch
        // included, matching C3-D11 (Preview variables default to staging for all branches). Without the PR-branch
        // case every PR preview would throw.
        expect(getAppEnv({ APP_ENV: "staging", ...preview(ref) })).toBe("staging");
      },
    );

    it("refuses staging on production and on a preview of dev", () => {
      // Proves (C3-D7): staging on the production deployment is the "copied variable" mistake; staging on the
      // dev branch means the dev override is missing.
      expect(() => getAppEnv({ APP_ENV: "staging", ...production })).toThrow(/staging/);
      expect(() => getAppEnv({ APP_ENV: "staging", ...preview("dev") })).toThrow(/staging/);
    });

    it("accepts dev only on a preview of dev", () => {
      // Proves (C3-D7): `dev` means the dev lane's preview and nothing else.
      expect(getAppEnv({ APP_ENV: "dev", ...preview("dev") })).toBe("dev");
      expect(() => getAppEnv({ APP_ENV: "dev", ...preview("main") })).toThrow(/dev/);
      expect(() => getAppEnv({ APP_ENV: "dev", ...production })).toThrow(/dev/);
    });

    it("refuses local on Vercel", () => {
      // Proves (C3-D7): `local` on a deployed build is a leftover from a copied .env, not a place.
      expect(() => getAppEnv({ APP_ENV: "local", ...production })).toThrow(/local/);
      expect(() => getAppEnv({ APP_ENV: "local", ...preview("main") })).toThrow(/local/);
    });
  });

  it("does nothing at import time", async () => {
    // Proves (C3-D7): importing the module never reads or validates APP_ENV, so a missing variable cannot fail
    // a build or a prerender (the Preview failure in the plan's context: a guard that threw at import broke
    // every build). Only calling getAppEnv can throw. The module is imported fresh with APP_ENV removed.
    const saved = process.env.APP_ENV;
    delete process.env.APP_ENV;
    vi.resetModules();
    try {
      await expect(import("./app-env")).resolves.toBeDefined();
    } finally {
      if (saved !== undefined) process.env.APP_ENV = saved;
    }
  });
});
