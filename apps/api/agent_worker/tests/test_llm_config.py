"""Tests for the configurable model endpoint and the per-role model options (C6-D2, C6-D4, C6-D5).

HOW TO READ THIS
  C6 moves inference from a hard-coded local Ollama to a configurable endpoint (DeepInfra when hosted) and gives
  each kind of model call its own model name. Four things are pinned here:

  * **Settings -> roles** (`llm.roles_from_settings`): with no new variable set, every role is exactly today's
    options, so the request A2.1 measured (56 of 60) is unchanged; a role with its own model name uses it.
  * **The provider decides the request's extras** (`llm.request_kwargs`, C6-D5): Ollama gets its `num_ctx`
    option, a hosted OpenAI-compatible endpoint gets nothing extra.
  * **Threading**: the act splitter and the status question receive their own role's options, including the
    splitter call the status merge makes for a listing it adds.
  * **The worker's start-up rule** (`main.model_endpoint_problem`, C6-PR1-1): a hosted worker must not point at
    localhost. It lives in the worker, not in `Settings`, because the hosted API builds `Settings` too and never
    sets a model endpoint.

  Expected values are literals taken from the plan (`c6-hosted-inference.md`) and from the request that
  `llm.request_kwargs` sent before C6, not read from the code under test. Every `Settings(...)` passes
  `_env_file=None` and clears the model variables, so a developer's `.env` cannot change a result.
"""

import datetime
from dataclasses import replace
from typing import Any

import pytest

from agent_worker import extraction
from agent_worker.llm import (
    ModelRoles,
    RequestOptions,
    build_clients,
    request_kwargs,
    roles_from_settings,
)
from agent_worker.main import model_endpoint_problem
from agent_worker.tests.fakes import (
    PAGE,
    SPLITTER,
    STATUS,
    completions,
    listing,
    listings_answer,
    scripted_client,
    split_answer,
    text_page,
)
from app.config import Settings

LOCAL_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/calendar_dev"
HOSTED_DB = "postgresql+asyncpg://calendar_prod:pw@ep-example-123456-pooler.us-east-2.aws.neon.tech/neondb"


@pytest.fixture(autouse=True)
def isolate_from_the_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    # Same reason as test_config.py: pydantic-settings still reads exported process variables.
    for name in (
        "APP_ENV",
        "RAILWAY_ENVIRONMENT_NAME",
        "MONGODB_URI",
        "MODEL_NAME",
        "MODEL_BASE_URL",
        "MODEL_API_KEY",
        "MODEL_PROVIDER",
        "SPLITTER_MODEL_NAME",
        "STATUS_MODEL_NAME",
        "MATCHER_MODEL_NAME",
        "ESCALATION_MODEL_NAME",
    ):
        monkeypatch.delenv(name, raising=False)


def make_settings(**fields: Any) -> Settings:
    """A `Settings` for a laptop, with the given fields set and no `.env` read."""
    return Settings(_env_file=None, database_url=LOCAL_URL, model_name="page-model", **fields)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Settings -> roles
# ---------------------------------------------------------------------------


def test_with_no_new_variable_every_role_is_todays_options_and_todays_request() -> None:
    # Proves (C6-D2): the default configuration changes nothing. All four roles equal the one
    # `RequestOptions` the pipeline used before C6, and the keyword arguments sent for it are the pre-C6 dict,
    # so A2.1's measured request is still the one that goes out. The literal below is what `request_kwargs`
    # returned before this milestone (model, max_tokens, max_retries, Ollama's num_ctx, temperature).
    roles = roles_from_settings(make_settings(), temperature=0.0)
    expected = RequestOptions(model="page-model", temperature=0.0)
    assert roles.page == roles.splitter == roles.status == roles.matcher == expected
    assert request_kwargs(roles.page) == {
        "model": "page-model",
        "max_tokens": 16000,
        "max_retries": 1,
        "extra_body": {"options": {"num_ctx": 32768}},
        "temperature": 0.0,
    }


def test_a_role_with_its_own_model_name_uses_it_and_the_others_keep_the_page_model() -> None:
    # Proves (C6-D2): the splitter alone can run a larger model, which is how A2.1-E1 is tried and a change in
    # the numbers is put down to the splitter.
    roles = roles_from_settings(make_settings(splitter_model_name="big-model"), temperature=0.0)
    assert roles.splitter.model == "big-model"
    assert roles.page.model == roles.status.model == roles.matcher.model == "page-model"


@pytest.mark.parametrize("name", ["", None])
def test_an_empty_role_model_name_means_not_configured(name: str | None) -> None:
    # Proves (A3-CR1-3's shape): `SPLITTER_MODEL_NAME=` left empty is read as "", which must fall back to the
    # page model and not become a model named "".
    roles = roles_from_settings(make_settings(splitter_model_name=name, status_model_name=name), temperature=0.0)
    assert roles.splitter.model == roles.status.model == "page-model"


