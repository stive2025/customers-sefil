"""add count_effective and count_not_effective to collection_phones and collection_addresses

Revision ID: a2b3c4d5e6f7
Revises: e1f2g3h4i5j6
Create Date: 2026-07-29

"""
from alembic import op
import sqlalchemy as sa

revision = 'a2b3c4d5e6f7'
down_revision = 'e1f2g3h4i5j6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'collection_phones',
        sa.Column('count_effective', sa.SmallInteger(), nullable=True,
                  comment='Number of effective management contacts')
    )
    op.add_column(
        'collection_phones',
        sa.Column('count_not_effective', sa.SmallInteger(), nullable=True,
                  comment='Number of non-effective management contacts')
    )
    op.add_column(
        'collection_addresses',
        sa.Column('count_effective', sa.SmallInteger(), nullable=True,
                  comment='Number of effective management contacts')
    )
    op.add_column(
        'collection_addresses',
        sa.Column('count_not_effective', sa.SmallInteger(), nullable=True,
                  comment='Number of non-effective management contacts')
    )


def downgrade() -> None:
    op.drop_column('collection_addresses', 'count_not_effective')
    op.drop_column('collection_addresses', 'count_effective')
    op.drop_column('collection_phones', 'count_not_effective')
    op.drop_column('collection_phones', 'count_effective')
