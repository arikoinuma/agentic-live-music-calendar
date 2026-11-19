"""Tests for the environment setting and the rule that keeps it honest (C3-D3, C3-D4, C3-K1).

HOW TO READ THIS
  `APP_ENV` says which of four places a process believes it is (`local`, `dev`, `staging`, `prod`). Two things
  are tested:

  * **The setting itself (C3-D3):** it defaults to `local`, and a value outside the four is refused at startup.
  * **The consistency rule (C3-D4):** `environment_problem` compares that belief with where the process
    actually is, in four independent ways, and `Settings` refuses to build when it finds a problem. The rule is
    a pure function, so it is tested as a table of cases with no database and no process environment.

  Every `Settings(...)` here passes `_env_file=None` and every field it cares about explicitly, so a developer's
  `apps/api/.env` or exported shell variables cannot change a result (C3-PR1-11). The expected values are
  literals chosen from the plan's table (`c3-environments-and-deploy.md`, T1 and T2), not read from the code
  under test.

  The rows of `RULE_CASES` that expect a problem are built so that exactly ONE of the four checks is wrong. That
  is what makes the table a mutation test: deleting one check turns exactly one row red. The rows that expect
  `None` pin the likeliest mistakes the other way (C3-K1).
"""

import os
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.config import AppEnv, Settings, environment_problem


@pytest.fixture(autouse=True)
def isolate_from_the_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    # `_env_file=None` keeps `apps/api/.env` out, but pydantic-settings still reads exported process variables.
    # Remove every one of `Settings`' optional variables a developer's shell might export, so a laptop with
    # `MONGODB_URI` set gives the same result as CI (C3-PR1-11, C3-CR1-3).
    for name in (
        "APP_ENV",
        "RAILWAY_ENVIRONMENT_NAME",
        "MONGODB_URI",
        "MONGODB_DATABASE",
        "LOG_FORMAT",
        "ESCALATION_MODEL_NAME",
        "R2_ENDPOINT_URL",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET",
    ):
        monkeypatch.delenv(name, raising=False)
    # Feature-flag variables too (C3.1-D12): `Settings` now refuses a bad one, so a developer's exported
    # `FLAG_*` must not decide a result here.
    for name in list(os.environ):
        if name.startswith("FLAG_"):
            monkeypatch.delenv(name, raising=False)


LOCAL_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/calendar_dev"
# A Neon-shaped host: what a hosted database looks like to the rule. The role (`calendar_<env>`) is the marker.
HOSTED = "ep-example-123456-pooler.us-east-2.aws.neon.tech"


def hosted_url(role: str) -> str:
    return f"postgresql+asyncpg://{role}:secret@{HOSTED}/neondb"


# ---------------------------------------------------------------------------
# The setting: default and allowed values (C3-D3)
# ---------------------------------------------------------------------------


def test_app_env_defaults_to_local(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves: a process that forgets `APP_ENV` behaves as `local`, the safe default (C3-D3). The consistency
    # rule then refuses a hosted database for it. Defaulting to `prod` would make a forgotten variable look like
    # production. `APP_ENV` is removed from the process environment so the shell running the tests cannot decide.
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
    settings = Settings(_env_file=None, database_url=LOCAL_URL, model_name="m")  # type: ignore[call-arg]
    assert settings.app_env == "local"


def test_an_unknown_app_env_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves: a typo in the variable fails at startup instead of becoming a fifth environment (C3-D3). Without
    # the `Literal`, `prodution` would be accepted and every check keyed on `prod` would silently not apply.
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=LOCAL_URL, model_name="m", app_env="prodution")  # type: ignore[call-arg,arg-type]


