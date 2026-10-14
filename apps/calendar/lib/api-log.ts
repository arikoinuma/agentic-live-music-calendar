/**
 * The pure parts of the API request log: when full bodies are logged, how a
 * body is summarised on one line, and how sizes and long bodies are shown.
 *
 * lib/api.ts writes the log lines (see its docstring); this file decides
 * what goes in them, as plain functions with no env, no fetch and no
 * console, so api-log.test.ts can pin every case without mocks.
 *
 * Why a SUMMARY by default and the full JSON behind a switch (Ari, October
 * 14, 2026). The point of logging a body is to notice anomalies — a field
 * that is suddenly null, a list that is suddenly empty — and in hosted logs
 * (Vercel, Railway) that has to be searchable and short: a real metro's
 * /shows is tens of KB, five API calls fire per page load, and long lines
 * are what platform log search handles worst. A one-line summary carries the
 * signal; the full JSON is for chasing one specific problem
 * (`LOG_API_BODIES=1`). In the browser's Network tab you'd click through a
 * JSON tree; locally, `curl … | jq` or FastAPI's /docs gives the same tree
 * (docs/dev/debugging.md).
 */

/**
 * Whether to log full response bodies: only when `LOG_API_BODIES` is "1" or
 * "true", and NEVER in production. The production guard is deliberate: a
 * stray env var on Vercel must not make the server write whole API
 * responses (large lines, and data nobody chose to retain) into hosted logs.
 */
export function bodyLoggingEnabled(env: {
  LOG_API_BODIES?: string;
  NODE_ENV?: string;
}): boolean {
  if (env.NODE_ENV === "production") return false;
  return env.LOG_API_BODIES === "1" || env.LOG_API_BODIES === "true";
}

/** 156 -> "156 B", 8288 -> "8.1 KB", 1048576 -> "1.0 MB". */
export function describeSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// The longest body written in full, in characters. Beyond this the line is
// cut and says so: a log line that silently ends mid-object looks complete.
const MAX_BODY_CHARS = 4000;

/**
 * The body as ONE line of compact JSON, cut at `max` characters with a
 * marker saying how much was cut. One line, not pretty-printed: a log
 * search treats each line as a record, so a body split across lines
 * can't be found or copied as a unit.
 */
export function compactJson(body: unknown, max: number = MAX_BODY_CHARS): string {
  const text = JSON.stringify(body) ?? String(body);
  if (text.length <= max) return text;
  return `${text.slice(0, max)}…(+${text.length - max} chars)`;
}

// A summary is a glance, not a record; past this it is cut.
const MAX_SUMMARY_CHARS = 240;
const MAX_STRING_CHARS = 40;

/**
 * One line describing a parsed response body. Never throws — it is called
 * from the request path with whatever the API sent, including the wrong
 * shape (which is what this line exists to reveal).
 *
 * `path` is the route without its query ("/shows"): the shape of `/shows`
 * is the one worth specific attention, every other route gets the generic
 * summary.
 */
export function summarizeBody(path: string, body: unknown): string {
  try {
    if (path === "/shows" && isShowList(body)) return summarizeShowList(body);
    return clip(summarizeGeneric(body), MAX_SUMMARY_CHARS);
  } catch {
    return "(could not summarize)";
  }
}

type ShowListBody = {
  start: string;
  end: string;
  shows: Record<string, unknown>[];
};

function isShowList(body: unknown): body is ShowListBody {
  if (typeof body !== "object" || body === null) return false;
  const b = body as Record<string, unknown>;
  return typeof b.start === "string" && typeof b.end === "string" && Array.isArray(b.shows);
}

/**
 * "25 shows (2026-09-28..2026-10-25); 3 without start_time; 0 with empty
 * lineup; 2 with no admission info".
 *
 * The counts are the gaps most often meaning the extraction missed
 * something: no time, no artists. "No admission info" is legitimate (many
 * listings don't say) — it is here because a sudden jump in it means the
 * agent stopped reading prices. Not all-null means NOT free: that is the
 * API contract's rule, so it is counted, never treated as "free".
 */
function summarizeShowList(body: ShowListBody): string {
  const shows = body.shows.filter((s) => typeof s === "object" && s !== null);
  const noTime = shows.filter((s) => s.start_time == null).length;
  const emptyLineup = shows.filter(
    (s) => !Array.isArray(s.lineup) || s.lineup.length === 0,
  ).length;
  const noAdmission = shows.filter(
    (s) => s.admission_advance == null && s.admission_day == null && s.free_admission == null,
  ).length;
  return (
    `${body.shows.length} shows (${body.start}..${body.end}); ` +
    `${noTime} without start_time; ${emptyLineup} with empty lineup; ` +
    `${noAdmission} with no admission info`
  );
}

/**
 * Any other body: scalars printed outright (strings shortened), arrays as
 * `key[3]`, nested objects as `key{…}`, and the null fields listed apart at
 * the end — "this field is unexpectedly null" is the commonest anomaly, so
 * it gets its own place to be spotted.
 *   {id:7, tags:["a","b"], owner:{…}, website:null}
 *     -> `id=7, tags[2], owner{…}; null: website`
 */
function summarizeGeneric(body: unknown): string {
  if (body === null) return "null";
  if (Array.isArray(body)) return `[${body.length} items]`;
  if (typeof body === "string") return JSON.stringify(clip(body, MAX_STRING_CHARS));
  if (typeof body !== "object") return String(body);

  const parts: string[] = [];
  const nulls: string[] = [];
  for (const [key, value] of Object.entries(body)) {
    if (value === null) nulls.push(key);
    else if (Array.isArray(value)) parts.push(`${key}[${value.length}]`);
    else if (typeof value === "object") parts.push(`${key}{…}`);
    else if (typeof value === "string") parts.push(`${key}=${JSON.stringify(clip(value, MAX_STRING_CHARS))}`);
    else parts.push(`${key}=${String(value)}`);
  }
  const listed = parts.join(", ");
  return nulls.length === 0 ? listed : `${listed}${listed ? "; " : ""}null: ${nulls.join(", ")}`;
}

// Cuts to `max` characters total, the last being "…".
function clip(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 1)}…`;
}
