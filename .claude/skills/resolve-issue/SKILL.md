---
name: resolve-issue
description: Resolve one or more issues (review findings like PQR1-4, GitHub issues, or a bug Ari describes) in one record, one branch and one draft PR, with a code review by a different model in between. The issue track in AGENTS.md, "Issue resolution track".
argument-hint: <issue IDs, GitHub issue numbers/URLs, and/or a bug description — e.g. "PQR1-4 PQR1-5" or "#17" or "the calendar shows yesterday's shows after midnight">
disable-model-invocation: true
---

Resolve **$ARGUMENTS** following `AGENTS.md`, "Issue resolution track", and `docs/dev/issues/README.md` (the tiers,
the stop conditions and the record template). **Everything named in $ARGUMENTS is this run's scope: one record, one
branch, one PR.** Don't widen or split it. If something adjacent turns up, note it in the record's log under
"Noticed, not in scope" and suggest it as a separate task.

Invoking this skill is Ari's request to commit, push and open the draft PR at the end. It is **not** permission to merge.

**Commit and push work in progress whenever it's worth saving.** A cloud container can be reclaimed, and a stop hook
may ask for it. What must wait is the **PR**: it opens only at step 7, after the code review is resolved. A commit pushed
before the review is fine; say so in the Implementation log, so the reviewer knows the scope is a commit range.

0. **Intake: turn each item into an issue with an ID.** For each item in $ARGUMENTS:
   - **A review ID** (`PQR1-4`, also a range like `PQR1-1..3`): read its row in the review doc that `docs/dev/conventions.md`
     maps the scope to, plus any section the row points to (for example "Check locally"). The ID stays as written. If
     the ID doesn't exist (a typo such as `PRQ1-4`), say what you think was meant and ask before going on.
   - **A GitHub issue** (`#17`, `GH-17`, or a URL): read it with the GitHub MCP `issue_read`, including its comments.
     The ID is `GH-17` in the record, the code and the docs. **In the PR body it must also appear as plain `#17`**
     (see step 7), because GitHub links an issue only from `#<n>`, never from `GH-<n>`.
   - **A described issue**: the ID is the next free `ISS-<n>` (check the file names in `docs/dev/issues/`).
     If the description doesn't say what happens, what should happen and where, **ask Ari clarifying questions and stop
     until he answers**. Don't guess a reproduction.
   - Check the source's Resolution tracker (review docs) or the issue's linked PRs. If an item is already resolved or in
     an open PR, say so and leave it out unless Ari confirms.

1. **Open the record.** Branch: in a cloud session use the designated branch. Locally, create
   `issue-<lead id lowercase>-<slug>` from an up-to-date `origin/main`.
   - **Designated branch whose last PR already merged:** restart it from `main` with
     `git fetch origin main && git checkout -B <branch> origin/main`. `main` already contains the merged branch, so the
     next push is a **fast-forward**: use a plain `git push -u origin <branch>`, never `--force` or `--force-with-lease`.
   - **Designated branch with an open, unmerged PR:** don't reset it, because that drops the PR's commits. Stop and ask Ari
     whether to wait for the merge or use another branch. Write the diff base (`git rev-parse HEAD`)
   down now. Create `docs/dev/issues/<lead id lowercase>-<slug>.md` from the template in `docs/dev/issues/README.md`,
   fill the header and `## Issues`, and set Status to `Triage`.

2. **Triage.** Give each issue a tier using the README's table, set the record's tier to the highest, and write the
   one-line reason. Then check the stop conditions:
   - **A decision that belongs to Ari** (the source says so, or nothing in the docs settles a design choice): write it
     under "Decisions for Ari" in `## Approach` with your recommendation, set Status to `Awaiting approval`, and go to
     step 8 (hand off, with no PR).
   - **T2:** write the full plan in `## Approach`, then run one plan-review round as in step 5, but for a *plan review*.
     Skip that round only with a stated reason. Resolve it, set Status to `Awaiting approval`, and go to step 8. A later
     `/resolve-issue <record file>` run, once Ari has set `Approved`, continues from step 3.
   - **Local-only verification in a cloud session:** carry on, and mark it **local check pending** wherever verification is reported.
   - **T0/T1:** write the Approach (a line for T0, a paragraph for T1) and carry on. No approval gate.

