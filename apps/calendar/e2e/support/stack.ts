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
