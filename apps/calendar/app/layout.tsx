import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import "./globals.css";
import { Geist } from "next/font/google";
import { getMetroOrNull, siteDescription } from "@/lib/metro";
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

// `generateMetadata` is the App Router's replacement for hand-writing
// <title> and <meta> tags, in the form that may depend on data (a plain
// `export const metadata` object can't). `template` means a child page
// that exports `metadata = { title: "Venues" }` gets "Venues · Agentic
// Live Music Calendar" with no string-gluing of its own; `default` is used
// when a page sets no title. Placeholder name — no product name exists yet.
//
// The description names the metro, which comes from the API
// (`GET /metro`, v0.1-G24). `getMetroOrNull` never throws on an API outage —
// it returns null and `siteDescription` falls back to a generic sentence —
// so a down API costs the description its metro name, not the whole site.
// The metro call is shared with <MetroName> below through React's
// `cache()` (see getMetro in lib/api.ts): one API request per render
// (two on a page that calls `notFound()`, which renders the layout again).
export async function generateMetadata(): Promise<Metadata> {
  const metro = await getMetroOrNull();
  return {
    title: { default: SITE_NAME, template: `%s · ${SITE_NAME}` },
    description: siteDescription(metro),
  };
}

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
// There's no `await` in this layout's body, deliberately. The style
// guide's Streaming section: awaiting at the top of a layout blocks
// everything beneath it. The one thing the layout needs from the API (the
// metro name in the footer) lives in a small async child, <MetroName>,
// inside <Suspense>, so the header and the page's own content can stream
// to the browser before that call returns.
//
// Be precise about what <Suspense> buys here. It does NOT keep this shell
// statically prerenderable: without `cacheComponents`, a `no-store` fetch
// anywhere in the root layout makes EVERY route dynamic, including `/` and
// `/_not-found`. That is the accepted cost of decision B2-D1 (no persistent
// caching in B2; arch-initial.md §11): each request pays one extra, cheap
// /metro call, and in exchange `next build` doesn't need the API to be
// reachable. The benefit of the boundary is streaming, not prerendering.
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
            <nav className="ml-6 flex gap-4 text-sm">
              <Link href="/venues" className="hover:underline">
                Venues
              </Link>
              <Link href="/artists" className="hover:underline">
                Artists
              </Link>
            </nav>
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
          {children}
        </main>
        <footer className="border-t">
          <div className="mx-auto flex w-full max-w-6xl items-center justify-between px-4 py-3 text-sm text-muted-foreground">
            <Suspense fallback={<span aria-hidden="true">&nbsp;</span>}>
              <MetroName />
            </Suspense>
            <Link href="/health" className="hover:text-foreground">
              Status
            </Link>
          </div>
        </footer>
      </body>
    </html>
  );
}

// The footer's metro name. An async Server Component of its own so the
// `await` is below the <Suspense> boundary, not in the layout body.
// Renders nothing visible if the API is unavailable (getMetroOrNull
// returns null): a missing label beats a broken footer.
async function MetroName() {
  const metro = await getMetroOrNull();
  return <span>{metro?.name}</span>;
}