@pytest.mark.parametrize(
    ("app_env", "database_url"),
    [
        ("local", LOCAL_URL),
        ("dev", hosted_url("calendar_dev")),
        ("staging", hosted_url("calendar_staging")),
        ("prod", hosted_url("calendar_prod")),
    ],
)
def test_each_of_the_four_environments_is_accepted_when_consistent(
    app_env: str,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Proves: all four values build a `Settings` when the database agrees with them, so the allowed set is
    # exactly local/dev/staging/prod and the rule does not reject a correct configuration.
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
    settings = Settings(_env_file=None, database_url=database_url, model_name="m", app_env=app_env)  # type: ignore[call-arg,arg-type]
    assert settings.app_env == app_env


# ---------------------------------------------------------------------------
# The consistency rule (C3-D4, C3-K1)
# ---------------------------------------------------------------------------

# (id, app_env, database_url, railway_name, mongodb_uri, mongodb_database, expect_problem)
# Each expect_problem=True row has exactly one wrong thing, named in its id.
RULE_CASES = [
    # a) the local-versus-hosted database host
    ("local-on-localhost", "local", LOCAL_URL, None, None, "calendar", False),
    (
        "local-on-ipv6-loopback-with-an-at-in-the-password",
        "local",
        "postgresql+asyncpg://postgres:p%40ss@[::1]:5432/calendar_dev",
        None,
        None,
        "calendar",
        False,
    ),
    ("local-pointing-at-neon", "local", hosted_url("calendar_prod"), None, None, "calendar", True),
    (
        "prod-pointing-at-localhost",
        "prod",
        LOCAL_URL.replace("postgres:postgres", "calendar_prod:x"),
        None,
        None,
        "calendar",
        True,
    ),
    # c) the role marker on a hosted database
    ("prod-with-its-own-role", "prod", hosted_url("calendar_prod"), None, None, "calendar", False),
    ("prod-with-the-staging-role", "prod", hosted_url("calendar_staging"), None, None, "calendar", True),
    ("staging-with-the-prod-role", "staging", hosted_url("calendar_prod"), None, None, "calendar_staging", True),
    ("dev-with-its-own-role", "dev", hosted_url("calendar_dev"), None, None, "calendar_dev", False),
    ("staging-with-its-own-role", "staging", hosted_url("calendar_staging"), None, None, "calendar_staging", False),
    # b) the platform's own environment name (absent locally and on Vercel, so absence is not a mismatch)
    (
        "staging-on-railway-production",
        "staging",
        hosted_url("calendar_staging"),
        "production",
        None,
        "calendar_staging",
        True,
    ),
    ("prod-on-railway-production", "prod", hosted_url("calendar_prod"), "production", None, "calendar", False),
    ("dev-on-railway-dev", "dev", hosted_url("calendar_dev"), "dev", None, "calendar_dev", False),
    (
        "railway-name-is-case-insensitive",
        "staging",
        hosted_url("calendar_staging"),
        "Staging",
        None,
        "calendar_staging",
        False,
    ),
    (
        "no-railway-name-is-not-a-mismatch",
        "staging",
        hosted_url("calendar_staging"),
        None,
        None,
        "calendar_staging",
        False,
    ),
    # d) the MongoDB database name, checked only when a MongoDB URI is set
    (
        "staging-on-the-default-mongo-database",
        "staging",
        hosted_url("calendar_staging"),
        None,
        "mongodb://example",
        "calendar",
        True,
    ),
    # A local MongoDB is skipped, the same local/hosted split (a) makes for Postgres, so the laptop's override
    # commands (APP_ENV=staging against a hosted Postgres, MONGODB_URI still the Docker one) are not refused for
    # a database name nothing hosted is using (C3-CR1-1).
    (
        "staging-with-a-local-mongo-uri",
        "staging",
        hosted_url("calendar_staging"),
        None,
        "mongodb://localhost:27017",
        "calendar",
        False,
    ),
    (
        "staging-with-an-atlas-uri-and-the-default-database",
        "staging",
        hosted_url("calendar_staging"),
        None,
        "mongodb+srv://calendar_staging:x@cluster0.example.mongodb.net/?retryWrites=true",
        "calendar",
        True,
    ),
    (
        "prod-on-the-default-mongo-database",
        "prod",
        hosted_url("calendar_prod"),
        None,
        "mongodb://example",
        "calendar",
        False,
    ),
    (
        "prod-on-a-staging-mongo-database",
        "prod",
        hosted_url("calendar_prod"),
        None,
        "mongodb://example",
        "calendar_staging",
        True,
    ),
    (
        "staging-on-its-own-mongo-database",
        "staging",
        hosted_url("calendar_staging"),
        None,
        "mongodb://example",
        "calendar_staging",
        False,
    ),
    ("no-mongo-uri-skips-the-database-name", "staging", hosted_url("calendar_staging"), None, None, "calendar", False),
]


@pytest.mark.parametrize(
    ("app_env", "database_url", "railway_name", "mongodb_uri", "mongodb_database", "expect_problem"),
    [case[1:] for case in RULE_CASES],
    ids=[case[0] for case in RULE_CASES],
)
def test_environment_rule(
    app_env: AppEnv,
    database_url: str,
    railway_name: str | None,
    mongodb_uri: str | None,
    mongodb_database: str,
    expect_problem: bool,
) -> None:
    # Proves (C3-K1): the rule fires on each of its four causes and on no other. A row that expects a problem
    # has exactly one thing wrong, so removing a check turns exactly one row red; a row that expects none pins
    # the likeliest mistakes the other way (a missing Railway name treated as a mismatch; an IPv6 host or an `@`
    # in a password mis-parsed by a string split).
    problem = environment_problem(
        app_env,
        database_url,
        railway_name,
        mongodb_uri=mongodb_uri,
        mongodb_database=mongodb_database,
    )
    assert (problem is not None) is expect_problem, problem


# ---------------------------------------------------------------------------
# The R2 bucket rule (C9-D9, C9-T13)
# ---------------------------------------------------------------------------

# (id, app_env, r2_bucket, expect_problem). The database and Mongo arguments are fixed to values that agree with each
# `app_env`, so each row's problem, if any, can only be the bucket's.
BUCKET_CASES: list[tuple[str, AppEnv, str | None, bool]] = [
    ("staging-with-its-own-bucket", "staging", "pebblebeats-snapshots-staging", False),
    ("staging-with-the-production-bucket", "staging", "pebblebeats-snapshots-prod", True),
    ("staging-with-a-bucket-with-no-suffix", "staging", "pebblebeats-snapshots", True),
    ("prod-with-the-staging-bucket", "prod", "pebblebeats-snapshots-staging", True),
    ("prod-with-its-own-bucket", "prod", "pebblebeats-snapshots-prod", False),
    ("dev-with-its-own-bucket", "dev", "pebblebeats-snapshots-dev", False),
    ("staging-with-no-bucket-is-skipped", "staging", None, False),
    ("staging-with-a-blank-bucket-is-skipped", "staging", "  ", False),
    # A laptop may use a bucket made for it (`-local`), but never a hosted environment's, `-dev` included: keys carry
    # no environment, so a laptop's run 412 of venue 3 would overwrite staging's (or dev's) object of the same key
    # (C9-PR1-4, C9-CR1-3).
    ("local-with-a-staging-bucket", "local", "pebblebeats-snapshots-staging", True),
    ("local-with-a-prod-bucket", "local", "pebblebeats-snapshots-prod", True),
    ("local-with-a-dev-bucket", "local", "pebblebeats-snapshots-dev", True),
    ("local-with-a-local-bucket", "local", "pebblebeats-snapshots-local", False),
    ("local-with-no-bucket", "local", None, False),
]


def database_for(app_env: AppEnv) -> str:
    """A database URL that agrees with `app_env`, so the other rules of `environment_problem` stay quiet."""
    return LOCAL_URL if app_env == "local" else hosted_url(f"calendar_{app_env}")


@pytest.mark.parametrize(
    ("app_env", "bucket", "expect_problem"),
    [case[1:] for case in BUCKET_CASES],
    ids=[case[0] for case in BUCKET_CASES],
)
def test_the_r2_bucket_rule(app_env: AppEnv, bucket: str | None, expect_problem: bool) -> None:
    # Proves (C9-T13, C9-D9): a hosted bucket must end in `-<app_env>` (a copied variable set would otherwise point a
    # staging worker at production's bucket, which `APP_ENV` alone would not notice), and a laptop's bucket must not
    # end in `-dev`, `-staging` or `-prod` (the hosted suffixes; `-dev` since C9-CR1-3, because dev gets a worker whose
    # run numbers would collide with a laptop's). An unset or blank bucket is skipped, as a local MongoDB is. The expected verdicts
    # are written from the topology table in the deployment plan (§4.1: buckets are `…-dev`, `…-staging`, `…-prod`).
    problem = environment_problem(app_env, database_for(app_env), None, r2_bucket=bucket)
    assert (problem is not None) is expect_problem, problem
    if expect_problem:
        assert bucket is not None and bucket.strip() in (problem or "")


def test_settings_refuses_a_bucket_that_names_another_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (C9-D9, C9-T13): the bucket rule is wired into `Settings`, so a staging process holding production's bucket
    # does not start; a rule nobody calls would pass every row above and protect nothing. The same values with the
    # matching bucket build.
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
    common: dict[str, Any] = {"database_url": hosted_url("calendar_staging"), "model_name": "m", "app_env": "staging"}
    with pytest.raises(ValidationError, match="pebblebeats-snapshots-prod"):
        Settings(_env_file=None, r2_bucket="pebblebeats-snapshots-prod", **common)
    Settings(_env_file=None, r2_bucket="pebblebeats-snapshots-staging", **common)


def test_settings_reads_a_blank_r2_value_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (C9-PR1-11, C9-D8): a blank or whitespace R2 variable becomes `None`, including the secret (which would
    # otherwise be a truthy `SecretStr("")` and pass a "is it set" check), so every later check compares `None`. This is
    # the shape a dashboard produces when a variable is created and left empty.
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
    built = Settings(  # type: ignore[call-arg]
        _env_file=None,
        database_url=LOCAL_URL,
        model_name="m",
        r2_endpoint_url="",
        r2_access_key_id="  ",
        r2_secret_access_key="",
        r2_bucket=" ",
    )
    assert built.r2_endpoint_url is None and built.r2_access_key_id is None
    assert built.r2_secret_access_key is None and built.r2_bucket is None
    secret = "s3cret"
    set_ones = Settings(  # type: ignore[call-arg]
        _env_file=None, database_url=LOCAL_URL, model_name="m", r2_secret_access_key=secret
    )
    assert set_ones.r2_secret_access_key is not None
    assert secret not in repr(set_ones)  # a SecretStr: a repr or a traceback cannot print it


def test_settings_refuses_to_start_on_a_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (C3-D4): the rule is wired into `Settings`, so a process whose `APP_ENV` disagrees with its database
    # does not start (a `ValidationError`, as a missing `DATABASE_URL` raises). A rule nobody calls would pass
    # every row of the table above and protect nothing; this is the test that the validator calls it.
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_NAME", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=hosted_url("calendar_prod"), model_name="m", app_env="local")  # type: ignore[call-arg]


def test_settings_reads_the_railway_name_from_the_platform_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (C3-D4(b)): the platform check reads `RAILWAY_ENVIRONMENT_NAME`, the variable Railway itself sets and
    # that cannot be copied from another environment, so a staging service holding production's `APP_ENV` and
    # `DATABASE_URL` is refused. This is the "copy variables from Production" hazard the check exists for.
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "staging")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=hosted_url("calendar_prod"), model_name="m", app_env="prod")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Feature-flag variables are checked at startup (C3.1-T5, C3.1-D12)
# ---------------------------------------------------------------------------


