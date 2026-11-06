# apps/api

The Python half of the Agentic Live Music Calendar, a live music calendar for Minneapolis/St. Paul. Scheduled agents
read venue calendar pages, extract show listings with a language model, validate and reconcile them, and store the
result. A Next.js app (`apps/calendar/`) renders the calendar from this directory's read API.

## What's here

| Path | What it is |
|---|---|
| `app/` | The FastAPI read API. It serves shows, venues, artists and the calendar to the frontend. It also holds the shared configuration (`config.py`), the database models and session (`db/`) and the response schemas (`schemas.py`), which are the API contract |
| `agent_worker/` | The extraction pipeline: a LangGraph graph run as a scheduled batch job, one run per venue (fetch → extract → validate → reconcile → commit, or escalate). It imports from `app/`. Production code in `app/` never imports from it (one test in `app/tests/` does, to check staging) |
| `agent_worker/model_eval/` | Measurement only: scores a model, or the whole pipeline, against hand-labeled venue pages. Nothing on the scheduled path imports it (see its `README.md`) |
| `migrations/` | The Alembic history for the one Postgres schema that both halves share |
| `scripts/` | One-off commands: seed the starting venues, dump the OpenAPI schema, generate the frontend's fixtures, rehearse a migration on a Neon branch |

## Running it

Python 3.13 and [uv](https://docs.astral.sh/uv/). Postgres and MongoDB run in Docker. The commands below run from the
**repository root**, and `make help` lists the rest.

```bash
make setup     # first time: install dependencies, start the databases, migrate and seed
make api       # the API alone, with reload, on port 8000 (make dev runs the API, the frontend and Postgres together)
make seed      # re-seed the metro and the starting venues (safe to re-run)
make worker    # one worker run over every venue, or VENUE=<id>; needs make db-up and a model endpoint (Ollama locally)
```

Configuration comes from the environment and `apps/api/.env` (`make setup` creates it from `.env.example`).
`app/config.py` lists every variable and refuses to start when the settings don't match the environment it's
running in.

## Testing and checks

```bash
make check     # everything CI runs: ruff, mypy, pytest, vitest, the contract check, the designation check, Playwright
make test      # pytest (database tests required) and vitest
make format    # auto-format the Python code; make lint and CI fail on unformatted code
```

Inside `apps/api`, `uv run pytest`, `uv run ruff check .` and `uv run mypy` run the Python checks alone. The pytest
database tests run against a real Postgres and skip if it's down. `make test` and `make check` refuse to pass with them
skipped.

## Read next

- `AGENTS.md` in this directory: how this code differs from stock FastAPI and LangGraph practice, and why
- `docs/references/fastapi-style-guide.md`: the idiom this code follows, and its Anti-patterns review checklist
- `docs/arch/arch-initial.md` (architecture), `docs/arch/data-model-initial.md` (schema),
  `docs/dev/api-contract.md` (the API's shape)
- The repository's root `AGENTS.md`: the documentation map and the development process
