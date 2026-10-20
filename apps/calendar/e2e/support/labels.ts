/**
 * The page labels that key the ratchet baseline (B6-D5), built in ONE place.
 *
 * Every accessibility test holds its findings to the baseline rows whose `page` equals a
 * label it passes in. If a spec builds its label by hand, the label can drift from the
 * baseline's row (or a screen can leave the list) and the row is silently never compared.
 * So the specs build every label here, and `a11y-baseline.test.ts` checks that every
 * committed baseline row belongs to one of them.
 *
 * Pure strings and lists, no Playwright: it is imported by a Vitest unit test.
 */
import { SCREENS, WIDTHS } from "./screens";

/** An axe scan of one screen at one width: `/day/2026-10-07 @375`. */
export const screenLabel = (path: string, width: number) => `${path} @${width}`;

/** The error screen (the API answering 502), at one width. */
export const apiDownLabel = (width: number) => `/ (API down) @${width}`;

/** The three filter popups, open (a11y-popups.spec.ts), desktop width. */
export const POPUP_LABELS = {
  venues: "/ venues popup open @1280",
  artists: "/ artists popup open, option highlighted @1280",
  month: "/ month popup open @1280",
} as const;

/** The painted focus indicators and the control borders (focus-indicator.spec.ts). */
export const FOCUS_LABEL = "focus indicators and borders @1280";

/** The pages whose Tab stops are walked for hidden focus, and the widths (keyboard.spec.ts). */
export const TAB_STOP_PAGES = ["/", "/venue/1"];
export const TAB_STOP_WIDTHS = [1280, 375];
export const tabStopsLabel = (path: string, width: number) => `tab stops hidden ${path} @${width}`;

/** Every label some spec produces. */
export const ALL_LABELS = new Set<string>([
  ...WIDTHS.flatMap((width) => [...SCREENS.map((s) => screenLabel(s.path, width)), apiDownLabel(width)]),
  ...Object.values(POPUP_LABELS),
  FOCUS_LABEL,
  ...TAB_STOP_PAGES.flatMap((path) => TAB_STOP_WIDTHS.map((width) => tabStopsLabel(path, width))),
]);
