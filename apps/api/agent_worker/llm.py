"""The model clients and the options every model call sends — one place for both.

A2.1 adds a second model call (the act splitter, `act_split.py`) and a temperature setting
to the extraction call. A2 learned that when two places build the same request they drift
(`prompts.py` exists because the eval's copy of the instruction had), so every call builds
its arguments here, from one `RequestOptions`.

C6 makes the endpoint configurable (Ollama locally, DeepInfra hosted) and gives each KIND of call its own
options (`ModelRoles`: page, splitter, status, matcher), so a larger model can be tried for the act splitter
alone (A2.1-E1) and a change in the numbers can be put down to it. The pipeline and the eval harness build
their clients from the same function (`build_clients`), so a hosted run cannot silently use Ollama.

How to read it: `build_clients` makes the OpenAI client and the instructor client from `Settings`;
`RequestOptions` is what a call is configured with; `ModelRoles` is one `RequestOptions` per kind of call and
`roles_from_settings` builds it; `request_kwargs` turns options into the arguments
`chat.completions.create` takes, and each line of it says why that argument is there.
"""

from dataclasses import dataclass, replace
from typing import Any, Literal

import instructor
from instructor import Mode
from instructor.core.exceptions import InstructorError
from openai import OpenAI, OpenAIError

from app.config import Settings, settings

# Which request extras a provider gets (C6-D5). `ollama`: its /v1 endpoint is where `num_ctx` was sent (and ignored,
# notes.md). `openai_compatible`: a hosted endpoint such as DeepInfra, which gets only the standard arguments.
Provider = Literal["ollama", "openai_compatible"]


def build_clients(config: Settings) -> tuple[OpenAI, Any]:
    """The OpenAI client for the configured endpoint, and the instructor client wrapped around it.

    Mode.JSON, not Mode.TOOLS: Phase 5 found the local model never reliably completed a tool call but does
    emit valid JSON (docs/dev/env-setup.md, Phase 5; eval/run_eval.py keeps the longer note). Whether JSON mode
    works against DeepInfra is C6's Step 1 probe, not an assumption. Constructing the clients makes no network
    call, so importing this module is safe in CI. The pipeline and the eval harness both call this, which is
    what keeps them on the same endpoint.
    """
    raw = OpenAI(base_url=config.model_base_url, api_key=config.model_api_key.get_secret_value())
    return raw, instructor.from_openai(raw, mode=Mode.JSON)


client, instructor_client = build_clients(settings)


@dataclass(frozen=True)
class RequestOptions:
    """What every model call is configured with. Frozen, so a label's configuration can't be
    changed halfway through a run, and comparable, so a test can check the eval harness and
    the pipeline use the same one (extraction.PIPELINE_OPTIONS)."""

    model: str
    # None = the model's own default (temperature 1 for gemma4-e4b-32k), which is what every
    # A2 label ran at. A2.1's `a21-temp0` rung measures 0 (plan, A2-S11 / A2.1-D8).
    temperature: float | None = None
    # A page with many shows needs a genuinely large structured answer; Phase 5's value.
    max_tokens: int = 16000
    # instructor's re-asks after a response that fails the schema: 1 means up to 2 attempts per call.
    # A3-D7 lowered it from instructor's default of 3 (4 attempts). The graph's own 3-attempt cap
    # multiplies it, and a venue makes up to three model calls per attempt (page, splitter, status),
    # so 3 meant up to 3 x (4 + 4 + 4) = 36 calls for one venue. Measured: the 45 `a21-confirm` runs
    # used 0 re-asks (mean 1.0 attempts, 0 parse failures), so the extra budget had never earned its
    # cost. One re-ask is kept: instructor sends the validation error back, which is a different
    # request from the first, and exactly what recovers a time the normalizer refused.
    # NO SLACK ON MORTIMER'S: the current pipeline (`a21-review2`, `a3-confirm`) spends that one re-ask on
    # Mortimer's page on every run (2 attempts, 1 parse failure, deterministic at temperature 0). So 1 is
    # the minimum, not a margin: lowering it to 0, or a change that adds a second schema failure there,
    # turns that page into a failed attempt.
    max_retries: int = 1
    # Still sent to Ollama, though its /v1 endpoint ignores it (docs/dev/notes.md); the working
    # window comes from the derived model's Modelfile. Kept so the request is unchanged. Not sent to
    # a hosted provider (`request_kwargs`, C6-D5).
    num_ctx: int = 32768
    # Which provider's request extras to send (C6-D5). Defaults to Ollama, today's behaviour.
    provider: Provider = "ollama"


