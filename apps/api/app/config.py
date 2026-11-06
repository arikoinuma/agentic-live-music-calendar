"""The process's configuration, read once at import from the environment and `apps/api/.env`.

HOW TO READ THIS
  * `Settings` declares every variable the API and the worker read. `docs/dev/environments.md` lists the same
    variables per environment, and `app/tests/test_environments_doc.py` fails if the two drift.
  * `app_env` says which of four places the process believes it is in (C3-D3). `environment_problem` compares
    that belief with where the process actually is, and the validator on `Settings` refuses to build on a
    mismatch (C3-D4), so a wrong connection string stops the process instead of writing to the wrong database.
  * `settings = Settings()` runs at import, so a bad configuration fails at startup for every entry point:
    the API, the worker, Alembic and the tests.

docs/dev/implementations/c3-environments-and-deploy.md, C3-D3, C3-D4, C3-K1.
"""

from typing import Literal, Self
from urllib.parse import urlparse

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

# The four places a process can be (C3-D3). `local` is a laptop (or CI); the other three are hosted
# (Dep-D1). A `Literal`, as `log_format` below does, so a typo such as "prodution" fails at startup instead of
# becoming a fifth environment that no check applies to.
AppEnv = Literal["local", "dev", "staging", "prod"]


def environment_problem(
    app_env: AppEnv,
    database_url: str,
    railway_name: str | None,
    *,
    mongodb_uri: str | None = None,
    mongodb_database: str = "calendar",
) -> str | None:
    """What is wrong with this configuration, as a sentence, or `None` when `app_env` agrees with where we are.

    Pure: it reads nothing from the process, which is what lets `test_config.py` drive it as a table. It checks
    four independent things, because the realistic mistake is a copied variable set and not a typo: Railway's
    "copy variables from Production" brings `DATABASE_URL` and `APP_ENV=prod` into staging together, so a rule
    that only compared `APP_ENV` with the database host would pass it (C3-D4).

      a) a `local` process uses a local database, and a hosted one does not;
      b) when Railway says which environment this is, it must be the one `app_env` names;
      c) on a hosted database the login role ends in the environment (`calendar_staging`);
      d) when a HOSTED MongoDB is configured (a local one is skipped, as a local Postgres is in (a)), `prod` uses
         the `calendar` database and every other hosted value uses `calendar_<env>`.
    """
    # Four independent checks rather than one, because the realistic mistake is a copied variable set, not a
    # typo (C3-D4, C3-K1). Each fires on its own cause and passes on its own cause, so deleting one turns a
    # distinct row of `test_environment_rule` red. `make_url` parses the connection string, so an IPv6 host or
    # an `@` in a password cannot fool it as a string split would.
    url = make_url(database_url)
    host = url.host or ""
    role = url.username or ""

    # a) local vs hosted database
    local_db = host in ("localhost", "127.0.0.1", "::1")
    if (app_env == "local") != local_db:
        return f"APP_ENV={app_env} but the database host is {host!r}"

    # b) Railway's own environment name. Railway sets it per environment and "copy variables" does not copy it,
    # so it catches a staging service holding production's variables. Absent (laptop, Vercel) is not a mismatch.
    expected = {"production": "prod", "staging": "staging", "dev": "dev"}
    if railway_name and expected.get(railway_name.lower()) != app_env:
        return f"APP_ENV={app_env} but Railway says this is {railway_name!r}"

    # c) the login role is the marker on a hosted database (`calendar_staging`), catching a pasted URL.
    if app_env != "local" and not role.endswith(f"_{app_env}"):
        return f"APP_ENV={app_env} but the database role is {role!r}"

    # d) the MongoDB database name. The setting's default, `calendar`, is production's name, so a lower
    # environment that forgets it would stage into production's database. Skipped for a local MongoDB, the same
    # split (a) makes for Postgres, so a laptop that keeps its Docker `MONGODB_URI` is not refused (C3-CR1-1).
    want = "calendar" if app_env == "prod" else f"calendar_{app_env}"
    mongo_host = urlparse(mongodb_uri or "").hostname or ""
    if mongo_host not in ("", "localhost", "127.0.0.1", "::1") and mongodb_database != want:
        return f"APP_ENV={app_env} but the MongoDB database is {mongodb_database!r}"
    return None


