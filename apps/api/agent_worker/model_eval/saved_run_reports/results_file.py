"""The results file: where a graph-eval run is stored, what it holds, and how to read it back or slim it for committing.

What this is: everything about the FILE a `make eval-graph` run leaves behind (`model_eval/results/graph-<label>.json`, gitignored)
and its committable summary (`docs/dev/eval-baselines/<label>.json`), and nothing about producing or scoring a run. It has no
database, graph or model imports, so the report and compare tools can load a run on a machine that has none of those.

Why it is one module: the file's SHAPE changes for its own reasons, apart from the CLI and the runner. C6 must keep a hosted
model's key out of the file and out of every snapshot (C5 log, Round 7), and that change belongs in `build_record` (what is
written) and `slim` (what is committed), side by side, with one test module.

How to read it: the paths, then `build_record` and `write_results` (writing a run), then `load_results`, `slim` and `snapshot`
(reading and committing). Other modules must read `RESULTS_DIR` and `SNAPSHOT_DIR` as attributes of this module at call time
(`results_file.RESULTS_DIR`), never copy them with `from results_file import RESULTS_DIR`: the tests redirect them with
`monkeypatch.setattr(results_file, ...)`, and a copied name would escape the patch and touch the developer's real folders.

docs/dev/implementations/c5-pipeline-eval-harness.md, Steps 3 and 8 (C5-D1, C5-D2); moved out of `run_labeled_pages.py` in code review
round 2 (C5-CR2-2).
"""

import dataclasses
import hashlib
import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agent_worker.model_eval import labels, run_eval
from agent_worker.model_eval.labels import PageLabel
from agent_worker.policy import RetryPolicy

RESULTS_DIR = run_eval.RESULTS_DIR
# Committable summaries of runs (`--snapshot`): the raw results above are gitignored, because they hold the venues' page text and
# every extraction. A snapshot keeps the scores, the aggregate, the model and the prompt's hashes, which is what comparing needs.
SNAPSHOT_DIR = Path(__file__).resolve().parents[5] / "docs" / "dev" / "eval-baselines"
LABELS_FILE = Path(labels.__file__)

_HEAVY_RUN_KEYS = ("raw", "validated", "committed", "staged_documents")
_PROMPT_HASHES = ("instruction_sha", "response_schema_sha", "response_schema_chars")


# ---------------------------------------------------------------------------
# Facts the file records about the run
# ---------------------------------------------------------------------------


def labels_sha(path: Path = LABELS_FILE) -> str:
    """The SHA-256 of the label file, so a results file names the exact labels that scored it."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def held_out_scored(fixtures: list[str], page_labels: Mapping[str, PageLabel]) -> bool:
    """Whether any held-out page was scored in this run. The first such scoring is C6's, so the file says so outright (C5-D3)."""
    return any(page_labels[name].held_out for name in fixtures if name in page_labels)


def git_commit() -> str | None:
    """The commit the harness ran at, for the record; None outside a git checkout."""
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, timeout=10
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


# ---------------------------------------------------------------------------
# Writing a run
# ---------------------------------------------------------------------------


def build_record(
    *,
    label: str | None,
    started_at: str,
    set_name: str,
    scenario: str | None,
    fixture_names: list[str],
    page_labels: Mapping[str, PageLabel],
    config: Any,
    options: Any,
    request: dict[str, Any],
    policy: RetryPolicy,
    provenance: dict[str, Any] | None,
    aggregate: dict[str, Any],
    scenarios: list[dict[str, Any]],
    runs: list[dict[str, Any]],
) -> dict[str, Any]:
    """The results file's content, in the order the file lists it. This is the one place the file's shape is defined.

    `config` and `options` are the run_eval dataclasses; they are written whole, so a secret must never become a field of either
    (or must be dropped here), because `slim` keeps `request_options` in the committed snapshot."""
    return {
        "label": label,
        "started_at": started_at,
        "set": set_name,
        "scenario": scenario,
        "labels_sha": labels_sha(),
        "held_out_scored": held_out_scored(fixture_names, page_labels),
        "harness_commit": git_commit(),
        "config": dataclasses.asdict(config),
        "request_options": dataclasses.asdict(options),
        "request": request,
        "policy": dataclasses.asdict(policy),
        "provenance": provenance,
        "aggregate": aggregate,
        "scenarios": scenarios,
        "runs": runs,
    }


def results_path(label: str | None) -> Path:
    """Where the run named `label` is stored."""
    return RESULTS_DIR / f"graph-{label}.json"


def rescore_path(label: str) -> Path:
    """Where the rescore of the run named `label` is written (a new file; the original is never touched)."""
    return RESULTS_DIR / f"graph-rescore-{label}.json"


def write_results(path: Path, record: dict[str, Any]) -> Path:
    """Write a results record (or a rescored copy of one) as JSON; `default=str` keeps a stray date from failing a long run."""
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False, default=str))
    return path


# ---------------------------------------------------------------------------
# Reading a run, and the committable summary
# ---------------------------------------------------------------------------


def load_results(label: str) -> dict[str, Any]:
    """A saved run: the full raw file if it is still on this machine, else the committed snapshot of the same label."""
    raw, snap = results_path(label), SNAPSHOT_DIR / f"{label}.json"
    for path in (raw, snap):
        if path.is_file():
            loaded: dict[str, Any] = json.loads(path.read_text())
            return loaded
    raise FileNotFoundError(f"no saved run {label!r}: looked for {raw} and {snap}")


def _slim_run(run: dict[str, Any]) -> dict[str, Any]:
    """A run record without the extractions and staged documents (the venue's page text lives in the latter)."""
    return {k: v for k, v in run.items() if k not in _HEAVY_RUN_KEYS}


def slim(data: dict[str, Any]) -> dict[str, Any]:
    """The part of a results file worth committing: scores, aggregate, scenarios, model and policy, and the prompt's hashes.

    Left out, and why: each run's extractions and staged documents (they carry the venues' page text and are why the raw files are
    gitignored), and the full prompt and schema text (their hashes say which prompt produced the numbers). Everything `--report` and
    `--compare` read is kept, so a snapshot renders the same report as the raw file."""
    out = {k: v for k, v in data.items() if k not in ("runs", "scenarios", "request")}
    out["request"] = {k: v for k, v in (data.get("request") or {}).items() if k in _PROMPT_HASHES}
    out["runs"] = [_slim_run(r) for r in data["runs"]]
    out["scenarios"] = [
        {**s, "result": {**s["result"], "runs": [_slim_run(r) for r in s["result"]["runs"]]}}
        for s in data.get("scenarios", [])
    ]
    return out


def snapshot(label: str) -> Path:
    """Write the slim summary of a saved run to `SNAPSHOT_DIR/<label>.json`, ready to commit."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    out = SNAPSHOT_DIR / f"{label}.json"
    out.write_text(json.dumps(slim(load_results(label)), indent=2, ensure_ascii=False))
    return out
