"""agent_run feature_flags

Adds `agent_run.feature_flags` (JSONB, nullable, no default): the feature-flag values the run ran under, as
`{"worker.scheduled_runs": false}`. C3.1, decision C3.1-D3, C3.1-D15: docs/dev/implementations/c3.1-feature-flags.md.
Expand-only on purpose, exactly like `agent_run.app_env` (829af2c3f26f): the API (which runs this migration before it
starts) and the worker do not redeploy together, so a column the old worker never writes must not be required.
Written by hand (the `down_revision` is the newest migration, `c4a1e5b7d903`) and checked against the models by
`test_models_and_migration_agree` (what autogenerate would produce): one add_column, no enum types, no index, nothing else.

Revision ID: d7b3c2a91e45
Revises: c4a1e5b7d903
Create Date: 2026-11-09 10:00:00.000000-06:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d7b3c2a91e45"
down_revision: str | Sequence[str] | None = "c4a1e5b7d903"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("agent_run", sa.Column("feature_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("agent_run", "feature_flags")
