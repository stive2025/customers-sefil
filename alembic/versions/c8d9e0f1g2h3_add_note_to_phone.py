"""add_note_to_phone

Revision ID: c8d9e0f1g2h3
Revises: b8c9d0e1f2a3
Create Date: 2026-06-19 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8d9e0f1g2h3'
down_revision: Union[str, None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('collection_phones', sa.Column('note', sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column('collection_phones', 'note')
