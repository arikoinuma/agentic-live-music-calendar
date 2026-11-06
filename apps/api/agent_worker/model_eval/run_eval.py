"""Throwaway evaluation script — see docs/dev/env-setup.md Phase 5.

Not part of the app. Nothing here needs to be production-quality; the
point is to look at raw output by hand and decide which model to use,
per the doc's three comparison axes (schema match, retry frequency,
confidence calibration). Delete or keep around for future model swaps —
either is fine.

Fetch is deliberately not part of this script. Fixtures are already-saved
static files (per the doc's fixture-collection step) standing in for a
real Fetch step — this script only exercises Extract, the one part of
the pipeline that's actually in question at this phase.

A2 extended it from "print what came back" into a measurement harness
(docs/dev/implementations/a2-extraction-schema.md, Step 1): run every fixture
`--runs N` times under a `--label`, record per-run outcomes, retries by field, latency,
and what was filled in, and write `model_eval/results/<label>.json` (git-ignored). Scoring
facts that need a human — which entries are non-music, which pages state an end time —
live in `reference.py`, written before the baseline so every label is scored the same way.

    uv run python -m agent_worker.model_eval.run_eval --label baseline --runs 3
    uv run python -m agent_worker.model_eval.run_eval --compare baseline schema-only after

A2.1 (docs/dev/implementations/a2.1-extraction-reliability.md) made it measure Ari's accuracy
standard: fixtures come from `labels.PAGE_LABELS` (`--set gated|informational|all`), every run
is scored against hand-written labels by `scoring.py`, and the label's gate line (did every
run meet every tier?) is recorded and compared. Extraction goes through the pipeline's own
`extraction.extract_page` / `extract_image`, starting from the pipeline's configuration; each
experiment flag overrides exactly one setting (`configure`). `--rescore` writes a new
`a21-rescore-<label>.json` and leaves the original untouched.

    uv run python -m agent_worker.model_eval.run_eval --label a21-rebaseline --set all --runs 5
    uv run python -m agent_worker.model_eval.run_eval --label a21-newlines --set all --line-breaks
    uv run python -m agent_worker.model_eval.run_eval --rescore after
"""

import argparse
import base64
import contextvars
import datetime
import hashlib
import json
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

from agent_worker import act_split, extraction, policy, status_check, validation
from agent_worker.llm import ModelRoles, RequestOptions, build_clients, request_kwargs
from agent_worker.main import model_endpoint_problem
from agent_worker.model_eval import labels, scoring
from agent_worker.model_eval import legacy as legacy_config
from agent_worker.model_eval.labels import (
    PAGE_LABELS,
    VENUE_FACTS,
    gated_fixtures,
    held_out_fixtures,
    informational_fixtures,
)
from agent_worker.model_eval.reference import REFERENCE, FixtureReference, fixture_key
from agent_worker.schemas import ShowExtraction
from app.config import settings

CAPTURED_PAGES_DIR = Path(__file__).parent / "captured_pages"
RESULTS_DIR = Path(__file__).parent / "results"

# Request options are the pipeline's own (`extraction.PIPELINE_OPTIONS`: model from MODEL_NAME,
# max_tokens, max_retries, num_ctx), recorded in every results file so a run can be reproduced
# and a later label compared like-for-like. A2.1 moved them out of this file so the eval can't
# drift from what the pipeline sends.
#
# The model: qwen3-vl:4b was the original candidate but is out — confirmed that it never
# reliably completes structured extraction against this schema via instructor, regardless of
# Mode or max_tokens, despite answering correctly in plain chat. gemma4:e4b is the fallback the
# doc anticipated; since A2 the model follows MODEL_NAME (apps/api/.env) — currently the derived
# 32768-token-context model, gemma4-e4b-32k (apps/api/ollama/gemma4-e4b-32k.Modelfile).

# The eval's client comes from the same factory as the pipeline's (C6): one OpenAI-SDK client pointed at the
# configured endpoint (Ollama locally, DeepInfra hosted), wrapped by instructor so `response_model=` is available
# and output is validated against the Pydantic schema, retrying on a validation failure. Before C6 this module
# built its own Ollama client, so a "hosted" run would have silently gone to localhost.
#
# Mode.JSON, not Mode.TOOLS (chosen in `llm.build_clients`): confirmed directly against the local model —
# qwen3-vl:4b puts its "thinking" output in a separate `reasoning` field
# distinct from `content` (visible in the raw Ollama response), and in
# Mode.TOOLS it was never reliably completing an actual tool call even
# with a very high max_tokens, raising IncompleteOutputException every
# time. Mode.JSON only needs the model to eventually emit valid JSON in
# `content`, which doesn't depend on tool-calling working correctly on
# top of a model that's already spending a lot of its output on
# reasoning — much more reliable in practice for this model/backend.
client, instructor_client = build_clients(settings)

# Per-run counters (C6-PR1-6). instructor re-asks the model when its output fails Pydantic validation and emits
# "parse:error" on every failed parse, including the final attempt, which is then raised rather than retried. (An
# IncompleteOutputException, the Phase 5 failure, is re-raised immediately and never emits this hook, so it only
# shows up as an outcome.) Its completion hook carries the response's token `usage`. Both hooks are registered once
# and write to the CURRENT run's `RunCounters`, found through a ContextVar: a run on its own thread sees only its
# own counts, which throughput measurements with parallel requests depend on (module-level lists cleared by each
# run would have been scrambled by the first overlap).


@dataclass
class RunCounters:
    """What one run's hooks saw: failed parses, and the token usage summed over every call in the run."""

    parse_errors: list[Exception] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    usage_seen: bool = False

    def tokens_record(self) -> dict[str, int] | None:
        """The run's tokens, or None when no response carried `usage`: a provider that reports nothing is
        an unknown cost, never 0 tokens."""
        if not self.usage_seen:
            return None
        return {"prompt": self.prompt_tokens, "completion": self.completion_tokens}