def test_the_api_key_is_a_secret_that_a_settings_repr_does_not_print() -> None:
    # Proves (C6-PR1-7): the key is a `SecretStr`, so a traceback or a log of `Settings` cannot leak it.
    settings = make_settings(model_api_key="sk-not-a-real-key")
    assert "sk-not-a-real-key" not in repr(settings)
    assert settings.model_api_key.get_secret_value() == "sk-not-a-real-key"


def test_the_hosted_api_builds_settings_without_any_model_endpoint() -> None:
    # Proves (C6-PR1-1): the API runs hosted with `APP_ENV=prod` and never sets a model endpoint, so the new
    # fields' defaults (a localhost URL) must not make `Settings` refuse to build there.
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        app_env="prod",
        database_url=HOSTED_DB,
        model_name="placeholder",
        railway_environment_name="production",
    )
    assert settings.app_env == "prod"


# ---------------------------------------------------------------------------
# The provider decides the request's extras (C6-D5)
# ---------------------------------------------------------------------------


def test_a_hosted_provider_sends_no_ollama_options() -> None:
    # Proves (C6-D5): `extra_body.options.num_ctx` is Ollama's; a hosted OpenAI-compatible endpoint may reject
    # or ignore it, so it is not sent. Everything else is unchanged.
    options = RequestOptions(model="m", temperature=0.0, provider="openai_compatible")
    kwargs = request_kwargs(options, seed=3)
    assert "extra_body" not in kwargs
    assert kwargs == {"model": "m", "max_tokens": 16000, "max_retries": 1, "temperature": 0.0, "seed": 3}


def test_the_provider_reaches_every_role() -> None:
    # Proves: `MODEL_PROVIDER` is applied to all four roles, so no call silently keeps Ollama's extras.
    roles = roles_from_settings(make_settings(model_provider="openai_compatible"), temperature=0.0)
    assert {roles.page.provider, roles.splitter.provider, roles.status.provider, roles.matcher.provider} == {
        "openai_compatible"
    }


def test_the_clients_are_built_from_the_settings() -> None:
    # Proves: the pipeline's and the eval's client both come from `build_clients(settings)`, so a hosted run
    # cannot silently use Ollama (C6 plan, Risks). Expected URL and key are the literals the test sets.
    settings = make_settings(model_base_url="https://api.example.test/v1/openai", model_api_key="k-123")
    raw, wrapped = build_clients(settings)
    assert str(raw.base_url).rstrip("/") == "https://api.example.test/v1/openai"
    assert raw.api_key == "k-123"
    assert wrapped is not None


# ---------------------------------------------------------------------------
# Escalation (C6-D4)
# ---------------------------------------------------------------------------


def test_escalation_swaps_page_splitter_and_status_but_not_the_matcher() -> None:
    # Proves (C6-D4, C6-PR1-2): tier 3 uses the larger model for the three extraction calls, as it did when they
    # shared one `options`; reconcile's matcher keeps its own role (it never followed the attempt count).
    roles = roles_from_settings(make_settings(splitter_model_name="split"), temperature=0.0)
    escalated = roles.escalated("gemma-big")
    assert escalated.page.model == escalated.splitter.model == escalated.status.model == "gemma-big"
    assert escalated.matcher == roles.matcher
    assert isinstance(escalated, ModelRoles)


# ---------------------------------------------------------------------------
# Threading: each call gets its own role's options
# ---------------------------------------------------------------------------

FETCHED = datetime.date(2026, 10, 12)


def run_with_roles(html: str, client: Any, **config: Any) -> extraction.PageExtractionResult:
    return extraction.extract_page(
        html,
        venue_name="The Venue",
        metro_timezone="America/Chicago",
        fetch_date=FETCHED,
        client=client,
        options=replace(extraction.PIPELINE_OPTIONS, model="page-m"),
        splitter_options=replace(extraction.PIPELINE_OPTIONS, model="split-m"),
        status_options=replace(extraction.PIPELINE_OPTIONS, model="status-m"),
        config=replace(extraction.PIPELINE_CONFIG, **config),
    )


def test_each_call_is_sent_its_own_roles_model() -> None:
    # Proves (C6-D2): the page call, the splitter call and the status call each carry the model of their role;
    # the page call does not get the splitter's.
    client = scripted_client(
        {
            PAGE: [listings_answer(listing("2026-10-20", "Nona"))],
            SPLITTER: [split_answer(("Nona", ["Nona"]))],
            STATUS: [{"items": []}],
        }
    )
    run_with_roles(text_page("Nona", "Oct 20", "cancelled shows are listed"), client)
    calls = completions(client)
    assert [c["model"] for c in calls.calls_for(PAGE)] == ["page-m"]
    assert [c["model"] for c in calls.calls_for(SPLITTER)] == ["split-m"]
    assert [c["model"] for c in calls.calls_for(STATUS)] == ["status-m"]


