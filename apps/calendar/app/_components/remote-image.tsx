import { httpUrlOrNull } from "@/lib/detail-format";
import { cn } from "@/lib/utils";

/**
 * A poster or photo hosted on someone else's site: the app's ONE place that
 * renders a remote image, and so the only `@next/next/no-img-element`
 * exception (B4 plan, decision D4).
 *
 * WHY A PLAIN <img> AND NOT `next/image`. `image_url` and `photo_url` point
 * at arbitrary venue and artist hosts. `next/image` would need an
 * open-ended `images.remotePatterns` (every host on the internet) and a
 * width and height that scraped data doesn't have. Under the repo's
 * `--max-warnings 0`, a bare <img> fails lint; the disable comment below
 * is checked to be the single exception (Verification 2: grep finds one).
 *
 * WHAT IT DOES INSTEAD:
 *  - `httpUrlOrNull` first — only an http(s) URL renders; `javascript:`,
 *    `data:`, `file:` or junk become nothing at all.
 *  - `referrerPolicy="no-referrer"`: the image's host learns that someone
 *    requested the image, not which page of ours they were on.
 *  - `loading="lazy"` and `decoding="async"`: a below-the-fold photo
 *    doesn't hold up the page.
 *  - A height cap with `object-contain`, so a huge or oddly shaped image
 *    can't break the layout. No dimensions are known, so no space is
 *    reserved and the layout can shift as the image loads (accepted, D4).
 *
 * ACCEPTED COSTS (D4): the reader's browser contacts a third-party host
 * (it sees their IP); a dead link shows the browser's broken-image marker
 * with the `alt` text, because a cosmetic `onError` fallback would need a
 * Client Component. Copies served from our own storage (R2, hosted phase)
 * would replace the `src` here and nowhere else.
 */
export function RemoteImage({
  src,
  alt,
  className,
}: {
  src: string | null | undefined;
  alt: string;
  className?: string;
}) {
  const safe = httpUrlOrNull(src);
  if (safe === null) return null;
  return (
    // eslint-disable-next-line @next/next/no-img-element -- remote hosts we can't enumerate: see the comment above
    <img
      src={safe}
      alt={alt}
      loading="lazy"
      decoding="async"
      referrerPolicy="no-referrer"
      className={cn("max-h-80 w-auto max-w-full rounded-md border object-contain", className)}
    />
  );
}
