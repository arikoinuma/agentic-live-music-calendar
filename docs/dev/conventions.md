# Conventions

How this repo writes things down. `AGENTS.md` holds the rules agents must follow; this file
explains the reasoning and the details, for anyone reading code or docs. Language style
lives in `docs/references/`; this file covers what applies across the whole repo.

## Designations: every ID carries its scope

A designation is a short ID that points at a decision, a finding, a gap, or a review item.
`D5` alone is ambiguous: act conventions in one plan, the larger-model tier in another, and
sample rows in a third. So every designation is written as `<scope>-<ID>`, and the scope is
always the document that defines the ID.

### Scopes

| Scope | Defined in |
|---|---|
| `v0.1` | `docs/dev/alpha-build-plan.md` (v0.1 is the alpha; the plan's header says so) |
| `A1` | `docs/dev/implementations/a1-data-layer.md` |
| `A2` | `docs/dev/implementations/a2-extraction-schema.md` |
| `A2.1` | `docs/dev/implementations/a2.1-extraction-reliability.md` |
| `A3` | `docs/dev/implementations/a3-validation-and-retry.md` |
| `B2` | `docs/dev/implementations/b2-routes-and-data-loading.md` |
| `B3` | `docs/dev/implementations/b3-the-calendar.md` |

Future milestones use their own IDs (`A4`, `H1`, …) the same way.

### Forms

| Form | Means | Example | Defined in |
|---|---|---|---|
| `<scope>-D<n>` | a decision | `A2.1-D5` | that plan's decision table |
| `<scope>-E<n>` | an experiment or lever | `A2.1-E1` | that plan's experiment table |
| `<scope>-F<n>` | a failure found in an eval | `A2-F9` | that plan's failure table |
| `<scope>-S<n>` | a sampling or design lever | `A2-S6` | that plan's lever list |
| `<scope>-K<n>` | a fill-in step's key point | `A3-K2` | that plan's `[fill-in]` steps |
| `<scope>-R<round>-<n>` | a review item | `A2.1-R2-3` | that plan's review sections |
| `v0.1-G<n>` | a known gap in the catalogue | `v0.1-G6` | `alpha-build-plan.md` §1.3 |

### Why `K` and `v0.1-G`

- **`K` is for key points.** A fill-in step's gap is the point of the lesson, so it's a key
  point. Numbering makes the order visible, so `A3-K2` is the second key point in A3.
- **`v0.1-G` ties the catalogue to a version.** The catalogue lives in the alpha plan, so its
  gaps belong to v0.1. A later version can keep its own catalogue without renumbering.
- Together they separate the two kinds of "gap". The catalogue is `v0.1-G…`, and fill-in
  steps are `…-K…`. Neither is a bare letter any more.

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
2. **Scope everywhere.** That includes code, tests, docs, and inside a plan file itself. An
   excerpt has to stand on its own, so a bare ID is never acceptable.
3. **Write the token form:** `A2.1-D5`, with no space and no comma. It is one token, so it
   can be searched for, and a reader sees it as one thing.
4. **Review items carry their round:** `A2.1-R2-3` means round 2, item 3. Items with no
   round number get one assigned in their plan before they are cited.
5. **The catalogue is versioned.** Write `v0.1-G6`, never `G6`. A bare `G6` no longer means
   anything once a second version exists.

### Checking

This search finds bare designations. It excludes the virtualenv, caches, and generated
files:

```
grep -rnE --exclude-dir=.venv --exclude-dir=node_modules --exclude-dir=.mypy_cache \
  --exclude-dir=__pycache__ --exclude-dir=.next -I \
  '(^|[^A-Za-z0-9._-])(D|E|F|S|G)[0-9]+([^0-9]|$)|Gap[s]? [A-E]\b' .
```

Any hit is a bare designation to fix. The exceptions below are the only expected hits.

## Known exceptions

- **Not yet applied.** Only the pilot files use the new forms so far. Everything else still
  uses the earlier scheme until it is converted.
- **String literals.** The label notes in `apps/api/agent_worker/eval/labels.py` and two
  `argparse` help strings in `eval/run_eval.py` still use bare IDs. They are data and
  user-facing text, so they're converted separately from the comment-only passes.
