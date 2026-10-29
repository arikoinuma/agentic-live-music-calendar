# C4 — metro hosts and the domain

**Status:** Plan review
**Date:** October 29, 2026
**Author model:** Claude Sonnet 5.5
**Reviewer model:** Claude Opus 5.5 (plan review round 1; to be filled by the reviewer)
**Spec:** `docs/dev/alpha-deployment-plan.md` §6 C4 (and §2 point 6; §3 Dep-D2, Dep-D3, Dep-D4, Dep-D7, Dep-D8, Dep-D11, Dep-D12, Dep-D15; §4.2 hostnames; §5.2 traps "Attaching the production domain early" and "No domain chosen when C4's DNS step or C11 arrives"), `docs/dev/implementations/c3-environments-and-deploy.md` (C3-D7 `getAppEnv()`, C3-D11 previews, `environments.md`), `docs/dev/implementations/c2-api-reads-database.md` (C2-D5, `current_metro`), `docs/arch/arch-initial.md` §4, §11, `docs/arch/data-model-initial.md` (`metro`), `docs/dev/api-contract.md` §2, §6, `docs/references/nextjs-style-guide.md` (Routing, `proxy.ts`, Anti-patterns), `docs/references/fastapi-style-guide.md`, `apps/calendar/AGENTS.md`, `apps/api/AGENTS.md`

**Designations.** Inside this plan the decisions are `D1`–`D11`, the tests `T1`–`T9`, and the two fill-in key points `K1` (host parsing: strip the environment's zone on a label boundary) and `K2` (the proxy's decision order: gate before metro redirect). Elsewhere they are written `C4-D1`, `C4-T1`, `C4-K1` and so on (`docs/dev/conventions.md`); code, tests, comments and other documents must use the scoped form, and the build step copies from this file, so copy the scoped form. Review items are `C4-PR<round>-<n>` for the plan review and `C4-CR<round>-<n>` for the code review. The `TODO(Ari)` blocks cite their key points as `C4-K1` and `C4-K2`. The deployment plan's decisions keep their own scope (`Dep-D2`), and other plans' IDs carry theirs (`C3-D7`, `C2-D5`, `B2-D1`). Adding `C4` to the scope table in `docs/dev/conventions.md` is a step below.

## Context

### What this milestone is

Dep-D2 makes each metro its own subdomain of an environment's zone (`msp.<domain>`, `msp.staging.<domain>`, `msp.dev.<domain>`). C4 pulls the **minimum** of multi-metro forward: a slug on the metro, resolving the metro from the request host, an apex that sends visitors to the live metro, the non-production gate (Dep-D4) and `noindex`. It does **not** scope queries by metro (`arch-initial.md` §11, "Multi-metro scoping enforcement" stays deferred) and does not attach the production domain (C11, Dep-D11).

The milestone has three halves with different handling, as C3 did:

| Half | Who | What | Verified by |
|---|---|---|---|
| **Code and tests** | Claude (cloud-suited; the host parsing, the gate and the decision order are pure and test-first) | `metro.slug` and its migration, `GET /metro` carrying it, host parsing, `proxy.ts`, the gate, `noindex`, canonical and JSON-LD URLs | `make check`, tests written first |
| **Dashboards** | Ari, with Claude walking through | Vercel variables (gate password, zone) and, once a domain is chosen, the two hosts and their DNS | A runbook (below), a check after every step |
| **The domain** | Ari | Choosing and registering a name (Dep-D7) | Blocks one step only: the DNS and hosts step |

### What is true today (from C2, C3 and the repo, October 29, 2026)

- **There is no slug, no `proxy.ts`, no canonical URL.** `metro` has `id`, `name`, `timezone` (`app/db/models/calendar.py`); `MetroSummary` is the same three fields; `apps/calendar/` has no `proxy.ts` or `middleware.ts`; `app/layout.tsx` exports `generateMetadata` with a title and description only; `lib/json-ld.ts` omits `url` "on purpose: there is no site URL until the hosted phase".
- **One metro, resolved by being the first row.** `current_metro` (`app/dependencies.py`) returns the lowest-id `metro` row; its docstring says "C4's slug lookup later replaces this function". D9 below decides it does not (the spec keeps scoping deferred).
- **`getAppEnv()` exists** (`lib/app-env.ts`, C3-D7), validated against Vercel's own variables, written so that C4's `proxy.ts` reuses it. It throws when called, never at import.
- **Previews are live** (C3): the Vercel Preview environment holds `API_BASE_URL` and `APP_ENV=staging` for all branches. The `dev` branch does not exist yet, and **dev has no Railway service** (C3-D1: on demand), so there is no dev API for a dev host to read (D10).
- **A custom domain makes a host public.** Vercel's protection covers `*.vercel.app` only (`alpha-deployment-plan.md` §1.1, "Vercel protection"). The moment `msp.staging.<domain>` is added, the app-level gate is the **only** thing between the internet and staging (and the Railway API stays public until C10). So the gate must be built and proven on the `*.vercel.app` URL **before** any domain is attached (an ordering trap, Step 5).
- **No domain is chosen.** Dep-D7: Ari registers at Namecheap and points the nameservers at Vercel when he settles on a name. Everything except Step 6 runs without one.
- **Dev's database is stamped at `67609c405218`, not head** (`environments.md`, C3 Step 3): the new migration's `upgrade` runs the C3 `app_env` migration first when `dev` is next migrated. That is correct but unrehearsed; Step 1's check covers it.

