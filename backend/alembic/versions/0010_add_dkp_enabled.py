"""Add dkp_enabled column to dkp_rules

Revision ID: 0010
Revises: 0009
Create Date: 2026-01-20

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade():
    # Check if column already exists
    conn = op.get_bind()
    result = conn.execute(sa.text("PRAGMA table_info(dkp_rules)"))
    columns = [row[1] for row in result]
    
    if 'dkp_enabled' not in columns:
        op.add_column('dkp_rules', sa.Column('dkp_enabled', sa.Boolean(), nullable=True, server_default='1'))
    
    # Set all existing rules to enabled
    op.execute("UPDATE dkp_rules SET dkp_enabled = 1 WHERE dkp_enabled IS NULL")


def downgrade():
    op.drop_column('dkp_rules', 'dkp_enabled')
