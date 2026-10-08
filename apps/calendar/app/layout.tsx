import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { Geist } from "next/font/google";
import { cn } from "@/lib/utils";

const geist = Geist({ subsets: ["latin"], variable: "--font-sans" });

// localFont references to the default Turborepo-generated
// ./fonts/GeistVF.woff and GeistMonoVF.woff were removed here —
// those files are deliberately not committed to the repo (same
// decision as the default favicon; see docs/dev/env-setup.md Phase 1),
// so next/font/local can't resolve them and Vercel's build fails.
// The Geist font above (next/font/google) already covers this app's
// styling and is fetched at build time, no local file needed.

const SITE_NAME = "Agentic Live Music Calendar";

// `metadata` is the App Router's replacement for hand-writing <title> and
// <meta> tags: export a plain object from a layout or page and Next.js
// renders the tags. `template` means a child page that exports
// `metadata = { title: "Venues" }` gets "Venues · Agentic Live Music
// Calendar" with no string-gluing of its own; `default` is used when a
// page sets no title. Placeholder name — no product name exists yet.
//
// TODO(G24, v1-build-plan.md B2): the metro name in `description` below and
// in the footer is hard-coded. It should come from the metro record via
// the API (`MetroSummary.name`), here through `generateMetadata`. Needs a
// `GET /metro` endpoint first — the contract only exposes metro nested
// inside VenueDetail today.
export const metadata: Metadata = {
  title: { default: SITE_NAME, template: `%s · ${SITE_NAME}` },
  description:
    "Live music in Minneapolis and St. Paul, gathered from venue calendars.",
};

// ROOT LAYOUT — what it is and what it costs.
//
// A layout wraps every page beneath it and, crucially, is NOT re-rendered
// when you navigate between those pages: the header below stays mounted
// while `{children}` swaps. That's why shared chrome lives here, not in
// each page.
//
// This is a Server Component (no "use client"): it runs on the server and
// ships HTML, not JavaScript. `<Link>` is fine here — it's a client-capable
// component that Server Components may render; it prefetches the target
// route when it scrolls into view.
//
// There's no `await` anywhere in this layout, deliberately. The style
// guide's Streaming section: awaiting params/cookies at the top of a
// layout blocks everything beneath it. A synchronous shell lets Next.js
// prerender it once and reuse it.
//
// Nav links to /venues and /artists arrive in B2, when those routes exist.
// A link to a route that 404s is worse than no link.
export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={cn("font-sans", geist.variable)}>
      <body className="flex min-h-dvh flex-col">
        <header className="border-b">
          <div className="mx-auto flex w-full max-w-6xl items-center px-4 py-3">
            <Link href="/" className="font-semibold tracking-tight">
              {SITE_NAME}
            </Link>
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
          {children}
        </main>
        <footer className="border-t">
          <div className="mx-auto flex w-full max-w-6xl items-center justify-between px-4 py-3 text-sm text-muted-foreground">
            {/* TODO(G24): metro name from the API, not a literal. Don't
                await it in this layout body — wrap a small async child in
                <Suspense> so the shell stays prerenderable. */}
            <span>Minneapolis / St. Paul</span>
            <Link href="/health" className="hover:text-foreground">
              Status
            </Link>
          </div>
        </footer>
      </body>
    </html>
  );
}
