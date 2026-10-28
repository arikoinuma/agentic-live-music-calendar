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
from urllib.parse import urlparse  # noqa: F401  (used by environment_problem once C3-K1 is filled)

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url  # noqa: F401  (used by environment_problem once C3-K1 is filled)

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
    # TODO(Ari) — C3-K1. Key point of interest: the rule that decides whether a process may start is four independent
    #   checks, not one, because the realistic mistake is a copied variable set, not a typo (C3-D4;
    #   c3-environments-and-deploy.md). Each check must fail on its own cause and pass on its own cause.
    # To align: copy the Code lines below by hand, then run the Check. Replace the `return None` below.
    # Code:
    #   url = make_url(database_url); host = url.host or ""; role = url.username or ""
    #   local_db = host in ("localhost", "127.0.0.1", "::1")                                  # a)
    #   if (app_env == "local") != local_db:
    #       return f"APP_ENV={app_env} but the database host is {host!r}"
    #   expected = {"production": "prod", "staging": "staging", "dev": "dev"}                 # b)
    #   if railway_name and expected.get(railway_name.lower()) != app_env:
    #       return f"APP_ENV={app_env} but Railway says this is {railway_name!r}"
    #   if app_env != "local" and not role.endswith(f"_{app_env}"):                           # c)
    #       return f"APP_ENV={app_env} but the database role is {role!r}"
    #   want = "calendar" if app_env == "prod" else f"calendar_{app_env}"                     # d)
    #   mongo_host = urlparse(mongodb_uri or "").hostname or ""
    #   if mongo_host not in ("", "localhost", "127.0.0.1", "::1") and mongodb_database != want:
    #       return f"APP_ENV={app_env} but the MongoDB database is {mongodb_database!r}"
    #   return None
    # Check: uv run pytest app/tests/test_config.py::test_environment_rule — the likeliest mistakes are treating
    #   a missing RAILWAY_ENVIRONMENT_NAME as a mismatch (it is absent locally and on Vercel), and parsing the
    #   host with a string split instead of make_url, which breaks on an IPv6 host or an `@` in a password.
    # Placeholder: returns "no problem" rather than raising, because `settings = Settings()` runs at import and a
    #   raising placeholder would turn the whole suite red (C3-PR1-3).
    return None


class Settings(BaseSettings):
    # model_config tells pydantic-settings where to load values from.
    # Use SettingsConfigDict(env_file=".env") so it reads apps/api/.env
    # (uv run executes with apps/api/ as the working directory, so a plain
    # ".env" relative path is enough — no need for an absolute path).
    model_config = SettingsConfigDict(env_file='.env')

    # Which place this process believes it is in (C3-D3). Defaults to `local` so a hosted service that forgets
    # the variable behaves as a laptop, and the consistency rule below then refuses a hosted database for it.
    app_env: AppEnv = "local"

    # Railway sets this itself, to the name of the environment the service runs in ("production", "staging",
    # "dev"); it is not copied between environments, which is why the rule trusts it (C3-D4 b). Absent locally
    # and on Vercel.
    railway_environment_name: str | None = None

    # declare a field named `database_url` typed as `str`.
    # pydantic-settings matches env var names to field names case-insensitively
    # by default, so a field called `database_url` will pick up the
    # DATABASE_URL value from .env automatically — no extra config needed.
    database_url: str

    # declare a local model name
    model_name: str 

    # The larger model the third retry attempt escalates to (arch-initial.md §7: "larger model
    # second"; agent_worker/policy.py). Optional and unset by default: the development laptop can't
    # run a larger model (A2.1-E1), so tier 3 then reruns the same model with the full retry hint
    # and the attempt record says no escalation happened. Until C6 (formerly H1) makes model endpoints
    # configurable, it must be a model name Ollama serves.
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


# instantiate the class once at module load time, e.g.:
#   settings = Settings()
# Other modules (like app/main.py) will import this `settings` object
# rather than constructing their own — that's what makes it work like a
# single shared source of config for the whole app.

settings = Settings()