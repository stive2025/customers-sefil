"""add_death_date_to_customer

Revision ID: d6cc833d6094
Revises: a2b3c4d5e6f7
Create Date: 2026-08-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd6cc833d6094'
down_revision: Union[str, Sequence[str], None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('customers', sa.Column('death_date', sa.Date(), nullable=True, comment='Date of death, if applicable'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('customers', 'death_date')
