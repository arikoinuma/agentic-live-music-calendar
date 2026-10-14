"""Assertions on the SQLAlchemy models' metadata. No database needed.

HOW TO READ THIS FILE
  The ORM models in app/db/models/ describe the schema in Python. This file
  checks that description against what docs/arch/data-model-initial.md says
  the schema should be: which tables and columns exist, which are required,
  what types they have, how enums are labelled, and how constraints/indexes
  are named. Nothing here connects to Postgres, so it runs everywhere
  (including a laptop with Docker off).

  It is only half the story. A model can be right while the Alembic
  migration that actually builds the database is wrong; that comparison is
  in test_db_schema.py, against a real Postgres.

WHY THE EXPECTED VALUES ARE TYPED OUT BY HAND
  Written before the models (docs/dev/implementations/a1-data-layer.md,
  "Test approach", layer 1). The expected values below are transcribed from
  docs/arch/data-model-initial.md on purpose rather than derived from the
  models: a test that reads its expectations from the code under test can't
  catch the code being wrong.
"""

import inspect
import re
from enum import StrEnum

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app import enums
from app.db import models  # noqa: F401  (importing registers every table)
from app.db.base import Base

# Every table the models declare, keyed by table name. Importing
# `app.db.models` above is what populates this; a model nobody imported
# would simply be missing here (and from Alembic's view of the world).
TABLES = Base.metadata.tables

# --- The spec, transcribed ---------------------------------------------------

# Column lists transcribed from data-model-initial.md sections 2-3, with the
# departures recorded in docs/dev/implementations/a1-data-layer.md:
# audit_log has no contributor_id / session_hash, agent_run has no
# triggered_by (their targets or purpose are deferred), and agent_run /
# audit_log / show_artist skip created_at/updated_at.
# `_TS` is the timestamp pair most tables share (see TimestampMixin in
# app/db/base.py); `| _TS` below means "plus created_at and updated_at".
_TS = {"created_at", "updated_at"}
EXPECTED_COLUMNS: dict[str, set[str]] = {
    "metro": {"id", "name", "timezone"} | _TS,
    "venue": {
        "id", "metro_id", "name", "calendar_url", "photo_url", "address",
        "phone_numbers", "emails", "website", "age_restriction",
        "serves_alcohol", "venue_type", "setting", "seating",
        "fetch_strategy", "extra_metadata",
    } | _TS,
    "artist": {
        "id", "name", "photo_url", "website", "hometown", "format",
        "repertoire", "extra_metadata",
    } | _TS,
    "event": {"id", "name", "start_date", "end_date"} | _TS,
    "show": {
        "id", "venue_id", "event_id", "date", "start_time", "end_time",
        "age_restriction", "serves_alcohol", "setting", "seating",
        "admission_advance", "admission_day", "free_admission", "image_url",
        "original_url", "status",
    } | _TS,
    "show_artist": {"show_id", "artist_id", "start_time", "sequence_number"},
    "agent_run": {"id", "venue_id", "trigger", "started_at", "finished_at"},
    "audit_log": {
        "id", "run_id", "attempt_number", "step_type", "source", "entity_type",
        "entity_id", "outcome", "model_used", "confidence", "previous_value",
        "new_value", "snapshot_key", "created_at",
        # A4 (docs/dev/implementations/a4-auditability.md, D2): the evidence behind a step.
        "detail",
    },
}

# data-model-initial.md section 4, written out literally: Postgres type name
# -> labels, in order. Deliberately NOT derived from app/enums.py — a wrong
# label there would otherwise pass every test, because the other checks
# compare the models and the database to enums.py. This is the one place
# the spec's own words are the oracle.
EXPECTED_ENUM_LABELS: dict[str, list[str]] = {
    "age_restriction": ["all_ages", "twenty_one_plus"],
    "setting": ["indoor", "outdoor", "both"],
    "seating": ["standing", "seated", "both"],
    "venue_type": ["bar", "club", "theater", "coffeehouse", "arena", "park", "other"],
    "fetch_strategy": ["http", "browser"],
    "show_status": ["active", "removed"],
    "artist_format": ["solo", "duo", "trio", "band"],
    "artist_repertoire": ["original", "cover", "both_other"],
    "run_trigger": ["scheduled", "manual", "submission", "flag_threshold"],
    "step_type": ["fetch", "extract", "validate", "reconcile", "commit", "escalate"],
    "audit_source": ["agent", "user"],
    "audit_outcome": ["inserted", "updated", "removed", "no_op", "escalated"],
    "entity_type": ["venue", "artist", "show", "event"],
}

