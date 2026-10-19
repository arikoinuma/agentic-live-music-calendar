# Milestone workflow

A portable pair of Claude Code skills for taking one milestone from spec to signed-off code, with a
second model reviewing the work and a human approving it at two gates.

| Piece | Path | Role |
|---|---|---|
| `plan-milestone` skill | `skills/plan-milestone/SKILL.md` | Author plans the milestone. Gate 1 |
| `build-milestone` skill | `skills/build-milestone/SKILL.md` | Author builds the approved plan. Gate 2 |
| `milestone-reviewer` agent | `agents/milestone-reviewer.md` | Reviews once per gate, on a different model |
| Config | `milestones.example.json` | Copy to `.claude/milestones.json` and edit |

Nothing here names a project, a file layout, or a convention. Those come from the config and from
the repo's own conventions files.

## Install

```bash
# In a project: keep the workflow with that repo
cp -r milestone-workflow/skills/plan-milestone milestone-workflow/skills/build-milestone .claude/skills/
cp milestone-workflow/agents/milestone-reviewer.md .claude/agents/
cp milestone-workflow/milestones.example.json .claude/milestones.json   # then edit it

# Or for every project: use ~/.claude/ in place of .claude/
```

If a project already has skills named `plan-milestone` or `build-milestone`, copying over them
replaces them. Check first.

## The flow

| Step | Who | Ends with |
|---|---|---|
| Plan | author (`plan-milestone`) | Plan file written, `Plan review` |
| Review 1 | reviewer, `reviewer_model` | Round appended, `Plan review: findings open` |
| Resolve | author | `Awaiting plan approval` (**gate 1**) |
| Decide | human | `approve` → `Approved` · `reject` → `Rejected` · `send back` → back to Plan |
| Build | author (`build-milestone`) | Code written, `Code review` |
| Review 2 | reviewer, `reviewer_model` | Round appended, `Code review: findings open` |
| Resolve | author | `Awaiting sign-off` (**gate 2**) |
| Decide | human | `approve` → `Done` · `reject` → `Rejected` · `send back` → back to Build |

Each skill runs one review round per invocation and then stops. A send back loops: the author
revises, runs one more round, and stops at the same gate again.

## Commands

```text
/plan-milestone <ref>                              start a plan (or resume one)
/plan-milestone <ref> approve                      gate 1: plan approved, build may start
/plan-milestone <ref> reject <reason>              gate 1: milestone closed
/plan-milestone <ref> send back: <notes>           gate 1: revise, review again, stop at the gate

/build-milestone <plan file>                       build an Approved plan
/build-milestone <plan file> approve               gate 2: milestone done
/build-milestone <plan file> reject <reason>       gate 2: milestone closed, code left as-is
/build-milestone <plan file> send back: <notes>    gate 2: rebuild with the notes, review, stop
```

Add `reviewer=<model>` to any command to use a different reviewer for that run only.

A decision given in chat is not recorded until the skill runs with the argument, so the skill
will suggest the exact command. Each decision is written to the plan file's **Decisions log**, so
the record survives the chat.

## Configuration

`.claude/milestones.json`. Every key is optional.

| Key | Default | Meaning |
|---|---|---|
| `author_model` | unset | The model the session should run on. Plans and code both come from it. The skill stops if the session is on another model |
| `reviewer_model` | `opus` | `sonnet`, `opus`, `haiku`, or `fable`. Must differ from the author's model |
| `plans_dir` | `docs/milestones` | Where plan files are saved (the paper trail) |
| `verify_command` | unset | The check command the author runs and the reviewer re-runs, e.g. `make check` or `npm test` |
| `conventions_files` | `[]` | Repo rule files the reviewer reads first, e.g. `["AGENTS.md", "CONTRIBUTING.md"]` |
| `tracker_hint` | unset | Names the ticket system (e.g. `Jira`, `Linear`), so the author can search for its tools |

### Why the author is one setting, not two

Planning and coding are one author. A plan written by one model and coded by another loses the
reasoning that the plan's "why" depends on. So the config has one author model and one reviewer
model. A skill can't switch the model of the session it runs in. Start the session on
`author_model`, and the skill checks that it did.

## The milestone reference

The first argument can be any of these:

| Reference | How the spec is found |
|---|---|
| Ticket key, e.g. `PROJ-123` | The ticket tool, found by ToolSearch and `tracker_hint`; or paste if none is connected |
| URL | Fetched; paste if it needs a login |
| File path | Read |
| Quoted text | Used as the spec |

The spec is copied verbatim into the plan's **Spec** section, so the plan doesn't drift from the
ticket it came from.

## Design choices (change any of these)

| Choice | Why | Alternative |
|---|---|---|
| Approval is a skill argument, recorded in a Decisions log | The decision is on the record, not in chat | A hard stop with `AskUserQuestion` |
| Invoking build doesn't approve the plan | Gate 1 stays a real gate | Treat invocation as approval (the project's original rule) |
| One review round per invocation | Keeps a human between rounds; the author doesn't loop alone | Auto-loop until clean |
| Reject leaves code and plan in place | Nothing is deleted without a human looking | Revert the branch on reject |
| No commits without an explicit request | The human reviews the working tree first | Auto-commit per gate |

## What this doesn't do

- It doesn't write back to the ticket tracker. Status changes stay in the plan file.
- It doesn't split a milestone into several plans or several branches.
- It doesn't run the reviewer in the background. Its result is needed before the next step.
- It doesn't check the repo's own check command beyond running it. `verify_command` is only as good as the project's tests.
