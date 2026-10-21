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

Future milestones use their own IDs (`A7`, `H1`, …) the same way.

### Forms

| Form | Means | Example | Defined in |
|---|---|---|---|
| `<scope>-D<n>` | a decision | `A2.1-D5` | that plan's decision table |
| `<scope>-E<n>` | an experiment or lever | `A2.1-E1` | that plan's experiment table |
| `<scope>-F<n>` | a failure found in an eval | `A2-F9` | that plan's failure table |
| `<scope>-S<n>` | a sampling or design lever | `A2-S6` | that plan's lever list |
| `<scope>-K<n>` | a fill-in step's key point | `A3-K2` | that plan's `[fill-in]` steps |
| `<scope>-M<n>` | a mutation check: a deliberate break of the code under test that a named test must catch | `B5-M4` | that plan's mutation table (Verification) |
| `<scope>-PR<round>-<n>` | a plan-review item | `A3-PR1-3` | that plan's Plan review rounds |
| `<scope>-CR<round>-<n>` | a code-review item | `A3-CR1-3` | that plan's Code review rounds |
| `v0.1-G<n>` | a known gap in the catalogue | `v0.1-G6` | `alpha-build-plan.md` §1.3 |

### Why `K` and `v0.1-G`

- **`K` is for key points.** A fill-in step's gap is the point of the lesson, so it's a key
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
the added lines (committed, uncommitted and new files), skips the plan files under `docs/dev/implementations/` (they
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
- **String literals.** The label notes in `apps/api/agent_worker/eval/labels.py` and two
  `argparse` help strings in `eval/run_eval.py` still use bare IDs. They are data and
  user-facing text, so they're converted separately from the comment-only passes.
