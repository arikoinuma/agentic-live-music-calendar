import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ErrorPage from "./error";

// What this file tests (B5, section 5 of the plan; decision B5-D2): the error
// boundary every route falls back to when its data can't be loaded. It is a
// pin on three small promises whose loss would be silent — nothing crashes
// if the page starts printing a stack trace, it just leaks.
//
// Where the expected values come from: the component's own contract (its
// header comment in error.tsx — detail goes to the server log, visitors get
// a sentence, the opaque `digest` is the one safe thing to show) and B2's
// reasoning for it. The "secret" message below is a realistic one: a
// connection error naming an internal host and port.

const SECRET = "connect ECONNREFUSED 10.0.0.5:5432";

// An Error carrying the `digest` Next attaches to server-side failures.
function failure(digest?: string) {
  return Object.assign(new Error(SECRET), digest === undefined ? {} : { digest });
}

describe("ErrorPage", () => {
  it("never prints the error's message", () => {
    // Proves: in development a server error's message can carry URLs or env
    // var names; the page must show a generic sentence only. A change to
    // render `{error.message}` (mutation B5-M11) would leak it to every visitor.
    render(<ErrorPage error={failure("abc123")} retry={() => {}} />);

    expect(screen.queryByText(/ECONNREFUSED/)).not.toBeInTheDocument();
    expect(screen.queryByText(/10\.0\.0\.5/)).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Something went wrong" })).toBeInTheDocument();
  });

  it("shows the digest as a reference when there is one, and no reference line when there isn't", () => {
    // Proves: the digest is the opaque id that matches the server log line,
    // so a bug report can be traced; without one, no empty "Reference:".
    const { unmount } = render(<ErrorPage error={failure("abc123")} retry={() => {}} />);
    expect(screen.getByText("Reference: abc123")).toBeInTheDocument();
    unmount();

    render(<ErrorPage error={failure()} retry={() => {}} />);
    expect(screen.queryByText(/Reference/)).not.toBeInTheDocument();
  });

  it("'Try again' calls retry exactly once", async () => {
    // Proves: the button is wired to `retry` (Next 16.3's re-fetch), not to
    // the old `reset`, which would re-render the same failed payload
    // (B2-CR1-1).
    const retry = vi.fn();
    const user = userEvent.setup();
    render(<ErrorPage error={failure()} retry={retry} />);

    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(retry).toHaveBeenCalledTimes(1);
  });
});
