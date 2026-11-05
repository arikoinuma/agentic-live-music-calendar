# Evaluation snapshots

Slim, committed summaries of graph-level evaluation runs (`make eval-snapshot LABEL=<name>`). The raw results files (`apps/api/agent_worker/eval/results/graph-<label>.json`) are gitignored because they hold the venues' page text and every extraction; a snapshot keeps what comparing runs needs and nothing else:

- **Kept:** the aggregate (headline, retry loop, validation recall, field accuracy, gate), every run's scores and attempts, the scenarios' reconcile counts and database scores, the model and its provenance, the policy, `labels_sha`, the harness commit, and the **hashes** of the prompt and response schema (they say which prompt produced the numbers).
- **Left out:** each run's extractions, the staged documents (page text), and the full prompt and schema text.

A snapshot reads like the raw file: `make eval-report LABEL=<name>` and `make eval-compare LABELS="a b"` use the raw file if it is on the machine and fall back to the snapshot here. `--rescore` needs the raw file (it recomputes scores from the stored extractions), so a snapshot cannot be rescored.

Commit a snapshot for a run that matters (a milestone's baseline, a hosted-model run in C6) and say in the milestone's log which one it is. How to run and read these: `docs/dev/evaluating-model-performance.md`.