_counters: contextvars.ContextVar[RunCounters | None] = contextvars.ContextVar("run_eval_counters", default=None)


def new_counters() -> RunCounters:
    """Start counting a new run in the current thread (context) and return its counters."""
    counters = RunCounters()
    _counters.set(counters)
    return counters


def _record_parse_error(error: Exception) -> None:
    """Hook for instructor's `parse:error` event: remember a response that failed to parse into the schema, on the
    current run's counters. Does nothing outside a counted run (`new_counters()` not called in this thread)."""
    counters = _counters.get()
    if counters is not None:
        counters.parse_errors.append(error)


def _record_completion(response: Any) -> None:
    """Hook for instructor's `completion:response` event: add the call's token usage to the current run's counters.
    A response with no usage block (a provider that omits it) adds nothing and leaves `usage_seen` false, so the
    run's token count reads as unknown, never as zero. Does nothing outside a counted run."""
    counters = _counters.get()
    usage = getattr(response, "usage", None)
    if counters is not None and usage is not None:
        counters.usage_seen = True
        counters.prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
        counters.completion_tokens += getattr(usage, "completion_tokens", 0) or 0


def register_hooks(instructor: Any) -> None:
    """Attach the counting hooks to an instructor client. A function so a test can check both are registered:
    forgetting the completion hook would leave every results file with `tokens: null` and nothing failing."""
    instructor.on("parse:error", _record_parse_error)
    instructor.on("completion:response", _record_completion)


register_hooks(instructor_client)


def load_text_fixture(path: Path) -> str:
    """A captured page's visible text, cleaned exactly as the pipeline cleans a page (flat form, as A2's metrics were
    defined on). Confirmed on the White Squirrel capture: a 93KB "Save As" dump was 97% <script>/markup around 2.7KB
    of content."""
    return extraction.clean_text(path.read_text(), keep_line_breaks=False)


def load_image_fixture(path: Path) -> str:
    """A saved poster image, base64-encoded for a multimodal message. The details of how it is embedded follow."""
    # read a saved image fixture (the flyer-image case) and return
    # it base64-encoded. Multimodal chat messages take an image as a
    # data URL: f"data:image/png;base64,{encoded}" (adjust the mime type
    # to match the actual file, e.g. image/jpeg) inside an
    # {"type": "image_url", "image_url": {"url": ...}} content block.
    binary_image = path.read_bytes()
    base64_bytes = base64.b64encode(binary_image)
    return base64_bytes.decode()



def extract(
    fixture_path: Path,
    *,
    options: RequestOptions,
    config: extraction.ExtractionConfig,
    venue_name: str = "",
    metro_timezone: str = "",
    fetch_date: datetime.date | None = None,
    seed: int | None = None,
    legacy: bool = False,
    splitter_options: RequestOptions | None = None,
    status_options: RequestOptions | None = None,
) -> extraction.PageExtractionResult:
    """Extract one fixture, exactly as the pipeline would (A2.1: through `extract_page` /
    `extract_image`, with this module's hooked client so parse failures are counted).

    `legacy` swaps in the frozen pre-A2 schema and prompt (model_eval/legacy.py) so A2's `baseline`
    label stays re-runnable; it bypasses the A2.1 entry point on purpose.
    """
    is_image = fixture_path.suffix in (".jpg", ".jpeg", ".png", ".webp")
    # Don't add retry/error-handling around these calls: how often they need instructor's
    # built-in retries, and how often they fail outright, is the thing being measured.
    if legacy:
        if is_image:
            content: Any = [
                {"type": "text", "text": legacy_config.LEGACY_INSTRUCTION},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{load_image_fixture(fixture_path)}"}},
            ]
        else:
            content = legacy_config.LEGACY_INSTRUCTION + load_text_fixture(fixture_path)
        result = instructor_client.chat.completions.create(
            response_model=legacy_config.VenuePageExtraction,
            messages=[{"role": "user", "content": content}],
            **request_kwargs(options, seed),
        )
        # The frozen pre-A2 schema is deliberately a different class from the live one (model_eval/legacy.py), so it does
        # not fit the result's type; this path bypasses the A2.1 entry point on purpose (see the docstring).
        return extraction.PageExtractionResult(extraction=result, source="model", sent_text="")  # type: ignore[arg-type]

    if not (venue_name and metro_timezone and fetch_date):
        raise ValueError("extract() needs venue_name, metro_timezone and fetch_date (labels.py)")
    if is_image:
        # NOTE: every image is labelled image/png, including the .webp fixture — the pipeline
        # does the same. Pre-existing, equal across labels (a2-extraction-schema.md, Step 1).
        return extraction.extract_image(
            load_image_fixture(fixture_path), mime="image/png", fetch_date=fetch_date,
            client=instructor_client, options=options, config=config, seed=seed,
        )
    return extraction.extract_page(
        fixture_path.read_text(), venue_name=venue_name, metro_timezone=metro_timezone,
        fetch_date=fetch_date, client=instructor_client, options=options, config=config, seed=seed,
        splitter_options=splitter_options, status_options=status_options,
    )


# ---------------------------------------------------------------------------
# Configuration: the pipeline's, plus at most one experiment override per flag
# ---------------------------------------------------------------------------


