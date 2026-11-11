# Conventions

How this repo writes things down. `AGENTS.md` holds the rules agents must follow; this file
explains the reasoning and the details, for anyone reading code or docs. Language style
lives in `docs/references/`; this file covers what applies across the whole repo.

## Designations: bare inside the defining document, scoped everywhere else

A designation is a short ID that points at a decision, a finding, a gap, or a review item.
The same ID can mean different things in different documents: `D5` is act conventions in A2.1,
the larger-model tier in A3, and sample rows in B3. So the rule is one line: inside the document
that defines an ID it is written bare, and from any other document, or in code and tests, it
carries that defining document's scope.

### Scopes

| Scope | Defined in |
|---|---|
| `v0.1` | `docs/dev/alpha-build-plan.md` (v0.1 is the alpha; the plan's header says so) |
| `Dep` | `docs/dev/alpha-deployment-plan.md` (its plan-level decisions, `Dep-D1`; each C milestone in it gets its own scope when planned) |
| `A1` | `docs/dev/implementations/a1-data-layer.md` |
| `A2` | `docs/dev/implementations/a2-extraction-schema.md` |
| `A2.1` | `docs/dev/implementations/a2.1-extraction-reliability.md` |
| `A3` | `docs/dev/implementations/a3-validation-and-retry.md` |
| `A4` | `docs/dev/implementations/a4-auditability.md` |
| `A5` | `docs/dev/implementations/a5-reconcile.md` |
| `A6` | `docs/dev/implementations/a6-commit.md` |
| `A7` | `docs/dev/implementations/a7-testing.md` |
| `B2` | `docs/dev/implementations/b2-routes-and-data-loading.md` |
| `B3` | `docs/dev/implementations/b3-the-calendar.md` |
| `B4` | `docs/dev/implementations/b4-detail-pages.md` |
| `B5` | `docs/dev/implementations/b5-frontend-testing.md` |
| `B6` | `docs/dev/implementations/b6-accessibility-and-e2e.md` |
| `C2` | `docs/dev/implementations/c2-api-reads-database.md` |
| `C3` | `docs/dev/implementations/c3-environments-and-deploy.md` |
| `C3.1` | `docs/dev/implementations/c3.1-feature-flags.md` |
| `C4` | `docs/dev/implementations/c4-metro-hosts.md` |
| `C5` | `docs/dev/implementations/c5-pipeline-eval-harness.md` |
| `C5.1` | `docs/dev/implementations/c5.1-model-eval-layout.md` |
| `C7` | `docs/dev/implementations/c7-pipeline-eval.md` |
| `C8` | `docs/dev/implementations/c8-worker-on-railway.md` |
| `PQR1` | `docs/dev/review/2026-11-06-python-code-quality-review.md` (Python Quality Review, round 1) |

| `GH-<n>` | GitHub issue `<n>` in this repository (the number is GitHub's own); its resolution record is `docs/dev/issues/gh-<n>-<slug>.md` |
| `ISS-<n>` | an issue Ari described, with no review or GitHub issue behind it; numbered in order of its record in `docs/dev/issues/` |

Future milestones use their own IDs (`B6`, `C2`, …) the same way. A code quality review in `docs/dev/review/` takes
`PQR<round>` as its scope, and numbers its findings `PQR<round>-<n>` with no letter (`PQR1-4`), so a later review
round (`PQR2-4`) can be told apart from this one.

**Issue records** (`docs/dev/issues/`) keep the ID their issue came with: a review finding stays `PQR1-4`, a GitHub
issue is `GH-17`, a described issue is `ISS-3`. (`GH-17` is the repo's searchable form; GitHub itself links only
`#17`, so a PR body or commit message that should link the issue writes `#17` as well, as in `Closes #17`.) A record defines its own plan-review and code-review items, written bare
inside the record (`CR1-2`). Everywhere else they take the record's **lead issue** (the first in its scope) as their
scope: `PQR1-4-CR1-2`, `GH-17-CR1-1`, `ISS-3-PR1-2`. `docs/dev/issues/README.md` has the rest of the issue track.

### Forms

| Form | Means | Example | Defined in |
|---|---|---|---|
| `<scope>-D<n>` | a decision | `A2.1-D5` | that plan's decision table |
| `<scope>-E<n>` | an experiment or lever | `A2.1-E1` | that plan's experiment table |
| `<scope>-F<n>` | a failure found in an eval, or a finding from a scan or check | `A2-F9`, `B6-F2` | that plan's failure table or findings table |
| `<scope>-S<n>` | a sampling or design lever | `A2-S6` | that plan's lever list |
| `<scope>-K<n>` | a fill-in step's key point | `A3-K2` | that plan's `[fill-in]` steps |
| `<scope>-T<n>` | a test row in a plan's test approach (the test file names it) | `C3.1-T2`, `C3-T6` | that plan's test-approach table |
| `<scope>-M<n>` | a mutation check: a deliberate break of the code under test that a named test must catch | `B5-M4` | that plan's mutation table (Verification) |
| `<scope>-Q<n>` | a question a measurement milestone answers | `C7-Q4` | that plan's questions table (Context) |
| `<scope>-R<n>` | a pre-registered reading: the rule, fixed before the runs, that turns a measurement into a recommendation | `C7-R3` | that plan's readings table |
| `<scope>-U<n>` | an unverified outside fact: something about a service we cannot read from the repo (Railway's behavior, a vendor's limit), written down with the step that checks it, and marked resolved or carried when that step has run | `C8-U1` | that plan's table of unverified facts (Context) |
| `<scope>-PR<round>-<n>` | a plan-review item | `A3-PR1-3` | that plan's Plan review rounds |
| `<scope>-CR<round>-<n>` | a code-review item | `A3-CR1-3` | that plan's Code review rounds |
| `v0.1-G<n>` | a known gap in the catalogue | `v0.1-G6` | `alpha-build-plan.md` §1.3 |

### Why `K` and `v0.1-G`

- **`K` is for key points.** A fill-in step's gap is a key point of interest, so it's a key
  point. Numbering makes the order visible, so `A3-K2` is the second key point in A3.
- **`v0.1-G` ties the catalogue to a version.** The catalogue lives in the alpha plan, so its
  gaps belong to v0.1. A later version can keep its own catalogue without renumbering.
- Together they separate the two kinds of "gap". The catalogue is `v0.1-G…`, and fill-in
  steps are `…-K…`. Neither is a bare letter any more. Inside its own plan, K1 is written bare, like any other ID the plan defines.

### Mapping from the old gap letters

Fill-in gaps used to be lettered A–E. They're now numbered:

| Old | New |
|---|---|
| `Gap A` | `K1` |
| `Gap B` | `K2` |
| `Gap C` | `K3` |
| `Gap D` | `K4` |
| `Gap E` | `K5` |

So `A3-Gap-B` (`classify_page`) is now `A3-K2`.

### Rules

1. **The scope is the document that defines the ID, not the one that cites it.** `S6` is
   defined in A2's lever list, so it is `A2-S6` even where A2.1 cites it.
2. **Scope cross-references, not in-file items.** Inside the document that defines an ID, a
   bare ID is fine: `D3` in A1 is A1's own D3, so it stays `D3`. Only a reference to another
   document's item carries its scope, for example `A2.1-D3` written in A1. Code, tests and code
   comments always scope, **even when they implement the one plan in view**, since they cite plans
   rather than define them (`A5-D7` in `reconcile.py`, never `D7`).
3. **Write the token form:** `A2.1-D5`, with no space and no comma. It is one token, so it
   can be searched for, and a reader sees it as one thing.
4. **Review items say which review they belong to.** A plan has two kinds of review round,
   `PR` for plan review and `CR` for code review, and each numbers its rounds from 1. So
   `A3-PR1-3` is A3's plan-review round 1, item 3, and `A3-CR1-3` is its code-review round 1,
   item 3. Items with no round number get one assigned in their plan before they are cited.
5. **The catalogue is versioned.** Outside `alpha-build-plan.md`, write `v0.1-G6`, never `G6`.
   Inside the build plan, the catalogue is its own, so a bare `G6` stays.

### Checking

**For new work, run the branch check.** It looks only at the lines a branch adds, so the exceptions below don't get in
the way. It is part of `make check` and its own CI job (pull requests only), so a bare designation fails the PR:

```
make designation-check                  # base: where this branch left origin/main
make designation-check BASE=<commit>    # an explicit base, e.g. the diff base a milestone's Implementation log names
```

Fetch `origin/main` first; a stale one makes the base too old and the check flags other people's lines. `BASE` is the diff base the milestone's Implementation log names, if you need an explicit one. The script is `scripts/check_designations.py`: it reads
the added lines (committed, uncommitted and new files), skips the plan files under `docs/dev/implementations/` and the issue records under `docs/dev/issues/` (they
define their own IDs, so bare is right there), and flags `D`, `E`, `F`, `S`, `G`, `K` and `PR`/`CR` tokens with no
scope. A token that is not a designation (a ruff code, "S3") is silenced with `designation-ok` on the line, or `noqa`.
Its default base is the merge-base with `origin/main`, which is only right when a branch holds one milestone; CI always passes the PR's own base.

**To audit the whole repo,** this search finds bare designations. It excludes the virtualenv, caches, and generated
files:

```
grep -rnE --exclude-dir=.venv --exclude-dir=node_modules --exclude-dir=.mypy_cache \
  --exclude-dir=__pycache__ --exclude-dir=.next -I \
  '(^|[^A-Za-z0-9._-])(D|E|F|S|G|K)[0-9]+([^0-9]|$)|Gap[s]? [A-E]\b' .
```

A hit inside the document that defines the ID is fine. Any other hit is a cross-reference
that needs its scope. The exceptions below are the only expected hits.

## Known exceptions

- **Code not yet converted.** The docs use the new forms. Most code and tests still use the
  earlier scheme until they are converted.
- **Quoted history.** Where a document quotes old scaffold text (for example
  `(Ari) — Gap X. Lesson:`), the quote stays as written.
- **String literals.** The label notes in `apps/api/agent_worker/model_eval/labels.py` and two
  `argparse` help strings in `model_eval/run_eval.py` still use bare IDs. They are data and
  user-facing text, so they're converted separately from the comment-only passes.

## Terms

- **Feature flag** is a named on/off switch for a behavior that must differ by environment or be switchable without a
  code change (`app/flags.py`, `docs/dev/environments.md` "Feature flags"; C3.1). **"Flag" alone** is a user flagging a
  wrong listing (`arch-initial.md` §7), and `RunTrigger.FLAG_THRESHOLD` means that. Write "feature flag" for the toggle.