### What C4 delivers

| Piece | Where | What changes |
|---|---|---|
| `metro.slug` | `app/db/models/calendar.py`, one migration, `app/db/seed.py`, `app/schemas.py`, `app/testing/sample_data.py` | `NOT NULL`, unique, format-checked column; `msp` seeded; `MetroSummary.slug`; contract, types and fixtures regenerated (D3). **Its own early PR** |
| Host to metro | `apps/calendar/lib/metro-host.ts` (+ test), `lib/reserved-slugs.json` | Pure parser: strip the environment's zone, the remainder is the slug (`C4-K1`, D2) |
| The decision order | `apps/calendar/lib/request-plan.ts` (+ test) | Pure function from (environment, host class, gate cookie, path) to an action: next, redirect or unavailable (`C4-K2`) |
| `proxy.ts` | `apps/calendar/proxy.ts` (+ test) | Thin glue that reads the request, calls the two pure modules, performs the action, sets `x-metro-slug` and `X-Robots-Tag` (D7), with a `config.matcher` |
| The gate | `lib/gate.ts` (+ test), `app/gate/page.tsx`, `app/gate/enter/route.ts` | Password form, signed host-only cookie, safe `next` redirect (D6) |
| Canonical URLs | `lib/site-url.ts` (+ test), `app/layout.tsx`, `lib/json-ld.ts`, the show and venue pages | `metadataBase`, canonical and JSON-LD `url` computed from configuration, never from the raw `Host` (D8) |
| Docs | `api-contract.md`, `data-model-initial.md`, `arch-initial.md`, `environments.md`, `conventions.md`, `apps/calendar/AGENTS.md`, `notes.md` | The slug, the hosts, the new variables, the scope row |
| Hosts | Vercel (Ari) | Gate password and zone variables per environment; `msp.staging.<domain>` and `msp.dev.<domain>` bound to `main` and `dev` (Step 6, needs the domain) |

What C4 does **not** do: scope any query by metro, add `metro_id` parameters or a `/metros` list, build a chooser page for more than one metro, attach `msp.<domain>` to Production (C11), the shared secret (C10), feature flags (C3.1 will pass `x-metro-slug` into `isEnabled`).

## Decisions

Recommended; Ari approves them by approving the plan. The rows marked ★ need Ari's answer (also listed under "Decisions for the user / reviewer").

