<!--
Pull request template. GitHub fills this in as the body of every new PR.
Replace the comments and placeholders; delete any section that truly doesn't
apply, but say so in one line rather than leaving it blank.

Repo conventions this follows: AGENTS.md ("Implementation plans" and
"Branches and PRs"). Milestone PRs are opened as drafts; Ari reviews and merges.
-->

## Summary

<!-- What changed and why, in two or three sentences. Link the design doc or
     plan file if one exists (docs/dev/implementations/<milestone>-<slug>.md). -->

## Milestone / plan

<!-- Milestone ID from docs/dev/alpha-build-plan.md, e.g. A5, B2. Write "none"
     for a change outside the build plan (docs, chores, dependency bumps). -->

- Milestone:
- Plan file:
- Plan status (if applicable):

## Changes

<!-- Bullets, one per meaningful change. Name the area: api, calendar, docs, ci. -->

-

## Verification

<!-- Paste the result of `make check` (or the relevant subset) and say which
     checks you ran. "Passes CI" is not a substitute for running it. -->

- [ ] `make check` passes locally (paste summary below)
- [ ] Tests added or updated, and each new test has a `Proves:` comment
- [ ] Manual check in the running app, if the change is user-visible

```
<!-- make check output summary -->
```

## Generated files

<!-- Edits to schemas.py or sample_data.py require regenerating the contract. -->

- [ ] Not applicable
- [ ] `make types` / `make fixtures` run, and the regenerated files are committed
      (`lib/api-types.ts`, `lib/fixtures/` are never hand-edited)

## Open gaps and decisions

<!-- Any `TODO(Ari)` blocks left in the diff, each as file:line with its lesson,
     and any decision that needs Ari's call. Write "none" if there are none. -->

- None

## Review notes

<!-- Where you want the reviewer to look hardest, and what you are least sure of. -->

-
