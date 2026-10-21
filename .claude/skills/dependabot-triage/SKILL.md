---
name: dependabot-triage
description: Turn the repo's open Dependabot alerts into a ranked fix plan. Fetches the alerts with gh (needs a local session logged in to GitHub; in a cloud session it stops and says to re-run locally), collapses them into root causes, cross-checks the lockfiles, reads the open Dependabot PRs, and recommends an order by alerts closed per action. Read-only; changes nothing.
argument-hint: [optional path to an existing alerts TSV; omit to fetch with gh]
disable-model-invocation: true
---

Triage the open Dependabot alerts for this repo. **$ARGUMENTS** is an existing alert export if Ari
gave a path (then skip the fetch in step 1); otherwise start at step 1. This skill is **read-only**: it recommends, and does not edit
lockfiles, merge PRs, dismiss alerts or comment on PRs. Any of those needs Ari's say-so first.

The helper is `.claude/skills/dependabot-triage/triage.py` (standard library only; always run it
as `python3 -I`). It was checked against a real 118-alert export, so its totals are the ones to trust.

## Why the workflow looks like this

Raw alert counts mislead. 118 alerts were really about six fixes: Dependabot raises one alert per
advisory **per manifest**, so one framework pinned in three places counts nine advisories as
twenty-seven alerts, and one CLI tool with a deep dependency tree accounted for about 48 more.
The point of this skill is to find those levers and rank them by alerts closed per action.

## 1. Get the alerts

If `$ARGUMENTS` is a path to an existing export, use it and go to step 2. Otherwise fetch the
open alerts with `gh` (the scratchpad directory, not `/tmp` and not the repo, is the place for the file):

```
python3 -I .claude/skills/dependabot-triage/triage.py fetch <scratchpad>/alerts.tsv
```

Branch on the exit code:

| Exit | Meaning | What to do |
|---|---|---|
| 0 | Wrote the alert rows | Go on to step 2 |
| 3 | `gh` has no access (HTTP 403 or 401) | **Stop.** See below |
| 4 | `gh` is not installed | Stop and say so; the remedy is the same as for 3 |
| 1 | Some other failure (network, rate limit) | Show the error and stop; don't guess |

**On exit 3, stop and tell Ari to re-run `/dependabot-triage` in a local Claude Code session where
`gh auth status` shows them logged in as themselves.** Say why in a sentence: the alerts endpoint needs
the `vulnerability_alerts: read` permission, and a cloud session's GitHub credential is an App token
without it (it answers `403 Resource not accessible by integration`; the response header
`X-Accepted-Github-Permissions: vulnerability_alerts=read` names the permission). Then end the turn.

Do not, on exit 3: ask Ari to paste an export unless they offer one, run the lockfile audits from step 3
as a stand-in, or try GraphQL or the global `/advisories` endpoint (sessions block both, deliberately).
If Ari then asks for a best-effort picture anyway, the audits in step 3 can produce one; label it an
approximation of Dependabot's list and not the list.

**Do not recommend a third-party "export alerts" GitHub Action.** It would receive a token that can
read the repo's unpatched-vulnerability list, runs unfamiliar code from a personal repo behind a
mutable tag, and (this repo is public) a CSV uploaded as a workflow artifact can be downloaded by
other signed-in GitHub users. `fetch` needs no secret and no new code.

## 2. Summarize

```
python3 -I .claude/skills/dependabot-triage/triage.py summarize <alerts file>
```

It prints totals by severity, a list of alert numbers missing from the sequence (fixed or dismissed;
use it to reconcile with the number on the Security tab, which counts only open alerts), and tables by
manifest, by package (npm and Python separately) and the critical alerts. A package marked `×3` is
pinned in three manifests, so each of its advisories is counted three times; one upgrade closes all of
them.

## 3. Find the root causes (this is the step that matters)

The package table says what is vulnerable. The question is **which dependency the repo chose that
drags it in**.

**npm** (`pnpm audit` exits non-zero when it finds anything, which is expected):

