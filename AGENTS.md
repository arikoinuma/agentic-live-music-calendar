# Agentic Live Music Calendar

An agentic live music calendar for Minneapolis/St. Paul: scheduled agents read venue
calendar pages, extract show listings with a local open-weight model, validate and
reconcile them, and a Next.js frontend renders the result. Also a deliberate learning
project — agent orchestration, validation of agentic output, auditability, Python, and
React/Next.js from scratch.

## Read before writing code

Language-specific style guides live in `docs/references/`. **Read the relevant one before
non-trivial work in that stack** — both are current, repo-aware, and contradict a lot of
stale training data (Next.js 16 and FastAPI/Pydantic v2 both moved recently).

| Stack | Guide | Also read |
|---|---|---|
| Python / FastAPI / agents | `docs/references/fastapi-style-guide.md` | `apps/api/AGENTS.md` |
| Next.js / React / Tailwind | `docs/references/nextjs-style-guide.md` | `apps/calendar/AGENTS.md` |

Each guide ends with an **Anti-patterns** table of mistakes agents actually make. When
reviewing a diff in that stack, check it against that table.

## Documentation map

Design decisions are already made and written down. Check here before proposing an
approach — most "what should we do about X" questions have an answer with reasoning.

| Question | Document |
|---|---|
| What is this and what must it do? | `docs/arch/project-overview.md` |
| What does each screen do? | `docs/arch/requirements-initial.md` |
| How is it built, and why? | `docs/arch/arch-initial.md` |
| What's the database schema? | `docs/arch/data-model-initial.md` |
| What's the API's shape? | `docs/dev/api-contract.md` |
| What are we building next? | `docs/dev/alpha-build-plan.md` |
| What comes after that — the hosted alpha? | `docs/dev/alpha-deployment-plan.md` |
| How was the environment set up? | `docs/dev/env-setup.md` |
| What non-obvious thing bit us before? | `docs/dev/notes.md` |
| How is a given milestone being implemented? | `docs/dev/implementations/` |
| What does a designation like `A2.1-D5` or `v0.1-G6` mean, and how do I write one? | `docs/dev/conventions.md` |

When a real debugging session turns up something non-obvious, add it to `docs/dev/notes.md`.
When a design decision gets made, record it where the surrounding reasoning lives.

## Commands

`make help` lists everything. The ones that matter:

```
make dev              # Postgres + FastAPI + Next.js together
make check            # everything CI runs — do this before claiming done
make types            # regenerate lib/api-types.ts after changing app/schemas.py
make migration m="…"  # autogenerate an Alembic migration
make db-shell         # psql against local Postgres
```

Never hand-edit `apps/calendar/lib/api-types.ts` or `apps/calendar/lib/fixtures/` — both
are generated from `apps/api/app/schemas.py` and `app/sample_data.py`. `make contract-check`
(part of `make check`, and its own CI job) fails if they're stale.

## Layout

```
apps/api/        FastAPI service + agent worker (Python, uv) — outside Turborepo
apps/calendar/   Public Next.js app, port 3000
apps/admin/      Untouched template; no v1 role (arch-initial.md §7)
packages/ui/     @repo/ui — shared shadcn components
docs/            Architecture, dev runbooks, style guides
```

Turborepo governs the JS/TS task graph only. `apps/api` has its own tooling (uv, ruff,
mypy, pytest) and is not in the pipeline.

## Conventions

- **Comments explain why, in addition to what.** This codebase is unusually comment-dense on purpose:
  it's a learning project, and the reasoning behind a decision is the point. Match that —
  but comment the non-obvious choice, not the obvious line.
- **Every file is understandable to an engineer who has never seen this app.** Each module
  opens with a docstring saying what it is and how to read it. Each class, function, and
  logical block says what it is for at a high level, so nobody has to reverse-engineer a
  chunk of code to learn its role. This sits alongside the "why, not what" rule: explain
  the purpose of a block, not the syntax of its lines.
- **Tests state what they prove.** Every test opens with a comment beginning `Proves:`
  that says what behavior it pins down and why that matters, plus the failure it would
  catch where that isn't obvious. Group tests under labelled section comments, and explain
  each helper and fixture in plain terms. Tests that read their expectations from the code
  under test can't catch that code being wrong, so say where the expected values come from.
- **Comment-only passes must not change code.** When adding or revising comments across
  files, snapshot the files first and compare syntax trees (ignoring comments and
  docstrings) afterwards, then run `make check`. See A1's comment pass for the pattern. Taking the
  scaffold out of filled `TODO(Ari)` blocks is one of these passes.
- **Cite the source of a decision.** When code implements something a doc specifies, name
  the doc and section. When it deliberately departs, say so and why.
