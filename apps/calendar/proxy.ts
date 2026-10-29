/**
 * Next.js 16's `proxy.ts` (the new name of `middleware.ts`): it runs before a page is built, on the Node runtime.
 *
 * What it does for C4: resolves the metro from the request's host, sends the apex and bad hosts to the default
 * metro, puts the non-production gate in front of staging, and marks every non-production response `noindex`
 * (alpha-deployment-plan.md C4, Dep-D2, Dep-D4). The work is in `lib/proxy-handler.ts` and `lib/request-plan.ts`;
 * this file only wires them to Next, because a proxy file may export nothing else but its function and `config`.
 *
 * `config.matcher` SKIPS only the static build output, the image optimizer and the favicon, and covers every page,
 * `/health` included (the style guide: a proxy with no matcher runs on every asset request, including
 * `_next/static`). docs/dev/implementations/c4-metro-hosts.md: C4-D1, C4-D6.
 */

import type { NextRequest } from "next/server";
import { handleRequest } from "@/lib/proxy-handler";

export default function proxy(request: NextRequest) {
  return handleRequest(request);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
