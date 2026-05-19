"""add calls_effective and calls_not_effective to collection_phones

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-19

"""
from alembic import op
import sqlalchemy as sa

revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'collection_phones',
        sa.Column('calls_effective', sa.SmallInteger(), nullable=True,
                  comment='Number of effective calls (Collecta)')
    )
    op.add_column(
        'collection_phones',
        sa.Column('calls_not_effective', sa.SmallInteger(), nullable=True,
                  comment='Number of non-effective calls (Collecta)')
    )


def downgrade() -> None:
    op.drop_column('collection_phones', 'calls_not_effective')
    op.drop_column('collection_phones', 'calls_effective')
