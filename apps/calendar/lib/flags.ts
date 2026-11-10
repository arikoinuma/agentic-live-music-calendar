/**
 * Feature flags for the Next.js app: the TypeScript half of `apps/api/app/flags.py` (C3.1-D2, C3.1-D17).
 *
 * HOW TO READ THIS
 *   The registry is Python's. `scripts/flags.py --write-ts` (run by `make types`) renders it into
 *   `lib/flag-registry.ts`, and `make contract-check` fails when that file is stale, so the two languages cannot hold
 *   different lists. This file is the reader: the same rules as Python, written out again, and tested against the
 *   same hand-written case table (`lib/flag-cases.json`, read by `app/tests/test_flags.py` and `lib/flags.test.ts`),
 *   so the two implementations of one rule are checked against one set of answers.
 *
 *   * `isEnabled(name, { metro })` is the ONLY way to read a flag in app code. Its `name` is the union of flags the
 *     web code base reads (`WebFlagName`), which is `never` today: no web code reads a flag yet, and a name that
 *     only Python reads does not type-check. The name must be a string literal at the call site; `make flags
 *     ARGS=--check` finds reads by scanning for it (C3.1-D18).
 *   * `createFlagReader(registry, env)` is what the tests drive: the same reader over a registry and an environment
 *     they supply.
 *   * `checkFlagEnvironment(env, registry)` lists what is wrong with the `FLAG_*` variables.
 *
 * THE RULES (identical to Python's, C3.1-D9, C3.1-D10, C3.1-D12)
 *   A flag's variable is `FLAG_` plus its name upper-cased with `.` written `_`; a metro-scoped flag also accepts
 *   `FLAG_<NAME>__<SLUG>`. The value is exactly `true` or `false`. Precedence: metro override, then the
 *   environment's value, then the registry default. An UNSET variable defers to the next level; a SET one never does,
 *   even when it is empty or malformed.
 *
 * WHEN IT THROWS
 *   Only when called, never at import: a guard that threw at import time broke every preview build (the lesson of
 *   `lib/app-env.ts`, C3-D7). `isEnabled` throws if the environment has any problem, or if the name is unknown to
 *   this code base. No `instrumentation.ts` refuses a deploy over a variable nothing reads (C3.1-D19); the status page
 *   reports the problems instead. A change to a variable applies to NEW deployments (Vercel), so a flag changes with a
 *   redeploy, not instantly (Dep-D17).
 *
 * docs/dev/implementations/c3.1-feature-flags.md, C3.1-D2, C3.1-D17, C3.1-D19.
 */

import "server-only";

import { FLAG_REGISTRY, type WebFlagName } from "./flag-registry";

export type Surface = "python" | "web";

// The part of a registry entry the reader needs. The generated registry is `as const`, so its entries are assignable.
export type FlagDef = {
  readonly scope: "environment" | "metro";
  readonly surfaces: readonly Surface[];
  readonly default: boolean;
};
export type Registry = Readonly<Record<string, FlagDef>>;
export type FlagEnv = Readonly<Record<string, string | undefined>>;

const PREFIX = "FLAG_";
// The metro part of an override variable: a metro slug upper-cased with `-` written `_` (C3.1-D10).
const METRO_PART = /^[A-Z][A-Z0-9_]{1,30}[A-Z0-9]$/;

/** A name that is not registered, or that the web code base does not read (C3.1-D8). */
export class UnknownFlagError extends Error {}

/** A flag variable set to something other than `true` or `false` (C3.1-D9). */
export class FlagValueError extends Error {}

export function envKey(name: string): string {
  return PREFIX + name.toUpperCase().replaceAll(".", "_");
}

export function metroKey(name: string, metro: string): string {
  return `${envKey(name)}__${metro.toUpperCase().replaceAll("-", "_")}`;
}

export function parseFlagValue(key: string, raw: string): boolean {
  if (raw === "true") return true;
  if (raw === "false") return false;
  throw new FlagValueError(
    `${key}=${JSON.stringify(raw)} is not a feature flag value: write exactly 'true' or 'false'`,
  );
}

/**
 * The flag's value: metro override, then the environment's value, then the default. Pure: it reads only its arguments.
 * The most specific level that is SET wins (an unset one defers); a set one that is not `true`/`false` throws.
 */
