---
name: build-milestone
description: Implement an approved milestone plan test-first, reading the repo's reference docs before coding. A reviewer on a different model checks the code for one round, the findings get fixed, and the skill stops at a human sign-off gate. The human answers approve, reject, or send back. Gate 2 of the milestone workflow; plan-milestone is gate 1.
argument-hint: <plan file path, or milestone ref> [approve | reject [reason] | send back: <notes>] [reviewer=<model>]
disable-model-invocation: true
---

# Build a milestone

You are the **author** for the implementation half of the cycle. You build the approved plan, a
reviewer on a different model checks the code once, and a human signs off at the gate. Only the
human moves the milestone past sign-off.

Arguments: `$ARGUMENTS`

Running this skill does **not** approve the plan. Plan approval is gate 1, recorded by
`plan-milestone`. This skill refuses to build a plan that isn't `Approved`.

**Testing comes first in this workflow.** Write the tests before any implementation code. Then keep
coding, running the tests after each change, until every test passes. Step 2 spells out the rules.

## Step 0: Configuration, the gate, and the model pair

1. Read `.claude/milestones.json` the same way `plan-milestone` does (its Step 0 has the keys and
   defaults). Apply the same model-pair checks: the session should run on `author_model`, and the
   reviewer must not be the author's model. `reviewer=<model>` in the arguments overrides it for
   this run only.
2. Resolve the argument. A path to a file is the plan. A ref is looked up as
   `<plans_dir>/<slug>.md`. If several files match a ref, list them and stop.
3. Read the plan in full, including the review rounds, the Implementation log, and the Decisions
   log.
4. Act on the `Status` and the argument:

| Status | Argument | Action |
|---|---|---|
| `Approved` | *(none)* | Build (Steps 1 to 3), then Steps 4 to 6 |
| `Changes requested` | *(none)* | Build (Steps 1 to 3), then Steps 4 to 6. The latest send-back note in the Decisions log is the work order |
| `Awaiting sign-off` | `approve` | Record the decision. Set `Done`. Stop and hand off |
| `Awaiting sign-off` | `reject [reason]` | Record it with the reason. Set `Rejected`. Stop. Don't revert any code; list the changed files so the human can decide |
| `Awaiting sign-off` | `send back: <notes>` | Record the notes verbatim. Set `Changes requested`. Build (Steps 1 to 3) with the notes as the work order, then Steps 4 to 6 |
| `Awaiting sign-off` | *(none)* | Change nothing. Re-show the handoff and the three commands |
| `Awaiting plan approval`, `Plan review`, `Plan review: findings open` | any | Stop. The plan isn't approved. Run `plan-milestone` on it |
| `Approved` or `Changes requested` with a decision argument | any | Stop. Sign-off hasn't been reached, so there's nothing to decide |
| `Building`, `Code review`, `Code review: findings open` | any | Stop and ask the human. The last run may have been interrupted, and the working tree may be half-built |
| `Done`, `Rejected` | any | Stop. The milestone is closed |

**Decisions log row:** `| # | Gate | Date | Decision | By | Notes |`. `Gate` is `2`. `By` follows the same
rule as in `plan-milestone`.

## Step 1: Set up

1. Set `Status` to `Building`.
2. **Reference docs.** The plan's **Reference docs read** table and the sections its steps cite are
   the context. Read those sections in full. Then decide whether to read the whole
   `reference_docs_dir` (recursively, in full):
   - **Read the whole folder** if you can't be sure the planner's reads are still in your context: a
     new session, a resumed session, a compacted thread, or any doubt. When in doubt, read it all.
   - **Skip the full re-read** only when you know the planning reads are still in your context, as
     in the same thread. Then the cited sections are enough.
   - If `reference_docs_dir` isn't configured, read the usual higher-level docs in the repo (README,
     architecture, style guide, `CONTRIBUTING`) and tell the human to set it.
   - If a constraint you need isn't cited in the plan, read the doc that covers it and record it as a
     departure, because the plan missed a citation.
3. Read the repo's `conventions_files`, and every file the plan's **Critical files** section names.
4. Re-read the plan's **Test strategy** and **Acceptance criteria**. They are the contract for the
   code.

## Step 2: Tests first, then code until green

This is the core loop. Follow it in order.

