---
name: open-pr
description: Open a draft pull request for the current branch with the repo's template, the make check result, and automatic PR subscription. Covers the "Branches and PRs" rules in AGENTS.md. Stops at Ari's merge gate; never merges or marks ready.
argument-hint: [optional PR title; omit to derive it from the branch's commits]
disable-model-invocation: true
---

Open a **draft** PR for the current branch, following `AGENTS.md`, "Branches and PRs". **$ARGUMENTS**
is an optional title. Work through these steps in order and stop at the end.

0. **Check for an existing PR.** Search open PRs for this branch as `head`. If one exists, say so and
   update its body instead of opening a second one. Don't open a duplicate.

1. **Check the branch.** Run `git rev-parse --abbrev-ref HEAD`.
   - If it is `main`, stop. Never open a PR from `main`; ask Ari which branch to use.
   - If it doesn't match `<milestone>-<slug>` (for example `a5-reconcile`), keep going, but say so in
     the PR's "Review notes". Don't rename the branch. In a cloud session the harness designates the
     branch, and renaming it can break the session's push target. Ari decides on any rename.

2. **Make sure the work is pushed.** `git status --porcelain` must be empty. Push with
   `git push -u origin <branch>`, retrying network failures with 2, 4, 8 and 16 second waits. If the
   tree is dirty, stop and list what is uncommitted. Don't commit on your own.

3. **Run the checks.** Run `make check` and keep the summary lines (ruff, pytest, vitest, e2e, and
   contract). If the plan has a milestone, also run `make designation-check BASE=<diff base>`, using the
   base named in the Implementation log. If anything fails, stop and report it. Don't open a PR on a red
   check.

4. **Fill the template.** Read `.github/pull_request_template.md`, and mirror its sections exactly.
   - Fill each section from the diff, not from memory: `git diff --stat <base>...HEAD` and the
     commit log.
   - Put the `make check` summary in Verification.
   - If a section doesn't apply, write one line saying why. Don't leave it blank.
   - Name any `TODO(Ari)` gap as a file:line link with its key point of interest.
   - End the body with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
   - Don't put a model name in the title or body.

5. **Open the PR as a draft.** Use the GitHub MCP tool `create_pull_request` with `draft: true`.
   Load it with ToolSearch first if its schema isn't loaded. Base is `main` unless the plan names
   another. The title is short, at most 70 characters. Use `$ARGUMENTS` if given.

6. **Subscribe at once.** Call `subscribe_pr_activity` on the new PR. Don't ask first. This rule is
   standing: Ari has asked for it to be automatic.

7. **Stop.** Report the PR link, the `make check` result, and any gate or open decision at the top of
   the PR body. Say once that the next PR event will bring you back.

**Never:** merge, mark the PR ready for review, force-push, rebase a branch someone else is on, or
skip a failing check to get the PR open. Ari reviews and merges.
