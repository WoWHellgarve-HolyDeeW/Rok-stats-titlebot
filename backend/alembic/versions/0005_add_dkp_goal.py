"""Add dkp_goal column to dkp_rules table

Revision ID: 0005_add_dkp_goal
Revises: 331d84d7f701
Create Date: 2025-01-13 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0005_add_dkp_goal'
down_revision = '331d84d7f701'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add dkp_goal column to dkp_rules table
    op.add_column('dkp_rules', sa.Column('dkp_goal', sa.BigInteger(), nullable=True, server_default='0'))


def downgrade() -> None:
    op.drop_column('dkp_rules', 'dkp_goal')