def add_override_flags(parser: argparse.ArgumentParser) -> None:
    """The experiment ladder's flags (a2.1 plan, "Experiment protocol"). Each overrides one
    field of the pipeline's configuration; none given = exactly what the pipeline runs."""
    parser.add_argument("--temperature", type=float, default=None, help="sampling temperature (rung a21-temp0)")
    # Model overrides (C6): one flag per role, so a rung changes one model and a change is attributable to it.
    parser.add_argument("--model", dest="model", default=None, help="the page model (default MODEL_NAME)")
    parser.add_argument("--splitter-model", dest="splitter_model", default=None, help="the act splitter's model (rung c6-split-*)")
    parser.add_argument("--status-model", dest="status_model", default=None, help="the status question's model")
    parser.add_argument("--route", choices=["auto", "model"], default=None, help="auto = JSON-LD first (rung a21-structured)")
    # Typed as Any-valued so `**flag` is accepted for every add_argument parameter (inferred as dict[str, object],
    # it matches none of them).
    flag: dict[str, Any] = {"action": "store_const", "const": True, "default": None}
    parser.add_argument("--line-breaks", dest="keep_line_breaks", help="clean with line breaks (rung a21-newlines)", **flag)
    parser.add_argument("--status", dest="status_field", help="status field + cancelled sentence (rung a21-cancelled)", **flag)
    parser.add_argument("--year-rule", dest="year_rule", help="years from the fetch date (rung a21-year)", **flag)
    parser.add_argument("--act-conventions", dest="act_conventions", help="D5's conventions on the model route (rung a21-act-conventions)", **flag)
    parser.add_argument("--acts-desc", dest="acts_split_description", help="the split-acts description (rung a21-acts-desc)", **flag)
    parser.add_argument("--status-pass", dest="status_pass", help="the separate cancelled/postponed question (rung a21-status-pass)", **flag)
    parser.add_argument("--title-split", dest="title_split", help="verbatim titles + the act splitter on the model route (rung a21-title-split)", **flag)
    parser.add_argument("--image-urls", dest="keep_image_urls", help="keep <img> URLs in the cleaned text (rung a3-image-urls, G25)", **flag)
    parser.add_argument("--old-rules", dest="include_new_rules", action="store_const", const=False, default=None,
                        help="extraction_instruction(include_new_rules=False): A2's schema-only label")


_CONFIG_FIELDS = ("route", "keep_line_breaks", "status_field", "year_rule", "act_conventions",
                  "acts_split_description", "include_new_rules", "status_pass", "title_split", "keep_image_urls")


def overrides_from(args: argparse.Namespace) -> dict[str, Any]:
    """The flags that were actually given, as {field: value}."""
    names = ("temperature", "model", "splitter_model", "status_model", *_CONFIG_FIELDS)
    return {name: getattr(args, name) for name in names if getattr(args, name, None) is not None}


def parse_overrides(argv: list[str]) -> dict[str, Any]:
    """Parse only the override flags (used by tests and by `main`)."""
    parser = argparse.ArgumentParser(add_help=False)
    add_override_flags(parser)
    return overrides_from(parser.parse_args(argv))


def configure(overrides: dict[str, Any]) -> tuple[RequestOptions, extraction.ExtractionConfig]:
    """Start from the pipeline's configuration and apply the overrides. With none, the result
    IS the pipeline's (A2.1-PR2-5): a label measures whatever the pipeline has adopted."""
    options = extraction.PIPELINE_OPTIONS
    if "temperature" in overrides:
        options = replace(options, temperature=overrides["temperature"])
    if "model" in overrides:
        options = replace(options, model=overrides["model"])
    config = replace(extraction.PIPELINE_CONFIG, **{k: v for k, v in overrides.items() if k in _CONFIG_FIELDS})
    return options, config


def configure_roles(overrides: dict[str, Any]) -> ModelRoles:
    """The pipeline's per-role options with at most one model override per role (C6). With none, the result IS the
    pipeline's roles, as `configure` does for the page options. `--temperature` applies to every role, since the
    pipeline sends one temperature on all its calls."""
    roles = extraction.PIPELINE_ROLES
    if "temperature" in overrides:
        roles = ModelRoles(**{k: replace(v, temperature=overrides["temperature"]) for k, v in vars(roles).items()})
    for flag, role in (("model", "page"), ("splitter_model", "splitter"), ("status_model", "status")):
        if flag in overrides:
            roles = replace(roles, **{role: replace(getattr(roles, role), model=overrides[flag])})
    return roles


# ---------------------------------------------------------------------------
# Scoring — turning one extraction into countable facts
# ---------------------------------------------------------------------------

# Fields every show must have in either schema; everything else is optional and gets a
# fill count.
_ALWAYS_PRESENT = {"venue", "date", "acts", "is_ambiguous", "confidence"}
# Fields that, when filled where the page states no price, are invented prices.
_PRICE_FIELDS = ("ticket_info", "admission_advance", "admission_day", "free_admission")


def _act_name(act: Any) -> str:
    """One act's name, whichever schema produced it: the baseline's acts are plain strings, the new schema's are
    objects with a `name`."""
    return act if isinstance(act, str) else str(act.get("name", ""))