export function resolveValue(
  name: string,
  flag: FlagDef,
  env: FlagEnv,
  metro: string | null | undefined,
): boolean {
  const keys = [envKey(name)];
  if (flag.scope === "metro" && metro != null) keys.unshift(metroKey(name, metro));
  for (const key of keys) {
    const raw = env[key];
    if (raw !== undefined) return parseFlagValue(key, raw);
  }
  return flag.default;
}

/**
 * What is wrong with the `FLAG_*` variables in `env`, as sentences; empty when all is well. One problem per bad
 * variable, in sorted order, with the checks in a fixed order (unregistered, unread here, metro misuse, value): the
 * same as Python's `environment_problems`, which the shared case table checks.
 */
export function checkFlagEnvironment(
  env: FlagEnv,
  registry: Registry = FLAG_REGISTRY,
  surface: Surface = "web",
): string[] {
  const byVariable = new Map(Object.entries(registry).map(([name, flag]) => [envKey(name), { name, flag }]));
  const readable = [...byVariable]
    .filter(([, { flag }]) => flag.surfaces.includes(surface))
    .map(([key]) => key)
    .sort();
  const problems: string[] = [];
  for (const key of Object.keys(env).sort()) {
    const raw = env[key];
    if (!key.startsWith(PREFIX) || raw === undefined) continue;
    // Split at the FIRST `__`: a flag name has none, so what follows is the metro part (C3.1-D6).
    const at = key.indexOf("__");
    const base = at === -1 ? key : key.slice(0, at);
    const metroPart = at === -1 ? null : key.slice(at + 2);
    const entry = byVariable.get(base);
    if (entry === undefined) {
      problems.push(
        `${key} names no registered feature flag; the variables this code base reads: ${JSON.stringify(readable)}`,
      );
      continue;
    }
    if (!entry.flag.surfaces.includes(surface)) {
      problems.push(
        `${key} sets a flag that is read by ${JSON.stringify(entry.flag.surfaces)} only, not by ${surface}; remove it from this service's variables`,
      );
      continue;
    }
    if (metroPart !== null) {
      if (entry.flag.scope !== "metro") {
        problems.push(
          `${key} is a metro override, but ${entry.name} is environment-scoped and takes none`,
        );
        continue;
      }
      if (metroPart.includes("__") || !METRO_PART.test(metroPart)) {
        problems.push(
          `${key} has a malformed metro part ${JSON.stringify(metroPart)}: upper-case letters, digits and single underscores, starting with a letter (a hyphen in a slug is written _)`,
        );
        continue;
      }
    }
    try {
      parseFlagValue(key, raw);
    } catch (err) {
      problems.push(err instanceof Error ? err.message : String(err));
    }
  }
  return problems;
}

/**
 * A reader over `registry` and `env`. Nothing is checked at creation; the first call checks the whole environment
 * and throws if it has any problem (and so does every later call), then looks the name up, throwing
 * `UnknownFlagError` for a name that is unregistered or that `surface` does not read.
 */
export function createFlagReader(
  registry: Registry,
  env: FlagEnv,
  surface: Surface = "web",
): (name: string, options?: { metro?: string | null }) => boolean {
  let problems: string[] | undefined;
  return (name, options) => {
    problems ??= checkFlagEnvironment(env, registry, surface);
    if (problems.length > 0) {
      throw new Error(`feature flag environment is invalid: ${problems.join("; ")}`);
    }
    const flag = registry[name];
    if (flag === undefined) {
      throw new UnknownFlagError(`${JSON.stringify(name)} is not a registered feature flag`);
    }
    if (!flag.surfaces.includes(surface)) {
      throw new UnknownFlagError(
        `${JSON.stringify(name)} is not read by the ${surface} code base (it is read by ${JSON.stringify(flag.surfaces)})`,
      );
    }
    return resolveValue(name, flag, env, options?.metro);
  };
}

/**
 * Whether the feature flag `name` is on, under this server's environment. The only way to read a flag in app code.
 * `metro` is a metro slug (what `lib/site-context.ts` reads from `x-metro-slug`), used for `metro`-scoped flags only.
 */
export function isEnabled(
  name: WebFlagName,
  options?: { metro?: string | null },
): boolean {
  return createFlagReader(FLAG_REGISTRY, process.env)(name, options);
}