# Postgres type name -> the Python enum class in app/enums.py that backs it.
# Used to check that enums.py and the spec above agree, and that every enum
# in enums.py is actually wired to a column.
EXPECTED_ENUMS: dict[str, type[StrEnum]] = {
    "age_restriction": enums.AgeRestriction,
    "setting": enums.Setting,
    "seating": enums.Seating,
    "venue_type": enums.VenueType,
    "fetch_strategy": enums.FetchStrategy,
    "show_status": enums.ShowStatus,
    "artist_format": enums.ArtistFormat,
    "artist_repertoire": enums.ArtistRepertoire,
    "run_trigger": enums.RunTrigger,
    "step_type": enums.StepType,
    "audit_source": enums.AuditSource,
    "audit_outcome": enums.AuditOutcome,
    "entity_type": enums.EntityType,
}


# --- Tables and columns ------------------------------------------------------


def test_expected_tables_exist_and_deferred_ones_do_not() -> None:
    # Proves: A1 built exactly the core-calendar + audit tables, nothing more.
    assert set(TABLES) == set(EXPECTED_COLUMNS)
    # Deferred per alpha-build-plan.md section 8: nothing consumes these yet, and
    # this repo's rule is not to build what has no consumer. If one of these
    # shows up here, someone scaffolded ahead of need.
    for deferred in ("contributor", "flag", "venue_submission", "genre", "instrument", "member"):
        assert deferred not in TABLES


@pytest.mark.parametrize("table", sorted(EXPECTED_COLUMNS))
def test_table_has_exactly_the_specified_columns(table: str) -> None:
    # Proves: each table has every column the spec lists and no extras.
    # Parametrized so a failure names the table. "No extras" matters as much
    # as "no missing": an unlisted column is an undocumented departure.
    assert {c.name for c in TABLES[table].columns} == EXPECTED_COLUMNS[table]


def test_required_columns_are_not_null_and_optional_ones_are_nullable() -> None:
    # Proves: NOT NULL is exactly where the spec says "required" and nowhere
    # else. A too-strict column makes the agent's inserts fail on a listing
    # that merely omits a field; a too-loose one lets bad rows in.
    #
    # Per table: the columns that must be NOT NULL (primary keys and the
    # timestamp pair are skipped below: they're NOT NULL by construction).
    not_null = {
        "metro": {"name", "timezone"},
        "venue": {"metro_id", "name", "calendar_url", "fetch_strategy"},
        "artist": {"name"},
        "event": {"name"},
        "show": {"venue_id", "date", "status"},
        "agent_run": {"venue_id", "trigger", "started_at"},
        "audit_log": {"attempt_number", "step_type", "source", "created_at"},
    }
    for table, required in not_null.items():
        for col in TABLES[table].columns:
            if col.primary_key or col.name in _TS:
                continue
            # Both directions at once: required columns are NOT NULL, and
            # every other column is nullable.
            assert (not col.nullable) == (col.name in required), f"{table}.{col.name}"
    # The spec's headline nullable fields. A listing often has no start time,
    # and the model must be able to say "not stated" rather than invent one.
    assert TABLES["show"].c.start_time.nullable
    assert TABLES["show"].c.free_admission.nullable  # absence of a price is NOT "free"


