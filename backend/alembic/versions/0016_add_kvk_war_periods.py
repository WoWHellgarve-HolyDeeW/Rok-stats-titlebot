"""add kvk war periods

Revision ID: 0016
Revises: 0015
Create Date: 2026-04-10 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("kingdoms", sa.Column("war1_start", sa.DateTime(), nullable=True))
    op.add_column("kingdoms", sa.Column("war1_end", sa.DateTime(), nullable=True))
    op.add_column("kingdoms", sa.Column("war2_start", sa.DateTime(), nullable=True))
    op.add_column("kingdoms", sa.Column("war2_end", sa.DateTime(), nullable=True))
    op.add_column("kingdoms", sa.Column("war3_start", sa.DateTime(), nullable=True))
    op.add_column("kingdoms", sa.Column("war3_end", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("kingdoms", "war3_end")
    op.drop_column("kingdoms", "war3_start")
    op.drop_column("kingdoms", "war2_end")
    op.drop_column("kingdoms", "war2_start")
    op.drop_column("kingdoms", "war1_end")
    op.drop_column("kingdoms", "war1_start")