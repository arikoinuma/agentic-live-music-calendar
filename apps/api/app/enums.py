"""Shared enum types, per docs/arch/data-model-initial.md Section 4.

These live here — at `app/`'s top level rather than inside `app/db/` or
`app/schemas.py` — because three different layers need the same values
and none of them should own the definition:

  * the SQLAlchemy models (milestone A1), where each becomes a native
    Postgres ENUM type rather than a free-text column;
  * the API response models in app/schemas.py, where they constrain what
    the API can emit;
  * the agent worker, where reconcile and the audit writes use them.

`StrEnum` (Python 3.11+) rather than `Enum`: members compare equal to
their own string value, so `AgeRestriction.ALL_AGES == "all_ages"` is
True, and JSON serialization is the plain string with no encoder needed.
SQLAlchemy does NOT store the value by default — it persists the member
*name* ("ALL_AGES") — unless the column's Enum sets `values_callable`,
which app/db/types.py does for every type here. The existing
agent_worker/constants.py already uses StrEnum for the same reasons.

Only the enums for tables this phase actually builds are here — core
calendar plus audit. `submission_status` and `social_platform` from the
data-model doc are omitted along with the tables that use them
(venue_submission, venue_social, artist_social).
"""

from enum import StrEnum

# ---------------------------------------------------------------------
# Venue and show dimensions
# ---------------------------------------------------------------------


class AgeRestriction(StrEnum):
    ALL_AGES = "all_ages"
    TWENTY_ONE_PLUS = "twenty_one_plus"


class Setting(StrEnum):
    INDOOR = "indoor"
    OUTDOOR = "outdoor"
    BOTH = "both"


class Seating(StrEnum):
    STANDING = "standing"
    SEATED = "seated"
    BOTH = "both"


class VenueType(StrEnum):
    BAR = "bar"
    CLUB = "club"
    THEATER = "theater"
    COFFEEHOUSE = "coffeehouse"
    ARENA = "arena"
    PARK = "park"
    OTHER = "other"


class FetchStrategy(StrEnum):
    """How the agent worker retrieves a venue's calendar page.

    `HTTP` is a plain httpx GET. `BROWSER` means Playwright is needed —
    either the page is JS-rendered, or its pagination is a click-driven
    "load more" that a plain fetch can't follow. Only the HTTP path is
    implemented this phase (alpha-build-plan.md section 8).
    """

    HTTP = "http"
    BROWSER = "browser"


class ShowStatus(StrEnum):
    """Soft delete, per the reconciliation rule.

    A show that disappears from a venue's page — within the date range
    that fetch actually covered — becomes REMOVED rather than being
    deleted, so the record and its audit history survive. The read API
    filters to ACTIVE.
    """

    ACTIVE = "active"
    REMOVED = "removed"


class ArtistFormat(StrEnum):
    """Describes the act itself, not a given performance's configuration
    — a solo artist touring with a backing band is still SOLO.
    """

    SOLO = "solo"
    DUO = "duo"
    TRIO = "trio"
    BAND = "band"


class ArtistRepertoire(StrEnum):
    ORIGINAL = "original"
    COVER = "cover"
    BOTH_OTHER = "both_other"


# ---------------------------------------------------------------------
# Agent run and audit trail (milestone A4)
# ---------------------------------------------------------------------


class RunTrigger(StrEnum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"
    SUBMISSION = "submission"
    FLAG_THRESHOLD = "flag_threshold"


class StepType(StrEnum):
    """Which pipeline stage an audit_log row came from.

    Deliberately the same six values as `NodeNames` in
    agent_worker/constants.py, because they describe the same six graph
    nodes. Worth being aware of the duplication: A4 should either import
    one from the other or assert they agree in a test, rather than
    leaving two lists to drift apart silently.
    """

    FETCH = "fetch"
    EXTRACT = "extract"
    VALIDATE = "validate"
    RECONCILE = "reconcile"
    COMMIT = "commit"
    ESCALATE = "escalate"


class AuditSource(StrEnum):
    """What produced an audit_log row. The same table records human
    edits alongside agent actions, which is what this distinguishes.
    """

    AGENT = "agent"
    USER = "user"


class AuditOutcome(StrEnum):
    INSERTED = "inserted"
    UPDATED = "updated"
    REMOVED = "removed"
    NO_OP = "no_op"
    ESCALATED = "escalated"


class EntityType(StrEnum):
    VENUE = "venue"
    ARTIST = "artist"
    SHOW = "show"
    EVENT = "event"
