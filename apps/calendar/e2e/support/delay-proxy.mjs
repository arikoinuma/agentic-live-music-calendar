/**
 * A pass-through HTTP proxy between the Next server and the FastAPI app.
 *
 *   node delay-proxy.mjs <listen port> <upstream port>
 *
 * Step 1 of the B6 plan only needs it to forward requests unchanged, so the
 * wiring (Next -> proxy -> API) is in place from the first green test. Step 4
 * adds the controls tests use to make the API slow or broken (`POST
 * /__delay/<ms>`, `/__fail`, `/__reset`); those are what let a browser test
 * observe the loading skeleton and the "Updating…" state, which last a few
 * milliseconds against a fast API.
 *
 * Test infrastructure only. Plain Node, no dependencies.
 */
import http from "node:http";

const [listenPort, upstreamPort] = process.argv.slice(2).map(Number);

http
  .createServer((req, res) => {
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
  })
  .listen(listenPort, "127.0.0.1");
