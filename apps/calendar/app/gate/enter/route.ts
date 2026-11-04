import { handleGateEnter } from "@/lib/gate-enter";

// The gate's login post (C4-D6). The logic is in lib/gate-enter.ts so it can be unit tested: a route file may
// export only its handlers.
export async function POST(request: Request) {
  return handleGateEnter(request);
}