- **Verify, don't assume.** Claims in this repo's docs were checked against real behavior.
  Keep that standard: run it before saying it works.
- **Cross-references carry a scope.** When a document cites an item from another document,
  the ID carries that document's scope: `A2.1-D5` (decision), `A2-F9` (eval failure), `A3-K2`
  (fill-in key point), `A3-PR1-3` (plan-review item), `A3-CR1-3` (code-review item), `v0.1-G6` (catalogue gap). Inside the
  defining document, a bare ID is fine. The build-plan catalogue is written `v0.1-G<n>` in
  every other document. The full forms, the mapping from the old gap letters, and the check
  command are in `docs/dev/conventions.md`.
- **Commit attribution names the model.** Git commit messages end with the trailer
  `Co-Authored-By: Claude <model name>` (for example `Co-Authored-By: Claude Haiku 5.5`), with
  no email address. Model names are allowed in commits, PR titles and PR bodies.

## Current phase

`docs/dev/alpha-build-plan.md` is the active plan: get the whole thing running locally, with
real agent writes and a real calendar UI. Two tracks (Python/agent, Next.js) meeting at the
API contract. Nothing hosted is in scope — Vercel, Railway, and Neon are deployed and left
alone. Hosted work, including the extraction accuracy work that needs a larger hosted model
(A2.1's open gap), belongs to the next phase, `docs/dev/alpha-deployment-plan.md` (milestones H1–H4).

Tasks in that plan are marked **[fill-in]** or **[written]** (write it complete, then walk
through it). Respect the marking — the next section is what [fill-in] means in practice.

## [fill-in] tasks — Ari types the lines that carry the lesson

A task is marked [fill-in] because a few lines in it teach something that reading finished code
doesn't. **The deliverable for a [fill-in] task is a scaffold with deliberate gaps, not working
code.**

1. **Write everything around the lesson** — imports, types, signatures, wiring, markup,
   boilerplate, and the tests (which stay red).
2. **Leave the 1–3 spots where the concept lives as `TODO(Ari)` blocks**, each a few lines at
   most. Every block has three parts:
   - **Lesson** — the idea, and why it's done this way *here*, citing the doc that decided it.
   - **Code** — the near-exact lines, in a comment, complete enough to type or paste. Speed
     matters (Oct 8 update): a gap should cost minutes, not research.
   - **Check** — the test that goes green when it's right (if it's a testable area), 
   and the most likely way to get it wrong.

   The placeholder must fail loudly (`raise NotImplementedError("TODO(Ari)")` /
   `throw new Error("TODO(Ari)")`) so the tests stay red rather than passing by accident, if it makes
   sense for the line of code to have tests against them. But it is not a firm requirement that
   every `TODO(Ari)` be testable. Prioritize learning higher. 
3. **Stop and hand off**: list each `TODO(Ari)` as a file:line link with its one-line lesson,
   plus the command that runs its tests. Don't fill them in. Tell Ari the cleanup in step 4 follows
   once the gaps are closed.
4. **After a gap is filled, take the scaffold out.** The lesson blocks are teaching aids, not
   documentation: once the code is real they come out, and the code keeps only ordinary comments.
   The lesson, the code and the check stay on record in the implementation plan (its `TODO(Ari)`
   gaps section and the Implementation log), so the source doesn't need to carry them. Whoever
   fills a block does this in the same change; when Ari fills them himself, a Claude pass follows
   his commit and comes before sign-off ("clean up the closed gaps in `<milestone>`"). The pass:
   - Rewrite each block as a plain why-comment in the style of its neighbours: drop `TODO(Ari)`,
     the `Lesson:` / `Code:` / `Check:` labels, test-command pointers, the "likeliest mistake"
     list and any "replace the `todo` line" instructions. **Keep the reasoning** (why it is done
     this way here, the doc that decided it, what goes wrong otherwise) as sentences of rationale.
   - Keep the plan-level references, written as K-forms (`A3-K4`; see `docs/dev/conventions.md`).
     A key point the plan names stays where it helps a reader follow the plan: a test section
     header, a `Proves (…)` line, a module docstring's reading order. The old letter becomes its
     K number, and what goes is the scaffolding: `TODO(Ari)` markers and "stay red until Ari fills
     …" notes in test docstrings.
   - Delete the placeholder helper (`lib/todo.ts`) once no gap calls it, along with any import or
     `noqa` the scaffold left for the gap.
   - It is a comment-only pass, so verify it as one (see Conventions): compare syntax trees before
     and after, then `make check`.

A scaffolded block (step 2) looks like this:

