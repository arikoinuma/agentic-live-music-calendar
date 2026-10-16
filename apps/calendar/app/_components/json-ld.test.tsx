import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { JsonLd } from "./json-ld";

// What this file tests (B5, section 5 of the plan; decision B5-D2): the one
// `dangerouslySetInnerHTML` in the app. It is safe only because
// `jsonLdScriptContent` escapes `<` in the structured data, and the data
// includes names scraped from venue websites — so a show called
// `</script><script>alert(1)</script>` must not be able to close the tag.
// lib/json-ld.test.ts pins that the STRING never contains a `<`; this file
// pins that the COMPONENT uses it.
//
// WHY THIS RENDERS TO MARKUP AND PARSES IT, instead of using Testing
// Library's `render` (B5-PR1-1). `render` goes through React DOM on the
// client, which sets a script's text with `innerHTML`, and that path never
// treats the text `</script>` as an end tag — so a client render stays green
// even for an unescaped `JSON.stringify` (mutation B5-M13), and the test would
// guard nothing. The breakout happens when the SERVER's HTML goes through
// the document parser, which is exactly what a search engine's crawler does.
// So: render the way the server does (`renderToStaticMarkup`), then parse
// the result as a document.
//
// Where the expected values come from: the hostile name is the classic
// script-tag breakout; the assertions are what a correct page must satisfy
// (one script, and its text parses back to exactly the data we passed).

const hostile = {
  "@type": "Event",
  name: "</script><script>alert(1)</script>",
};

// The server's HTML for `<JsonLd data={data} />`, parsed the way a browser or
// crawler would parse a page that contains it.
function parseServerHtml(data: unknown): Document {
  const html = renderToStaticMarkup(<JsonLd data={data} />);
  return new DOMParser().parseFromString(`<!doctype html><body>${html}</body>`, "text/html");
}

describe("JsonLd", () => {
  it("cannot be closed early by a </script> in the data", () => {
    // Proves: with a hostile name, the parsed page still holds exactly ONE
    // script, typed as JSON-LD, and its text parses back to the original
    // data. If `</script>` ended the tag early there would be two scripts and
    // the second would be live code.
    const doc = parseServerHtml(hostile);

    const scripts = doc.body.querySelectorAll("script");
    expect(scripts).toHaveLength(1);
    // `getAttribute`, not jest-dom's `toHaveAttribute`: elements of a
    // DOMParser document have no `defaultView`, and jest-dom rejects any
    // element it can't tie to a window ("received value must be an
    // HTMLElement") even though this one is exactly that.
    expect(scripts[0]!.getAttribute("type")).toBe("application/ld+json");
    expect(JSON.parse(scripts[0]!.textContent!)).toEqual(hostile);
  });

  it("renders an array of events as a single script", () => {
    // Proves: a page with several events (the venue calendar) emits one
    // script holding the whole array, not one per item.
    const events = [hostile, { "@type": "Event", name: "Plain" }];
    const doc = parseServerHtml(events);

    const scripts = doc.body.querySelectorAll("script");
    expect(scripts).toHaveLength(1);
    expect(JSON.parse(scripts[0]!.textContent!)).toEqual(events);
  });
});
