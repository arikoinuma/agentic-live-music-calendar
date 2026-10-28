"""agent_run app_env

Adds `agent_run.app_env` (String(16), nullable, no default): which environment ("local", "dev", "staging" or
"prod") wrote the run. C3, decision C3-D5: docs/dev/implementations/c3-environments-and-deploy.md. Expand-only on
purpose: the API (which runs this migration before it starts) and the worker do not redeploy together, so a
column the old worker never writes must not be required. Read after autogenerate: one add_column, no enum
types (the value is a plain string, so adding an environment later needs no migration), nothing corrected by hand.

Revision ID: 829af2c3f26f
Revises: 67609c405218
Create Date: 2026-10-28 10:37:02.908398-05:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '829af2c3f26f'
down_revision: str | Sequence[str] | None = '67609c405218'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('agent_run', sa.Column('app_env', sa.String(length=16), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('agent_run', 'app_env')
