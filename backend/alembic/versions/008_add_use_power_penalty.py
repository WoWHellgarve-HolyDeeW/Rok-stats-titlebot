"""Add use_power_penalty column to DKP rules

Revision ID: 0008
Revises: 0006
Create Date: 2025-01-01

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0008'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    # Check if column already exists (in case of partial migration)
    conn = op.get_bind()
    result = conn.execute(sa.text("PRAGMA table_info(dkp_rules)"))
    columns = [row[1] for row in result]
    
    if 'use_power_penalty' not in columns:
        op.add_column('dkp_rules', sa.Column('use_power_penalty', sa.Boolean(), nullable=True, server_default='1'))
    
    # Update existing rules to have new default weights
    op.execute("UPDATE dkp_rules SET weight_t4 = 2, weight_t5 = 4, weight_dead = 6, use_power_penalty = 1")


def downgrade():
    op.drop_column('dkp_rules', 'use_power_penalty')
