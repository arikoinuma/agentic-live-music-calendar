/**
 * API liveness check for the /health diagnostics page.
 *
 * Returns a value instead of throwing. The template's inline version
 * let any failure (API down, bad JSON, unset env var) escape into the
 * page render, which made the diagnostics page the first thing to
 * crash when something was wrong — the opposite of its job. A
 * discriminated union makes the page handle both branches because
 * TypeScript won't let it read `.message` without checking `ok`.
 *
 * `fetchImpl` is a parameter so tests can pass a fake; production
 * callers omit it and get the real fetch.
 */

import { apiUrl } from "./api-url";

// `appEnv` is the environment the API says it is in (C3-D6). Optional: an API deployed before C3 reports only
// `message`, and during the cutover the new frontend talks to that older API for a while. Absence means "unknown",
// not failure.
export type ApiHealth =
  | { ok: true; message: string; appEnv: string | undefined }
  | { ok: false; reason: string };

// Diagnostics should answer quickly even when the API is hung. Without
// a timeout a stuck backend would hold the page open until the platform
// kills the request.
const TIMEOUT_MS = 3000;

export async function getApiHealth(
  baseUrl: string | undefined,
  fetchImpl: typeof fetch = fetch,
): Promise<ApiHealth> {
  if (!baseUrl) {
    return {
      ok: false,
      reason: "API_BASE_URL is not set (see apps/calendar/.env.local)",
    };
  }

  let response: Response;
  try {
    // `cache: "no-store"` is explicit rather than relying on the
    // default: a health check that returns a cached "up" is worse than
    // none. (fetch is uncached by default since Next 15, but the intent
    // belongs at the call site.)
    // apiUrl strips trailing slashes from the base (lib/api-url.ts).
    response = await fetchImpl(apiUrl(baseUrl, "/health"), {
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch (err) {
    return { ok: false, reason: failureReason("request failed", err) };
  }

  if (!response.ok) {
    return { ok: false, reason: `API answered HTTP ${response.status}` };
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch (err) {
    // The timeout signal also covers reading the body, so headers
    // arriving and then stalling surfaces here as a TimeoutError — not
    // as bad JSON. Tell the two apart.
    return {
      ok: false,
      reason: isTimeout(err)
        ? failureReason("reading the response", err)
        : "API response was not valid JSON",
    };
  }

  // Narrow `unknown` by hand. A schema library (Zod) is deferred until
  // the edit forms need it (api-contract.md §7); one string field
  // doesn't justify it.
  if (
    typeof body === "object" &&
    body !== null &&
    "message" in body &&
    typeof body.message === "string"
  ) {
    // `app_env` is read by hand like `message`; anything that is not a string is dropped, not rendered.
    const appEnv =
      "app_env" in body && typeof body.app_env === "string"
        ? body.app_env
        : undefined;
    return { ok: true, message: body.message, appEnv };
  }
  return { ok: false, reason: "API response had no string `message`" };
}

// `AbortSignal.timeout()` aborts with a DOMException named "TimeoutError".
// (A manual `controller.abort()` would be "AbortError"; we don't use one.)
function isTimeout(err: unknown): boolean {
  return err instanceof DOMException && err.name === "TimeoutError";
}

function failureReason(stage: string, err: unknown): string {
  if (isTimeout(err)) return `${stage}: timed out after ${TIMEOUT_MS}ms`;
  return `${stage}: ${err instanceof Error ? err.message : String(err)}`;
}
