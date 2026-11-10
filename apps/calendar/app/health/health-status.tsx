import type { AppEnv } from "@/lib/app-env";
import type { ApiHealth } from "@/lib/health";

// What `getAppEnv()` produced for this server: a value, or the reason it could not (C3-D7). The page catches
// the throw and passes the result here, because a status page must never crash on the thing it reports.
export type FrontendEnv =
  | { ok: true; value: AppEnv }
  | { ok: false; reason: string };

// The synchronous half of the /health page, split out so it can be tested (the page is an async Server
// Component, which the style guide says not to unit test; same split as B5's CalendarResults).
//
// It shows BOTH environments, the frontend's and the API's, because the mistake worth seeing is a mismatch:
// a staging frontend pointed at the production API (a copied API_BASE_URL) looks healthy on "API: up" alone
// (C3-D7). `showDetail` gates the raw error text: this page is linked from every footer, so strangers can read
// it, and the reason is for the person running the app (see page.tsx).
//
// `flagProblems` is what `checkFlagEnvironment` found wrong with the web side's `FLAG_*` variables (C3.1-D19). It
// follows the same rule as the other reasons: the page always says something is misconfigured, and the variable names
// and values appear only when `showDetail` is set (C3.1-PR1-9).
export function HealthStatus({
  health,
  frontendEnv,
  showDetail,
  flagProblems = [],
}: {
  health: ApiHealth;
  frontendEnv: FrontendEnv;
  showDetail: boolean;
  flagProblems?: string[];
}) {
  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">Status</h1>
      <dl className="mt-4 grid max-w-md grid-cols-[auto_1fr] gap-x-6 gap-y-2">
        <dt className="text-muted-foreground">API</dt>
        <dd>
          {health.ok ? (
            <span>up ({health.message})</span>
          ) : (
            <span className="text-destructive">
              down
              {showDetail && <> — {health.reason}</>}
            </span>
          )}
        </dd>
        <dt className="text-muted-foreground">Frontend environment</dt>
        <dd>
          {frontendEnv.ok ? (
            <span>{frontendEnv.value}</span>
          ) : (
            <span className="text-destructive">
              unavailable
              {showDetail && <> — {frontendEnv.reason}</>}
            </span>
          )}
        </dd>
        <dt className="text-muted-foreground">API environment</dt>
        <dd>
          {health.ok ? (
            <span>{health.appEnv ?? "unknown"}</span>
          ) : (
            <span>unknown</span>
          )}
        </dd>
        <dt className="text-muted-foreground">Feature flags (API)</dt>
        <dd>{apiFlags(health)}</dd>
        {flagProblems.length > 0 && (
          <>
            <dt className="text-muted-foreground">Feature flags (web)</dt>
            <dd className="text-destructive">
              misconfigured
              {showDetail && <> — {flagProblems.join("; ")}</>}
            </dd>
          </>
        )}
      </dl>
    </section>
  );
}

// The API's feature-flag values as one line each ("worker.scheduled_runs: off"), or why there are none to show:
// production hides them (`null`), an older API or a down one cannot say (C3.1-D16).
function apiFlags(health: ApiHealth) {
  if (!health.ok || health.featureFlags === undefined) return <span>unknown</span>;
  if (health.featureFlags === null) return <span>not shown in production</span>;
  const entries = Object.entries(health.featureFlags);
  if (entries.length === 0) return <span>none registered</span>;
  return (
    <ul>
      {entries.map(([name, value]) => (
        <li key={name}>
          {name}: {value ? "on" : "off"}
        </li>
      ))}
    </ul>
  );
}
