import type { Metadata } from "next";
import { safeNextPath } from "@/lib/gate";

// `robots: noindex` on the page itself: in production there is no gate (and /gate/enter answers 404), but this page
// still renders, and once the production host is public a crawler that follows a link to it must not list a password
// form. Elsewhere the proxy's X-Robots-Tag already says the same (C4-CR1-2).
export const metadata: Metadata = { title: "Password required", robots: { index: false, follow: false } };

// The password form for the non-production gate (C4-D6). A plain HTML form that posts to /gate/enter: no client
// JavaScript, no Server Action (an action POSTs to the route that renders it, which a proxy matcher change could
// silently leave unprotected, nextjs-style-guide.md Anti-patterns). The proxy sends unauthenticated visitors here
// with `?next=<their path>`; it is carried in a hidden field and re-checked by the server before any redirect, so
// the value is only a hint. `?error=1` is how a refused password comes back.
//
// Reachable in every environment (the proxy only gates staging and dev), but only /gate/enter's answer matters:
// where there is no gate, it answers 404.
export default async function GatePage(props: PageProps<"/gate">) {
  const searchParams = await props.searchParams;
  const nextRaw = searchParams.next;
  const next = safeNextPath(typeof nextRaw === "string" ? nextRaw : null);
  const failed = searchParams.error === "1";

  return (
    <section className="mx-auto max-w-sm py-12">
      <h1 className="text-xl font-semibold tracking-tight">Password required</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        This copy of the calendar is not public. Enter the password to continue.
      </p>
      {failed && (
        <p role="alert" className="mt-4 text-sm font-medium text-destructive">
          That password was not accepted.
        </p>
      )}
      <form method="post" action="/gate/enter" className="mt-6 flex flex-col gap-3">
        <input type="hidden" name="next" value={next} />
        <label htmlFor="gate-password" className="text-sm font-medium">
          Password
        </label>
        <input
          id="gate-password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          className="rounded-md border px-3 py-2"
        />
        <button type="submit" className="rounded-md border px-3 py-2 text-sm font-medium hover:bg-accent">
          Continue
        </button>
      </form>
    </section>
  );
}
