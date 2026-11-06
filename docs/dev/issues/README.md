# Issue records

This folder holds one **issue record** per `/resolve-issue` run. An issue is a single, bounded problem: a finding from
a review in `docs/dev/review/`, a GitHub issue, or a bug Ari describes. Milestones (the C1–C11 plan) are still handled
by `docs/dev/implementations/` and the `/plan-milestone` + `/build-milestone` cycle. This track is the lighter path
for the work that comes in issue-sized pieces.

The process rules are in `AGENTS.md`, "Issue resolution track". This file explains the reasoning behind them and
holds the record template.

## The rules

| Rule | Why |
|---|---|
| **One run, one record, one branch, one PR.** The issues Ari names at the start of a run are its scope, whether that's one or five. | Ari decides the batching up front. A PR that matches what was asked for is easier to review than one the agent grouped on its own. |
| **The issue keeps its source's ID.** A review finding stays `PQR1-4`. A GitHub issue is `GH-<its number>`. An issue Ari describes gets the next free `ISS-<n>` (`ISS-1`, `ISS-2`, …). | The ID is how the source doc, the record, the code comments and the PR find each other. Renumbering would break that link. |
| **Risk sets the amount of process (tiers T0–T2), not the source of the issue and not the file count.** | `ruff format` touches 125 files and carries almost no risk. A URL check that blocks SSRF touches two files and is a security design decision. Counting files would get both of these wrong. |
| **Always required: a test or check that fails first, an Implementation log, a code review by a different model, and closing the loop with the source.** | These are what make the change auditable, and auditability is one of the project's goals (`docs/arch/project-overview.md`). The gates are what got lighter, not the record. |
| **The PR opens automatically after the code review is resolved. Merging it is Ari's sign-off.** | There's no separate `Done` status. The merge state lives on GitHub. |
| **A GitHub issue appears in the PR body as plain `#<n>`, in a `Closes #<n>` line, as well as `GH-<n>`.** | GitHub links and auto-closes an issue only from `#<n>`. `GH-<n>` is the repo's own searchable form, and GitHub ignores it. |
| **No `TODO(Ari)` gaps.** | Ari doesn't hand-fill issue fixes. The `[fill-in]` rules in `AGENTS.md` apply to milestones only. |

## Tiers

The record's tier is the highest tier among its issues. Write the reason in one line, so Ari can disagree with it.

| Tier | What qualifies | Plan | Plan review | Ari approves before code |
|---|---|---|---|---|
| **T0: mechanical** | Format, rename, lint config, docs, a comment-only pass, removing unused dependencies | None | No | No |
| **T1: contained fix** | A behavior change in one area, with a clear fix and no contract change | A short **Approach** paragraph | Optional | No |
| **T2: far-reaching** | Any of these: changes `app/schemas.py` or the API contract; needs a database migration; makes a security design choice; changes a repo-wide convention; or the source marks it as Ari's decision | A full plan in **Approach** | Yes by default (skipping it needs a stated reason) | **Yes: stop at `Awaiting approval`** |

Two conditions stop the run whatever the tier:

- **A decision that belongs to Ari.** The source says so (for example `PQR1-10`), or a design choice comes up with no doc that settles it.
- **Verification that needs the local machine** (the model, the network to venue sites, or gitignored eval fixtures; see
  `AGENTS.md`, "Cloud sessions"). The run doesn't stop. It writes the cloud-checkable part (for example a
  `MockTransport` test), marks the rest **local check pending** in the log and the PR, and doesn't call it verified.

## Status values

`Triage` → (T2 only: `Plan review` → `Awaiting approval` → `Approved`) → `Code review` → `Code review: findings open` → `PR open`.

## Designations inside a record

A record defines its own review items. They are bare inside the record (`CR1-2`, `PR1-1`). Everywhere else they carry
the record's **lead issue** (the first issue in its scope) as the scope: `PQR1-4-CR1-2`, `GH-17-CR1-1`, `ISS-2-CR1-3`. The
issue IDs themselves (`PQR1-4`, `GH-17`, `ISS-2`) are already scoped and are written the same everywhere. See
`docs/dev/conventions.md`.

## File names

`docs/dev/issues/<lead id, lowercase>-<slug>.md`, for example `pqr1-4-fetch-redirects.md`, `gh-17-venue-timezone.md`,
`iss-1-duplicate-shows.md`. A record with several issues is named after its lead issue, with a slug that covers the batch
(`pqr1-1-first-impression-pass.md`).

## Template

Copy this into the new record. Delete `## Plan review` for T0/T1 records that skip it.

```markdown
# <Lead ID>: <short title>

**Status:** Triage
**Date:** <Month D, YYYY>
**Scope:** <every issue ID in this run, e.g. PQR1-1, PQR1-3, PQR1-6>
**Sources:** <each ID → where it is defined: review doc § and row, GitHub issue URL, or "described by Ari, <date>">
**Tier:** <T0 | T1 | T2> — <one-line reason>
**Author model:** <model> (<what it did, date; cloud or local session>)
**Reviewer model:** <model> (<plan review / code review round n, date>)
**Branch / PR:** <branch> / <PR link once opened>

**Designations.** Review items here are bare (`CR1-2`). Outside this record they are `<Lead ID>-CR1-2`
(`docs/dev/issues/README.md`, `docs/dev/conventions.md`).

## Issues

One subsection per issue: what is wrong, the evidence (quoted from the source, or reproduced here), and what "fixed" means.
For an ISS issue, include Ari's description in his words and any answers to the clarifying questions.

### <ID>: <title>

## Approach

T0: one line ("mechanical; verified by …"). T1: a paragraph covering the fix, the test that fails first, and the files.
T2: a full plan in the shape of a milestone plan (context, test approach, steps, critical files, verification).

## Plan review

## Implementation log

### Round 1

- **Scope:** diff base `<sha>`, files touched
- **Per issue:** what changed, the test or check that failed first and now passes
- **Departures from the approach**, each with its reason
- **Verification:** `make check`, `make designation-check BASE=<sha>`, AST comparison for comment-only parts, and any
  check marked **local check pending**
- **Where to look hardest**

## Code review
```