def test_column_types_the_doc_specifies() -> None:
    # Proves: the columns whose *type* carries meaning have the right one.
    show, venue, log = TABLES["show"], TABLES["venue"], TABLES["audit_log"]
    # Money is exact (the API sends Decimal as a string for the same reason).
    assert isinstance(show.c.admission_advance.type, sa.Numeric)
    assert show.c.admission_advance.type.asdecimal
    # Phone numbers/emails are plain Postgres arrays, not child tables.
    assert isinstance(venue.c.phone_numbers.type, postgresql.ARRAY)
    assert isinstance(venue.c.emails.type, postgresql.ARRAY)
    # JSONB (not JSON) so the GIN indexes below can work on it; the audit
    # snapshots are JSONB because they hold whole-row copies for revert.
    assert isinstance(venue.c.extra_metadata.type, postgresql.JSONB)
    assert isinstance(log.c.previous_value.type, postgresql.JSONB)
    assert isinstance(log.c.new_value.type, postgresql.JSONB)
    assert isinstance(TABLES["artist"].c.extra_metadata.type, postgresql.JSONB)
    # Timestamps are timestamptz everywhere (data-model-initial.md section 1).
    # A naive timestamp would silently mean "server local time".
    for table, col in [("venue", "created_at"), ("agent_run", "started_at"), ("audit_log", "created_at")]:
        assert TABLES[table].c[col].type.timezone, f"{table}.{col}"  # type: ignore[attr-defined]


# --- Enums -------------------------------------------------------------------


def _enum_columns() -> list[tuple[str, str, sa.Enum]]:
    """Every enum-typed column in the schema, as (table, column, type)."""
    return [
        (t.name, c.name, c.type)
        for t in TABLES.values()
        for c in t.columns
        if isinstance(c.type, sa.Enum)
    ]


def test_every_python_enum_is_a_postgres_type_and_nothing_else_is() -> None:
    # Proves: app/enums.py and the database's enum types are the same set.
    # Catches both an enum defined but never used on a column, and a column
    # using an enum type that has no Python counterpart.
    in_enums_py = {
        obj
        for _, obj in inspect.getmembers(enums, inspect.isclass)
        if issubclass(obj, StrEnum) and obj is not StrEnum
    }
    # 13 today; derived rather than hard-coded so a new enum in enums.py
    # that nobody mapped to a column fails here.
    assert in_enums_py == set(EXPECTED_ENUMS.values())
    assert {e.name for _, _, e in _enum_columns()} == set(EXPECTED_ENUMS)


def test_enums_py_matches_the_data_model_doc() -> None:
    # Proves: the labels in app/enums.py equal the spec's literals above.
    # This is the test that would catch a typo in enums.py itself, since
    # every other check is relative to that file.
    assert {n: [m.value for m in cls] for n, cls in EXPECTED_ENUMS.items()} == EXPECTED_ENUM_LABELS


def test_enum_labels_are_the_python_values_not_the_member_names() -> None:
    # Proves: the Postgres labels are lowercase *values* ("all_ages"), not
    # Python member names ("ALL_AGES").
    # SQLAlchemy persists member NAMES ("ALL_AGES") unless values_callable
    # is set — and enums.py's own docstring used to claim otherwise. This is
    # the test that keeps the labels honest, against the spec's literals.
    for table, column, sa_enum in _enum_columns():
        assert list(sa_enum.enums) == EXPECTED_ENUM_LABELS[sa_enum.name], f"{table}.{column}"  # type: ignore[index]


def test_shared_enum_types_are_one_object_not_two_copies() -> None:
    # Proves: age_restriction, setting and seating (used by both `venue` and
    # `show`) are a single type object, not two copies that could drift
    # apart. See app/db/types.py for why they're defined once.
    by_name: dict[str, set[int]] = {}
    for _, _, sa_enum in _enum_columns():
        by_name.setdefault(sa_enum.name, set()).add(id(sa_enum))  # type: ignore[arg-type]
    for name in ("age_restriction", "setting", "seating"):
        assert len(by_name[name]) == 1, f"{name} is defined twice and can drift"


# --- Constraint and index naming --------------------------------------------


def _ddl(table: sa.Table) -> str:
    """The CREATE TABLE statement SQLAlchemy would emit for Postgres."""
    return str(CreateTable(table).compile(dialect=postgresql.dialect()))


