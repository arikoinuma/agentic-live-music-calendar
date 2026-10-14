/**
 * What `/` shows while its data is on the way (plan D4: a <Suspense>
 * boundary inside the home page, not a root `loading.tsx`, which would turn
 * every page's `notFound()` into an HTTP 200). Grey bars in the grid's
 * rough shape; no data, no interactivity.
 */
export function CalendarSkeleton() {
  return (
    <div aria-hidden="true" className="mt-6 animate-pulse space-y-6">
      <div className="h-8 rounded-lg bg-muted" />
      {Array.from({ length: 5 }, (_, i) => (
        <div key={i} className="grid gap-3 md:grid-cols-[9rem_1fr]">
          <div className="h-5 w-24 rounded bg-muted" />
          <div className="h-24 rounded-lg bg-muted" />
        </div>
      ))}
    </div>
  );
}
