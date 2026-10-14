# Agentic Live Music Calendar

A browsable, consolidated live music calendar for Minneapolis/St. Paul. Scheduled AI agents read each venue's own calendar page once a day, extract the listed shows with a local open-weight model, validate and reconcile them against what is already stored, and a Next.js frontend renders the result.

It is also a learning project: agent orchestration, validation of agentic output, auditability, and Python and React/Next.js built from scratch. Focus is on local and indie acts and smaller venues that national listing sites miss.

## About the Owner

Ari Koinuma is a software engineering leader based in St. Paul, Minnesota. He spent 15 years delivering software for enterprise clients, most recently as a Director of Software Engineering at a Big 4 consulting firm. He is also a freelance musician on the side and wanted a live music calendar that covers the small rooms and local artists. He defines the requirements, architects all layers, sets the accuracy standards, directs Claude Code, and explores how to work effectively with AI to build software. 

This application is intentionally built robustly: audit trails, accuracy gates and tests that fail loudly. That discipline is how Ari is learning to run an agentic system in production. Other metro areas are possible later, once the Twin Cities version works.

## How it fits together

| Piece | Path | Role |
|---|---|---|
| Calendar | `apps/calendar` | Public Next.js app. The only thing the browser talks to. Server Components call the API server-to-server |
| API | `apps/api/app` | FastAPI service: reads and writes calendar data, serves `/docs` |
| Agent worker | `apps/api/agent_worker` | Daily fetch → extract → validate → reconcile → commit pipeline (LangGraph) |
| Postgres | Docker locally, Neon hosted | Canonical calendar data and the append-only audit trail |
| Shared UI | `packages/ui` | `@repo/ui`, shadcn components used by the calendar |

The architecture is documented in `docs/arch/`:

- [project-overview.md](docs/arch/project-overview.md): the problem, and what the system must do
- [requirements-initial.md](docs/arch/requirements-initial.md): each screen, and the agent's rules for extraction, validation and reconciliation
- [arch-initial.md](docs/arch/arch-initial.md): how it is built and why, including hosting, the agent pipeline and the audit trail
- [data-model-initial.md](docs/arch/data-model-initial.md): the Postgres schema

The full documentation map, with the implementation logs for each milestone, is in [AGENTS.md](AGENTS.md) and `docs/dev/`.

## Running it locally

```sh
make setup   # first time only: install deps, start Postgres, migrate, seed
make dev     # Postgres + FastAPI (:8000) + Next.js (:3000) together; Ctrl-C stops them
make check   # everything CI runs — do this before calling something done
```

`make help` lists every target. One file isn't created for you: the calendar needs
`apps/calendar/.env.local` (git-ignored) containing

```
API_BASE_URL=http://localhost:8000
```

Open <http://localhost:3000>. The API's own browsable docs are at <http://localhost:8000/docs>.

Commands you'll use most:

```sh
make types            # regenerate apps/calendar/lib/api-types.ts after changing app/schemas.py
make migration m="…"  # autogenerate an Alembic migration
make db-shell         # psql against local Postgres
```

Don't hand-edit `apps/calendar/lib/api-types.ts` or `apps/calendar/lib/fixtures/`. Both are generated from `apps/api/app/schemas.py` and `app/sample_data.py`, and `make contract-check` (part of `make check`) fails if they are stale.

## When something looks wrong

**The browser never talks to the API.** The Next.js *server* does (the pages are Server
Components that run on it), then sends back finished HTML. So the browser's Network tab shows only
the page itself and one `?_rsc=` fetch per filter change; the API calls are invisible there. Look
in these places instead, in order. The first three need no debugger.

| # | Question | Where to look |
|---|---|---|
| 1 | Did Next get the right URL? | The address bar, and the `GET /?venue=3 200 in …` line in the **Next terminal** |
| 2 | What did Next ask the API for, and what came back? | The **Next terminal**: one `[api] GET /shows?venue_id=3 -> 200 in 41ms` line per API call, then a one-line summary of the response, e.g. `body (2.0 KB): 6 shows (…); 0 without start_time; 0 with empty lineup; …`. Null fields are listed at the end of the summary |
| 3 | What does the API itself return? | Skip the UI: `curl -s 'localhost:8000/shows?venue_id=3' \| jq`, or open <http://localhost:8000/docs> and use "Try it out" for a collapsible JSON tree. The **uvicorn terminal** has one access-log line per call |
| 4 | The data is right but the page is wrong | It's the Next code. Use the debugger (below), or a `console.log` in a Server Component, which prints in the Next terminal, not the browser |

**See the full response JSON.** The summary is the default so logs stay short and searchable. To
log each response body in full, on one line (cut at 4000 characters), add this to
`apps/calendar/.env.local` and restart the Next.js server:

```
LOG_API_BODIES=1
```

It is ignored in production builds: hosted logs get summaries only. Remove the line (or set it to
`0`) to turn it off.

**Step through the code.** `.vscode/launch.json` has debug configs for the API, the Next.js
server and the browser. Stop `make dev` first (they use the same ports), then pick
`Full stack: API + Next.js server` in VS Code's Run and Debug panel. The guided trace of one page
load, with the exact breakpoints to set, is [docs/dev/debugging.md](docs/dev/debugging.md).

## JavaScript and TypeScript tasks (Turborepo)

Turborepo runs the JS/TS side of the repo. The Python API has its own tooling (uv, ruff, mypy, pytest) and sits outside the Turborepo pipeline.

```sh
pnpm build                                   # build all JS/TS apps and packages
pnpm exec turbo dev --filter=calendar        # run only the calendar app's dev server
pnpm exec turbo lint                         # lint every JS/TS package
```

Shared configuration lives in `packages/eslint-config` and `packages/typescript-config`. Tooling: TypeScript for type checking, ESLint for linting, Prettier for formatting (`pnpm format`).

## Conventions

Read [AGENTS.md](AGENTS.md) before contributing. The short version:

- Comments explain *why*, not just *what*. Each module opens with a docstring saying what it is.
- Every change ends with `make check` passing.
- Design decisions are written down in `docs/arch/` and `docs/dev/notes.md`. Check there before proposing an approach.

## Useful links

- [Turborepo: tasks and filtering](https://turborepo.dev/docs/crafting-your-repository/running-tasks)
- [Next.js documentation](https://nextjs.org/docs)
- [FastAPI documentation](https://fastapi.tiangolo.com/)