def test_settings_refuses_an_unregistered_flag_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (C3.1-T5, C3.1-D12): `Settings` builds with a `FLAG_*` variable in the process environment only
    # when it names a registered flag, so a typo (`FLAG_WORKER_SCHEDULED_RUN`) stops the process at startup
    # instead of doing nothing while looking set. The message names the variable, so the traceback says what to
    # fix. A validator that is not wired in would pass every row of `test_flags.py` and protect nothing; this is
    # the test that `Settings` calls it.
    monkeypatch.setenv("FLAG_NOPE", "true")
    with pytest.raises(ValidationError, match="FLAG_NOPE"):
        Settings(_env_file=None, database_url=LOCAL_URL, model_name="m")  # type: ignore[call-arg]


def test_settings_refuses_a_malformed_flag_value(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (C3.1-T5, C3.1-D9, C3.1-D12): a registered flag set to something other than `true`/`false` fails at
    # startup too, so a half-typed Railway value fails the deploy (Railway keeps the old deployment) instead of
    # failing a later request or, worse, reading as the default.
    monkeypatch.setenv("FLAG_WORKER_SCHEDULED_RUNS", "yes")
    with pytest.raises(ValidationError, match="FLAG_WORKER_SCHEDULED_RUNS"):
        Settings(_env_file=None, database_url=LOCAL_URL, model_name="m")  # type: ignore[call-arg]


def test_settings_builds_with_a_registered_flag_set(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (C3.1-T5, C3.1-D12): the rule does not reject a correct configuration; the registered variable, set
    # to either spelling, builds a `Settings`.
    monkeypatch.setenv("FLAG_WORKER_SCHEDULED_RUNS", "false")
    Settings(_env_file=None, database_url=LOCAL_URL, model_name="m")  # type: ignore[call-arg]
    monkeypatch.setenv("FLAG_WORKER_SCHEDULED_RUNS", "true")
    Settings(_env_file=None, database_url=LOCAL_URL, model_name="m")  # type: ignore[call-arg]


def test_a_flag_line_in_the_dotenv_file_is_refused(tmp_path: Path) -> None:
    # Proves (C3.1-D11): flags come from the process environment only. `Settings` already forbids unknown keys in
    # `.env`, so a `FLAG_*` line there fails at startup (pydantic's "Extra inputs are not permitted") rather than
    # being silently ignored; `.env.example` says so. If `Settings` ever gains `extra="allow"` this fails and the
    # decision has to be remade on purpose. The expectation is the behavior confirmed by experiment on
    # November 9, 2026 (the plan's fact table), not read from the code.
    env_file = tmp_path / ".env"
    env_file.write_text("FLAG_WORKER_SCHEDULED_RUNS=true\n")
    with pytest.raises(ValidationError, match="flag_worker_scheduled_runs"):
        Settings(_env_file=env_file, database_url=LOCAL_URL, model_name="m")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Isolation from the shell (C9-CR1-1)
# ---------------------------------------------------------------------------


def test_the_four_r2_variables_are_cleared_from_the_process_before_each_test() -> None:
    # Proves (C9-CR1-1): the autouse fixture removes the four `R2_*` variables a developer's shell might export, so
    # the bucket rule (C9-D9) never reads a laptop's real bucket name in a test that is about something else. Without
    # this, `R2_BUCKET=pebblebeats-snapshots-local` in the shell fails three unrelated tests in this file (the same
    # failure C3-CR1-3 fixed for `MONGODB_URI`). On CI, where nothing is exported, it passes either way: it earns its
    # keep on a laptop, run with `R2_BUCKET=x uv run pytest app/tests/test_config.py::<this test>`.
    for name in ("R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"):
        assert name not in os.environ
