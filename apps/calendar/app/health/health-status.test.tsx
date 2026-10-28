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
        showDetail={false}
      />,
    );
    expect(screen.getByText(/unavailable/i)).toBeInTheDocument();
    expect(screen.queryByText(/APP_ENV is not set/)).not.toBeInTheDocument();

    rerender(
      <HealthStatus
        health={{ ok: true, message: "up", appEnv: undefined }}
        frontendEnv={{ ok: false, reason: "APP_ENV is not set" }}
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
        showDetail={false}
      />,
    );

    expect(screen.getByText(/unknown/i)).toBeInTheDocument();
  });

  it("still reports the API as down when it is", () => {
    // Proves: adding the environment rows did not change the page's first job.
    render(
      <HealthStatus
        health={{ ok: false, reason: "API answered HTTP 500" }}
        frontendEnv={{ ok: true, value: "prod" }}
        showDetail={false}
      />,
    );

    expect(screen.getByText(/down/)).toBeInTheDocument();
  });
});