def score_extraction(
    extraction: dict[str, Any], ref: FixtureReference, page_text: str, *,
    source: str = "model", page_html: str = "",
) -> dict[str, Any]:
    """Count what one run filled in and what it got wrong, against the hand reference.

    `invented_*` means "the page states no such thing (reference.py), yet the model
    returned one". `leaks` are returned acts matching a non-music term. Both are only as
    good as reference.py, which is written by hand and kept deliberately small.

    `source` and `page_html` make the invented-image-URL count meaningful (A3-PR1-11): a URL on
    a JSON-LD show came from structured data, not a model, and an image run has no page to check,
    so neither can be "invented" — checked against the cleaned text, every JSON-LD URL was (225 in
    a21-confirm). The rest are checked against the unescaped HTML as well as the text: the same
    rule as the pipeline's repair (validation.verify_image_url).
    """
    fills: Counter[str] = Counter()
    act_counts: list[int] = []
    leaks: list[str] = []
    borderline: list[str] = []
    image_urls: list[str] = []
    empty_acts = 0
    for show in extraction["shows"]:
        for key, value in show.items():
            if key not in _ALWAYS_PRESENT and value is not None:
                fills[key] += 1
        act_counts.append(len(show["acts"]))
        if not show["acts"]:
            empty_acts += 1
        # A model sometimes puts an entry's title in `venue` and returns no acts at all;
        # a leak named only there would otherwise score as clean.
        if any(term in str(show.get("venue", "")).lower() for term in ref.non_music_terms):
            leaks.append(str(show["venue"]))
        for act in show["acts"]:
            if isinstance(act, dict):
                for key in ("start_time", "sequence_number"):
                    if act.get(key) is not None:
                        fills[f"acts.{key}"] += 1
            name = _act_name(act).lower()
            if any(term in name for term in ref.non_music_terms):
                leaks.append(_act_name(act))
            if any(term in name for term in ref.borderline_terms):
                borderline.append(_act_name(act))
        if show.get("image_url"):
            image_urls.append(show["image_url"])
    return {
        "fills": dict(fills),
        "act_counts": act_counts,
        # Shows returned with no performing act: usually a leaked non-music entry or a
        # model that couldn't read the lineup. A3's completeness check owns dropping them;
        # here they are counted so the leak metric has no blind spot.
        "empty_acts": empty_acts,
        "leaks": leaks,
        "borderline": borderline,
        # A start time the page never states. Under the baseline schema `time` is
        # required, so every show on such a page counts — that is v0.1-G8's cost, measured.
        "invented_time": 0 if ref.states_start_time else fills["time"],
        "invented_end_time": 0 if ref.states_end_time else fills["end_time"],
        "invented_price": 0 if ref.states_price else sum(fills[f] for f in _PRICE_FIELDS),
        # A model-route URL must appear verbatim in the page (the cleaned text, which carries
        # "[image: URL]" lines when keep_image_urls is on, or the unescaped HTML); one that doesn't is
        # almost certainly made up. Not checked for structured or image runs (see the docstring).
        "image_urls": image_urls,
        "invented_image_urls": (
            [] if source in ("structured", "image")
            else [u for u in image_urls if not validation.verify_image_url(u, page_html, page_text)]
        ),
    }


def _generalize_loc(loc: tuple[Any, ...]) -> str:
    """A validation error's location as a path with list positions replaced by `*`
    (`("shows", 3, "acts", 0, "start_time")` -> `"shows.*.acts.*.start_time"`), so failures on different list
    positions aggregate together."""
    return ".".join("*" if isinstance(part, int) else str(part) for part in loc)


def classify_parse_error(error: Exception) -> list[str]:
    """Name the field and kind of each validation problem in a failed parse."""
    if isinstance(error, ValidationError):
        return [f"{_generalize_loc(e['loc'])}:{e['type']}" for e in error.errors()]
    return [type(error).__name__]


def _same_model(listed: str | None, wanted: str) -> bool:
    """True when Ollama's listed model name is the one asked for. Ollama lists a model created without a tag as
    "name:latest" and `MODEL_NAME` may omit the tag, so both spellings match."""
    return listed in (wanted, f"{wanted}:latest")


def ollama_root(base_url: str | None) -> str:
    """Ollama's own API root, from the OpenAI-compatible URL the worker is configured with: the same host without
    its `/v1`. No URL is written in the code (Ari's comment on PR 80); the endpoint is `MODEL_BASE_URL` and nothing else."""
    return (base_url or "").rstrip("/").removesuffix("/v1")


def loaded_context_length(model: str, base_url: str | None) -> int | None:
    """The context window Ollama actually loaded the model with (from /api/ps). Called
    right after a label's runs, while the model is still resident. If this isn't num_ctx,
    the request's num_ctx override didn't take effect."""
    loaded = httpx.get(f"{ollama_root(base_url)}/api/ps", timeout=10).json().get("models", [])
    return next((m.get("context_length") for m in loaded if _same_model(m.get("name"), model)), None)


def model_provenance(options: RequestOptions, base_url: str | None) -> dict[str, str | int | None]:
    """Which model build produced a label, so a later run can be checked against it.

    Ollama (`provider` "ollama"): its version and the model's digest (`ollama pull` silently changes a tag), from
    /api/version and /api/tags (/api/show on this Ollama version doesn't carry the digest), and the context
    window it actually loaded, which is how a request's ignored `num_ctx` was found out. A hosted provider has no
    such endpoints, and asking localhost would fail or describe the wrong model, so it makes no request: it
    records the provider, the endpoint's host and the requested model id (C6 plan, Test 3). A hosted model's
    weights and quantization are the provider's to change, which is why the parity run (C6 Step 6) compares the
    numbers instead of trusting the name.
    """
    if options.provider != "ollama":
        return {
            "provider": options.provider, "base_url_host": urlparse(base_url or "").hostname, "model": options.model,
        }
    model, num_ctx = options.model, options.num_ctx
    root = ollama_root(base_url)
    version = httpx.get(f"{root}/api/version", timeout=10).json().get("version")
    tags = httpx.get(f"{root}/api/tags", timeout=10).json().get("models", [])
    digest = next((m.get("digest") for m in tags if _same_model(m.get("name"), model)), None)
    return {
        "provider": options.provider,
        "ollama_version": version,
        "model_digest": digest,
        "loaded_context_length": loaded_context_length(model, base_url),
        "requested_num_ctx": num_ctx,
    }


