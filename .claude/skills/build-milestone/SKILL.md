---
name: build-milestone
description: Implement an approved implementation plan, have a different model QA the code for one round, fix the findings, and stop for Ari's sign-off. Steps 5–7 of the cycle in AGENTS.md.
argument-hint: <plan file, e.g. docs/dev/implementations/b2-routes-and-data-loading.md>
disable-model-invocation: true
---

Run steps 5–7 of the cycle in `AGENTS.md`, "Implementation plans", for **$ARGUMENTS**, then stop
at Ari's sign-off gate.

0. **Check the gate.** Read the plan in full, including its review rounds. Invoking this skill
   counts as Ari's approval: if Status isn't `Approved`, set it to `Approved` and say so in the
   handoff. If any plan-review Resolution cell is still empty, stop and report it instead of
   building.

1. **Implement.** Tests first (build plan §3), then the steps in order. **Cite the plan's items with the
   milestone scope everywhere outside the plan file**: `A5-D7`, `A5-K1`, `A5-PR1-3`, `A5-CR1-4`, never a bare
   `D7` (code, tests, comments, docstrings, section headers and other docs; a bare ID can't be searched for or told
   apart from another plan's). Copy IDs from the plan's "Designations" paragraph in the scoped form. [written] steps are
   written complete. [fill-in] steps follow `AGENTS.md`, "[fill-in] tasks": scaffold, leave
   the `TODO(Ari)` blocks open, and don't fill them; this skill isn't a request to fill them.
   Run `make check`. Its tests for open gaps are expected to fail; anything else failing must
   be fixed or explained. Then run **`make designation-check BASE=<diff base>`** (the base the Implementation log
   will name: the commit before you started) and fix every bare designation it lists; it must exit 0 before you
   spawn the reviewer. A fix that only changes comments is a comment-only pass, so verify it as `AGENTS.md`
   says (syntax trees before and after, then `make check`). Then add a round under `## Implementation log` (scope as a diff base
   and files touched, departures, `TODO(Ari)` status, verification results, where to look
   hardest) and set Status to `Code review`. Don't commit unless Ari has asked; give the
   reviewer the working tree as the scope instead.

2. **Review.** Follow "Running a review round from the author's session" in `AGENTS.md`:
   snapshot, spawn `plan-reviewer` with `model` set to a model other than yours, prompting
   it for a *code review* of the newest Implementation log round, then check it changed nothing
   besides the plan file.

3. **Resolve.** Fix the code (failing test first where the finding is testable), fill every
   Resolution cell, re-run `make check` and `make designation-check BASE=<diff base>`, record the result at the end of the round, and set
   Status to `Awaiting sign-off`. If round 2 looks warranted, don't run it; say so.

4. **Stop and hand off** to Ari as `AGENTS.md` describes, plus: each open `TODO(Ari)` as a
   file:line link with its one-line key point of interest, and the command that runs its tests.