3. **Make it fail first.** For a behavior change, write the failing test first (`Proves:` comment, the repo's test
   conventions) and run it to show it fails. For T0, run the check that shows the problem (for example
   `uv run ruff format --check .`). Record what failed.

4. **Fix, verify, log.**
   - Make the change in the stack's style (read `docs/references/<stack>-style-guide.md` and its Anti-patterns table first).
   - A comment-only part is a comment-only pass: compare syntax trees before and after (`AGENTS.md`, Conventions).
   - Cite issue IDs in code and comments only where they explain *why* (for example `# PQR1-4: venue sites redirect
     http→https`). Don't scatter them.
   - Run `make check` and `make designation-check BASE=<diff base>`. Both must pass apart from failures you explain.
   - Write `## Implementation log` Round 1 as the template lays out, then set Status to `Code review`.

5. **Code review (required).** Follow `AGENTS.md`, "Running a review round from the author's session":
   - snapshot `git status --porcelain`;
   - spawn `plan-reviewer` in the foreground with `model` set to a model other than yours. The prompt names the
     record file, says it is an **issue record** and a **code review** of Implementation log Round 1, and gives the diff base;
   - check that it changed only the record (an appended round, plus the Status and reviewer header lines).

6. **Resolve.** Fill every Resolution cell (**Fixed** + what and where, or **Rejected** + why), writing a failing test
   before any testable fix. Re-run `make check` and `make designation-check BASE=<diff base>` and record the result at
   the end of the round. If the fixes are big enough for a second round, don't run it: say so in the handoff. Set Status to `PR open`.

7. **Commit, push, open the PR, close the loop.**
   - Commit with a message naming the issue IDs (`fix(api): follow redirects in fetch (PQR1-4)`; for a GitHub issue, `(GH-17, #17)`), ending with the
     attribution trailers. Push with `git push -u origin <branch>`, retrying network failures after 2, 4, 8 and 16 seconds.
   - Open the draft PR by following `.claude/skills/open-pr/SKILL.md` steps 0–6. In the template, "Milestone / plan"
     becomes `Issues: <IDs>` and `Record: docs/dev/issues/<file>`. **For each GitHub issue, the body must contain a line `Closes #<n>` with the plain `#<n>`** (for example
     `Closes #17`, not `Closes GH-17`). That's what makes GitHub link the issue to the PR and close it on merge. Put the
     same `#<n>` in the commit message as well (`fix(api): … (GH-17, #17)`). After opening, check that the issue shows
     the PR as linked.
     Put **local check pending** items and any rejected review findings at the top of the body.
   - Close the loop with each source:
     - **Review doc:** update the issue's row in its `Resolution tracker` (create the table at the end of the doc if
       there isn't one, with every finding listed and Open as the default) to `In PR` with the PR link and the record path;
     - **GitHub issue:** add a comment linking the PR and the record, ending with the attribution footer;
     - **ISS:** nothing to update. The record is the trail.
   - Write the PR link into the record's header. Commit and push both edits.

8. **Stop and hand off.** Lead with the status and anything waiting on Ari. Then give, per issue: tier, what changed,
   and how it was verified. Add the review verdict and counts, the rejected findings with reasons, any local check
   pending (with the command to run locally), and the PR link. If you stopped at a gate, say exactly what Ari needs to decide.

**Never:** merge, mark the PR ready, add `TODO(Ari)` gaps, fill a decision that belongs to Ari, or widen the scope past
$ARGUMENTS.
