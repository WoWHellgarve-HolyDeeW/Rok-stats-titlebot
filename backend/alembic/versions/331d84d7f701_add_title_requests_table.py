"""add_title_requests_table

Revision ID: 331d84d7f701
Revises: 0004_add_admin_users
Create Date: 2025-12-10 15:05:36.392359

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '331d84d7f701'
down_revision: Union[str, None] = '0004_add_admin_users'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create title_requests table
    op.create_table('title_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kingdom_id', sa.Integer(), nullable=False),
        sa.Column('governor_id', sa.BigInteger(), nullable=False),
        sa.Column('governor_name', sa.String(length=100), nullable=False),
        sa.Column('alliance_tag', sa.String(length=10), nullable=True),
        sa.Column('title_type', sa.String(length=20), nullable=False),
        sa.Column('duration_hours', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('assigned_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('bot_message', sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(['kingdom_id'], ['kingdoms.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_title_requests_id'), 'title_requests', ['id'], unique=False)
    op.create_index(op.f('ix_title_requests_governor_id'), 'title_requests', ['governor_id'], unique=False)
    op.create_index(op.f('ix_title_requests_status'), 'title_requests', ['status'], unique=False)
    op.create_index(op.f('ix_title_requests_created_at'), 'title_requests', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_title_requests_created_at'), table_name='title_requests')
    op.drop_index(op.f('ix_title_requests_status'), table_name='title_requests')
    op.drop_index(op.f('ix_title_requests_governor_id'), table_name='title_requests')
    op.drop_index(op.f('ix_title_requests_id'), table_name='title_requests')
    op.drop_table('title_requests')