def test_the_status_merges_own_splitter_call_uses_the_splitters_options() -> None:
    # Proves (C6-PR1-2c): the extra `split_titles` call the status merge makes for a listing it adds takes the
    # splitter role, not the page model, so a rung's change is attributable to the splitter on those rows too.
    client = scripted_client(
        {
            PAGE: [listings_answer()],
            STATUS: [{"items": [{"date": "2026-10-20", "acts": ["Ghost Band"], "status": "cancelled"}]}],
            SPLITTER: [split_answer(("Ghost Band", ["Ghost Band"]))],
        }
    )
    run_with_roles(text_page("Ghost Band Oct 20 CANCELLED"), client)
    assert [c["model"] for c in completions(client).calls_for(SPLITTER)] == ["split-m"]


def test_without_role_options_every_call_uses_the_page_options() -> None:
    # Proves: the old call shape (one `options`) is unchanged, so the eval and the older tests behave as before.
    client = scripted_client(
        {
            PAGE: [listings_answer(listing("2026-10-20", "Nona"))],
            SPLITTER: [split_answer(("Nona", ["Nona"]))],
            STATUS: [{"items": []}],
        }
    )
    extraction.extract_page(
        text_page("Nona", "Oct 20"),
        venue_name="The Venue",
        metro_timezone="America/Chicago",
        fetch_date=FETCHED,
        client=client,
        options=replace(extraction.PIPELINE_OPTIONS, model="only-m"),
        config=extraction.PIPELINE_CONFIG,
    )
    assert {c["model"] for c in completions(client).calls} == {"only-m"}


# ---------------------------------------------------------------------------
# The worker's start-up rule (C6-PR1-1)
# ---------------------------------------------------------------------------

ENDPOINT_CASES = [
    # (app_env, provider, base_url, api_key, a problem is expected, why)
    ("local", "ollama", "http://localhost:11434/v1", "ollama", False, "a laptop with Ollama is the default"),
    (
        "local",
        "openai_compatible",
        "https://api.deepinfra.com/v1/openai",
        "real-key",
        False,
        "C6 runs hosted from a laptop",
    ),
    (
        "prod",
        "openai_compatible",
        "https://api.deepinfra.com/v1/openai",
        "real-key",
        False,
        "the hosted worker's shape",
    ),
    ("prod", "openai_compatible", "http://localhost:11434/v1", "real-key", True, "localhost doesn't exist on Railway"),
    ("staging", "ollama", "http://127.0.0.1:11434/v1", "ollama", True, "any hosted env, loopback spelled as an IP"),
    ("dev", "openai_compatible", "http://[::1]:11434/v1", "real-key", True, "IPv6 loopback"),
    (
        "prod",
        "openai_compatible",
        "https://api.deepinfra.com/v1/openai",
        "ollama",
        True,
        "the placeholder key would 401",
    ),
    (
        "local",
        "openai_compatible",
        "https://api.deepinfra.com/v1/openai",
        "ollama",
        True,
        "a hosted URL with no key either",
    ),
    ("local", "ollama", None, "ollama", True, "no endpoint is configured anywhere: there is no built-in default"),
    ("prod", "openai_compatible", "", "real-key", True, "an empty MODEL_BASE_URL counts as unset"),
]


@pytest.mark.parametrize(("app_env", "provider", "base_url", "api_key", "problem", "why"), ENDPOINT_CASES)
def test_the_workers_model_endpoint_rule(
    app_env: str, provider: str, base_url: str | None, api_key: str, problem: bool, why: str
) -> None:
    # Proves (C6-PR1-1): the rule that stops a hosted worker pointing at localhost, or a hosted endpoint with the
    # placeholder key, before the first model call fails with a connection error or a 401. `why` names each row.
    result = model_endpoint_problem(app_env, provider, base_url, api_key)  # type: ignore[arg-type]
    assert (result is not None) == problem, why


def test_no_endpoint_url_is_built_into_the_code() -> None:
    # Proves (Ari's comment on PR 80): the model endpoint comes only from the environment (`MODEL_BASE_URL`), never from a URL
    # written in `Settings`. With nothing set the field is None, and the worker's start-up rule is what refuses to run;
    # the hosted API, which never sets it, still builds `Settings` (C6-PR1-1). Fails if a default URL is put back.
    assert make_settings().model_base_url is None
    assert make_settings(model_base_url="https://api.example.test/v1").model_base_url == "https://api.example.test/v1"


