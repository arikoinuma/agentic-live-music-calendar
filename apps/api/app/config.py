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


# instantiate the class once at module load time, e.g.:
#   settings = Settings()
# Other modules (like app/main.py) will import this `settings` object
# rather than constructing their own — that's what makes it work like a
# single shared source of config for the whole app.

settings = Settings()