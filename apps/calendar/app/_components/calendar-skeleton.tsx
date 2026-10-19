/**
 * What `/` shows while its data is on the way (plan B3-D4: a <Suspense>
 * boundary inside the home page, not a root `loading.tsx`, which would turn
 * every page's `notFound()` into an HTTP 200). Grey bars in the grid's
 * rough shape; no data, no interactivity.
 *
 * The bars are decoration and stay `aria-hidden`. The one thing exposed is a
 * visually hidden status, "Loading shows" (B6 plan D8, finding B6-F5): without it the
 * skeleton had no text at all, so a screen-reader user met nothing while the
 * calendar loaded and a browser test had no role-based way to find it. Be exact about
 * what it buys: it is READABLE if a user goes looking; a live region that is already
 * in the first HTML is generally not announced on its own, so whether anything is
 * spoken stays a manual-pass question. `relative` is the project's rule for `sr-only`
 * (it is `position: absolute`, and needs a positioned ancestor to stay put).
 */
export function CalendarSkeleton() {
  return (
    <div className="relative mt-6">
      <p role="status" className="sr-only">
        Loading shows
      </p>
      <div aria-hidden="true" className="animate-pulse space-y-6">
        <div className="h-8 rounded-lg bg-muted" />
        {Array.from({ length: 5 }, (_, i) => (
          <div key={i} className="grid gap-3 md:grid-cols-[9rem_1fr]">
            <div className="h-5 w-24 rounded bg-muted" />
            <div className="h-24 rounded-lg bg-muted" />
          </div>
        ))}
      </div>
    </div>
  );
}
