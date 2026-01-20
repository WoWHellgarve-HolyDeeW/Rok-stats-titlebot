"""Add admin_users table

Revision ID: 0004_add_admin_users
Revises: 0003_add_access_code
Create Date: 2025-01-21

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0004_add_admin_users'
down_revision = '0003_add_access_code'
branch_labels = None
depends_on = None


def upgrade():
    # Create admin_users table
    op.create_table(
        'admin_users',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('username', sa.String(50), unique=True, nullable=False, index=True),
        sa.Column('password_hash', sa.String(64), nullable=False),
        sa.Column('is_super', sa.Boolean(), default=False),
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
    )


def downgrade():
    op.drop_table('admin_users')
