/**
 * A proxy between the Next server and the FastAPI app, with controls for tests.
 *
 *   node delay-proxy.mjs <listen port> <upstream port>
 *
 * By default it forwards every request unchanged. A test can make the API slow or
 * broken, which is the only way a browser test can SEE the states that last a few
 * milliseconds against a fast API: the loading skeleton and the "Updating…" busy
 * state. The delay has to live here, between Next and the API, because the API is
 * called by Next's SERVER, which a browser-side `page.route` cannot see.
 *
 *   POST /__delay/<ms>   answer every API request after <ms> milliseconds
 *   POST /__fail         answer every API request with 502 (an API outage)
 *   POST /__reset        back to a plain pass-through
 *
 * The mode is GLOBAL state, one setting for the whole proxy, which is why the suite
 * runs one worker (playwright.config.ts) and why `e2e/support/test.ts` resets it
 * after every test, pass or fail. Test infrastructure only; plain Node, no dependencies.
 */
import http from "node:http";

const [listenPort, upstreamPort] = process.argv.slice(2).map(Number);

// The longest delay a control request may ask for. Tests use a few seconds at most; the cap exists
// so a mistyped or hostile `/__delay/<ms>` cannot park every request on a timer for hours (the
// proxy listens on 127.0.0.1 only, but CodeQL rightly flags a timer whose duration comes straight
// from a request URL).
const MAX_DELAY_MS = 30_000;

let delayMs = 0;
let failing = false;

http
  .createServer((req, res) => {
    // The control endpoints. POST only, so a stray GET (a browser, a health check)
    // cannot flip the mode.
    if (req.method === "POST" && req.url?.startsWith("/__")) {
      const delay = req.url.match(/^\/__delay\/(\d+)$/);
      if (delay) {
        delayMs = Math.min(Number(delay[1]), MAX_DELAY_MS);
        failing = false;
      } else if (req.url === "/__fail") {
        failing = true;
      } else if (req.url === "/__reset") {
        delayMs = 0;
        failing = false;
      } else {
        res.statusCode = 404;
        res.end();
        return;
      }
      res.end("ok");
      return;
    }

    if (failing) {
      res.statusCode = 502;
      res.end();
      return;
    }

    // The delay applies to the whole request, before it is forwarded.
    setTimeout(() => {
      const upstream = http.request(
        { host: "127.0.0.1", port: upstreamPort, path: req.url, method: req.method, headers: req.headers },
        (upstreamRes) => {
          res.writeHead(upstreamRes.statusCode ?? 502, upstreamRes.headers);
          upstreamRes.pipe(res);
        },
      );
      // An unreachable API is a 502 to Next, which is what a real outage looks like.
      upstream.on("error", () => {
        res.statusCode = 502;
        res.end();
      });
      req.pipe(upstream);
    }, delayMs);
  })
  .listen(listenPort, "127.0.0.1");