def labels_sha() -> str:
    """The sha-256 of `labels.py` as it is now, recorded in every results file (C6-D8): a score on a held-out page
    can then be shown to postdate the labels it was scored against."""
    return hashlib.sha256(Path(labels.__file__).read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Running and aggregating
# ---------------------------------------------------------------------------


def run_once(
    item: Path, run_index: int, options: RequestOptions, config: extraction.ExtractionConfig,
    legacy: bool = False, roles: ModelRoles | None = None,
) -> dict[str, Any]:
    """One extraction of one fixture, recorded as a plain dict (no extraction exception escapes).

    Two scores are kept: A2's per-run metrics (`score`, against reference.py) and, for a
    labelled fixture, A2.1's `label_score` against Ari's standard (scoring.py).
    """
    key = fixture_key(item)
    ref = REFERENCE.get(key, FixtureReference())
    label = PAGE_LABELS.get(item.name)
    facts = VENUE_FACTS[label.venue] if label else None
    is_image = item.suffix in (".jpg", ".jpeg", ".png", ".webp")
    page_text = "" if is_image else load_text_fixture(item)

    counters = new_counters()
    started = time.perf_counter()
    record: dict[str, Any] = {"fixture": item.name, "key": key, "run": run_index, "seed": run_index}
    result = None
    # Broad except is deliberate (see the pyproject ruff ignore): one failing run must
    # not stop the loop, and *how* it failed — its exception class — is a result.
    try:
        result = extract(
            item, options=options, config=config, seed=run_index, legacy=legacy,
            splitter_options=roles.splitter if roles else None, status_options=roles.status if roles else None,
            venue_name=facts.name if facts else "", metro_timezone=facts.metro_timezone if facts else "",
            fetch_date=label.captured_on if label else None,
        )
        record["outcome"] = "ok"
    except Exception as err:
        record["outcome"] = type(err).__name__
        record["error"] = str(err)[:400]
    record["seconds"] = round(time.perf_counter() - started, 1)

    if result is not None:
        dump = result.extraction.model_dump(mode="json")
        record["page_readable"] = dump["page_readable"]
        record["shows"] = len(dump["shows"])
        record["source"] = result.source
        record["sent_text"] = result.sent_text
        record["notes"] = result.notes
        record["score"] = score_extraction(
            dump, ref, page_text, source=result.source, page_html="" if is_image else item.read_text(),
        )
        record["extraction"] = dump
        # Scored outside the try above: a scoring bug must surface, not be recorded as a
        # model failure.
        if label is not None:
            page_score = scoring.score_page(label, dump, "" if is_image else item.read_text(), item.name)
            page_score.route = result.source
            record["label_score"] = asdict(page_score)
    failures = [c for e in counters.parse_errors for c in classify_parse_error(e)]
    record["parse_failures"] = len(counters.parse_errors)
    record["tokens"] = counters.tokens_record()
    record["parse_failure_fields"] = failures
    # parse:error fires on every failed parse including the last, so attempts used =
    # failed parses + the one that succeeded. (A call that dies of IncompleteOutputException
    # emits no parse:error, so its aborted attempt isn't counted here — it is the outcome.)
    record["attempts_used"] = len(counters.parse_errors) + (1 if record["outcome"] == "ok" else 0)
    return record


def gate_summary(runs: list[dict[str, Any]], route_when_failed: str = "any") -> dict[str, Any]:
    """Ari's standard applied to a label's gated pages (scoring.gate), overall and per route,
    plus each labelled page's per-run counts for reading where it fell short."""
    by_run: dict[int, list[scoring.PageScore | scoring.PageFailure]] = {}
    pages: dict[str, list[dict[str, Any]]] = {}
    for r in runs:
        label = PAGE_LABELS.get(r.get("fixture", ""))
        if label is None:  # an unlabelled fixture has no gate to apply
            continue
        if r["outcome"] != "ok":
            outcome: scoring.PageScore | scoring.PageFailure = scoring.PageFailure(
                fixture=r["fixture"], error=r["outcome"], route=route_when_failed
            )
            counts: dict[str, Any] = {"run": r["run"], "raised": r["outcome"]}
        elif "label_score" in r:
            outcome = scoring.PageScore.from_dict(r["label_score"])
            counts = {
                "run": r["run"], "route": outcome.route,
                **{k: getattr(outcome, k) for k in ("missed", "acts_wrong", "fabricated", "leaks", "unsplit", "dropped_empty")},
                "fields_wrong": {n: t.wrong for n, t in outcome.fields.items() if t.wrong},
                "fields_missing": {n: f"{t.missing}/{t.stated}" for n, t in outcome.fields.items() if t.missing},
            }
        else:
            continue
        pages.setdefault(r["fixture"], []).append(counts)
        if label.gated:
            by_run.setdefault(r["run"], []).append(outcome)
    gates = {}
    for scope in ("all", "structured", "model"):
        result = scoring.gate(by_run, route=None if scope == "all" else scope)
        gates[scope] = {"passed": result.passed, "failures": result.failures, "pages": result.pages}
    return {"gate": gates, "pages": pages}


def _runs_identical(ok_runs: list[dict[str, Any]]) -> bool | None:
    """True/False when every page has at least two successful runs to compare; else None."""
    pages: dict[str, list[dict[str, Any]]] = {}
    for r in ok_runs:
        pages.setdefault(r.get("fixture", ""), []).append(r)
    if not pages or any(len(same) < 2 for same in pages.values()):
        return None
    return all(all(r["extraction"] == same[0]["extraction"] for r in same) for same in pages.values())


def aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll a label's runs up into the numbers the comparison reads."""
    ok = [r for r in runs if r["outcome"] == "ok"]
    out: dict[str, Any] = {
        "runs": len(runs),
        "ok": len(ok),
        "outcomes": dict(Counter(r["outcome"] for r in runs)),
        "mean_attempts_used": round(sum(r["attempts_used"] for r in runs) / max(len(runs), 1), 2),
        "parse_failures": sum(r["parse_failures"] for r in runs),
        "parse_failure_fields": dict(Counter(f for r in runs for f in r["parse_failure_fields"])),
        "mean_seconds": round(sum(r["seconds"] for r in runs) / max(len(runs), 1), 1),
        "invented_time": sum(r["score"]["invented_time"] for r in ok),
        "invented_end_time": sum(r["score"]["invented_end_time"] for r in ok),
        "invented_price": sum(r["score"]["invented_price"] for r in ok),
        "invented_image_urls": sum(len(r["score"]["invented_image_urls"]) for r in ok),
        "leaks": sum(len(r["score"]["leaks"]) for r in ok),
        "empty_acts": sum(r["score"]["empty_acts"] for r in ok),
        "borderline": sum(len(r["score"]["borderline"]) for r in ok),
        "fills": dict(sum((Counter(r["score"]["fills"]) for r in ok), Counter())),
        "is_ambiguous_true": sum(
            1 for r in ok for s in r["extraction"]["shows"] if s["is_ambiguous"]
        ),
        "shows_total": sum(r["shows"] for r in ok),
    }
    per_fixture: dict[str, dict[str, Any]] = {}
    for key in sorted({r["key"] for r in runs}):
        mine = [r for r in runs if r["key"] == key]
        mine_ok = [r for r in mine if r["outcome"] == "ok"]
        counts = [r["shows"] for r in mine_ok]
        per_fixture[key] = {
            "ok": f"{len(mine_ok)}/{len(mine)}",
            "shows": counts,
            "approx_expected": REFERENCE[key].approx_shows if key in REFERENCE else None,
            "seconds": [r["seconds"] for r in mine],
            "leaks": [r["score"]["leaks"] for r in mine_ok],
            "page_readable": [r["page_readable"] for r in mine_ok],
            # Whether every successful run returned the same extraction. At temperature 0 the
            # runs may be identical, which makes "worst of 5" one sample in disguise (A2.1-D1,
            # A2.1-CR1-3); the comparison has to be able to say so.
            # Compared per page file (a venue key can hold several pages); claimed only when every
            # page has two or more successful runs — otherwise unknown, None (A2.1-CR2-5).
            "runs_identical": _runs_identical(mine_ok),
        }
    out["per_fixture"] = per_fixture
    out.update(gate_summary(runs))
    return out


def request_record(config: extraction.ExtractionConfig, legacy: bool) -> dict[str, Any]:
    """What was actually sent to the model for this label: the instruction text and the JSON
    schema `instructor` derives from the response model, plus short hashes for eyeballing
    whether two labels used the same ones. Stored in the results file so a label is
    auditable without reconstructing the code that produced it. (On the JSON-LD route the
    splitter's own instruction is sent instead, for those pages.)"""
    instruction = legacy_config.LEGACY_INSTRUCTION if legacy else extraction.instruction_for(config)
    model_cls = legacy_config.VenuePageExtraction if legacy else extraction.page_model_for(config)
    schema = json.dumps(model_cls.model_json_schema(), sort_keys=True)
    # Every prompt the label can send, not only the page model's (A2.1-CR2-3): the
    # act splitter's (it carries the conventions on the JSON-LD and title-split routes), the
    # status question's, and the image route's (which never uses title split).
    others = {} if legacy else {
        "splitter_instruction": act_split._act_split_instruction(),
        "status_instruction": status_check._instruction(),
        "image_instruction": extraction.instruction_for(replace(config, title_split=False)),
    }
    return {
        **others,
        "legacy_pre_a2": legacy,
        "instruction": instruction,
        "instruction_sha": hashlib.sha256(instruction.encode()).hexdigest()[:10],
        "response_schema": json.loads(schema),
        "response_schema_chars": len(schema),
        "response_schema_sha": hashlib.sha256(schema.encode()).hexdigest()[:10],
    }


def rescore(label: str) -> None:
    """Recompute a saved label's scores from its stored extractions, into a NEW file.

    The model output (`extraction`) is the raw data and doesn't change, so scoring — A2's
    reference metrics and A2.1's label scores — can be redone without a model call. Written to
    `results/a21-rescore-<label>.json`; the original stays byte-identical (A2.1-PR1-13).
    """
    source = RESULTS_DIR / f"{label}.json"
    data = json.loads(source.read_text())
    for run in data["runs"]:
        if run["outcome"] != "ok":
            continue
        fixture = CAPTURED_PAGES_DIR / run["fixture"]
        is_image = fixture.suffix in (".jpg", ".jpeg", ".png", ".webp")
        page_text = "" if is_image else load_text_fixture(fixture)
        ref = REFERENCE.get(run["key"], FixtureReference())
        run["score"] = score_extraction(run["extraction"], ref, page_text)
        page_label = PAGE_LABELS.get(run["fixture"])
        if page_label is not None:
            page_score = scoring.score_page(
                page_label, run["extraction"], "" if is_image else fixture.read_text(), run["fixture"]
            )
            page_score.route = policy.stored_route(run.get("source", "model")) or "model"
            run["label_score"] = asdict(page_score)
    data["aggregate"] = aggregate(data["runs"])
    data["rescored_from"] = label
    out = RESULTS_DIR / f"a21-rescore-{label}.json"
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"rescored {source.name} -> {out.name}")
    for scope in data["aggregate"]["gate"]:
        print(f"  gate [{scope}]: {_gate_line(data, scope)}")