@dataclass(frozen=True)
class ModelRoles:
    """One `RequestOptions` per kind of model call (C6-D2). Frozen, like the options, so a run's roles can't change
    halfway through it.

    `page` reads the listings, `splitter` splits titles into acts (including the splitter call the status merge
    makes for a listing it adds), `status` asks which listings are cancelled or postponed, and `matcher` is
    reconcile's question about an ambiguous artist name.
    """

    page: RequestOptions
    splitter: RequestOptions
    status: RequestOptions
    matcher: RequestOptions

    def escalated(self, model: str) -> "ModelRoles":
        """The roles for the larger-model retry tier (C6-D4): the three extraction calls use `model`; the matcher
        keeps its own. Before roles existed these three shared one `options` and tier 3 swapped it, and
        reconcile always used the pipeline's, never the attempt's. This preserves exactly that."""
        return replace(
            self, page=replace(self.page, model=model), splitter=replace(self.splitter, model=model),
            status=replace(self.status, model=model),
        )


def roles_from_settings(config: Settings, temperature: float | None) -> ModelRoles:
    """The pipeline's roles: every role on `model_name` unless its own model is set (an empty name counts as
    unset, the shape A3-CR1-3 hit for `ESCALATION_MODEL_NAME`), all on the configured provider."""

    def options(role_model: str | None) -> RequestOptions:
        return RequestOptions(
            model=role_model or config.model_name, temperature=temperature, provider=config.model_provider,
        )

    return ModelRoles(
        page=options(None), splitter=options(config.splitter_model_name),
        status=options(config.status_model_name), matcher=options(config.matcher_model_name),
    )


def request_kwargs(options: RequestOptions, seed: int | None = None) -> dict[str, Any]:
    """The keyword arguments for `chat.completions.create`, other than the messages and the
    response model."""
    kwargs: dict[str, Any] = {
        "model": options.model,
        "max_tokens": options.max_tokens,
        "max_retries": options.max_retries,
    }
    # Ollama's own option, sent only to Ollama (C6-D5). A hosted OpenAI-compatible endpoint may reject an
    # unknown body field or ignore it, and either way the working window is the model's, not this request's.
    if options.provider == "ollama":
        kwargs["extra_body"] = {"options": {"num_ctx": options.num_ctx}}
    # Top-level arguments, not `options`: /v1 honours the OpenAI-style `seed` and
    # `temperature` and silently ignores anything inside `options` (verified for seed, Oct 9
    # 2026; notes.md). Omitted when unset, so a default run sends exactly what A2 sent.
    if options.temperature is not None:
        kwargs["temperature"] = options.temperature
    if seed is not None:
        kwargs["seed"] = seed
    return kwargs


# What a failed model call is allowed to be (A3, v0.1-G2; moved here from nodes.py in A5). A named tuple, never a bare `Exception`: a
# KeyError or AttributeError in OUR code is a bug and should crash, not be recorded as a "failed
# attempt". Each member and why:
#   InstructorError   instructor re-asked and the answer still wouldn't validate (its
#                     InstructorRetryException subclass), or the response was cut off;
#   OpenAIError       the model server couldn't be reached, timed out, or answered with an error status;
#   ValueError        covers pydantic's ValidationError (which subclasses it) and a malformed JSON-LD
#                     date (`jsonld.local_wall_clock`'s fromisoformat). It is the broad member: a
#                     ValueError from our own code (a `zip(strict=True)` mismatch) is also recorded as
#                     a failed attempt. Accepted on purpose: it ends in an escalation with the error
#                     text kept, rather than a crash.
EXTRACTION_ERRORS = (InstructorError, OpenAIError, ValueError)
