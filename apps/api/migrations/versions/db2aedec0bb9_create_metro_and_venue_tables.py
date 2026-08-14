"""create metro and venue tables

This is the first migration in the project, so `down_revision` is None —
there's nothing before it to build on top of. Every later migration will
set `down_revision` to whatever revision id came immediately before it,
which is how Alembic knows the order to apply them in.

Scope note: this is deliberately minimal — just enough to prove Postgres,
SQLAlchemy, and Alembic are wired together correctly end to end (per
Phase 3 of docs/dev/env-setup.md). The full schema (genre/instrumentation
join tables, JSONB extra_metadata, audit trail, etc. — see
docs/arch/arch-initial.md Section 6) comes later.
"""

import sqlalchemy as sa
from alembic import op

# `revision` is this migration's own unique id — it must match the
# id already baked into this file's name (the part before the underscore).
# `down_revision` is the id of the migration that must run immediately
# before this one. Since this is the first migration, there isn't one.
revision = "db2aedec0bb9"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # create the `metro` table with op.create_table().
    # From docs/arch/arch-initial.md: "Metro is a first-class entity
    # (name, timezone)." Columns needed:
    #   - id: sa.Integer, primary_key=True
    #   - name: sa.String, nullable=False
    #   - timezone: sa.String, nullable=False
    #
    # Shape to follow:
    #   op.create_table(
    #       "metro",
    #       sa.Column("id", sa.Integer, primary_key=True),
    #       sa.Column(..., nullable=False),
    #       ...
    #   )
    op.create_table(
        "metro",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("timezone", sa.String, nullable=False)
    )

    # create the `venue` table with op.create_table().
    # Venues are scoped to a metro (per the same architecture doc section),
    # so this table needs a foreign key back to metro.id. Columns needed:
    #   - id: sa.Integer, primary_key=True
    #   - metro_id: sa.Integer, sa.ForeignKey("metro.id"), nullable=False
    #   - name: sa.String, nullable=False
    #   - calendar_url: sa.String, nullable=False
    #
    # A column's foreign key is declared inline as part of sa.Column, e.g.:
    #   sa.Column("metro_id", sa.Integer, sa.ForeignKey("metro.id"), nullable=False)
    op.create_table(
        "venue",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("metro_id", sa.Integer, sa.ForeignKey("metro.id"), nullable=False),
        sa.Column("calendar_url", sa.String, nullable=False)
    )


def downgrade() -> None:
    # undo exactly what upgrade() did, in reverse order. Since venue
    # has a foreign key pointing at metro, venue must be dropped first —
    # dropping metro while venue still references it would violate the
    # foreign key constraint.
    #   op.drop_table("venue")
    #   op.drop_table("metro")
    op.drop_table("venue")
    op.drop_table("metro")
