"""The model client and the options every model call sends — one place for both.

A2.1 adds a second model call (the act splitter, `act_split.py`) and a temperature setting
to the extraction call. A2 learned that when two places build the same request they drift
(`prompts.py` exists because the eval's copy of the instruction had), so every call builds
its arguments here, from one `RequestOptions`.

How to read it: `instructor_client` is the pipeline's client; `RequestOptions` is what a call
is configured with; `request_kwargs` turns those options into the arguments
`chat.completions.create` takes, and each line of it says why that argument is there.
"""

from dataclasses import dataclass
from typing import Any

import instructor
from instructor import Mode
from openai import OpenAI

# Ollama's OpenAI-compatible endpoint. Mode.JSON, not Mode.TOOLS: Phase 5 found this model
# never reliably completed a tool call but does emit valid JSON (docs/dev/env-setup.md,
# Phase 5; eval/run_eval.py keeps the longer note). Constructing the clients makes no
# network call, so importing this module is safe in CI.
client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
instructor_client = instructor.from_openai(client, mode=Mode.JSON)


@dataclass(frozen=True)
class RequestOptions:
    """What every model call is configured with. Frozen, so a label's configuration can't be
    changed halfway through a run, and comparable, so a test can check the eval harness and
    the pipeline use the same one (extraction.PIPELINE_OPTIONS)."""

    model: str
    # None = the model's own default (temperature 1 for gemma4-e4b-32k), which is what every
    # A2 label ran at. A2.1's `a21-temp0` rung measures 0 (plan, S11 / D8).
    temperature: float | None = None
    # A page with many shows needs a genuinely large structured answer; Phase 5's value.
    max_tokens: int = 16000
    # instructor's default, stated: up to 4 attempts per call, and the graph's own 3-attempt
    # cap multiplies it (A2, Step 0; A3 revisits the number).
    max_retries: int = 3
    # Still sent, though Ollama's /v1 endpoint ignores it (docs/dev/notes.md); the working
    # window comes from the derived model's Modelfile. Kept so the request is unchanged.
    num_ctx: int = 32768


def request_kwargs(options: RequestOptions, seed: int | None = None) -> dict[str, Any]:
    """The keyword arguments for `chat.completions.create`, other than the messages and the
    response model."""
    kwargs: dict[str, Any] = {
        "model": options.model,
        "max_tokens": options.max_tokens,
        "max_retries": options.max_retries,
        "extra_body": {"options": {"num_ctx": options.num_ctx}},
    }
    # Top-level arguments, not `options`: /v1 honours the OpenAI-style `seed` and
    # `temperature` and silently ignores anything inside `options` (verified for seed, Oct 9
    # 2026; notes.md). Omitted when unset, so a default run sends exactly what A2 sent.
    if options.temperature is not None:
        kwargs["temperature"] = options.temperature
    if seed is not None:
        kwargs["seed"] = seed
    return kwargs
