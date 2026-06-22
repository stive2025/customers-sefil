"""add_unique_constraint_emails

Revision ID: d9e0f1g2h3i4
Revises: c8d9e0f1g2h3
Create Date: 2026-06-22 15:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd9e0f1g2h3i4'
down_revision: Union[str, None] = 'c8d9e0f1g2h3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Agrega un constraint unico para evitar duplicados del mismo email por persona
    op.create_unique_constraint(
        'uq_collection_emails_customer_email',
        'collection_emails',
        ['customer_id', 'email_address']
    )


def downgrade() -> None:
    op.drop_constraint('uq_collection_emails_customer_email', 'collection_emails', type_='unique')
