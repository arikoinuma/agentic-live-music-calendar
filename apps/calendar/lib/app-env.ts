/**
 * Which environment this Next.js server believes it is in, validated against where Vercel says it is running.
 *
 * `APP_ENV` is one of local | dev | staging | prod (C3-D3), the same four values as the API's setting. C4's
 * `proxy.ts` will key its non-production gate on this, and a gate that read an unvalidated string would fail
 * open on a typo (`prodution`) or on a `prod` copied onto a preview. So `getAppEnv()` checks the value, then
 * cross-checks it with the variables Vercel sets itself and that cannot be copied between environments:
 *
 *   VERCEL_ENV=production              <-> prod
 *   VERCEL_ENV=preview, branch `dev`   <-> dev
 *   VERCEL_ENV=preview, any other      <-> staging   (`main` and every PR branch: C3-PR1-1, matching C3-D11)
 *   VERCEL_ENV absent (a laptop, or any host that is not Vercel) -> no cross-check
 *   `local` is refused wherever Vercel says it is deployed.
 *
 * It THROWS on a missing or inconsistent value, but only when CALLED, never at import. A guard that threw at
 * import time is exactly what broke every preview build (plan context: a missing `API_BASE_URL` threw before the
 * fetch that marks a route dynamic), so the caller decides what an error means: the status page catches it and
 * shows it; C4's gate will refuse the request.
 *
 * `env` is a parameter so tests pass a plain object; callers use the default, `process.env`.
 *
 * docs/dev/implementations/c3-environments-and-deploy.md, C3-D7, C3-PR1-1.
 */

import "server-only";

export const APP_ENVS = ["local", "dev", "staging", "prod"] as const;
export type AppEnv = (typeof APP_ENVS)[number];

type Env = Record<string, string | undefined>;

function isAppEnv(value: string | undefined): value is AppEnv {
  return (APP_ENVS as readonly string[]).includes(value ?? "");
}

export function getAppEnv(env: Env = process.env): AppEnv {
  const value = env.APP_ENV;
  if (!isAppEnv(value)) {
    throw new Error(
      `APP_ENV must be one of ${APP_ENVS.join(", ")}; got ${value === undefined ? "nothing" : JSON.stringify(value)}`,
    );
  }

  const platform = env.VERCEL_ENV;
  // Not on Vercel (or `vercel dev`, which reports "development"): nothing to cross-check against.
  if (platform === undefined || platform === "" || platform === "development") return value;

  // What Vercel says this deployment is, in our words.
  const branch = env.VERCEL_GIT_COMMIT_REF ?? "";
  const actual: AppEnv =
    platform === "production" ? "prod" : branch === "dev" ? "dev" : "staging";

  if (value !== actual) {
    throw new Error(
      `APP_ENV=${value} but Vercel reports a ${platform} deployment${platform === "preview" ? ` of branch ${JSON.stringify(branch)}` : ""}, which is ${actual}`,
    );
  }
  return value;
}
