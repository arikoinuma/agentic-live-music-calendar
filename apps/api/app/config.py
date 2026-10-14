from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # model_config tells pydantic-settings where to load values from.
    # Use SettingsConfigDict(env_file=".env") so it reads apps/api/.env
    # (uv run executes with apps/api/ as the working directory, so a plain
    # ".env" relative path is enough — no need for an absolute path).
    model_config = SettingsConfigDict(env_file='.env')

    # declare a field named `database_url` typed as `str`.
    # pydantic-settings matches env var names to field names case-insensitively
    # by default, so a field called `database_url` will pick up the
    # DATABASE_URL value from .env automatically — no extra config needed.
    database_url: str

    # declare a local model name
    model_name: str 

    # The larger model the third retry attempt escalates to (arch-initial.md §7: "larger model
    # second"; agent_worker/policy.py). Optional and unset by default: the development laptop can't
    # run a larger model (A2.1 E1), so tier 3 then reruns the same model with the full retry hint
    # and the attempt record says no escalation happened. Until H1 makes model endpoints
    # configurable, it must be a model name Ollama serves.
    escalation_model_name: str | None = None


# instantiate the class once at module load time, e.g.:
#   settings = Settings()
# Other modules (like app/main.py) will import this `settings` object
# rather than constructing their own — that's what makes it work like a
# single shared source of config for the whole app.

settings = Settings()