"""metro slug

Adds `metro.slug` (String, NOT NULL, unique, format-checked): the metro's short code in its web address
(`msp.<domain>`). C4, decision C4-D3: docs/dev/implementations/c4-metro-hosts.md.

One migration, not expand-then-contract (C4-D3): the column is added nullable, the one existing metro is given
`msp`, and only then is the column made NOT NULL. That is safe for a deploy where the API and the worker do not
redeploy together (arch-initial.md section 5) because nothing but the seed and the tests inserts a `metro`, and an
old API only selects the columns it names. A database holding a metro this migration cannot name stops here with
"column slug ... contains null values", on purpose: inventing a slug for an unknown metro would give it a wrong
address, and there is exactly one metro in every environment today.

Hand-written after autogenerate (which cannot backfill): the data step and the ordering are the part that matters.

Revision ID: c4a1e5b7d903
Revises: 829af2c3f26f
Create Date: 2026-10-29 09:00:00.000000-05:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c4a1e5b7d903'
down_revision: str | Sequence[str] | None = '829af2c3f26f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Step 1: the column, nullable for the moment so the existing row survives the ADD.
    op.add_column('metro', sa.Column('slug', sa.String(), nullable=True))
    # Step 2: name the one metro that exists (Dep-D3). Matches how the seed finds it: by name.
    op.execute("UPDATE metro SET slug = 'msp' WHERE name = 'Minneapolis/St. Paul'")
    # Step 3: now require it. A metro Step 2 could not name makes this fail loudly (see the docstring).
    op.alter_column('metro', 'slug', nullable=False)
    op.create_unique_constraint(op.f('metro_slug_key'), 'metro', ['slug'])
    op.create_check_constraint(op.f('metro_slug_format_check'), 'metro', "slug ~ '^[a-z][a-z0-9-]{1,30}[a-z0-9]$'")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f('metro_slug_format_check'), 'metro', type_='check')
    op.drop_constraint(op.f('metro_slug_key'), 'metro', type_='unique')
    op.drop_column('metro', 'slug')