| ID | Decision | Reason | Alternative and cost |
|---|---|---|---|
| **D1** | **The gate applies to `dev` and `staging` only.** `prod` is open (it is public at C11; until then Vercel's own protection covers its `*.vercel.app` URL). `local` is not gated (a laptop and the e2e stack are not worth a password). **`noindex` is sent in every environment except `prod`**, `local` included. The environment comes from `getAppEnv()`; if it throws (missing or inconsistent `APP_ENV`), every request answers 503 and says so, because a gate that cannot tell what it guards must not open. | Dep-D4: "non-production environments are gated … and send `noindex`", keyed on `APP_ENV`. Fail-closed is the C3-D7 lesson in reverse: that reader refuses to guess. `local` is excluded because `getAppEnv()` already refuses `local` on Vercel (a gate-free deployment cannot claim to be a laptop). | *Gate `local` too:* every `make dev` needs a password and the e2e stack must carry one. *Fail open on a bad `APP_ENV`:* a typo on staging would publish it. |
| **D2** | **Hosts: one zone per environment, configured; the slug is the one label left after stripping it.** Two server-only variables, set per environment: `SITE_ZONE` (the environment's own zone: `<domain>` in prod, `staging.<domain>`, `dev.<domain>`; **unset until a domain exists**) and `DEFAULT_METRO_SLUG` (`msp`). A host is classified as exactly one of: **outside** (not in the zone, or no zone configured: `*.vercel.app`, `localhost:3000`, `localhost:3100`) → the default metro, no redirect; **apex** (equals the zone) → redirect to the default metro's host (D5); **metro** (one valid, non-reserved label before the zone) → that slug; **bad** (several labels, an invalid or reserved label) → redirect to the apex. Host matching is on a **label boundary**, case-insensitive, port and trailing dot stripped. **A slug is 3–32 characters, `[a-z][a-z0-9-]*[a-z0-9]`** (Dep-D3's codes fit; longer aliases are allowed). The **reserved list is one JSON file**, `apps/calendar/lib/reserved-slugs.json` (`www`, `api`, `admin`, `dev`, `staging`, `app`, `mail`, `ftp`, `status`, plus any Ari adds); the TypeScript parser imports it and a Python test reads the same file and requires that no seeded slug is in it. | Dep-D2 gives the rule; the label boundary is why: `xdev.<domain>` and `msp.evildev.<domain>` must not parse as the dev zone. Outside hosts must work because previews, `localhost` and the e2e stack are all outside every zone (the plan's first test). One JSON file is the smallest thing that keeps two languages in step without generation; the API's deploy root (`apps/api`) cannot read it at run time, which is fine because only a CI test needs to. `dev` and `staging` are reserved because `dev.<domain>` is the dev zone's apex and must never parse as a metro of the production zone. | *Derive the zone from the first label of `Host`:* clever, and wrong for `localhost` and `*.vercel.app`. *Python as the source and TS generated:* the C3.1 pattern, heavier than a list of nine words. |
| **D3** | **`metro.slug` is `String`, `NOT NULL`, unique, with a `CHECK` on the format of D2, added by one migration** that adds the column nullable, backfills `msp` for the one metro (`name = 'Minneapolis/St. Paul'`), then sets `NOT NULL` and adds the unique constraint and the check. A database holding a metro the migration cannot name **fails loudly**, which is the intent. `Metro`, `MetroSummary`, the seed (`METRO_SLUG = "msp"`) and the sample world all carry it. | `GET /metro` carries the slug (spec). It is `NOT NULL` because a metro without one cannot have a host. Expand-contract (`arch-initial.md` §5): the API and worker do not redeploy together, but nothing but the seed and the tests inserts a `metro`, an old API only selects named columns, and the table has one row, so a single migration cannot break a deployed old service. Backfilling by name matches how the seed already finds the metro. The database owns the format so a hand-inserted `Bad_Slug` is refused whatever the code does. | *Nullable column:* a metro without a host is possible. *Two migrations (expand, then contract):* extra ceremony for one row; revisit if a second metro ever exists first. |
| **D4 ★** | **A slug inside the zone is checked against the live metro only when it is not the default.** The default slug (`msp`) is accepted from configuration with no API call, so the hot path adds no latency. Any other well-formed, non-reserved slug triggers one `GET /metro` from the proxy (short timeout), and is accepted only if it equals the returned `slug`; otherwise redirect to the apex. **If the API cannot answer, fail open** (treat as the default metro, no redirect), because an outage must not turn into a redirect storm and the page's own fetches will show the outage. | Spec: "an unknown slug inside an environment's zone goes to the chooser". The DB is the truth for which metros exist (D3), and the API serves it. With one live metro the extra call fires only for unknown slugs. | *(B) A configured list of slugs per environment* (`METRO_SLUGS`): no API call, no failure mode, but a second copy of what the database knows that must be edited with every metro. *(C) A time-limited in-memory cache:* contradicts the spirit of `B2-D1` (no persistent caching) for a lookup that is rare anyway. **Unverified, checked first in Step 2:** that `lib/api.ts` (`server-only`, React `cache`) can run inside `proxy.ts`; if not, the proxy uses a small `fetch` of its own against `API_BASE_URL`. |
| **D5** | **The apex "chooser" is a redirect, not a page, while one metro is live.** A request to the zone apex (any path and query) redirects 307 to `https://<DEFAULT_METRO_SLUG>.<zone><path>`; a bad host redirects to the apex, which redirects on. No `/choose` page and no `/metros` endpoint are built. The page arrives with the second metro, which will also need the list endpoint. | The spec: "redirects to `msp.` while one metro is live". 307 because it is temporary by design. Taking the target from configuration (not the API) keeps the apex working through an API outage. | *Build the page now:* UI and an endpoint with exactly one possible answer. |
| **D6** | **The gate is a shared password, checked by a route handler, remembered in a signed host-only cookie.** `SITE_GATE_PASSWORD` is a server-only secret set per environment (Vercel Preview, scoped by branch like `APP_ENV`, C3-D11); it is not in `Settings` (that is the API's) and is listed in `environments.md`. Unauthenticated requests redirect to `/gate?next=<path>` (non-GET/HEAD requests answer 401 instead). `POST /gate/enter` compares the submitted password to the configured one in **constant time**, and on success sets a cookie named **`__Host-gate`** (`Secure`, `HttpOnly`, `SameSite=Lax`, `Path=/`, **no `Domain`**, so host-only and the browser itself refuses to widen it, Dep plan §4.2), whose value is an HMAC (key: the password; message: `gate-v1:<APP_ENV>`), `Max-Age` 30 days, then redirects to `next` **only if it is a same-site path** (starts with a single `/`; not `//…`, not `/\…`, no scheme). Changing the password invalidates every cookie. **If `SITE_GATE_PASSWORD` is unset in a gated environment, the proxy answers 503 (fail closed).** The gate is a courtesy, not security (style guide: the proxy is not an auth boundary; the Railway API is public until C10): no rate limit, no per-user identity, so the password should be long. | Dep-D4 (app-level, any plan). HMAC over a constant makes the cookie unforgeable without the password and needs no session store or second secret. `__Host-` makes host-only a browser-enforced property, which is what keeps the environments from reading each other's cookies. A route handler is a pure request→response function and testable; a Server Action would POST to the page and be reachable around the matcher (style guide, Anti-patterns). | *HTTP basic auth:* no form, but the browser keeps no logout and `msp.staging` and `msp.dev` would each prompt unpredictably. *A cookie containing the password's hash:* a stolen cookie is the hash, which leaks the password's equivalent offline. |
| **D7** | **`noindex` is sent as an `X-Robots-Tag: noindex, nofollow` response header on every response from a non-`prod` environment, including the gate page and redirects, and mirrored in the `robots` metadata.** No `robots.txt` with `Disallow: /`. | A header covers non-HTML responses and the gate itself. A `Disallow` would stop crawlers from fetching a page to see its `noindex`, so a URL linked from elsewhere could still be listed bare; with the gate, crawlers see the gate page and its header and nothing else. | *`robots.txt` only:* does not remove an indexed URL and is advisory. |
| **D8** | **Canonical URLs, `metadataBase` and JSON-LD `url` come from configuration, not the `Host` header:** the origin is `https://<resolved slug>.<SITE_ZONE>`; with `SITE_ZONE` unset (the pre-domain state, and Production until C11) there is **no** `metadataBase`, no canonical and no JSON-LD `url`, rather than a wrong one. The root layout sets `alternates.canonical = "./"` (resolved against `metadataBase` per route). The resolved slug reaches pages as a request header `x-metro-slug` that **the proxy always overwrites** (a client-sent value is dropped, tested). JSON-LD gains `url` on events and the venue (`lib/json-ld.ts`'s header comment is revised). Non-production environments emit canonicals pointing at themselves (fine: `noindex`). | Spec: "come from the host". Echoing the raw `Host` makes a canonical-injection bug out of any request with a forged header; the host is trusted only after the parser has accepted it against the zone. A `*.vercel.app` alias of production then canonicalises to the real host. **Unverified, checked in Step 2 against `node_modules/next/dist/docs`:** that `alternates.canonical: "./"` resolves per route in this Next version. | *Read `Host` directly:* simple, forgeable. *Hard-code the origin in an env var per environment:* the slug is part of the host, so it would break at the second metro. |
| **D9** | **`current_metro` stays the lowest-id row; the host's slug does not reach the API.** C2-D5's docstring ("C4's slug lookup later replaces this function") is edited to say it did not and why. The slug is used by the frontend for the host check, canonical URLs and (C3.1) `isEnabled(name, { metro })`. | The spec keeps "scoping every query by metro" deferred (`arch-initial.md` §11), and with one metro an in-zone slug other than `msp` redirects (D4), so no request can reach the app asking for another metro's data. Replacing `current_metro` is the second metro's milestone, with the scoping it needs. | *Pass the slug to the API now:* the first half of multi-metro scoping with no second metro to test it on. |
| **D10 ★** | **Dev is verified to the gate, `noindex` and `/health` level in C4.** `msp.dev.<domain>` serves behind the gate with `APP_ENV=dev`, but its calendar shows the API-down shell, because dev has no Railway API (C3-D1). Staging gets the full check (calendar content). The calendar on the dev host waits for the dev API to be built (on demand, whenever the lane is next used). The Done-when's "serve their environments behind the gate" is read that way. | A dev API for a done-when check would spend the cost C3-D1 deferred, and the thing C4 builds (hosts, gate, `noindex`) is fully visible without it. | *Point Preview-`dev`'s `API_BASE_URL` at staging's API for the check:* shows content, but hides the dev/staging split C3-D11 draws and risks a "dev" host showing staging data as if it were dev's. *Build the dev API now:* a recurring cost for a check. |
| **D11** | **The slug change is its own early PR, on its own branch `c4-metro-slug`, merged before the rest.** The remaining C4 work is the milestone branch. | The spec: "in its own early PR, because the contract regenerates `lib/api-types.ts` and the fixtures" (`AGENTS.md`, "Parallel tracks"). It also gives the migration a separate, reviewable diff with a rollback story. A cloud session whose instructions name one branch (this plan's session did) may land both on that branch if Ari prefers one PR; say so in the PR's Review notes. | *One branch, one PR:* simpler, and the generated files then arrive with unrelated code. |

### Decisions for the user / reviewer

1. **D4 ★: how an unknown slug is recognised** (ask the API only for non-default slugs and fail open, versus a configured list). Recommended: the API check. If you would rather have no API call in the proxy at all, choose the list; the proxy and `C4-K2`'s input shrink and the unverified `server-only` question disappears.
2. **D10 ★: dev is checked without a calendar.** Recommended as written. Say if you want dev to point at staging's API for the check instead.
3. **D11: separate branch for the slug PR.** Recommended; one PR is acceptable.
4. **`C4-K1` and `C4-K2`: are two fill-in gaps the right number?** Dep-D15 says most infrastructure milestones are `[written]` with no gap. These two are the places in C4 where the design lives, are pure and fully testable, and are small (about ten lines each). Re-mark them `[written]` if you would rather not.
5. **The reserved-slug list** (D2): `www`, `api`, `admin`, `dev`, `staging`, `app`, `mail`, `ftp`, `status`. Add any word you want held back; it costs one line in a JSON file.
6. **The domain name** (Dep-D7) blocks only Step 6. If it is chosen before the code is done, Step 6 runs in the same session; otherwise Steps 1–5 close the milestone's code and the hosts wait.

## Test approach (written first, watched fail, then made green)

The plan's first test (`alpha-deployment-plan.md` §5.1, "First tests"): *host parsing*. Everything testable in C4 is pure (`metro-host.ts`, `request-plan.ts`, `gate.ts`, `site-url.ts`) or a function from `Request` to `Response` (the proxy glue and the gate route handler). Async Server Components are not unit-tested (`apps/calendar/AGENTS.md`).

| # | Test | File | Proves |
|---|---|---|---|
| **T1** | `parseHost` as a table. In a zone `dev.example.com` with default `msp`: `msp.dev.example.com` → metro `msp`; `MSP.Dev.Example.com:443` and `msp.dev.example.com.` → the same (case, port, trailing dot); `dev.example.com` → apex; `xdev.example.com`, `msp.evildev.example.com` and `example.com` → outside the zone (label boundary); `a.b.dev.example.com` → bad (two labels); `www.dev.example.com`, `staging.dev.example.com` → bad (reserved); `m.dev.example.com` and `-ab.dev.example.com` → bad (shape). With **no zone**: every host is outside. Outside hosts: `localhost:3000`, `localhost:3100`, `foo-abc.vercel.app`, `127.0.0.1`. The zone is a parameter, so the same table runs for `example.com` and `staging.example.com`, and a staging-zone host inside the production zone (`msp.staging.example.com` with zone `example.com`) is **bad**, not a metro. **`C4-K1` turns the "metro/apex/bad" rows green** | `lib/metro-host.test.ts` (new) | The parser strips exactly the environment's zone on a label boundary, and everything outside a zone is left alone so previews and `localhost` keep working. Expected values are written in the test from `alpha-deployment-plan.md` §4.2, not computed by the code |
| **T2** | The slug rules: shapes accepted and refused; every entry of `reserved-slugs.json` is refused; the JSON contains `www`, `api`, `admin`, `dev`, `staging` | same, plus `app/tests/test_metro_slug.py` (new, Python) for the seed and sample world: their slug matches the DB's format and is not in the reserved file | Dep-D3's reserved list is enforced once and a new seed slug is checked against it |
| **T3** | `decideRequest` as a table over (app env, host class, cookie valid, password set, path, liveness answer). Rows: `prod` + any host → next, no `noindex`; `staging` + no cookie + page → redirect to `/gate?next=…`; same on an **unknown slug host** → still the gate (not a redirect to the apex); `/gate` and `/gate/enter` → next without a cookie; `staging` + cookie + apex → 307 to the default metro host; + valid non-default slug whose liveness answers "no" → redirect to apex; "unknown/outage" → next; default slug → next with **no liveness call** (the fake is asserted not called); `dev` + no password configured → unavailable; `getAppEnv()` threw → unavailable; `local` + any → next with `noindex`, no gate; non-GET without cookie → 401. **`C4-K2` turns the order-dependent rows green** | `lib/request-plan.test.ts` (new) | The order of the checks (the gate first, so an unauthenticated visitor learns nothing about which metros exist) and the fail-closed rows. Expected actions are written in the table |
| **T4** | `gate.ts`: cookie value is deterministic per (password, env) and differs across both; a tampered, empty or other-environment cookie is invalid; `safeNextPath` accepts `/`, `/venue/3?x=1`, refuses `//evil.com`, `/\evil.com`, `https://evil.com`, `javascript:…`, an empty string and a missing value (→ `/`); the password comparison is constant-time (asserted by calling `timingSafeEqual` through a spy, not by timing) | `lib/gate.test.ts` (new) | A forged cookie, an open redirect and a prefix-match comparison are each ruled out |
| **T5** | The proxy glue with a real `NextRequest`: it overwrites a client-sent `x-metro-slug`; sets `X-Robots-Tag` on a next, a redirect and the gate response in `staging`, and on none in `prod`; the `config.matcher` matches `/`, `/health`, `/venue/3`, `/gate` and does **not** match `/_next/static/x.js`, `/_next/image`, `/favicon.ico` (checked with Next's own matcher test helper, name verified in Step 2) | `proxy.test.ts` (new) | The wiring, which the pure tests cannot see, and that the matcher covers every page including `/health` |
| **T6** | `gate/enter` handler: wrong password → redirect back to `/gate` with an error flag and **no** `Set-Cookie`; right → `Set-Cookie` has `__Host-gate`, `Secure`, `HttpOnly`, `SameSite=Lax`, `Path=/`, `Max-Age`, **no `Domain`**, and redirects to a safe `next` (or `/` for an unsafe one); unset password → 503 | `app/gate/enter/route.test.ts` (new) | The cookie is host-only by construction (Dep plan §4.2) and the redirect cannot leave the site |
| **T7** | `siteOrigin(zone, slug)`: `https://msp.staging.example.com`; `null` with no zone; `showJsonLd`/venue JSON-LD carry `url` when given an origin and omit it otherwise; the Next `Metadata` builder sets canonical only when an origin exists | `lib/site-url.test.ts` (new), `lib/json-ld.test.ts` (edit) | D8: nothing is emitted from the raw `Host`, and pre-domain pages carry no URL rather than a wrong one |
| **T8** | Python: the model has `slug` (`NOT NULL`); the migration upgrades and downgrades (`test_db_schema.py`'s round trip) and **backfills `msp` on a pre-existing row**; a duplicate slug and `Bad_Slug`/`ab`/`-abc` are refused by the database; `GET /metro` returns `slug`; `test_fixtures_agree.py` still passes; `make types` and `make fixtures` regenerate `metro.json` and the venue payloads' nested metro with the slug and `make contract-check` is clean | `app/tests/test_db_schema.py`, `app/tests/test_routers.py`, `app/tests/test_metro_slug.py` (edits and new) | D3, and that the backfill works on the data that exists in Neon (the migration test inserts the row *before* upgrading) |
| **T9** | The e2e stack (`APP_ENV=local`) is **not** gated and sends `X-Robots-Tag: noindex, nofollow`; the existing specs stay green on `localhost:3100` (an outside host → the default metro) | `e2e/home.spec.ts` or a new `e2e/non-production.spec.ts` | Hosts outside every zone resolve to the default metro and the local gate is off, in the real server, not only the unit tests |

**Mutation checks to run once green** (by hand, not committed; `C2-M1`-style): make the parser match on a suffix without the label boundary; run the gate check after the metro redirect; make `safeNextPath` accept `//x`; drop `Secure`/`__Host-` from the cookie; compare passwords with `===`; make a non-GET unauthenticated request pass. Each must turn a named test red. The build step records the results in the Implementation log.

## Implementation steps

Ordered so that the gate is proven before a domain makes a host public, and the schema change merges before the code that reads it. Steps 1–4 are cloud work; Steps 5–7 are Ari's, with Claude walking through; Step 6 waits on a chosen domain.

### Step 1 — `metro.slug`, its own PR on `c4-metro-slug` [written]

Test-first (T8). `Metro.slug`, one Alembic migration (D3), `seed.py` (`METRO_SLUG`), `MetroSummary.slug`, `sample_data.py` (`METRO` carries `slug="msp"`), the four test files that construct `Metro(...)` (`test_sample_data_loader.py` ×2, `test_routers.py`, `test_db_schema.py`), `make types` and `make fixtures`. Update `api-contract.md` (§2 table and §6 fixtures), `data-model-initial.md` (`metro`), and edit `current_metro`'s docstring (D9). Check: `make check`; `make types`/`make fixtures` produce only the slug diff; the migration runs against a database that already holds the one metro. **Not merged until:** Ari has run `APP_ENV=<env> DATABASE_URL=… uv run alembic upgrade head` against Neon `staging` first (the pre-deploy step does it on staging's next deploy anyway; run it by hand once to read the result) and then the pre-deploy step handles production. Never apply it to the dev branch from this PR's branch before it is merged (C3's rule): dev stays at its stamp until the PR merges.

### Step 2 — Code on the milestone branch [written, two fill-in gaps]

First, three short checks recorded in `notes.md` as found: (a) read `node_modules/next/dist/docs` for `proxy.ts` (what may be imported, Node runtime, the matcher test helper's name), `alternates.canonical` and `metadataBase`; (b) try importing `lib/api.ts` from `proxy.ts` in `next build` (D4's unverified); (c) confirm `headers()` is allowed inside `generateMetadata` in this version. Then in test-first order, each watched fail:

1. `lib/reserved-slugs.json` and `lib/metro-host.ts` (T1, T2). **[fill-in] `C4-K1`:** the zone-stripping body of `parseHost`.
2. `lib/gate.ts` (T4).
3. `lib/request-plan.ts` (T3). **[fill-in] `C4-K2`:** the order of the checks in `decideRequest`.
4. `lib/site-url.ts` and the Next `Metadata` and JSON-LD changes (T7); `app/layout.tsx` sets `metadataBase`, `alternates.canonical` and `robots` from them; `lib/json-ld.ts`'s header comment is revised.
5. `app/gate/page.tsx` (a plain form; `next` carried in a hidden field, never trusted) and `app/gate/enter/route.ts` (T6).
6. `proxy.ts` and its `config.matcher` (T5): reads `host`, `APP_ENV` through `getAppEnv()`, `SITE_ZONE`, `DEFAULT_METRO_SLUG`, `SITE_GATE_PASSWORD` and the cookie; calls `decideRequest`; performs the action; **deletes any incoming `x-metro-slug`** and sets its own.
7. T9 (the e2e stack needs no new variable: it is `APP_ENV=local` and outside every zone).
8. Docs: `environments.md` (the three new variables in the Next inventory, the hostnames as built, the cutover note for Step 6), `arch-initial.md` §9 (hosts and the gate), `apps/calendar/AGENTS.md` ("Where data and URL state live": the proxy, the host parser, the gate), `conventions.md` (the `C4` scope row), `notes.md` (what Step 2's checks found).

### Step 3 — Verify locally [written]

`make check`; the mutation checks; `make designation-check BASE=main`. Then the real server: `pnpm --filter calendar build`, then `APP_ENV=staging SITE_GATE_PASSWORD=x SITE_ZONE=staging.example.com next start` and `curl` with a `Host:` header: a page without the cookie answers a redirect to `/gate`; with the right password cookie answers 200 and `X-Robots-Tag`; `Host: staging.example.com` redirects to `msp.staging.example.com`; `Host: foo.staging.example.com` without the cookie answers the gate, and with it redirects to the apex; `APP_ENV=prod` answers pages with no `X-Robots-Tag`. Record the commands and results.

### Step 4 — Merge, then set the variables (Ari) [written]

Merge the slug PR (Step 1), then the milestone PR. **Staging deploys from `main`, so merging puts the gate in front of staging.** Before merging, set in Vercel, **Preview**, scoped to `main` (and to `dev` when it exists), the server-only `SITE_GATE_PASSWORD` (a long random value per environment; not committed, not pasted in chat), `DEFAULT_METRO_SLUG=msp`, and leave `SITE_ZONE` **unset**. Unset gate password with `APP_ENV=staging` answers 503 by design (D6), so an unset variable is visible, not open. Production: `DEFAULT_METRO_SLUG=msp` only; no gate password (prod is not gated), no `SITE_ZONE`.

### Step 5 — Prove the gate on `*.vercel.app` before any domain exists (Ari) [written]

On staging's and a PR preview's `*.vercel.app` URL: the page redirects to `/gate`; a wrong password is refused; the right one sets `__Host-gate` (read it in the browser's storage panel: `Secure`, `HttpOnly`, no domain) and lands back on the page; a `next` pointing at another site lands on `/`; `/health` is behind the gate; the response carries `X-Robots-Tag: noindex, nofollow`. These pages are *also* behind Vercel's login, so test in a private window signed out of the app gate but signed in to Vercel, or with `vercel curl`. **Do not add a domain until this passes.**

### Step 6 — DNS and hosts (Ari; needs the chosen domain) [written]

Register the name and point the nameservers at Vercel (Dep-D7). Then, in the Vercel project: add **`msp.staging.<domain>`** bound to branch `main`, set Preview `SITE_ZONE=staging.<domain>` for `main`; create the `dev` branch (a lane, Dep-D8), add **`msp.dev.<domain>`** bound to `dev`, set `SITE_ZONE=dev.<domain>` and `APP_ENV=dev` for the `dev` branch. Record which Hobby limits applied (branch-bound domains; whether wildcards need Vercel's nameservers: not needed here, the hosts are added one by one) in `notes.md`. **Do not add `msp.<domain>` or the apex to Production** (Dep-D11, C11). The apex of the *environment* zones (`staging.<domain>`, `dev.<domain>`) is added only if the redirect (D5) is wanted before C11. Checks: the matrix in Verification 5.

### Step 7 — Close (Claude) [written]

Fills `environments.md`'s current-state section from what Ari recorded; Implementation log; `AGENTS.md` is unchanged unless Ari wants the hosts named in "Current phase".

## `TODO(Ari)` gaps

Two, `C4-K1` and `C4-K2`. Everything else in C4 is `[written]` (Dep-D15). Both are pure functions with red tests; neither is called at import, so unlike `C3-K1` they use the usual `throw new Error("TODO(Ari)")` placeholder.

**`C4-K1` — host to metro: strip the environment's zone on a label boundary** (`lib/metro-host.ts`, `parseHost`).
- **Key point of interest:** the environment is the *parent zone*, and the remainder after removing it is the slug (`Dep-D2`, `alpha-deployment-plan.md` §4.2). The match must be on a **label boundary**: `endsWith("." + zone)` or equal to the zone, never a bare `endsWith(zone)`, or `xdev.example.com` parses as the dev zone. What is left must be exactly one valid, non-reserved label; anything else inside the zone is "bad", and anything outside the zone (or with no zone configured) is "outside", left alone.
- **Code (near-exact, for the scaffold's comment):**
  ```ts
  const h = host.toLowerCase().replace(/:\d+$/, "").replace(/\.$/, "");
  if (!zone) return { kind: "outside" };
  if (h === zone) return { kind: "apex" };
  if (!h.endsWith("." + zone)) return { kind: "outside" };
  const label = h.slice(0, -(zone.length + 1));
  if (!isValidSlug(label) || RESERVED.has(label)) return { kind: "bad" };
  return { kind: "metro", slug: label };
  ```
  (`isValidSlug` and `RESERVED` are written around it; a label containing `.` fails `isValidSlug`, which is what makes `a.b.zone` "bad".)
- **Check:** `pnpm --filter calendar test lib/metro-host.test.ts` (T1). The likeliest mistake: matching `endsWith(zone)` without the dot (the `xdev.example.com` row goes red), or lowercasing the zone but not the host, or stripping the port with a split on `:` that breaks an IPv6 literal (`[::1]:3000` is "outside", a row).

**`C4-K2` — the proxy's decision order: gate before metro redirect** (`lib/request-plan.ts`, `decideRequest`).
- **Key point of interest:** the *order* of five checks is the design, not any one of them. (1) An unreadable environment, or a gated environment with no password, is "unavailable" before anything else (fail closed, D1, D6). (2) The gate comes **before** the metro logic: an unauthenticated visitor to `anything.staging.<domain>` must get the gate, not a redirect to the apex, or the redirect tells a stranger which slugs exist (the differential is the leak) and the gate stops being the first thing a stranger meets. (3) `/gate` and `/gate/enter` pass without a cookie, or nobody can log in. (4) Only then host handling: apex and bad hosts redirect, a non-default in-zone slug is checked for liveness (D4; fail open on "unknown"), the default slug is accepted *without* asking. (5) `noindex` is a property of the environment, attached to whatever action results.
- **Code (near-exact):**
  ```ts
  if (!env.ok || (gated(env.value) && !input.password)) return { action: "unavailable" };
  const noindex = env.value !== "prod";
  if (gated(env.value) && !isGatePath(input.path) && !input.cookieValid)
    return { action: input.method === "GET" || input.method === "HEAD" ? "redirect-gate" : "deny", noindex };
  if (host.kind === "apex") return { action: "redirect-metro", slug: input.defaultSlug, noindex };
  if (host.kind === "bad") return { action: "redirect-apex", noindex };
  if (host.kind === "metro" && host.slug !== input.defaultSlug && (await input.isLiveSlug(host.slug)) === false)
    return { action: "redirect-apex", noindex };
  return { action: "next", slug: host.kind === "metro" ? host.slug : input.defaultSlug, noindex };
  ```
- **Check:** `pnpm --filter calendar test lib/request-plan.test.ts` (T3). The likeliest mistake: handling the host first (the "unknown slug without a cookie still gets the gate" row goes red), or calling `isLiveSlug` for the default slug (the "no call" assertion goes red), or treating `isLiveSlug` returning `null` (outage) as "not live" (the fail-open row).

## Critical files

| File | Change |
|---|---|
| `apps/api/app/db/models/calendar.py`, `migrations/versions/<new>.py`, `app/db/seed.py`, `app/schemas.py`, `app/testing/sample_data.py`, `app/dependencies.py` (docstring only) | `metro.slug` (Step 1) |
| `apps/api/app/tests/test_db_schema.py`, `test_routers.py`, `test_sample_data_loader.py`, `test_metro_slug.py` (new) | T2, T8 |
| `apps/calendar/lib/api-types.ts`, `lib/fixtures/*.json` | Generated; never hand-edited (`make types`, `make fixtures`) |
| `apps/calendar/lib/reserved-slugs.json`, `lib/metro-host.ts`, `lib/request-plan.ts`, `lib/gate.ts`, `lib/site-url.ts` (+ tests) | New pure modules |
| `apps/calendar/proxy.ts` (+ test), `app/gate/page.tsx`, `app/gate/enter/route.ts` (+ test) | New |
| `apps/calendar/app/layout.tsx`, `lib/json-ld.ts`, `app/show/[id]/page.tsx`, `app/venue/[id]/page.tsx` | `metadataBase`, canonical, `robots`, JSON-LD `url` |
| `apps/calendar/e2e/…` | T9 |
| `docs/dev/environments.md`, `docs/dev/api-contract.md`, `docs/arch/data-model-initial.md`, `docs/arch/arch-initial.md`, `docs/dev/conventions.md`, `apps/calendar/AGENTS.md`, `docs/dev/notes.md` | Docs (Steps 1, 2, 7) |
| `.github/workflows/ci.yml` | Unchanged (named so the reviewer can confirm) |

## Verification

1. `make check` green; `make types` and `make fixtures` change only the slug (D3); `make contract-check` clean.
2. T1–T9 and the mutation checks, as above.
3. `make designation-check BASE=<the diff base the Implementation log names>` clean.
4. The `curl` matrix of Step 3 against a real `next start`.
5. **In the dashboards** (each recorded in `environments.md`): staging's `*.vercel.app` URL gates and sends `noindex` (Step 5); once the domain exists, `msp.staging.<domain>` shows the gate, then the calendar after login, with `X-Robots-Tag` and a canonical of `https://msp.staging.<domain>/…`; `staging.<domain>` (if added) redirects to `msp.`; `foo.staging.<domain>` shows the gate, then redirects to the apex; `msp.dev.<domain>` shows the gate and `/health` reports `dev` (D10: no calendar); Production is untouched: no `msp.<domain>`, no `SITE_GATE_PASSWORD`.
6. A force of the trap: temporarily unset `SITE_GATE_PASSWORD` on a preview and confirm it answers 503, not the open site.

## Not doing in C4

- Any query scoping by metro, a `metro_id` parameter, a `/metros` list, a chooser page (D5, D9).
- Attaching `msp.<domain>` or the production apex (C11); a sitemap or `robots.txt`.
- The shared secret between Next and the API (C10): the Railway API stays public, so the gate protects the pages only.
- Rate limiting or per-user login on the gate (D6).
- Wildcard domains or certificates: hosts are added one by one.
- Feature flags (C3.1 consumes `x-metro-slug` later); a dev API (D10).

## Plan review

## Implementation log

## Code review
