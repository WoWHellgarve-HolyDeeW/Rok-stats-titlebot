"""Add acclaims and highest_acclaims to governor_snapshots

Revision ID: 0012
Revises: 0011
Create Date: 2025-01-25

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def _col_exists(table, column):
    bind = op.get_bind()
    insp = inspect(bind)
    cols = [c['name'] for c in insp.get_columns(table)]
    return column in cols


def upgrade():
    if not _col_exists('governor_snapshots', 'acclaims'):
        op.add_column('governor_snapshots',
                       sa.Column('acclaims', sa.BigInteger, default=0, server_default='0'))
    if not _col_exists('governor_snapshots', 'highest_acclaims'):
        op.add_column('governor_snapshots',
                       sa.Column('highest_acclaims', sa.BigInteger, default=0, server_default='0'))


def downgrade():
    op.drop_column('governor_snapshots', 'highest_acclaims')
    op.drop_column('governor_snapshots', 'acclaims')
