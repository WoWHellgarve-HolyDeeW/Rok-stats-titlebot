"""Add power_tiers column to dkp_rules

Revision ID: 0006
Revises: 0005_add_dkp_goal
Create Date: 2026-01-19

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0006'
down_revision = '0005_add_dkp_goal'
branch_labels = None
depends_on = None


def upgrade():
    # Add power_tiers column (JSON string for power-based DKP goals)
    op.add_column('dkp_rules', sa.Column('power_tiers', sa.String(2000), nullable=True))


def downgrade():
    op.drop_column('dkp_rules', 'power_tiers')
