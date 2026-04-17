"""add title request queue indexes

Revision ID: 0015
Revises: 0014
Create Date: 2026-04-08 00:00:00

"""
from typing import Sequence, Union

from alembic import op


revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_title_requests_queue_lookup",
        "title_requests",
        ["kingdom_id", "status", "priority", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_title_requests_stale_assigned",
        "title_requests",
        ["kingdom_id", "status", "assigned_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_title_requests_stale_assigned", table_name="title_requests")
    op.drop_index("ix_title_requests_queue_lookup", table_name="title_requests")