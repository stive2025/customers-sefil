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


def _add_if_not_exists(table: str, col_name: str, col_def: str) -> None:
    op.execute(
        f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col_name} {col_def}"
    )


def upgrade() -> None:
    # ── collection_phones ─────────────────────────────────────────────────────
    _add_if_not_exists('collection_phones', 'is_active',      'BOOLEAN NOT NULL DEFAULT TRUE')
    _add_if_not_exists('collection_phones', 'created_by',     'VARCHAR(100)')
    _add_if_not_exists('collection_phones', 'created_source', 'VARCHAR(50)')
    _add_if_not_exists('collection_phones', 'updated_at',     'TIMESTAMPTZ')
    _add_if_not_exists('collection_phones', 'updated_by',     'VARCHAR(100)')
    _add_if_not_exists('collection_phones', 'updated_source', 'VARCHAR(50)')
    _add_if_not_exists('collection_phones', 'deleted_at',     'TIMESTAMPTZ')
    _add_if_not_exists('collection_phones', 'deleted_by',     'VARCHAR(100)')
    _add_if_not_exists('collection_phones', 'deleted_source', 'VARCHAR(50)')

    # ── collection_addresses ──────────────────────────────────────────────────
    _add_if_not_exists('collection_addresses', 'is_active',      'BOOLEAN NOT NULL DEFAULT TRUE')
    _add_if_not_exists('collection_addresses', 'canton',         'VARCHAR(100)')
    _add_if_not_exists('collection_addresses', 'parish',         'VARCHAR(100)')
    _add_if_not_exists('collection_addresses', 'neighborhood',   'VARCHAR(100)')
    _add_if_not_exists('collection_addresses', 'created_by',     'VARCHAR(100)')
    _add_if_not_exists('collection_addresses', 'created_source', 'VARCHAR(50)')
    _add_if_not_exists('collection_addresses', 'updated_at',     'TIMESTAMPTZ')
    _add_if_not_exists('collection_addresses', 'updated_by',     'VARCHAR(100)')
    _add_if_not_exists('collection_addresses', 'updated_source', 'VARCHAR(50)')
    _add_if_not_exists('collection_addresses', 'deleted_at',     'TIMESTAMPTZ')
    _add_if_not_exists('collection_addresses', 'deleted_by',     'VARCHAR(100)')
    _add_if_not_exists('collection_addresses', 'deleted_source', 'VARCHAR(50)')

    # ── collection_emails ─────────────────────────────────────────────────────
    # is_active already exists on this table
    _add_if_not_exists('collection_emails', 'created_by',     'VARCHAR(100)')
    _add_if_not_exists('collection_emails', 'created_source', 'VARCHAR(50)')
    _add_if_not_exists('collection_emails', 'updated_at',     'TIMESTAMPTZ')
    _add_if_not_exists('collection_emails', 'updated_by',     'VARCHAR(100)')
    _add_if_not_exists('collection_emails', 'updated_source', 'VARCHAR(50)')
    _add_if_not_exists('collection_emails', 'deleted_at',     'TIMESTAMPTZ')
    _add_if_not_exists('collection_emails', 'deleted_by',     'VARCHAR(100)')
    _add_if_not_exists('collection_emails', 'deleted_source', 'VARCHAR(50)')


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