1. **Write the tests before any implementation code.** Build them from the plan's **Test strategy**
   and the acceptance criteria. Use the fixtures and expected values the plan names. Don't derive
   expected values from code you haven't written yet.
2. **Run the tests and confirm each one fails for the expected reason.** A test that passes before the
   code exists proves nothing. A test that fails with an import error or a typo is not a red test
   either. Fix the test until it fails because the behavior is missing.
3. **Keep coding until every test passes.** Implement the steps in the plan's order. Run the tests
   after each change. Stop only when they all pass.
4. **Don't weaken the tests to get green.** Don't skip, delete, loosen an assertion, or change an
   expected value to match the code. If a test really is wrong, change it, and record a departure with
   the reason and the spec or doc that shows the test was wrong.
5. **If a step can't be done as written,** make the smallest change that meets the acceptance criteria,
   and record it as a departure with a reason.

## Step 3: Verify

1. Run `verify_command`. Fix any failure, or explain it in the log if it is outside this milestone.
   If `verify_command` is unset, find the repo's own check command (its README, or its package or
   build manifest) and note in the log which one you used. Ask the human if you can't find one.
2. Run the plan's **Verification** steps and record each result.
3. **Don't commit** unless the human has asked. The reviewer reviews the working tree.
4. Append a round under `## Implementation log`:

```
### Round <n> — <author model>, <date>

**Scope:** diff base <commit or "working tree vs HEAD">; files touched: <list>
**Reference docs read:** <list, or "as in the plan">
**Tests:** <written first: yes/no, and the red-then-green evidence for the main ones>
**Departures from the plan:** <each one with its reason, or "none">
**Verification:** <each command, its result, and the test counts>
**Open items for the human:** <anything left for the human to do or decide>
**Where to look hardest:** <what you're least sure of>
```

5. Set `Status` to `Code review`.

## Step 4: One review round

Follow this protocol. It runs once per invocation.

1. **Snapshot.** Copy the plan file to a scratch directory outside the repo. Under git, also save
   `git status --porcelain` and a checksum of `git diff` there. The code is expected to be changed
   at this point, so the check compares against this snapshot, not against a clean tree.
2. **Spawn the reviewer.** Use the Agent tool with:
   - `subagent_type`: `milestone-reviewer`
   - `model`: the `reviewer_model` (always passed; never omitted)
   - `run_in_background`: `false`
   - a prompt that names: the plan file path; the mode, **code review**; the round number of the
     newest Implementation log entry; the reviewer model name; the `reference_docs_dir`; the
     `verify_command` (or the check command you recorded); the conventions files; and the instruction
     to review cold. Don't summarize your reasoning or your own findings.
3. **Check the reviewer stayed in its lane.** Under git, `git status --porcelain` and the `git diff`
   checksum should match the snapshot. The plan file's diff should show only the new round and the
   header lines. If anything else changed, revert that part, note it in the round's preamble, and
   tell the human. Outside git, check the plan file only.

## Step 5: Resolve the round

1. Fix the code. For each testable finding, write the failing test first, then the fix. This is the
   same loop as Step 2.
2. Fill every **Resolution** cell with `Fixed` plus what changed and where, or `Rejected` plus a
   one-line reason. No cell may stay empty.
3. Re-run `verify_command` and confirm every test passes. Record the result at the end of the review
   round, under a line that says "After fixes:".
4. If the verdict was `rework`, or the fixes change the approach substantially, don't run another
   round. Say so in the handoff.
5. Set `Status` to `Awaiting sign-off`. This is gate 2.

## Step 6: Stop at gate 2

Stop here. Write the handoff, with a short summary at the top and again at the bottom:

- The plan file path (a link, not just the name).
- The review round's verdict and counts, and the final verification results, including the test counts.
- Each rejected finding, with its reason, and any finding you're unsure of.
- Each departure from the plan, and any test you changed, with its reason.
- Each open item the human must do or decide, and the command that runs its tests.
- Anything you did not commit, and the list of files changed.
- What the human should check before signing off.
- The next commands:

| Decision | Command |
|---|---|
| Approve | `/build-milestone <plan file> approve` |
| Reject | `/build-milestone <plan file> reject <reason>` |
| Send back | `/build-milestone <plan file> send back: <what to change>` |
