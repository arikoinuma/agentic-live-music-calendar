---
name: plan-milestone
description: Write the implementation plan for a build-plan milestone, have a different model review it for one round, resolve the findings, and stop for Ari's approval. Steps 1–3 of the cycle in AGENTS.md.
argument-hint: <milestone, e.g. "B3" or "A2">
disable-model-invocation: true
---

Run steps 1–3 of the cycle in `AGENTS.md`, "Implementation plans", for milestone **$ARGUMENTS**,
then stop at Ari's approval gate. Write no code: this skill ends with a reviewed plan.

1. **Write the plan.** Read the milestone in `docs/dev/alpha-build-plan.md` (H milestones: `alpha-deployment-plan.md`), every doc it cites,
   the relevant style guide, and the code it touches. Write
   `docs/dev/implementations/<milestone>-<slug>.md` with the header (Status, Date, Author model
   = you, Reviewer model, Spec), then context, test approach, steps (marking [written] /
   [fill-in] and naming each `TODO(Ari)` gap with its lesson), critical files, and verification.
   Use `b2-routes-and-data-loading.md` as the model for shape and depth. If a decision is
   genuinely Ari's to make, list it under "Decisions for the user / reviewer" with your
   recommendation rather than stopping to ask. Set Status to `Plan review`.

2. **Review.** Follow "Running a review round from the author's session" in `AGENTS.md`:
   snapshot, spawn `plan-reviewer` with `model` set to a model other than yours, prompting
   it for a *plan review* of the file, then check it changed nothing else.

3. **Resolve.** Fill every Resolution cell and make the plan edits they describe. Set Status to
   `Awaiting approval`. If round 2 looks warranted, don't run it; say so.

4. **Stop and hand off** to Ari as `AGENTS.md` describes: the plan file link, the verdict and
   counts, the findings you rejected and why, open decisions for Ari, and what to check before
   approving. End by saying that `/build-milestone <plan file>` starts implementation once
   approved.
