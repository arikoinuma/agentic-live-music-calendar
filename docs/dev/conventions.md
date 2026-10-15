# Conventions

How this repo writes things down. `AGENTS.md` holds the rules agents must follow; this file
explains the reasoning and the details, for anyone reading code or docs. Language style
lives in `docs/references/`; this file covers what applies across the whole repo.

## Designations: scope first

A designation is a short ID that points at a decision, a finding, or a gap. `D5` alone is
not enough: `D5` means act conventions in one plan, the larger-model tier in another, and
sample rows in a third. Every designation therefore carries the scope of the plan that
defines it.

### Scopes

A scope is the milestone ID from the build plan. Each one matches a plan file in
`docs/dev/implementations/`:

| Scope | Plan file |
|---|---|
| `A1` | `a1-data-layer.md` |
| `A2` | `a2-extraction-schema.md` |
| `A2.1` | `a2.1-extraction-reliability.md` |
| `A3` | `a3-validation-and-retry.md` |
| `B2` | `b2-routes-and-data-loading.md` |
| `B3` | `b3-the-calendar.md` |

Future milestones use their own IDs (`A4`, `H1`, …) the same way.

### Forms

| Form | Means | Example | Defined in |
|---|---|---|---|
| `<scope>-D<n>` | a decision | `A2.1-D5` | that plan's decision table |
| `<scope>-E<n>` | an experiment or lever | `A2.1-E1` | that plan's experiment table |
| `<scope>-F<n>` | a failure found in an eval | `A2-F9` | that plan's failure table |
| `<scope>-S<n>` | a sampling or design lever | `A2-S6` | that plan's lever list |
| `<scope>-Gap-<X>` | a fill-in step's gap | `A3-Gap-B` | that plan's `[fill-in]` steps |
| `G<n>` | a known gap in the build plan | `G6` | `alpha-build-plan.md` §1.3 |
| review round | the round and the item | `A2.1 review round 2 #3` | that plan's review sections |

The `G<n>` catalogue is repo-wide, so it is **not** scoped. Every plan cites `G6` the same
way, and `A3-G6` would be wrong.

### Rules

1. **The scope is the plan that defines the ID, not the plan that cites it.** `S6` is
   defined in A2's lever list, so it is `A2-S6` even where A2.1 cites it.
2. **Code, tests, and cross-plan citations always scope.** Inside a plan file, bare IDs are
   fine, since the file is the scope.
3. **Write the token form in code:** `A2.1-D5`, with no space and no comma. It is one token,
   so it can be searched for, and a reader sees it as one thing.
4. **Write the review round with its scope:** `A2.1 review round 2 #3`, not `#3`.
5. **Gaps are scoped too.** `A3-Gap-B` is A3's fill-in step B (`classify_page`). `A2.1-Gap-B`
   is a different function, so the two must never be confused.

### Checking

A bare-ID search across the code finds what still needs scoping. It excludes the
virtualenv and the generated `G` catalogue:

```
grep -rnE --exclude-dir=.venv --exclude-dir=node_modules \
  '(^|[^A-Za-z0-9._-])(D|E|F|S)[0-9]+([^0-9]|$)' apps
```

Matches inside plan files are expected. Matches in code, tests, and docs that cite another
plan are not.

## Known exceptions

- **String literals.** The label notes in `apps/api/agent_worker/eval/labels.py` and two
  `argparse` help strings in `eval/run_eval.py` still use bare IDs. They are data and
  user-facing text, so changing them was out of scope for the comment-only pass that
  applied this convention.
- **Plan files citing other plans** still use some bare IDs. They are historical records,
  so they are not rewritten in place.
