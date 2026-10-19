---
name: build-milestone
description: Implement an approved milestone plan, have a reviewer on a different model check the code for one round, fix the findings, and stop at a human sign-off gate. The human answers approve, reject, or send back. Gate 2 of the milestone workflow; plan-milestone is gate 1.
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
| `Approved` | *(none)* | Build (Step 1) |
| `Changes requested` | *(none)* | Build (Step 1). The latest send-back note in the Decisions log is the work order |
| `Awaiting sign-off` | `approve` | Record the decision. Set `Done`. Stop and hand off |
| `Awaiting sign-off` | `reject [reason]` | Record it with the reason. Set `Rejected`. Stop. Don't revert any code; list the changed files so the human can decide |
| `Awaiting sign-off` | `send back: <notes>` | Record the notes verbatim. Set `Changes requested`. Build (Step 1) with the notes as the work order, then Steps 2 to 4 |
| `Awaiting sign-off` | *(none)* | Change nothing. Re-show the handoff and the three commands |
| `Awaiting plan approval`, `Plan review`, `Plan review: findings open` | any | Stop. The plan isn't approved. Run `plan-milestone` on it |
| `Approved` or `Changes requested` with a decision argument | any | Stop. Sign-off hasn't been reached, so there's nothing to decide |
| `Building`, `Code review`, `Code review: findings open` | any | Stop and ask the human. The last run may have been interrupted, and the working tree may be half-built |
| `Done`, `Rejected` | any | Stop. The milestone is closed |

**Decisions log row:** `| # | Gate | Date | Decision | By | Notes |`. `Gate` is `2`. `By` follows the same
rule as in `plan-milestone`.

## Step 1: Implement

1. Set `Status` to `Building`.
2. Read the repo's conventions files (`conventions_files` in the config). Read every file the plan's
   **Critical files** section names.
3. **Tests first.** Write the tests from the plan's **Test approach** and the acceptance criteria.
   Run them and confirm they fail for the expected reason. A test that passes before the code exists
   proves nothing.
4. Implement the steps in order. Follow the plan. If a step can't be done as written, make the
   smallest change that meets the acceptance criteria, and record it as a departure with a reason.
5. Run `verify_command`. Fix any failure, or explain it in the log if it is outside this milestone.
   If `verify_command` is unset, find the repo's own check command (its README, or its package or
   build manifest) and note in the log which one you used. Ask the human if you can't find one.
6. **Don't commit** unless the human has asked. The reviewer reviews the working tree.
7. Append a round under `## Implementation log`:

```
### Round <n> — <author model>, <date>

**Scope:** diff base <commit or "working tree vs HEAD">; files touched: <list>
**Departures from the plan:** <each one with its reason, or "none">
**Verification:** <each command, its result, and the test counts>
**Open items for the human:** <anything left for the human to do or decide>
**Where to look hardest:** <what you're least sure of>
```

8. Set `Status` to `Code review`.

## Step 2: One review round

Follow this protocol. It runs once per invocation.

1. **Snapshot.** Copy the plan file to a scratch directory outside the repo. Under git, also save
   `git status --porcelain` and a checksum of `git diff` there. The code is expected to be changed
   at this point, so the check compares against this snapshot, not against a clean tree.
2. **Spawn the reviewer.** Use the Agent tool with:
   - `subagent_type`: `milestone-reviewer`
   - `model`: the `reviewer_model` (always passed; never omitted)
   - `run_in_background`: `false`
   - a prompt that names: the plan file path; the mode, **code review**; the round number of the
     newest Implementation log entry; the reviewer model name; the `verify_command` (or the check
     command you recorded); the conventions files; and the instruction to review cold. Don't
     summarize your reasoning or your own findings.
3. **Check the reviewer stayed in its lane.** Under git, `git status --porcelain` and the `git diff`
   checksum should match the snapshot. The plan file's diff should show only the new round and the
   header lines. If anything else changed, revert that part, note it in the round's preamble, and
   tell the human. Outside git, check the plan file only.

## Step 3: Resolve the round

1. Fix the code. For each testable finding, write the failing test first, then the fix.
2. Fill every **Resolution** cell with `Fixed` plus what changed and where, or `Rejected` plus a
   one-line reason. No cell may stay empty.
3. Re-run `verify_command`. Record the result at the end of the review round, under a line that says
   "After fixes:".
4. If the verdict was `rework`, or the fixes change the approach substantially, don't run another
   round. Say so in the handoff.
5. Set `Status` to `Awaiting sign-off`. This is gate 2.

## Step 4: Stop at gate 2

Stop here. Write the handoff, with a short summary at the top and again at the bottom:

- The plan file path (a link, not just the name).
- The review round's verdict and counts, and the final verification results.
- Each rejected finding, with its reason, and any finding you're unsure of.
- Each open item the human must do or decide, and the command that runs its tests.
- Anything you did not commit, and the list of files changed.
- What the human should check before signing off.
- The next commands:

| Decision | Command |
|---|---|
| Approve | `/build-milestone <plan file> approve` |
| Reject | `/build-milestone <plan file> reject <reason>` |
| Send back | `/build-milestone <plan file> send back: <what to change>` |