class Settings(BaseSettings):
    # Real environment variables win over `.env`, which only fills in what isn't set. The relative path is
    # `apps/api/.env`, because every entry point runs with `apps/api/` as its working directory (`uv run`).
    model_config = SettingsConfigDict(env_file='.env')

    # Which place this process believes it is in (C3-D3). Defaults to `local` so a hosted service that forgets
    # the variable behaves as a laptop, and the consistency rule below then refuses a hosted database for it.
    app_env: AppEnv = "local"

    # Railway sets this itself, to the name of the environment the service runs in ("production", "staging",
    # "dev"); it is not copied between environments, which is why the rule trusts it (C3-D4 b). Absent locally
    # and on Vercel.
    railway_environment_name: str | None = None

    # The Postgres connection string (`DATABASE_URL`; pydantic-settings matches names case-insensitively).
    # Required, with no default: a process that doesn't know its database should not start.
    database_url: str

    # The model the page call uses (and the default for every other call). Locally an Ollama tag; hosted, the
    # provider's model id (C6). The API never calls a model, so a hosted API service carries only a placeholder.
    model_name: str

    # Where the worker's model calls go (C6-D2). ONE endpoint for every call site, with a model name per role
    # below: every hosted call goes to the same provider, so one URL and one key per environment is one value
    # to keep in step, not four. The URL has NO default in code (Ari's comment on PR 80): it comes only from the
    # `MODEL_BASE_URL` environment variable. A laptop sets it in `.env` (`.env.example` has the local Ollama's
    # line), a hosted worker sets it in its service variables. It is optional here because the hosted API builds
    # `Settings` too, never sets it, and must still start (C6-PR1-1); the rule that a WORKER must have one, and
    # that a hosted one must not point at localhost, lives in the worker's start-up
    # (`agent_worker.main.model_endpoint_problem`), not in the validator below.
    model_base_url: str | None = None
    # A `SecretStr`, so a `Settings` repr, a log line or a validation traceback cannot print the key (C6-PR1-7).
    # "ollama" is the placeholder the OpenAI client requires and Ollama ignores.
    model_api_key: SecretStr = SecretStr("ollama")
    # Decides which provider-specific request options are sent (`agent_worker.llm.request_kwargs`, C6-D5).
    model_provider: Literal["ollama", "openai_compatible"] = "ollama"
    # A role's own model, or None to use `model_name`. The act splitter is the one call a larger model is
    # expected to help (A2.1-E1); the status question and reconcile's artist matcher can follow separately.
    # An empty string (`SPLITTER_MODEL_NAME=` left blank) means "not configured".
    splitter_model_name: str | None = None
    status_model_name: str | None = None
    matcher_model_name: str | None = None

    # The larger model the third retry attempt escalates to (arch-initial.md §7: "larger model
    # second"; agent_worker/policy.py). Optional and unset by default: the development laptop can't
    # run a larger model (A2.1-E1), so tier 3 then reruns the same model with the full retry hint
    # and the attempt record says no escalation happened. It must be a model the configured endpoint serves.
    escalation_model_name: str | None = None

    # MongoDB, where the worker stages each extraction attempt's raw record before validation judges it
    # (arch-initial.md §6; docs/dev/implementations/a4-auditability.md, A4-D3 and A4-D4). Locally this is the
    # docker-compose `mongo` service; Atlas is C3's (the databases) and C8's (the worker). Optional here because the API never uses it; the
    # worker's entry point refuses to start without it, since an audit trail that silently skips its raw
    # record isn't auditable.
    mongodb_uri: str | None = None
    mongodb_database: str = "calendar"

    # How the worker renders log lines (app/log_config.py, A4-D7): "auto" picks a readable console format on a
    # terminal and JSON otherwise, so a cron job on Railway gets JSON without configuration.
    log_format: Literal["auto", "console", "json"] = "auto"

    # Refuse to start when `app_env` disagrees with where the process is (C3-D4). Runs once, after every field
    # is read; the message reaches whoever reads the traceback, so it names the disagreement.
    @model_validator(mode="after")
    def _environment_agrees_with_reality(self) -> Self:
        problem = environment_problem(
            self.app_env,
            self.database_url,
            self.railway_environment_name,
            mongodb_uri=self.mongodb_uri,
            mongodb_database=self.mongodb_database,
        )
        if problem:
            raise ValueError(problem)
        return self


# The one shared instance. Every module imports this object rather than building its own, so the environment is
# read and checked once, at import (see the module docstring).

settings = Settings()