```python
# TODO(Ari) — Lesson: the soft delete only considers shows inside the window this fetch covered
#   (data-model-initial.md, set-diff). A page listing two weeks must not "remove" week three.
# Code:
#   covered = {s.key for s in stored if window.start <= s.date <= window.end}
#   removed = covered - {e.key for e in extracted}
# Check: test_reconcile.py::test_soft_delete_respects_window — forgetting the window filter
#   deletes every show past the page's horizon.
raise NotImplementedError("TODO(Ari)")
```

**"Go ahead", "implement B2", "proceed with the plan" mean: carry out the plan, and for
[fill-in] steps the plan is the scaffold.** They don't give permission to fill `TODO(Ari)`
blocks. Fill a block only when Ari asks for that block (or file) by name — "fill in the TODOs in
`reconcile.py`", "complete it for me". When you do, clean up the block as step 4 below says.

**Picking the gaps:** choose lines where the concept lives, not where most of the typing is.
Good gaps: the `searchParams` → API-query mapping, the composite-key match that decides insert
vs. update, the routing function's branch conditions. Bad gaps: JSX markup, import lists,
Pydantic field declarations. If no line in a [fill-in] task meets that bar, say so in the
implementation plan and propose re-marking it [written] — don't invent a gap.

Implementation plans (below) name each [fill-in] step's `TODO(Ari)` blocks and their lessons, so
the reviewer can check that the gaps are the right ones.

## Implementation plans — written down, reviewed by a different model

Before non-trivial implementation work (any milestone in the build plan), **do not start
coding from a plan that only exists in a chat or a scratch file.** The plan file,
`docs/dev/implementations/<milestone>-<slug>.md` (e.g. `a1-data-layer.md`), is also **the only
channel between author and reviewer**: each one reads the file, does its part, writes the result
into the file, updates the header `Status`, and stops. Ari's prompts can then be one line ("review
`b2-…md`", "resolve the review in `b2-…md`") with nothing pasted between models.

### The cycle

| Step | Who | Writes | Then sets Status to |
|---|---|---|---|
| 1. Plan | Author | Context, test approach, steps (naming each `TODO(Ari)` gap — see above), critical files, verification | `Plan review` |
| 2. Plan review | Reviewer | A new round under `## Plan review` | `Plan review: findings open` |
| 3. Resolve | Author | The Resolution column of that round, plus the plan edits it describes | `Awaiting approval` (or `Plan review` if a fix needs another round) |
| 4. Approve | **Ari** | — | `Approved` |
| 5. Implement | Author | Code and tests; at the end, a new round under `## Implementation log` | `Code review` |
| 6. Code review | Reviewer | A new round under `## Code review` | `Code review: findings open` |
| 7. Resolve | Author | Fixes, plus the Resolution column | `Awaiting sign-off` (or `Code review` for another round) |
| 8. Sign off | **Ari** | — | `Done` |

Only Ari moves the status past steps 4 and 8. The header records the status, the date, the
author model, and the reviewer model for each round.

**Steps 1–3 and 5–7 run unattended**, via `/plan-milestone <milestone>` and
`/build-milestone <plan file>`. The author runs its step, spawns the `plan-reviewer` subagent
(`.claude/agents/plan-reviewer.md`) for one round, resolves that round, and stops at the next
Ari gate. Run by hand, each step still ends with the model stopping. If there are any decisions 
that Ari needs to make, mark them clearly in the document and draw his attention to them.

### Running a review round from the author's session

1. **Snapshot** `git status --porcelain` before spawning, so the check in step 3 compares
   against your own uncommitted work rather than a clean tree.
2. **Spawn** `plan-reviewer` in the foreground (`run_in_background: false`, since the next step
   needs its result), and **always pass `model`**: `opus` if you aren't Opus, otherwise
   `sonnet`. Leaving it out makes the reviewer inherit your model, which defeats the point of a
   second model. The prompt names the plan file, whether this is a plan review or a code review,
   and, for code review, the newest Implementation log round. Don't summarize your reasoning for
   it: the reviewer should judge the file cold.
3. **Check the reviewer stayed in its lane.** Compare against the snapshot: the only new change
   should be in the plan file, and `git diff` on that file should show only an appended round
   plus the header lines. If anything else changed, revert that part, note it in the round's
   preamble, and tell Ari.
4. **Resolve every row** (see "The author's side"), then set the next status and stop.

**One round per run.** If the resolutions change the plan or code substantially (a rejected or
reworked blocker, a verdict of *rework*), don't start round 2 on your own: say so in the handoff
and let Ari decide.

**Handoff to Ari** when stopping at a gate: the status, the round's verdict and counts, the
findings you rejected (with reasons) and any you're unsure of, and what Ari should check before
approving.

### What the reviewer may change