def map_runs(fn: Any, jobs: list[Any], *, concurrency: int = 1) -> list[Any]:
    """Run `fn` over `jobs`, `concurrency` at a time, and return the results in the order the jobs were given.

    C6 Step 11 measures throughput with parallel requests. One worker means no threads at all, so a sequential
    run is the code that ran before. Each job is one (fixture, run) pair with its own seed, so parallelism changes
    only when a request is sent, not what it asks; the per-run counters are context variables (see
    `RunCounters`), so two jobs on two threads cannot see each other's parse errors or token counts.
    """
    if concurrency <= 1:
        return [fn(job) for job in jobs]
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        return list(pool.map(fn, jobs))


def act_title_check(results: dict[str, Any]) -> dict[str, int]:
    """C6-D6: how often `validation.check_act_in_title` would have flagged the splitter's act mistakes.

    `run_eval` runs no validation, so the A2.1-E3 check ("every act name appears in its title") is replayed
    here over a saved results file. A run's shows are matched to `notes["titles"]` by position, which is only
    safe when the counts are equal; any other run is skipped and counted. Each flagged show is compared with
    the label scorer's "acts wrong <date>" errors for the same run and date: a finding on an erroring date is
    `caught`, a finding on a clean date is a `false_alarm`, and a label error with no finding was missed.
    Matching by date is approximate when a page lists two shows on one date.
    """
    out = {"runs_checked": 0, "runs_skipped": 0, "flagged": 0, "label_errors": 0, "caught": 0, "false_alarms": 0}
    for run in results["runs"]:
        titles = (run.get("notes") or {}).get("titles") or []
        shows = [ShowExtraction.model_validate(s) for s in (run.get("extraction") or {}).get("shows", [])]
        if run.get("outcome") != "ok" or not titles or len(titles) != len(shows):
            out["runs_skipped"] += 1
            continue
        out["runs_checked"] += 1
        bad_dates = {m.group(1) for e in (run.get("label_score") or {}).get("errors", [])
                     if (m := re.match(r"acts wrong (\d{4}-\d{2}-\d{2})", e))}
        out["label_errors"] += len(bad_dates)
        flagged_dates = {
            str(s.date) for i, (s, t) in enumerate(zip(shows, titles, strict=True))
            if validation.check_act_in_title(s, i, t)
        }
        out["flagged"] += len(flagged_dates)
        out["caught"] += len(flagged_dates & bad_dates)
        out["false_alarms"] += len(flagged_dates - bad_dates)
    return out


