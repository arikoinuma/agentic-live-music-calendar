---
name: plan-milestone
description: Plan one milestone (a user story, a ticket, or a spec) into a reviewable plan file. A reviewer on a different model checks the plan for one round, then the skill stops at a human approval gate. The human answers approve, reject, or send back. Gate 1 of the milestone workflow; build-milestone is gate 2.
argument-hint: <milestone ref: ticket key, URL, file path, or quoted title> [approve | reject [reason] | send back: <notes>] [reviewer=<model>]
disable-model-invocation: true
---

# Plan a milestone

You are the **author** in a two-model cycle. A reviewer on a different model checks your plan once,
and a human approves it at the gate. This skill writes no code. It ends with a reviewed plan and a
recorded decision.

Arguments: `$ARGUMENTS`

## The paper trail

Every milestone has one plan file, `<plans_dir>/<slug>.md`. It holds the header, the spec, the plan,
the review rounds, the implementation log (added by build-milestone), and a **Decisions log**. The
plan file is the only channel between author, reviewer, and human, and it is the record afterwards.
Decisions are recorded there when they are made, so nothing depends on chat history.

## Status values

| Status | Set by | Meaning |
|---|---|---|
| `Plan review` | author | Plan written or revised; the reviewer round hasn't run yet |
| `Plan review: findings open` | reviewer | Review round appended; the author must resolve it |
| `Awaiting plan approval` | author | **Gate 1.** The human decides: approve, reject, or send back |
| `Approved` | approve decision | The plan is approved. Build may start |
| `Rejected` | reject decision | Closed. No build. The file is kept as the record |

## Step 0: Configuration and the model pair

1. Read `.claude/milestones.json` if it exists. Any missing key takes its default:

   | Key | Default | Meaning |
   |---|---|---|
   | `author_model` | *(unset)* | The model this session should run on: the planner and coder |
   | `reviewer_model` | `opus` | The reviewer's model: one of `sonnet`, `opus`, `haiku`, `fable` |
   | `plans_dir` | `docs/milestones` | Where plan files live |
   | `verify_command` | *(unset)* | The repo's check command, e.g. `make check` or `npm test` |
   | `conventions_files` | `[]` | Repo rules the reviewer reads, e.g. `["AGENTS.md"]` |
   | `tracker_hint` | *(unset)* | Free text naming the ticket system, used to find its tools |

2. Let `reviewer=<model>` in the arguments override `reviewer_model` for this run only.
3. **The reviewer must be a different model from you.** Work out your own model from your system
   prompt and write it in the header as `Author model`. Then:
   - If `author_model` is set and it isn't you, stop and tell the human to restart the session on
     `author_model`. The plan's author should be the model the config names.
   - If `reviewer_model` equals your model, stop and ask the human to pick another reviewer.
     A same-model review is a second pass, not a second opinion.

## Step 1: Resolve the milestone reference

Work out what the first argument is. If it names an existing plan file under `plans_dir`, go to
Step 2 with that file. Otherwise, get the spec:

| Reference looks like | How to get the text |
|---|---|
| A ticket key (e.g. `PROJ-123`) | Search for the ticket tools with ToolSearch, guided by `tracker_hint`. Fetch the ticket. If no tracker tool is connected, ask the human to paste the text. Don't guess its contents |
| A URL | WebFetch it. If it needs a login, ask the human to paste the text |
| A file path | Read the file |
| Anything else | The quoted text is the milestone itself, such as a user story |

Copy the spec **verbatim** into the plan's `Spec` section, with a link or the source. A verbatim copy
stops the plan from drifting from the ticket it came from.

**Slug:** `<ref>-<short-title>`, lowercase, kebab-case, at most 60 characters (for example
`proj-123-email-login`). The plan file is `<plans_dir>/<slug>.md`.

## Step 2: Gate handling when a plan file already exists

Find the plan file's `Status`, then act on the row that matches. Record every decision in the
Decisions log before changing anything else.