The reviewer **writes only to the plan file, and only by adding a new round** at the end of
`## Plan review` or `## Code review`, plus the header's `Status` and reviewer lines. It doesn't
edit the plan body, earlier rounds, or any code, docs, or tests, even for a one-character fix.
A fix belongs in a finding. Scratch experiments are fine in a throwaway `git worktree` that is
removed afterwards; say so in the round's preamble.

Each round opens with its scope (the plan, or the diff and commit range), what was checked and
how (docs read, commands run, results), counts by severity, and a verdict (*proceed*, *proceed
after fixes*, *rework*). Then a findings table:

| # | Sev | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|

Severity is `blocker` / `should-fix` / `nit`. Evidence is a file:line, a doc section, or
command output, and is marked CONFIRMED (reproduced) or PLAUSIBLE (reasoned). The reviewer
leaves **Resolution** empty. Plan reviews also check the test approach (tests come first,
build plan §3) and whether the `TODO(Ari)` gaps are the right ones.

### The author's side

- **Resolving:** fill every Resolution cell with **Fixed** plus what changed (and where), or
  **Rejected** plus a one-line reason. Don't leave any empty or merge rows. End the round with a
  `Rejected:` line, and, for code review, the test-suite result after the fixes. For testable
  code findings, write the failing test before the fix.
- **Implementation log** (step 5) is the handoff to the code reviewer, so it names everything the
  reviewer needs without asking:
  - **Scope:** commit range or `git diff` base, and the files touched.
  - **Departures from the plan**, each with its reason.
  - **`TODO(Ari)` gaps:** each one listed as open, filled by Ari, or filled by Claude on
    request. Review the code as it stands; open gaps aren't findings.
  - **Verification:** the commands run and their results (`make check`, the plan's verification
    steps).
  - **Where to look hardest:** what the author is least sure of.

A second implementation pass after code review gets its own log round, scoped to the fixes.

## Cloud sessions — what runs there, and how it hands work back

Claude Code cloud sessions (`CLAUDE_CODE_REMOTE=true`) are set up by `scripts/cloud-setup.sh`,
a SessionStart hook in `.claude/settings.json`. The sandbox has Postgres and the full
`make check` suite, but **no Ollama, no gitignored eval fixtures, and no route to venue
websites** (Trusted network access only). So a cloud session cannot run live extraction, the
eval harness, `local_test`, or fixture capture, and 14 tests in
`agent_worker/tests/test_validation_on_real_pages.py` skip there. Don't try to work around
this; leave that work for a local session and say so in the PR. The sandbox has Node 22 and
CI uses 24, so a green JS check there is not quite a green CI.

Suited to cloud: deterministic, DB-tested work (reconcile, commit, audit writes, routes onto
the DB), the Next.js track, plan and code review rounds, docs. Needs local: anything that
calls the model, and filling `TODO(Ari)` gaps.

`/plan-milestone` can run in the cloud for any milestone, since it writes no code, with one
exception: if the plan's design depends on measurements only the local model can produce
(eval results, extraction-quality experiments such as H1's act splitter), plan it locally or
mark those facts as unverified in the plan. `/build-milestone` is cloud-suited only where
the milestone itself is (see the list above). The skills are user-invoked, so type them;
the session model is the author, and the reviewer subagent gets a different one, as
"Running a review round" requires.

### Branches and PRs

1. Work on a branch named `<milestone>-<slug>` (e.g. `a5-reconcile`), matching the plan
   file's name. Never commit to `main`. One milestone per branch.
2. Open the PR as a **draft**. Ari reviews and merges; don't merge it yourself.
3. Run `make check` before pushing and put its result in the PR description. Don't hand-edit
   generated files (`lib/api-types.ts`, `lib/fixtures/`); regenerate with `make types` /
   `make fixtures` if you change `schemas.py` or `sample_data.py`.
4. The plan file stays the only channel between author and reviewer: update its `Status` and
   append your rounds **on the same branch**, so they arrive with the code.
5. For a **[fill-in]** task, push the scaffold with its tests red, and list each
   `TODO(Ari)` gap in the PR description as a file:line link with its lesson and the test
   command, exactly as "[fill-in] tasks" above says. Ari fills the gaps locally by checking
   out the branch (or `claude --teleport`) and pushing to it.
6. At an Ari gate (plan approval, sign-off) or a decision that is his to make, stop and say so
   at the top of the PR description. Don't proceed past it.

**Parallel tracks.** The A (Python) and B (Next.js) tracks run at the same time and meet at the
API contract, so a change to `app/schemas.py` regenerates files that B-track branches depend
on. Keep schema changes in their own early PR so the other track can rebase onto them. Keep
edits to shared docs (`alpha-build-plan.md`, `notes.md`) small and append-only to avoid merge
conflicts. A5 and A6 write the same tables, so they are not run in parallel.
