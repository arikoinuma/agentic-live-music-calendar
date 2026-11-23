import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HealthStatus } from "./health-status";

// HealthStatus is the synchronous half of the /health page (the page itself is an async Server Component and is
// not unit tested, as the style guide says). Expected strings are written out by hand from the plan
// (c3-environments-and-deploy.md, C3-D6 and C3-D7).

describe("HealthStatus", () => {
  it("shows the frontend's environment and the API's side by side", () => {
    // Proves (C3-D7): both environments are on the page, so a staging frontend reading the production API
    // (a copied API_BASE_URL) is visible instead of hidden behind a green "up".
    render(
      <HealthStatus
        health={{ ok: true, message: "up", appEnv: "prod" }}
        frontendEnv={{ ok: true, value: "staging" }}
        dataAccess={{ state: "not checked" }}
        showDetail={false}
      />,
    );

    expect(screen.getByText("staging")).toBeInTheDocument();
    expect(screen.getByText(/prod/)).toBeInTheDocument();
  });

  it("renders an error line, without throwing, when the frontend's APP_ENV is invalid", () => {
    // Proves (C3-D7): this public status page must not crash because getAppEnv() threw (a missing or
    // mismatched APP_ENV); it says the environment is unavailable. The reason text is for the person running
    // the app, so it appears only when showDetail is true.
    const { rerender } = render(
      <HealthStatus
        health={{ ok: true, message: "up", appEnv: undefined }}
        frontendEnv={{ ok: false, reason: "APP_ENV is not set" }}
        dataAccess={{ state: "not checked" }}
        showDetail={false}
      />,
    );
    expect(screen.getByText(/unavailable/i)).toBeInTheDocument();
    expect(screen.queryByText(/APP_ENV is not set/)).not.toBeInTheDocument();

    rerender(
      <HealthStatus
        health={{ ok: true, message: "up", appEnv: undefined }}
        frontendEnv={{ ok: false, reason: "APP_ENV is not set" }}
        dataAccess={{ state: "not checked" }}
        showDetail
      />,
    );
    expect(screen.getByText(/APP_ENV is not set/)).toBeInTheDocument();
  });

  it("says the API's environment is unknown when an older API does not report one", () => {
    // Proves (C3-D6): an API without `app_env` (the old production API during cutover) reads "unknown", not a
    // blank and not an error.
    render(
      <HealthStatus
        health={{ ok: true, message: "up", appEnv: undefined }}
        frontendEnv={{ ok: true, value: "prod" }}
        dataAccess={{ state: "not checked" }}
        showDetail={false}
      />,
    );

    // Read the value beside the "API environment" label: the feature-flags row (C3.1-D16) also says "unknown" for an
    // API that does not report flags, so a page-wide query would match both.
    expect(screen.getByText("API environment").nextElementSibling).toHaveTextContent("unknown");
  });

  it("still reports the API as down when it is", () => {
    // Proves: adding the environment rows did not change the page's first job.
    render(
      <HealthStatus
        health={{ ok: false, reason: "API answered HTTP 500" }}
        frontendEnv={{ ok: true, value: "prod" }}
        dataAccess={{ state: "not checked" }}
        showDetail={false}
      />,
    );

    expect(screen.getByText(/down/)).toBeInTheDocument();
  });
});