def _gate_line(results: dict[str, Any], scope: str) -> str:
    """'PASS' / 'FAIL (n)' for one scope of a results file's gate, or '-' if it has none."""
    gates = results.get("aggregate", {}).get("gate", {})
    # A file written before C6.1 keys the structured route's gate "jsonld" (C6.1-D1); read it as today's name.
    gate = gates.get(scope) or next((gates[old] for old, new in policy.LEGACY_ROUTE_NAMES.items() if new == scope and old in gates), None)
    if gate is None:
        return "-"
    if not gate.get("pages", 1):
        return "n/a (no pages)"
    return "PASS" if gate["passed"] else f"FAIL ({len(gate['failures'])})"


def compare(labels: list[str]) -> None:
    """Print the headline numbers of saved labels side by side, provenance first — so a
    label run under a different context window or prompt is visibly not like-for-like."""
    files = {lab: json.loads((RESULTS_DIR / f"{lab}.json").read_text()) for lab in labels}
    data = {lab: files[lab]["aggregate"] for lab in labels}
    width = 30
    print("label".ljust(width) + "".join(lab.ljust(34) for lab in labels))
    for name, getter in {
        "provider": lambda f: (f.get("request_options") or {}).get("provider", "ollama"),
        "models (page/splitter/status)": lambda f: "/".join(
            str((f.get("role_options") or {}).get(role, {}).get("model", (f.get("request_options") or {}).get("model")))
            for role in ("page", "splitter", "status")
        ),
        "loaded_context_length": lambda f: next(iter(f["provenance"].values())).get("loaded_context_length"),
        "model_digest": lambda f: str(next(iter(f["provenance"].values())).get("model_digest"))[:12],
        "legacy_pre_a2": lambda f: f.get("request", {}).get("legacy_pre_a2"),
        "instruction_sha": lambda f: f.get("request", {}).get("instruction_sha"),
        "response_schema_chars": lambda f: f.get("request", {}).get("response_schema_chars"),
        "started_at": lambda f: f.get("started_at"),
        "config": lambda f: {k: v for k, v in (f.get("config") or {}).items() if v not in (False, None)} or "-",
        "temperature": lambda f: (f.get("request_options") or {}).get("temperature"),
        "gate (all)": lambda f: _gate_line(f, "all"),
        "gate (structured)": lambda f: _gate_line(f, "structured"),
        "gate (model)": lambda f: _gate_line(f, "model"),
    }.items():
        print(name.ljust(width) + "".join(str(getter(files[lab])).ljust(34) for lab in labels))
    print()
    rows = [
        "runs", "ok", "outcomes", "mean_attempts_used", "parse_failures", "mean_seconds",
        "shows_total", "invented_time", "invented_end_time", "invented_price",
        "invented_image_urls", "leaks", "empty_acts", "borderline", "is_ambiguous_true",
    ]
    print("metric".ljust(width) + "".join(lab.ljust(34) for lab in labels))
    for row in rows:
        print(row.ljust(width) + "".join(str(data[lab].get(row)).ljust(34) for lab in labels))
    print()
    for lab in labels:
        print(f"[{lab}] parse failures by field: {data[lab]['parse_failure_fields']}")
        print(f"[{lab}] optional-field fills:    {data[lab]['fills']}")
    print()
    for key in sorted({k for lab in labels for k in data[lab]["per_fixture"]}):
        for lab in labels:
            pf = data[lab]["per_fixture"].get(key)
            if pf:
                print(f"{key:18} [{lab}] ok {pf['ok']} shows {pf['shows']} (≈{pf['approx_expected']}) "
                      f"secs {pf['seconds']} leaks {pf['leaks']} identical {pf.get('runs_identical')}")