```
pnpm audit --json > <scratchpad>/pnpm-audit.json
pnpm audit --prod --json > <scratchpad>/pnpm-audit-prod.json
python3 -I .claude/skills/dependabot-triage/triage.py chains <scratchpad>/pnpm-audit-prod.json
```

Then confirm any lever with `pnpm why <package>`. Compare the full and `--prod` reports: a package
that is only in the full one comes from a dev dependency.

**Python** (`uvx pip-audit` queries PyPI; the OSV API was unreachable from the cloud sandbox):

```
cd apps/api
uv export --frozen --no-hashes --no-emit-project -o <scratchpad>/req.txt
uvx pip-audit -r <scratchpad>/req.txt --no-deps --disable-pip -f json -o <scratchpad>/pip-audit.json
uv tree --frozen --invert --package <vulnerable package>
```

`pip-audit` also lists `fix_versions` per advisory. An empty list means no upgrade can fix it.

These audits are an **approximation** of Dependabot's list (different advisory databases, different
counting; the reconstruction was within one alert of GitHub's count). Use them to explain the alerts,
and the export as the source of truth for the count.

Write the result as a table: lever, alerts it accounts for, what to do about it. If the lever
numbers don't add up to the export total, say what is unexplained.

## 4. Read the open Dependabot PRs

Use `search_pull_requests` with `author:app/dependabot is:open`, then `pull_request_read` for each
(`get` for the body, `get_check_runs` for CI). Classify each:

- **Security update** when the body ends with the "disable automated security fix PRs" footer.
- **Version bump** otherwise. A version bump can still contain CVE fixes (a pymongo range did), so
  read the release notes in the body.

Also report: whether the PR's base commit is behind `main` (a green CI run on an old base is weak
evidence), and whether a `@dependabot rebase` is needed. If an existing comment has the mention
defanged (for example `@·dependabot`), Dependabot never saw it.

## 5. Judge reachability, with evidence

For each critical and high lever, grep the app code (`apps/`, excluding `node_modules` and `.venv`;
a bare grep from `apps/api` otherwise reports hits inside the virtualenv) for the vulnerable
surface the advisory names, and say what you found. Say **"I could not show it is reachable"**, not
"it is not reachable". Hosting facts that change the answer are in `docs/dev/alpha-deployment-plan.md`
(the calendar runs on Vercel, the API on Railway). Never claim an exploit path you did not test.

## 6. Report

Follow Ari's formatting preferences (TL;DR first and again at the end, headers and tables). Include:

1. Totals, and how the count reconciles with GitHub's.
2. The lever table from step 3.
3. The critical alerts, each with reachability from step 5.
4. **A ranked plan by alerts closed per action**, each step naming the PR or command and an
   estimated count, flagged as an estimate. Dependabot closes alerts only when it rescans the merged
   lockfile, so the count will not drop the moment a PR merges.
5. Alerts a PR cannot fix (no patched version, empty `fix_versions`): list them for Ari to decide
   (override, replace the dependency, or dismiss with a written reason). Do not dismiss any yourself.
6. Questions for Ari: which fixes you should start, and whether to post rebase comments.

## Gotchas learned the hard way

- **Dependabot's `runtime` / `development` label is not a triage signal.** It marks a package
  `runtime` if it is reachable from a `dependencies` entry. A scaffolding CLI listed under
  `dependencies` (`shadcn` in `apps/calendar/package.json`) made its entire tree "runtime", and
  116 of 118 alerts read `runtime`. Decide by what runs in production, using `pnpm audit --prod`
  and the dependency chain, then consider moving build-only tools to `devDependencies`.
- **Package names differ in case** (`PyJWT`, `pyjwt`, `pyJWT`); the helper lower-cases them.
- **`apps/admin` is the untouched template with no v1 role** (`docs/arch/arch-initial.md` §7), yet it
  carries a share of the `next` alerts. Mention it; whether to keep it installed is Ari's call.
- **Fixes belong on a branch with a draft PR**, following `AGENTS.md` (branches, `make check` before
  pushing, never hand-edit generated files, Ari merges). This skill stops before that.
- The repo's other skills use `disable-model-invocation: true`; keep this one user-invoked too, since
  it reads security data.
