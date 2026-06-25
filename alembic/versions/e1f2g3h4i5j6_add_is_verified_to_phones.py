"""add_is_verified_to_phones

Revision ID: e1f2g3h4i5j6
Revises: d9e0f1g2h3i4
Create Date: 2026-06-25 08:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1f2g3h4i5j6'
down_revision: Union[str, None] = 'd9e0f1g2h3i4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Agrega la columna is_verified con default en False
    op.add_column('collection_phones', sa.Column('is_verified', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    op.drop_column('collection_phones', 'is_verified')
