"""Merge multiple heads

Revision ID: 0009
Revises: 0008, 005_name_history
Create Date: 2025-01-20

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0009'
down_revision = ('0008', '005_name_history')
branch_labels = None
depends_on = None


def upgrade():
    # This is a merge migration - no operations needed
    pass


def downgrade():
    # No downgrade needed for merge
    pass
