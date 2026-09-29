/**
 * Friendly names for the generated API types.
 *
 * DECISION (was open in Track 0): types are GENERATED from FastAPI's
 * OpenAPI schema — option 2. See docs/dev/api-contract.md section 7.
 *
 * The chain, end to end:
 *
 *   apps/api/app/schemas.py        Pydantic models, the source of truth
 *     -> FastAPI                   builds an OpenAPI document from the
 *                                  routes' return-type annotations
 *     -> apps/api/openapi.json     dumped without a server, git-ignored
 *     -> openapi-typescript        reads the standard, emits TypeScript
 *     -> lib/api-types.ts          generated, committed, never edited
 *     -> this file                 hand-written aliases, ~30 lines
 *
 * Run `make types` after any change to app/schemas.py or the routers.
 * CI regenerates and fails if the committed output differs, so a
 * backend shape change that nobody regenerated for becomes a red build
 * rather than a runtime `undefined` in production.
 *
 * Why this thin file exists at all: the generated form is
 * `components["schemas"]["ShowSummary"]`, which is accurate and
 * unpleasant to read at every call site. Aliasing costs one line per
 * type and can't drift, because each alias resolves into the generated
 * file — rename a Pydantic model and this stops compiling, which is
 * exactly the signal we wanted.
 *
 * ---------------------------------------------------------------------
 * Three things about the generated shapes that differ from what you'd
 * hand-write, and are worth knowing before you use them:
 *
 * 1. Fields with defaults are OPTIONAL (`start_time?: string | null`),
 *    not merely nullable. That's OpenAPI being correct: a field with a
 *    default isn't in the schema's `required` list. FastAPI does
 *    serialize them all, so at runtime they're present-and-null — but
 *    the type says `string | null | undefined` and you should handle
 *    all three. If this gets tiresome, the fix is on the Python side:
 *    drop the `= None` defaults so the fields become required-but-
 *    nullable. That costs verbosity when constructing them in Python.
 *
 * 2. Dates and times are `string`, because JSON has no date type.
 *    Parse with Temporal.PlainDate / Temporal.PlainTime, never
 *    `new Date("2026-09-28")` — that parses as UTC midnight and renders
 *    as the 27th anywhere west of Greenwich.
 *
 * 3. `Decimal` is `string`, not `number` — deliberate, to avoid float
 *    rounding on money. Format it; don't parseFloat it. Note the
 *    generator worked this out on its own from the Pydantic model.
 * ---------------------------------------------------------------------
 */

import type { components } from "./api-types";

type Schemas = components["schemas"];

// Entities
export type MetroSummary = Schemas["MetroSummary"];
export type VenueSummary = Schemas["VenueSummary"];
export type VenueDetail = Schemas["VenueDetail"];
export type ArtistSummary = Schemas["ArtistSummary"];
export type ArtistDetail = Schemas["ArtistDetail"];
export type EventSummary = Schemas["EventSummary"];
export type LineupEntry = Schemas["LineupEntry"];
export type ShowSummary = Schemas["ShowSummary"];
export type ShowDetail = Schemas["ShowDetail"];
export type CalendarMonth = Schemas["CalendarMonth"];

// Responses
export type ShowListResponse = Schemas["ShowListResponse"];
export type VenueListResponse = Schemas["VenueListResponse"];
export type ArtistListResponse = Schemas["ArtistListResponse"];
export type CalendarMonthsResponse = Schemas["CalendarMonthsResponse"];

// Enums. These come through as string-literal unions, so a typo in a
// comparison is a compile error rather than a condition that's silently
// always false.
export type AgeRestriction = Schemas["AgeRestriction"];
export type Setting = Schemas["Setting"];
export type Seating = Schemas["Seating"];
export type VenueType = Schemas["VenueType"];
export type ArtistFormat = Schemas["ArtistFormat"];
export type ArtistRepertoire = Schemas["ArtistRepertoire"];
