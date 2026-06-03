"""migrate profession to economic_activity

Revision ID: ed67c44258c7
Revises: e5f6a7b8c9d0
Create Date: 2026-06-03 13:41:04.802382

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ed67c44258c7'
down_revision: Union[str, Sequence[str], None] = 'c7728ca8b230'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Copiar los datos de profession a economic_activity si economic_activity está vacío
    op.execute(
        """
        UPDATE customers 
        SET economic_activity = profession 
        WHERE economic_activity IS NULL AND profession IS NOT NULL
        """
    )
    # 2. Eliminar la columna profession
    op.drop_column('customers', 'profession')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column('customers', sa.Column('profession', sa.String(length=500), nullable=True))
