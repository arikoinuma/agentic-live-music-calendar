/**
 * Where the end-to-end stack listens (B6 plan, "The stack").
 *
 * Three servers, started by `playwright.config.ts`, each on its own port so a
 * running `make dev` (3000 and 8000) is never reused and never collides:
 *
 *   browser -> Next (3100) -> delay proxy (8102) -> FastAPI (8101)
 *
 * The browser talks only to Next. Next's Server Components make the API calls,
 * which is why the proxy sits between Next and the API and not in the browser:
 * a browser-side `page.route` cannot see a request the Next SERVER makes.
 */
export const API_PORT = 8101;
export const PROXY_PORT = 8102;
export const WEB_PORT = 3100;

// 127.0.0.1, not "localhost": on some machines "localhost" resolves to ::1 first
// and the servers below listen on IPv4 only, which shows up as a slow, flaky start.
export const API_URL = `http://127.0.0.1:${API_PORT}`;
export const PROXY_URL = `http://127.0.0.1:${PROXY_PORT}`;
export const WEB_URL = `http://127.0.0.1:${WEB_PORT}`;

// The shared secret the e2e stack runs its API and its Next server with (C10-D12). The API refuses a call without it,
// so the 107 journeys passing is the proof that the calendar still renders with the guard on, on every pull request.
// It is a fixed, obviously fake value and not a secret: it protects a throwaway database on a port only this stack
// opens. It is 32+ characters only so it looks like what a hosted secret must be (C10-D9), though `APP_ENV=local`
// does not require that.
export const E2E_API_SECRET = "e2e-only-shared-secret-not-a-real-one-0123456789";