def test_a_client_built_with_no_endpoint_never_reaches_a_real_provider() -> None:
    # Proves (Ari's comment on PR 80): the OpenAI client treats `base_url=None` as api.openai.com. `build_clients` is called at
    # import by every process, the API included, so with no endpoint it must point somewhere that cannot answer
    # (the reserved `.invalid` TLD) rather than silently at OpenAI.
    raw, _ = build_clients(make_settings())
    assert "api.openai.com" not in str(raw.base_url) and ".invalid" in str(raw.base_url)


# ---------------------------------------------------------------------------
# The roles reach the real call sites (C6-CR1-1)
# ---------------------------------------------------------------------------


def distinct_roles() -> ModelRoles:
    """Four roles that differ only in model name, so a test can tell which role a call was sent."""
    base = extraction.PIPELINE_OPTIONS
    return ModelRoles(
        page=replace(base, model="page-m"),
        splitter=replace(base, model="split-m"),
        status=replace(base, model="status-m"),
        matcher=replace(base, model="matcher-m"),
    )


def extract_state(**fields: Any) -> Any:
    from agent_worker.state import VenueGraphState

    return VenueGraphState(
        venue_id=1,
        calendar_url="https://venue.example/events",
        venue_name="The Venue",
        metro_timezone="America/Chicago",
        fetched_on=FETCHED,
        run_id=1,
        page_html=text_page("Nona", "Oct 20"),
        **fields,
    )


def _script() -> Any:
    return scripted_client(
        {
            PAGE: [listings_answer(listing("2026-10-20", "Nona"))] * 3,
            SPLITTER: [split_answer(("Nona", ["Nona"]))] * 3,
            STATUS: [{"items": []}] * 3,
        }
    )


def test_extract_node_sends_each_call_its_roles_model(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (C6-CR1-1): the graph's extract node hands the attempt's roles to `extract_page`, so the splitter
    # and status calls go out with their own role's model and not the page model. With every role equal (the
    # default) this wiring is invisible, which is why the roles here differ.
    from agent_worker import nodes

    client = _script()
    monkeypatch.setattr(nodes, "instructor_client", client)
    monkeypatch.setattr(nodes, "PIPELINE_ROLES", distinct_roles())
    nodes.extract_node(extract_state())
    calls = completions(client)
    assert [c["model"] for c in calls.calls_for(PAGE)] == ["page-m"]
    assert [c["model"] for c in calls.calls_for(SPLITTER)] == ["split-m"]


def test_a_tier_three_attempt_sends_the_larger_model_on_the_extraction_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (C6-D4, C6-CR1-1): on the larger-model attempt the page and splitter calls carry the escalation
    # model, through the graph node and not only through the policy's plan.
    from agent_worker import nodes
    from agent_worker.policy import AttemptRecord, RetryPolicy
    from agent_worker.validation import FailureReason, Verdict

    failed = AttemptRecord(
        attempt=1,
        tier="initial",
        model="page-m",
        route="model",
        error=None,
        verdict=Verdict.FAILED,
        reasons=[FailureReason.CHECK_ERRORS],
        findings=[],
        confidence=None,
        error_count=1,
        warning_count=0,
    )
    client = _script()
    monkeypatch.setattr(nodes, "instructor_client", client)
    monkeypatch.setattr(nodes, "PIPELINE_ROLES", distinct_roles())
    nodes.extract_node(
        extract_state(
            attempt_count=2,
            attempt_history=[failed, replace(failed, attempt=2)],
            policy=RetryPolicy(escalation_model="big"),
        )
    )
    calls = completions(client)
    assert [c["model"] for c in calls.calls_for(PAGE)] == ["big"]
    assert [c["model"] for c in calls.calls_for(SPLITTER)] == ["big"]


def test_reconcile_node_uses_the_matcher_role_even_on_a_tier_three_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (C6-D4, C6-CR1-1): reconcile's artist question is configured by the matcher role and not by the
    # attempt, so escalating extraction does not change reconcile's model (it never did).
    from agent_worker import nodes

    seen: dict[str, Any] = {}

    def fake_build_plan(*args: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        raise StopIteration  # nothing past the call matters

    monkeypatch.setattr(nodes, "prepare_inputs", lambda *a, **k: object())
    monkeypatch.setattr(nodes, "build_plan", fake_build_plan)
    monkeypatch.setattr(nodes, "PIPELINE_ROLES", distinct_roles())
    with pytest.raises(StopIteration):
        nodes.reconcile_node(extract_state(attempt_count=3))
    assert seen["options"].model == "matcher-m"