// What the feature-flag row shows (C3.1-T10, C3.1-D16, C3.1-D19). The strings are written out by hand from the plan.
describe("HealthStatus feature flags", () => {
  const ok = (featureFlags?: Record<string, boolean> | null) => ({
    ok: true as const,
    message: "up",
    appEnv: "staging",
    featureFlags,
  });
  const apiFlags = () => screen.getByText("Feature flags (API)").nextElementSibling;

  it("lists each flag as on or off", () => {
    // Proves (C3.1-D16): outside production the page shows the API's effective values, so whoever opens the status
    // page can see whether the cron is armed without the Railway dashboard. A flag that is off must read "off",
    // not be omitted: an absent row and an off flag are different facts.
    render(
      <HealthStatus
        health={ok({ "worker.scheduled_runs": false, "demo.other": true })}
        frontendEnv={{ ok: true, value: "staging" }}
        dataAccess={{ state: "not checked" }}
        showDetail={false}
      />,
    );

    expect(apiFlags()).toHaveTextContent("worker.scheduled_runs: off");
    expect(apiFlags()).toHaveTextContent("demo.other: on");
  });

  it("says the flags are not shown in production when the API hides them", () => {
    // Proves (C3.1-D16): a `null` (production hides its values) reads "not shown in production", which is true and
    // different from "unknown" (an API that cannot say).
    render(
      <HealthStatus health={ok(null)} frontendEnv={{ ok: true, value: "prod" }} dataAccess={{ state: "not checked" }} showDetail={false} />,
    );

    expect(apiFlags()).toHaveTextContent("not shown in production");
  });

  it("says unknown when an older API does not report flags, or the API is down", () => {
    // Proves (C3.1-D16, risk "the cutover"): the new frontend talks to an older API for a while. An absent
    // `feature_flags` is "unknown", never an error and never a blank.
    const { rerender } = render(
      <HealthStatus health={ok(undefined)} frontendEnv={{ ok: true, value: "staging" }} dataAccess={{ state: "not checked" }} showDetail={false} />,
    );
    expect(apiFlags()).toHaveTextContent("unknown");

    rerender(
      <HealthStatus
        health={{ ok: false, reason: "API answered HTTP 500" }}
        frontendEnv={{ ok: true, value: "staging" }}
        dataAccess={{ state: "not checked" }}
        showDetail={false}
      />,
    );
    expect(apiFlags()).toHaveTextContent("unknown");
  });

  it("reports a misconfigured web flag environment, with the detail only when showDetail is set", () => {
    // Proves (C3.1-D19, C3.1-PR1-9): problems with the web side's `FLAG_*` variables appear on the page, but the
    // variable names and values are detail for the person running the app: this page is linked from every footer, so
    // production (`showDetail` false) shows only that something is misconfigured.
    const props = {
      health: ok({}),
      frontendEnv: { ok: true as const, value: "staging" as const },
      dataAccess: { state: "not checked" as const },
      flagProblems: ["FLAG_NOPE names no registered feature flag"],
    };
    const { rerender } = render(<HealthStatus {...props} showDetail={false} />);
    expect(screen.getByText("Feature flags (web)").nextElementSibling).toHaveTextContent("misconfigured");
    expect(screen.queryByText(/FLAG_NOPE/)).not.toBeInTheDocument();

    rerender(<HealthStatus {...props} showDetail />);
    expect(screen.getByText(/FLAG_NOPE names no registered feature flag/)).toBeInTheDocument();
  });

  it("shows no web-flag row when there is nothing wrong", () => {
    // Proves (C3.1-D19): with no web flag today and a clean environment, the page gains only the API row.
    render(<HealthStatus health={ok({})} frontendEnv={{ ok: true, value: "staging" }} dataAccess={{ state: "not checked" }} showDetail />);

    expect(screen.queryByText("Feature flags (web)")).not.toBeInTheDocument();
  });
  // --- the "API data access" row (C10-D3, C10-T16) ---------------------------------------------------------------

  const dataAccessRow = () => screen.getByText("API data access").nextElementSibling;

  it.each([
    [{ state: "ok" as const }, /ok/i],
    [{ state: "refused" as const }, /refused/i],
    [{ state: "unavailable" as const, reason: "API request timed out after 5000ms" }, /unavailable/i],
    [{ state: "not checked" as const }, /not checked/i],
  ])("renders the data-access row's %j state", (dataAccess, words) => {
    // Proves (C10-T16, C10-D3): each of the row's four states has its own words. "refused" is the one that matters: it
    // is how a Vercel value that disagrees with Railway's shows up, and it must not read as "the API is down" (a
    // refusal means the API answered).
    render(
      <HealthStatus
        health={ok({})}
        frontendEnv={{ ok: true, value: "staging" }}
        dataAccess={dataAccess}
        showDetail={false}
      />,
    );
    expect(dataAccessRow()).toHaveTextContent(words);
  });

  it("shows the data-access reason only when showDetail is set", () => {
    // Proves (C10-T16, C10-D3): the reason text (a timeout, an HTTP status) is for the person running the app, as the
    // API row's is: the page is linked from every footer, so a stranger sees the state word and not the reason.
    const dataAccess = { state: "unavailable" as const, reason: "API answered HTTP 503" };
    const { rerender } = render(
      <HealthStatus
        health={ok({})}
        frontendEnv={{ ok: true, value: "staging" }}
        dataAccess={dataAccess}
        showDetail={false}
      />,
    );
    expect(screen.queryByText(/API answered HTTP 503/)).not.toBeInTheDocument();

    rerender(
      <HealthStatus
        health={ok({})}
        frontendEnv={{ ok: true, value: "staging" }}
        dataAccess={dataAccess}
        showDetail
      />,
    );
    expect(screen.getByText(/API answered HTTP 503/)).toBeInTheDocument();
  });
});
