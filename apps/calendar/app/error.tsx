"use client";

// The error boundary for everything under the root layout. With real
// fetches, "the API is down or slow" is a normal event, not a bug, and
// this is what a visitor sees instead of a stack trace.
//
// This is the one place in B2 that MUST be a Client Component: React
// error boundaries are class/hook-based and only exist on the client, and
// `retry` is a client-side action. Nothing else about it needs the
// browser, which is why it stays tiny.
//
// `retry`, not `reset` (stable since Next 16.3): `retry()` re-fetches the
// route's server data and re-renders, which is what recovering from "the
// API was down" needs. `reset()` only clears the error state and re-renders
// the SAME failed payload, so it would show the same error again. (The
// style guide used to say `error`/`reset`; B2-CR1-1.)
//
// What it deliberately does NOT render: `error.message`. In a Server
// Component failure, Next replaces the real message with a generic one in
// production and attaches a `digest` instead — and in development the
// message may carry URLs or env var names. The same reasoning as the
// /health page (B1): detail goes to the server log, visitors get a
// sentence. The `digest` is safe to show: it's an opaque id that matches
// the server log line, so a bug report can be traced.
export default function ErrorPage({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">
        Something went wrong
      </h1>
      <p className="mt-2 text-muted-foreground">
        We couldn&apos;t load this page. It may be temporary.
      </p>
      {error.digest && (
        <p className="mt-2 text-sm text-muted-foreground">
          Reference: {error.digest}
        </p>
      )}
      <button className="mt-4 underline" onClick={() => retry()}>
        Try again
      </button>
    </section>
  );
}