def test_naming_convention_is_applied_to_constraints() -> None:
    # Proves: primary keys and foreign keys get the predictable names from
    # the NAMING_CONVENTION in app/db/base.py ("<table>_pkey",
    # "<table>_<col>_fkey"), rather than names Postgres invents. Stable names
    # are what let Alembic match and later alter a constraint reliably.
    #
    # Compiled DDL rather than constraint.name: the convention resolves at
    # DDL-compile time for constraints whose name was left as None.
    for name, table in TABLES.items():
        ddl = _ddl(table)
        pk_cols = [c.name for c in table.primary_key.columns]
        if len(pk_cols) >= 1:
            assert f"CONSTRAINT {name}_pkey PRIMARY KEY" in ddl, name
        for fk in table.foreign_key_constraints:
            first = next(iter(fk.columns)).name
            assert f"CONSTRAINT {name}_{first}_fkey FOREIGN KEY" in ddl, f"{name}.{first}"
    # The convention's ck template needs the constraint to be explicitly
    # named, or SQLAlchemy raises when the table is defined.
    assert "CONSTRAINT show_free_admission_check CHECK" in _ddl(TABLES["show"])


def test_indexes_and_their_names() -> None:
    # Proves: exactly these four indexes exist, with convention-derived
    # names, and the right kind. Every extra index costs write speed, so the
    # set is pinned; each one below has a named consumer.
    names = {}
    for table in TABLES.values():
        for index in table.indexes:
            sql = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
            names[re.search(r"INDEX (\w+) ON", sql).group(1)] = sql  # type: ignore[union-attr]
    assert set(names) == {
        "venue_extra_metadata_idx",
        "artist_extra_metadata_idx",
        "show_venue_id_idx",  # (venue_id, date): reconcile's composite-key lookup
        "audit_log_run_id_idx",  # "everything that happened in run N"
    }
    # GIN so containment queries on the JSONB blob stay indexed.
    assert "USING gin" in names["venue_extra_metadata_idx"]
    assert "USING gin" in names["artist_extra_metadata_idx"]
    # The composite index leads with venue_id, then date: reconcile looks up
    # one venue's shows in a date range.
    assert "venue_id, date" in names["show_venue_id_idx"]


def test_composite_primary_key_on_show_artist() -> None:
    # Proves: a show's lineup is keyed by (show, artist) together, so the
    # same artist can't be listed twice on one show but can appear on many.
    assert [c.name for c in TABLES["show_artist"].primary_key.columns] == ["show_id", "artist_id"]


# --- Defaults and the audit trail's deliberate looseness --------------------


def test_defaults_are_server_side_so_raw_sql_and_the_worker_get_them() -> None:
    # Proves: defaults live in the database (`server_default`), not in
    # Python. A Python-side default only applies to inserts SQLAlchemy builds;
    # a raw SQL INSERT, a psql session, or another tool would get NULL (or a
    # NOT NULL error) instead.
    must_have = [
        ("show", "status"),
        ("venue", "fetch_strategy"),
        ("audit_log", "attempt_number"),
        ("audit_log", "created_at"),
        ("agent_run", "started_at"),
        *[(t, c) for t in ("metro", "venue", "artist", "event", "show") for c in _TS],
    ]
    for table, column in must_have:
        assert TABLES[table].c[column].server_default is not None, f"{table}.{column}"
    # A Python-side default would be invisible to INSERTs outside SQLAlchemy.
    for col in (c for t in TABLES.values() for c in t.columns):
        assert col.default is None, f"{col.table.name}.{col.name} has a Python-side default"


def test_entity_id_is_deliberately_not_a_foreign_key() -> None:
    # Proves: audit_log.entity_id has no FK (it can point at a row in any of
    # several tables, and that row may later be deleted), while run_id does.
    # data-model-initial.md section 3: the referenced row can be deleted or
    # live in any of several tables, and the audit trail must survive that.
    assert not TABLES["audit_log"].c.entity_id.foreign_keys
    assert TABLES["audit_log"].c.run_id.foreign_keys
