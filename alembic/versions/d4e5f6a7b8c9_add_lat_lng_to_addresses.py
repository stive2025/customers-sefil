"""add latitude and longitude to collection_addresses

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-30
"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('collection_addresses', sa.Column('latitude',  sa.Float(), nullable=True))
    op.add_column('collection_addresses', sa.Column('longitude', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('collection_addresses', 'longitude')
    op.drop_column('collection_addresses', 'latitude')
