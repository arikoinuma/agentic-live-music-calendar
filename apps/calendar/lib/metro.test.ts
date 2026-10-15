import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import { FALLBACK_DESCRIPTION, getMetroOrNull, siteDescription } from "./metro";
import metro from "./fixtures/metro.json";

afterEach(() => vi.restoreAllMocks());

// --- getMetroOrNull-------------------------------------------------

describe("getMetroOrNull", () => {
  it("returns the metro when the fetch succeeds", async () => {
    // Proves: the safety net is transparent when nothing is wrong: the layout gets the real metro back.
    expect(await getMetroOrNull(async () => metro)).toEqual(metro);
  });

  it("returns null for an ApiError, and logs it instead of swallowing it silently", async () => {
    // Proves: every page renders the root layout, so a metro outage must
    // not take the whole shell down. The log is what makes the failure
    // findable afterwards.
    const log = vi.spyOn(console, "error").mockImplementation(() => {});
    const result = await getMetroOrNull(async () => {
      throw new ApiError("API down", { path: "/metro" });
    });
    expect(result).toBeNull();
    expect(log).toHaveBeenCalled();
  });

  it("rethrows Next's dynamic-usage signal unchanged", async () => {
    // Proves: a bare `catch { return null }` also swallows the error a
    // no-store fetch throws during `next build` to mark a route dynamic,
    // which turns a working build into a failing one (plan review #1).
    // That mistake passes the two tests above, so this one is the point.
    const signal = Object.assign(new Error("Dynamic server usage"), {
      digest: "DYNAMIC_SERVER_USAGE",
    });
    await expect(
      getMetroOrNull(async () => {
        throw signal;
      }),
    ).rejects.toBe(signal);
  });
});

// --- siteDescription -----------------------------------------------------------

describe("siteDescription", () => {
  it("names the metro when there is one", () => {
    // Proves: the page description names the metro it was given, so "Minneapolis/St. Paul" comes from the API
    // rather than a literal (G24).
    expect(siteDescription(metro)).toContain(metro.name);
  });

  it("falls back to the generic description when the metro is unavailable", () => {
    // Proves: the page <meta description> never contains "null". The
    // constant is exported so Verification 3 can grep the built HTML for
    // it (a static page with the fallback baked in is the D1 failure).
    expect(siteDescription(null)).toBe(FALLBACK_DESCRIPTION);
  });
});