| Status | Argument | Action |
|---|---|---|
| `Awaiting plan approval` | `approve` | Record the decision. Set `Approved`. Stop and hand off (Step 6) |
| `Awaiting plan approval` | `reject [reason]` | Record it with the reason. Set `Rejected`. Stop |
| `Awaiting plan approval` | `send back: <notes>` | Record the notes verbatim. Set `Plan review`. Go to Step 3, revise, then Steps 4 to 6 |
| `Awaiting plan approval` | *(none)* | Change nothing. Re-show the handoff and the three commands |
| `Plan review`, `Plan review: findings open` | any | The last run stopped early. Find the first unfinished step and resume it. Say which one |
| `Approved` | any | Stop. Planning is closed. Run `build-milestone` on the file |
| `Rejected` | any | Stop. A rejected milestone isn't reopened here. Start a new plan file if the scope changes |
| `Building`, `Code review…`, `Awaiting sign-off`, `Changes requested`, `Done` | any | Stop. The build workflow owns this file now |

A decision in chat ("looks good, approve it") isn't recorded until this skill runs with the
argument. Say so, and suggest the exact command.

**Decisions log row:** `| # | Gate | Date | Decision | By | Notes |`. `Gate` is `1`. `Date` is today.
`By` is the person as named in the conversation, or `user` if they didn't name themselves.
Notes hold the reason or the verbatim send-back notes.

## Step 3: Write the plan (or revise it after a send back)

**Fresh plan.** Write the file with these parts, in this order and under these headings:

```
# <Title>

**Status:** Plan review
**Date:** <today>
**Author model:** <your model>
**Reviewer model:** <reviewer_model>
**Spec:** <source link, or "pasted by user">

## Context          why this milestone exists, and what it is not
## Acceptance criteria   numbered, each one testable
## Test approach    tests written first; how each criterion is verified; what is not tested, and why
## Steps            ordered; each names the files it touches and the test that goes red, then green
## Critical files   the files a reviewer should read first
## Verification     verify_command, plus any manual checks, with expected results
## Decisions for the user   each open question, with your recommendation, marked **DECISION**
## Out of scope    what this milestone deliberately leaves alone
## Plan review
## Implementation log
## Decisions log    header row only
```

Write the plan so that a reader who has never seen the repo can follow it. Cite the conventions
file and section for each rule the plan relies on. Put any question that only the human can answer
under **Decisions for the user**, not in the steps. Don't guess a decision and bury it.

**Revision after send back.** Address each note in the plan body. Keep every earlier review round
and every earlier Decisions log row unchanged. In the Decisions log, note which sections changed.
Then run Steps 4 to 6 as normal.

## Step 4: One review round

Follow this protocol. It runs once per invocation. Don't start a second round.

1. **Snapshot.** Copy the plan file to a scratch directory outside the repo. If the repo is under git,
   also save `git status --porcelain` there.
2. **Spawn the reviewer.** Use the Agent tool with:
   - `subagent_type`: `milestone-reviewer`
   - `model`: the `reviewer_model` (passed explicitly; never omit it)
   - `run_in_background`: `false`, since the next step needs the result
   - a prompt that names: the plan file path; the mode, **plan review**; the round number (existing
     rounds plus one); the reviewer model name; the `verify_command` if set; the conventions files
     that exist; and the instruction to review cold. **Don't** summarize your own reasoning or
     tell the reviewer what you think is wrong.
3. **Check the reviewer stayed in its lane.** Diff the plan file against the snapshot. The only
   changes should be new lines in `## Plan review` and the `Status` and reviewer-model header lines.
   If git is available, `git status --porcelain` should match the snapshot. If anything else changed,
   revert that part, note it in the round's preamble, and tell the human.

## Step 5: Resolve the round

1. Fill every **Resolution** cell with `Fixed` plus what changed and where, or `Rejected` plus a
   one-line reason. No cell may stay empty.
2. Make the plan-body edits that the fixed findings need.
3. End the round with a `Rejected:` line that lists each rejected finding and why.
4. If the verdict was `rework`, or the fixes change the approach substantially, don't run another
   round. Say so in the handoff and let the human decide.
5. Set `Status` to `Awaiting plan approval`. This is gate 1.

## Step 6: Stop at gate 1

Stop here. Write the handoff, with a short summary at the top and again at the bottom:

- The plan file path (a link, not just the name).
- The round's verdict and counts by severity.
- Each rejected finding, with its reason, and any finding you're unsure of.
- The **Decisions for the user**, copied from the plan, with your recommendation for each.
- What the human should check before approving.
- The next commands:

| Decision | Command |
|---|---|
| Approve | `/plan-milestone <ref> approve` |
| Reject | `/plan-milestone <ref> reject <reason>` |
| Send back | `/plan-milestone <ref> send back: <what to change>` |

After approval, `/build-milestone <plan file>` starts the implementation.
