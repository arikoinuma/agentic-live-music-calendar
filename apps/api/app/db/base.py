"""The declarative base shared by FastAPI and the agent worker.

docs/arch/arch-initial.md section 5 calls for "one Python package of
SQLAlchemy models" imported by both processes, so there is exactly one
`Base` and one `MetaData` — and therefore one Alembic history.
"""

import datetime
from typing import Any, ClassVar

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Constraint and index naming, from docs/references/fastapi-style-guide.md.
# This has to exist *before* the first model: without it Postgres invents
# the names, autogenerate can't reliably match constraints it didn't name,
# and adding the convention later means renaming live constraints. These
# templates also happen to reproduce the names Postgres already gave
# `venue_pkey` and `venue_metro_id_fkey` in the first migration, so adopting
# them renames nothing.
#
# The "ck" template includes %(constraint_name)s, so every CheckConstraint
# must be given an explicit `name=`; SQLAlchemy raises at definition time
# for an unnamed one. A1 has no unique constraints, so "uq" is unused for now.
NAMING_CONVENTION = {
    "ix": "%(column_0_label)s_idx",
    "uq": "%(table_name)s_%(column_0_name)s_key",
    "ck": "%(table_name)s_%(constraint_name)s_check",
    "fk": "%(table_name)s_%(column_0_name)s_fkey",
    "pk": "%(table_name)s_pkey",
}


class Base(DeclarativeBase):
    """Parent of every model class.

    Subclassing this is what makes a Python class a table: SQLAlchemy
    collects each subclass into `Base.metadata`, which Alembic reads to
    compare the models against the database. The metadata object is
    created here, with the naming convention above, so every table and
    constraint shares it.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """`created_at` / `updated_at`, per data-model-initial.md section 1.

    Section 1 puts these on every table "unless noted". The tables that
    skip them skip them on purpose, each recorded as a departure in
    docs/dev/implementations/a1-data-layer.md: `show_artist` (a pure join),
    `audit_log` (append-only; `created_at` only, as section 3 specifies) and
    `agent_run` (its own `started_at` / `finished_at` are the lifecycle
    timestamps; a second pair would duplicate them).

    Both defaults are `server_default`, not a Python-side `default`, so a
    raw SQL INSERT or the worker gets them too. The one exception to
    "server-side" is `onupdate`: SQLAlchemy only applies it to UPDATEs it
    issues itself, not to raw SQL. No trigger is added to close that gap —
    nothing needs the guarantee yet.

    `eager_defaults=True`: with the default ("auto"), SQLAlchemy fetches
    server-generated values only on INSERT. `onupdate=func.now()` is a SQL
    expression, so after an ORM UPDATE `updated_at` would be left expired,
    and reading it under an AsyncSession is a hidden lazy load that raises
    MissingGreenlet. A6 snapshots a row right after updating it (for
    `audit_log.new_value`), which is exactly that read. True makes Postgres
    return the new value via RETURNING on UPDATE as well.
    """

    __mapper_args__: ClassVar[dict[str, Any]] = {"eager_defaults": True}

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
