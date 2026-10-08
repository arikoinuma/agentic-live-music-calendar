"""Importing this package registers every table on `Base.metadata`.

That side effect is load-bearing: Alembic's autogenerate and the schema
tests both read `Base.metadata`, and a model module nobody imported is a
table that silently doesn't exist as far as they're concerned.
"""

from app.db.models.audit import AgentRun, AuditLog
from app.db.models.calendar import Artist, Event, Metro, Show, ShowArtist, Venue

# The names re-exported when someone writes `from app.db.models import Venue`.
# Listing them also stops linters flagging the imports above as unused.
__all__ = [
    "AgentRun",
    "Artist",
    "AuditLog",
    "Event",
    "Metro",
    "Show",
    "ShowArtist",
    "Venue",
]
