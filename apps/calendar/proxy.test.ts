/**
 * proxy.ts as Next sees it: the exported function and the matcher (C4-T5).
 *
 * The matcher decides which requests reach the proxy at all, so a mistake in it silently ungates pages or gates
 * assets. Next ships a helper that evaluates a matcher the way the server does; it is `unstable_doesMiddlewareMatch`
 * in Next 16.4.1 (the bundled docs call it `unstable_doesProxyMatch`, which is not exported, C4-PR1-11).
 */

import { unstable_doesMiddlewareMatch } from "next/experimental/testing/server";
import { describe, expect, it } from "vitest";
import proxy, { config } from "./proxy";

describe("config.matcher", () => {
  it.each(["/", "/health", "/venue/3", "/gate", "/gate/enter", "/day/2026-10-07", "/nope"])(
    "covers the page %s",
    (url) => {
      // Proves (C4-D6): every page is behind the proxy, /health included, so the gate has no gaps.
      expect(unstable_doesMiddlewareMatch({ config, url })).toBe(true);
    },
  );

  it.each(["/_next/static/chunks/main.js", "/_next/image?url=%2Fa.png&w=64&q=75", "/favicon.ico"])(
    "skips the asset %s",
    (url) => {
      // Proves: build output, the image optimizer and the favicon do not run the proxy (the style guide's
      // 'proxy with no matcher runs on every request, including _next/static').
      expect(unstable_doesMiddlewareMatch({ config, url })).toBe(false);
    },
  );
});

describe("the default export", () => {
  it("is the proxy function Next looks for", () => {
    // Proves: the file exports `proxy` (Next 16's name; `middleware` is the old one), as a function.
    expect(typeof proxy).toBe("function");
  });
});
