"""Postgres ENUM types, each defined once.

The Python enums live in app/enums.py (shared with the API schemas and the
worker); this module turns each into a native Postgres ENUM type, per
data-model-initial.md section 1 and the type names in section 4.

Two reasons this is its own module rather than inline `Enum(...)` on each
column:

* `age_restriction`, `setting` and `seating` are used by both `venue` and
  `show`. Two inline copies are two objects that can drift apart; one
  module-level object per type can't.
* `values_callable` is easy to forget and its absence is silent (see below).
  Centralising it means it's written once.
"""

from enum import StrEnum

from sqlalchemy import Enum

from app import enums


def _pg_enum(py_enum: type[StrEnum], name: str) -> Enum:
    # SQLAlchemy persists enum member *names* ("ALL_AGES") by default, not
    # values ("all_ages"). `values_callable` flips that, so the Postgres
    # labels are the lowercase values in app/enums.py and data-model-initial.md
    # section 4 — and match what the API and the audit writes emit. An
    # explicit `name=` is required too; the default would be the lowercased
    # class name ("artistformat").
    return Enum(py_enum, name=name, values_callable=lambda e: [m.value for m in e])


# One constant per Postgres enum type, named in data-model-initial.md section
# 4. The first argument is the Python enum (the allowed values); the second is
# the type's name inside Postgres. Models import these by constant name, e.g.
# `mapped_column(types.AGE_RESTRICTION)`.
AGE_RESTRICTION = _pg_enum(enums.AgeRestriction, "age_restriction")
SETTING = _pg_enum(enums.Setting, "setting")
SEATING = _pg_enum(enums.Seating, "seating")
VENUE_TYPE = _pg_enum(enums.VenueType, "venue_type")
FETCH_STRATEGY = _pg_enum(enums.FetchStrategy, "fetch_strategy")
SHOW_STATUS = _pg_enum(enums.ShowStatus, "show_status")
ARTIST_FORMAT = _pg_enum(enums.ArtistFormat, "artist_format")
ARTIST_REPERTOIRE = _pg_enum(enums.ArtistRepertoire, "artist_repertoire")
# Audit-domain types (agent_run / audit_log) start here.
RUN_TRIGGER = _pg_enum(enums.RunTrigger, "run_trigger")
STEP_TYPE = _pg_enum(enums.StepType, "step_type")
AUDIT_SOURCE = _pg_enum(enums.AuditSource, "audit_source")
AUDIT_OUTCOME = _pg_enum(enums.AuditOutcome, "audit_outcome")
ENTITY_TYPE = _pg_enum(enums.EntityType, "entity_type")
