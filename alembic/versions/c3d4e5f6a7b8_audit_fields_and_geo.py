"""audit fields on collection tables + geographic fields on addresses

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-30

Adds to collection_phones:
  is_active, created_by, created_source,
  updated_at, updated_by, updated_source,
  deleted_at, deleted_by, deleted_source

Adds to collection_addresses:
  is_active, canton, parish, neighborhood,
  created_by, created_source,
  updated_at, updated_by, updated_source,
  deleted_at, deleted_by, deleted_source

Adds to collection_emails (is_active already exists):
  created_by, created_source,
  updated_at, updated_by, updated_source,
  deleted_at, deleted_by, deleted_source
"""
from alembic import op
import sqlalchemy as sa

revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None

# Audit columns shared by all 3 tables (excluding is_active)
_AUDIT_COLS = [
    sa.Column('created_by',     sa.String(100), nullable=True),
    sa.Column('created_source', sa.String(50),  nullable=True),
    sa.Column('updated_at',     sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_by',     sa.String(100), nullable=True),
    sa.Column('updated_source', sa.String(50),  nullable=True),
    sa.Column('deleted_at',     sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by',     sa.String(100), nullable=True),
    sa.Column('deleted_source', sa.String(50),  nullable=True),
]


def upgrade() -> None:
    # ── collection_phones ─────────────────────────────────────────────────────
    op.add_column('collection_phones',
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')))
    for col in _AUDIT_COLS:
        op.add_column('collection_phones', col)

    # ── collection_addresses ──────────────────────────────────────────────────
    op.add_column('collection_addresses',
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')))
    op.add_column('collection_addresses', sa.Column('canton',       sa.String(100), nullable=True))
    op.add_column('collection_addresses', sa.Column('parish',       sa.String(100), nullable=True))
    op.add_column('collection_addresses', sa.Column('neighborhood', sa.String(100), nullable=True))
    for col in _AUDIT_COLS:
        op.add_column('collection_addresses', col)

    # ── collection_emails ─────────────────────────────────────────────────────
    # is_active already exists on this table
    for col in _AUDIT_COLS:
        op.add_column('collection_emails', col)


def downgrade() -> None:
    audit_names = [
        'created_by', 'created_source',
        'updated_at', 'updated_by', 'updated_source',
        'deleted_at', 'deleted_by', 'deleted_source',
    ]

    for name in audit_names:
        op.drop_column('collection_phones', name)
    op.drop_column('collection_phones', 'is_active')

    for name in audit_names:
        op.drop_column('collection_addresses', name)
    for name in ('canton', 'parish', 'neighborhood', 'is_active'):
        op.drop_column('collection_addresses', name)

    for name in audit_names:
        op.drop_column('collection_emails', name)
