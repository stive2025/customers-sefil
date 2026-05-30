"""remove source column from collection_phones, migrate data to created_source

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-30
"""
from alembic import op

revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Preserve existing source data in created_source before dropping
    op.execute("""
        UPDATE collection_phones
        SET created_source = source
        WHERE source IS NOT NULL AND created_source IS NULL
    """)
    op.drop_column('collection_phones', 'source')


def downgrade() -> None:
    import sqlalchemy as sa
    op.add_column('collection_phones',
        sa.Column('source', sa.String(50), nullable=True, server_default='Manual'))
    op.execute("""
        UPDATE collection_phones
        SET source = created_source
        WHERE created_source IS NOT NULL
    """)
