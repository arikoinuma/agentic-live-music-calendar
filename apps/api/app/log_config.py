"""structlog, configured once: readable on a terminal, JSON everywhere else.

HOW TO READ THIS
  `configure_logging()` is called once at process start (the worker's `main`). After that, any module does
  `log = structlog.get_logger()` and logs `log.info("event name", key=value)`. A line is an event name plus
  key/value fields, not a formatted sentence, so it can be searched and joined to the database.

WHY IT'S SHAPED THIS WAY (alpha-build-plan.md v0.1-G12; docs/dev/implementations/a4-auditability.md, A4-D7)
  * Context variables are merged into every line. The worker binds `run_id` and `venue_id` once per run, so
    every line in the run carries the `agent_run.id` that the run's `audit_log` rows carry. A log line and an
    audit row about the same moment can be matched on that id.
  * The renderer is a switch, not two configurations: a human at a terminal gets coloured `key=value` text; a
    cron job (Railway, CI, `| head`) gets one JSON object per line, which a log shipper can parse.
  * Output goes to stderr through structlog's own `PrintLoggerFactory`, not the stdlib `logging` module. That
    keeps it clear of Alembic's `fileConfig()`, which disables stdlib loggers for the rest of a process
    (docs/dev/notes.md). Don't switch to the stdlib integration without re-reading that note.

It lives in `app/` so the API can call it once it has something to log; today only the worker does.
"""

import sys
from typing import Literal

import structlog
from structlog.typing import Processor

from app.config import settings

LogFormat = Literal["auto", "console", "json"]


def configure_logging(fmt: LogFormat | None = None) -> None:
    """Set structlog's processor chain and output. Safe to call more than once: each call replaces the
    configuration, it doesn't add to it.

    `fmt` defaults to `settings.log_format`. "auto" is "console" when stderr is a terminal, else "json".
    """
    chosen = fmt or settings.log_format
    if chosen == "auto":
        chosen = "console" if sys.stderr.isatty() else "json"

    # The chain runs top to bottom on every event dict, ending in the renderer that turns it into text.
    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,  # run_id / venue_id bound for the run
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]
    if chosen == "json":
        # Folds a logged exception into the line's `exception` field; the console renderer prints its own.
        processors.append(structlog.processors.format_exc_info)
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        # Not cached: with caching on, a logger created before a second `configure_logging()` call keeps the
        # old chain. The worker configures once at startup so it wouldn't matter there, but the tests
        # reconfigure per case, and the cost of rebuilding a bound logger per call is negligible here.
        cache_logger_on_first_use=False,
    )
