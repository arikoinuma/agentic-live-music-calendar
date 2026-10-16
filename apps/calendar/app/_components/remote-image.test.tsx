import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RemoteImage } from "./remote-image";

// What this file tests (B5, section 5 of the plan; decision B5-D2): the app's
// one place that renders an image hosted on someone else's site (B4-D4).
// The URLs come from scraped venue and artist pages, so they are untrusted.
// `httpUrlOrNull` has its own pure tests (lib/detail-format.test.ts); this
// file proves the COMPONENT honours it and sets the privacy-relevant
// attributes — a refactor that bypassed the guard (mutation B5-M12) would still
// type-check and still render posters.
//
// Where the expected values come from: B4-D4 and the component's header
// comment (http(s) only, `no-referrer`, lazy, height-capped).

describe("RemoteImage", () => {
  it.each([
    ["a javascript: URL", "javascript:alert(1)"],
    ["a data: URL", "data:text/html,<script>alert(1)</script>"],
    ["a file: URL", "file:///etc/passwd"],
    ["an empty string", ""],
    ["null", null],
    ["undefined", undefined],
  ])("renders nothing for %s", (_label, src) => {
    // Proves: only an http(s) URL becomes an <img>. Anything else renders no
    // element at all, rather than an image that loads (or runs) something
    // the venue's page never intended. `alt` is non-empty so a rendered image
    // WOULD be found by the role query: absence means absence.
    render(<RemoteImage src={src} alt="Poster" />);

    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("renders an https image with the privacy and performance attributes", () => {
    // Proves: `no-referrer` (the image's host learns that someone requested
    // it, not which page of ours they were on), `lazy` and `async` (a
    // below-the-fold photo doesn't hold up the page), and the alt text the
    // caller gave.
    render(<RemoteImage src="https://example.com/posters/nooky.jpg" alt="Nooky Jones poster" />);

    const image = screen.getByRole("img", { name: "Nooky Jones poster" });
    expect(image).toHaveAttribute("src", "https://example.com/posters/nooky.jpg");
    expect(image).toHaveAttribute("referrerpolicy", "no-referrer");
    expect(image).toHaveAttribute("loading", "lazy");
    expect(image).toHaveAttribute("decoding", "async");
  });

  it("adds a caller's class to the height cap instead of replacing it", () => {
    // Proves: `max-h-80` is the safety net that stops a huge or oddly shaped
    // image breaking the layout; a caller styling its own image must not
    // lose it.
    render(<RemoteImage src="https://example.com/a.jpg" alt="x" className="custom-class" />);

    expect(screen.getByRole("img")).toHaveClass("max-h-80", "custom-class");
  });
});
