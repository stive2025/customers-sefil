"""remove source column from collection_addresses and collection_emails

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-12
"""
from alembic import op

revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Preserve existing source data in created_source before dropping
    op.execute("""
        UPDATE collection_addresses
        SET created_source = source
        WHERE source IS NOT NULL AND created_source IS NULL
    """)
    op.drop_column('collection_addresses', 'source')

    op.execute("""
        UPDATE collection_emails
        SET created_source = source
        WHERE source IS NOT NULL AND created_source IS NULL
    """)
    op.drop_column('collection_emails', 'source')


def downgrade() -> None:
    import sqlalchemy as sa
    op.add_column('collection_addresses',
        sa.Column('source', sa.String(50), nullable=True, server_default='Manual'))
    op.execute("""
        UPDATE collection_addresses
        SET source = created_source
        WHERE created_source IS NOT NULL
    """)

    op.add_column('collection_emails',
        sa.Column('source', sa.String(50), nullable=True, server_default='Manual'))
    op.execute("""
        UPDATE collection_emails
        SET source = created_source
        WHERE created_source IS NOT NULL
    """)
