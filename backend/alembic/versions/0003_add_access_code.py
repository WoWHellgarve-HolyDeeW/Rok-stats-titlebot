"""Add access_code to kingdoms

Revision ID: 0003_add_access_code
Revises: 0002_ingest_hash_dkp
Create Date: 2025-01-21

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '0003_add_access_code'
down_revision = '0002_ingest_hash_dkp'
branch_labels = None
depends_on = None


def upgrade():
    # Add access_code column to kingdoms table if missing
    bind = op.get_bind()
    inspector = inspect(bind)
    cols = [c['name'] for c in inspector.get_columns('kingdoms')]
    if 'access_code' in cols:
        return
    # SQLite cannot add UNIQUE via ALTER; skip unique constraint there
    if bind.dialect.name == "sqlite":
        op.add_column('kingdoms', sa.Column('access_code', sa.String(20), nullable=True))
    else:
        op.add_column('kingdoms', sa.Column('access_code', sa.String(20), unique=True, nullable=True))


def downgrade():
    op.drop_column('kingdoms', 'access_code')