def select_fixtures(which: str, only: str | None) -> list[Path]:
    """The fixtures a label runs: drawn only from `labels.PAGE_LABELS` (so an unlabelled file,
    such as the Uptown Art House .ics feed with no reader yet, is never run as a page — A2.1-PR2-10), filtered by set and by `--only`, and present on disk (fixtures are git-ignored)."""
    # `held_out` (C5-D3) is its own set: "all" does not include it, so a run that scores everything else never sees those pages.
    names = {"gated": gated_fixtures(), "informational": informational_fixtures(),
             "all": gated_fixtures() + informational_fixtures(), "held_out": held_out_fixtures()}[which]
    chosen = []
    for name in sorted(names):
        path = CAPTURED_PAGES_DIR / name
        if only and only not in name:
            continue
        if not path.is_file():
            print(f"skipping {name}: not in {CAPTURED_PAGES_DIR} (fixtures are git-ignored; see model_eval/capture.py)")
            continue
        chosen.append(path)
    return chosen


def main() -> None:
    """The command line: parse the flags, then run the labelled pages `--runs` times under a `--label`, or print
    `--compare` / `--rescore` / `--act-check` results from saved files. Refuses an unusable model endpoint before
    the first call (`main.model_endpoint_problem`)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", help="name for this run set; results go to results/<label>.json")
    parser.add_argument("--runs", type=int, default=5, help="runs per fixture (default 5, seeds 0..n-1; A2.1 D1)")
    parser.add_argument("--set", choices=["gated", "informational", "all", "held_out"], default="all",
                        help="which labelled fixtures to run (labels.py; D2)")
    parser.add_argument("--only", help="only fixtures whose file name contains this text")
    parser.add_argument(
        "--legacy", action="store_true",
        help="use the frozen pre-A2 schema and prompt (model_eval/legacy.py): the baseline label",
    )
    add_override_flags(parser)
    parser.add_argument("--compare", nargs="+", metavar="LABEL", help="print saved labels side by side")
    parser.add_argument("--rescore", metavar="LABEL", help="rescore a saved label into results/a21-rescore-<LABEL>.json")
    parser.add_argument(
        "--concurrency", type=int, default=1,
        help="runs in flight at once (default 1, sequential); C6 Step 11 throughput measurement",
    )
    parser.add_argument(
        "--act-check", nargs="+", metavar="LABEL",
        help="replay the act-in-title check over saved labels and count what it catches (C6-D6)",
    )
    args = parser.parse_args()

    if args.act_check:
        for label in args.act_check:
            print(label, act_title_check(json.loads((RESULTS_DIR / f"{label}.json").read_text())))
        return
    if args.compare:
        compare(args.compare)
        return
    if args.rescore:
        rescore(args.rescore)
        return
    if not args.label:
        parser.error("--label is required unless --compare or --rescore is given")

    overrides = overrides_from(args)
    options, config = configure(overrides)
    roles = configure_roles(overrides)
    # The worker's start-up rule applies here too (C6-CR1-9): a hosted provider with the placeholder key would
    # otherwise run every fixture and run as a 401 outcome instead of stopping at once.
    problem = model_endpoint_problem(
        settings.app_env, options.provider, settings.model_base_url, settings.model_api_key.get_secret_value()
    )
    if problem:
        parser.error(problem)
    fixtures = select_fixtures(args.set, args.only)
    request = request_record(config, args.legacy)
    started_at = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    jobs = [(item, run_index) for item in fixtures for run_index in range(args.runs)]

    def do_job(job: tuple[Any, int]) -> dict[str, Any]:
        """One (page, run index) pair: run the extraction, print its progress line, and return the run's record.
        `map_runs` calls it once per job, on a worker thread when `--concurrency` is above 1."""
        item, run_index = job
        record = run_once(item, run_index, options, config, args.legacy, roles=roles)
        record["model"] = options.model
        print(
            f"{args.label} | {item.name[:34]:34} | run {run_index} | {record['outcome']:24} | "
            f"shows {record.get('shows', '-')} | attempts {record['attempts_used']} | {record['seconds']}s",
            flush=True,
        )
        return record

    wall_start = time.monotonic()
    runs = map_runs(do_job, jobs, concurrency=args.concurrency)
    wall_seconds = round(time.monotonic() - wall_start, 1)
    print(f"{args.label} | wall clock {wall_seconds}s for {len(jobs)} runs at concurrency {args.concurrency}")

    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = RESULTS_DIR / f"{args.label}.json"
    aggregate_data = aggregate(runs)
    out_path.write_text(json.dumps(
        {
            "label": args.label,
            "started_at": started_at,
            "set": args.set,
            "config": asdict(config),
            "request_options": asdict(options),
            "role_options": asdict(roles),
            "labels_sha": labels_sha(),
            "include_new_rules": config.include_new_rules,
            "request": request,
            "options": {"num_ctx": options.num_ctx, "max_tokens": options.max_tokens, "max_retries": options.max_retries,
                        "seed": "run index, top-level argument",
                        "temperature": "model default" if options.temperature is None else options.temperature},
            # One entry per distinct model any role used, so a local splitter rung's model build is recorded too
            # (C6-CR1-7); the page model is first.
            "provenance": {
                m: model_provenance(replace(options, model=m), settings.model_base_url)
                for m in dict.fromkeys([options.model, roles.splitter.model, roles.status.model, roles.matcher.model])
            },
            "aggregate": aggregate_data,
            "runs": runs,
        },
        indent=2, ensure_ascii=False,
    ))
    print(f"\nwrote {out_path}")
    for scope, result in aggregate_data["gate"].items():
        print(f"gate [{scope}]: {_gate_line({'aggregate': aggregate_data}, scope)}")
        for failure in result["failures"][:20]:
            print(f"    {failure}")


if __name__ == "__main__":
    main()
