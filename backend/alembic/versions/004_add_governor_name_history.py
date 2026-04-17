"""Add governor_name_history table

Revision ID: 005_name_history
Revises: 331d84d7f701
Create Date: 2025-12-12

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '005_name_history'
down_revision = '331d84d7f701'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'governor_name_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('governor_id_fk', sa.Integer(), nullable=False),
        sa.Column('governor_id', sa.BigInteger(), nullable=False),
        sa.Column('old_name', sa.String(100), nullable=False),
        sa.Column('new_name', sa.String(100), nullable=False),
        sa.Column('changed_at', sa.DateTime(), nullable=True),
        sa.Column('ingest_file_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['governor_id_fk'], ['governors.id'], ),
        sa.ForeignKeyConstraint(['ingest_file_id'], ['ingest_files.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_governor_name_history_id'), 'governor_name_history', ['id'], unique=False)
    op.create_index(op.f('ix_governor_name_history_governor_id_fk'), 'governor_name_history', ['governor_id_fk'], unique=False)
    op.create_index(op.f('ix_governor_name_history_governor_id'), 'governor_name_history', ['governor_id'], unique=False)
    op.create_index(op.f('ix_governor_name_history_changed_at'), 'governor_name_history', ['changed_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_governor_name_history_changed_at'), table_name='governor_name_history')
    op.drop_index(op.f('ix_governor_name_history_governor_id'), table_name='governor_name_history')
    op.drop_index(op.f('ix_governor_name_history_governor_id_fk'), table_name='governor_name_history')
    op.drop_index(op.f('ix_governor_name_history_id'), table_name='governor_name_history')
    op.drop_table('governor_name_history')
