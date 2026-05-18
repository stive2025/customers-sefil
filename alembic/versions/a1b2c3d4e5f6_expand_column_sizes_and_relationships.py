"""Expand column sizes and add customer_relationships table

Revision ID: a1b2c3d4e5f6
Revises: 7991cee60d14
Create Date: 2026-05-18 00:00:00.000000

Changes:
  - customers.first_name:  VARCHAR(100) → VARCHAR(200)
  - customers.last_name:   VARCHAR(100) → VARCHAR(200)
  - customers.birth_place: VARCHAR(100) → VARCHAR(200)
  - customers.nationality: VARCHAR(50)  → VARCHAR(100)
  - customers.profession:  VARCHAR(100) → VARCHAR(500)
  - collection_addresses.address_line: VARCHAR(250) → VARCHAR(500)
  - Add table: customer_relationships
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '7991cee60d14'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Expand customers column sizes ---
    op.alter_column('customers', 'first_name',
                    existing_type=sa.String(length=100),
                    type_=sa.String(length=200),
                    existing_nullable=False)
    op.alter_column('customers', 'last_name',
                    existing_type=sa.String(length=100),
                    type_=sa.String(length=200),
                    existing_nullable=False)
    op.alter_column('customers', 'birth_place',
                    existing_type=sa.String(length=100),
                    type_=sa.String(length=200),
                    existing_nullable=True)
    op.alter_column('customers', 'nationality',
                    existing_type=sa.String(length=50),
                    type_=sa.String(length=100),
                    existing_nullable=True)
    op.alter_column('customers', 'profession',
                    existing_type=sa.String(length=100),
                    type_=sa.String(length=500),
                    existing_nullable=True)

    # --- Expand address_line ---
    op.alter_column('collection_addresses', 'address_line',
                    existing_type=sa.String(length=250),
                    type_=sa.String(length=500),
                    existing_nullable=False)

    # --- Add customer_relationships table (idempotent) ---
    conn = op.get_bind()
    if not sa.inspect(conn).has_table('customer_relationships'):
        op.create_table(
            'customer_relationships',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('customer_id', sa.Integer(), nullable=False),
            sa.Column('relationship_type', sa.String(length=30), nullable=False),
            sa.Column('related_identification', sa.String(length=13), nullable=True),
            sa.Column('related_name', sa.String(length=200), nullable=True),
            sa.Column('related_birth_date', sa.Date(), nullable=True),
            sa.Column('related_gender', sa.String(length=20), nullable=True),
            sa.Column('related_civil_status', sa.String(length=30), nullable=True),
            sa.Column('related_death_date', sa.Date(), nullable=True),
            sa.Column('source', sa.String(length=50), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True),
                      server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_customer_relationships_customer_id',
                        'customer_relationships', ['customer_id'], unique=False)
        op.create_index('ix_customer_relationships_related_identification',
                        'customer_relationships', ['related_identification'], unique=False)
        op.create_index('ix_customer_relationships_id',
                        'customer_relationships', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_customer_relationships_id', table_name='customer_relationships')
    op.drop_index('ix_customer_relationships_related_identification', table_name='customer_relationships')
    op.drop_index('ix_customer_relationships_customer_id', table_name='customer_relationships')
    op.drop_table('customer_relationships')

    op.alter_column('collection_addresses', 'address_line',
                    existing_type=sa.String(length=500),
                    type_=sa.String(length=250),
                    existing_nullable=False)

    op.alter_column('customers', 'profession',
                    existing_type=sa.String(length=500),
                    type_=sa.String(length=100),
                    existing_nullable=True)
    op.alter_column('customers', 'nationality',
                    existing_type=sa.String(length=100),
                    type_=sa.String(length=50),
                    existing_nullable=True)
    op.alter_column('customers', 'birth_place',
                    existing_type=sa.String(length=200),
                    type_=sa.String(length=100),
                    existing_nullable=True)
    op.alter_column('customers', 'last_name',
                    existing_type=sa.String(length=200),
                    type_=sa.String(length=100),
                    existing_nullable=False)
    op.alter_column('customers', 'first_name',
                    existing_type=sa.String(length=200),
                    type_=sa.String(length=100),
                    existing_nullable=False)
