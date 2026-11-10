import { afterEach, describe, expect, it, vi } from "vitest";
import cases from "./flag-cases.json";
import { FLAG_REGISTRY } from "./flag-registry";
import {
  UnknownFlagError,
  checkFlagEnvironment,
  createFlagReader,
  envKey,
  isEnabled,
  metroKey,
  parseFlagValue,
  resolveValue,
  type Registry,
  type Surface,
} from "./flags";

// The TypeScript twin of apps/api/app/tests/test_flags.py (C3.1-T9). Both read `flag-cases.json`, hand-written from
// C3.1-D9 (values), C3.1-D10 (precedence, the metro override) and C3.1-D12 (startup problems), so the two languages
// are checked against one set of answers instead of each against its own reading of the rule. The table's own `flags`
// section is the registry here: the generated one holds a single Python-only flag. No expectation below is computed by
// the code under test.

const REGISTRY: Registry = Object.fromEntries(
  cases.flags.map((flag) => [
    flag.name,
    { scope: flag.scope, surfaces: flag.surfaces, default: flag.default },
  ]),
) as Registry;

type Expect = boolean | "unknown" | { error: string };

describe("the shared resolution table", () => {
  it.each(cases.resolution)("$id", (row) => {
    // Proves (C3.1-T9, C3.1-D9, C3.1-D10): the most specific level that is SET wins (metro override, then the
    // environment's value, then the default); an UNSET level defers; a SET level that is not `true`/`false` throws
    // and does not fall through; an override is looked up only for a `metro`-scoped flag and only when a metro is
    // given. The same file drives the Python twin. Mutations M6 (an empty string read as unset) and M7 (the
    // environment checked before the override) turn named rows red.
    const expectation = row.expect as Expect;
    const flag = REGISTRY[row.flag];
    if (flag === undefined) throw new Error(`the case table names an unknown flag ${row.flag}`);
    const run = () => resolveValue(row.flag, flag, row.environ, row.metro);
    if (typeof expectation === "object") {
      expect(run).toThrow(expectation.error);
    } else {
      expect(run()).toBe(expectation);
    }
  });
});

describe("reading through a reader", () => {
  it.each(cases.read)("$id", (row) => {
    // Proves (C3.1-T9, C3.1-D6, C3.1-D8): a name that is unregistered, or registered but not read by this code
    // base, throws `UnknownFlagError` at the call instead of answering `false`; a readable one resolves with the
    // metro passed through. The `surface` argument lets the Python-only rows run here.
    const read = createFlagReader(REGISTRY, row.environ, row.surface as Surface);
    if (row.expect === "unknown") {
      expect(() => read(row.name, { metro: row.metro })).toThrow(UnknownFlagError);
    } else {
      expect(read(row.name, { metro: row.metro })).toBe(row.expect);
    }
  });

  it("does not check the environment until a flag is read", () => {
    // Proves (C3.1-D19): creating a reader over a bad environment does not throw; the first call does. A guard that
    // threw at creation (import time, for the module-level `isEnabled`) would break every build that never reads a flag.
    expect(() => createFlagReader(REGISTRY, { FLAG_NOPE: "true" })).not.toThrow();
    const read = createFlagReader(REGISTRY, { FLAG_NOPE: "true" });
    expect(() => read("demo.web_only")).toThrow("FLAG_NOPE");
    // ...and keeps throwing: the environment does not change under a running server.
    expect(() => read("demo.web_only")).toThrow("FLAG_NOPE");
  });
});

describe("the shared startup table", () => {
  it.each(cases.startup)("$id", (row) => {
    // Proves (C3.1-T9, C3.1-D12): each bad variable is one problem, in sorted variable order, naming the strings the
    // table lists (the variable, and for an unregistered one the variables this code base reads); variables that
    // merely start like one are ignored. Mutation M8 (the unregistered check deleted) turns the FLAG_NOPE row red.
    const problems = checkFlagEnvironment(row.environ, REGISTRY, row.surface as Surface);
    expect(problems).toHaveLength(row.problems.length);
    row.problems.forEach((needles, index) => {
      for (const needle of needles) expect(problems[index]).toContain(needle);
    });
  });
});

describe("names and values", () => {
  it("writes the variable names as the plan does", () => {
    // Proves (C3.1-D6, C3.1-D10): `.` becomes `_`, the name is upper-cased, a metro slug's hyphen becomes `_` after
    // a double underscore. Literals are the same ones the Python test asserts.
    expect(envKey("worker.scheduled_runs")).toBe("FLAG_WORKER_SCHEDULED_RUNS");
    expect(metroKey("worker.scheduled_runs", "msp")).toBe("FLAG_WORKER_SCHEDULED_RUNS__MSP");
    expect(metroKey("demo.scoped", "new-york")).toBe("FLAG_DEMO_SCOPED__NEW_YORK");
  });

  it.each(["", "True", "FALSE", "1", "0", "yes", "no", " true", "true "])(
    "refuses %j as a value",
    (raw) => {
      // Proves (C3.1-D9): no lenient spelling is accepted, including the empty string and surrounding spaces.
      expect(() => parseFlagValue("FLAG_X", raw)).toThrow("FLAG_X");
    },
  );
});

describe("the generated registry and isEnabled", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("holds the Python flag, readable by Python only", () => {
    // Proves (C3.1-D8, C3.1-D17): the generated file carries the one registered flag with the surfaces Python
    // declares. `make contract-check` is what keeps it current; this pins what it currently says.
    expect(FLAG_REGISTRY["worker.scheduled_runs"]).toEqual({
      scope: "environment",
      surfaces: ["python"],
      default: false,
    });
  });

  it("does not accept a name only Python reads, at compile time or at run time", () => {
    // Proves (C3.1-D8, C3.1-D17): `WebFlagName` is `never` while no flag has the web surface, so naming the Python
    // flag is a type error (the expect-error line fails `check-types` if it ever stops being one, which is how
    // deleting it is caught), and at run time the reader refuses it as unknown to the web.
    // @ts-expect-error "worker.scheduled_runs" is Python-only, so it is not a WebFlagName
    expect(() => isEnabled("worker.scheduled_runs")).toThrow(UnknownFlagError);
  });

  it("throws on a bad flag environment only when called, never at import", async () => {
    // Proves (C3.1-D19, C3.1-CR1-4): importing the module with a malformed `FLAG_*` variable already in the environment
    // does not throw, and calling `isEnabled` does, naming the variable, so the status page and callers decide what an
    // error means. Same shape as `getAppEnv()` (C3-D7). The variable is stubbed BEFORE a fresh import
    // (`vi.resetModules` drops the copy imported at the top of this file), so a module-level check such as
    // `checkFlagEnvironment(process.env)` at the top of `lib/flags.ts` would fail the import here.
    vi.stubEnv("FLAG_NOPE", "true");
    vi.resetModules();
    const fresh = await import("./flags");
    // @ts-expect-error no web flag exists yet, so no name type-checks
    expect(() => fresh.isEnabled("worker.scheduled_runs")).toThrow("FLAG_NOPE");
  });
});
