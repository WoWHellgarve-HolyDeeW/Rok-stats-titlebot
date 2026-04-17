"""ingest hash and dkp rules

Revision ID: 0002_ingest_hash_dkp
Revises: 0001_init
Create Date: 2025-12-10
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_ingest_hash_dkp"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade():
    # ingest hash
    op.add_column("ingest_files", sa.Column("ingest_hash", sa.String(length=64), nullable=True))

    # SQLite cannot ALTER to add unique constraint; skip on SQLite
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.create_unique_constraint("uq_ingest_hash", "ingest_files", ["ingest_hash"])

    # dkp rules
    op.create_table(
        "dkp_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kingdom_id", sa.Integer(), sa.ForeignKey("kingdoms.id"), nullable=False),
        sa.Column("weight_t4", sa.Numeric(10, 2), nullable=True, server_default=sa.text("4")),
        sa.Column("weight_t5", sa.Numeric(10, 2), nullable=True, server_default=sa.text("10")),
        sa.Column("weight_dead", sa.Numeric(10, 2), nullable=True, server_default=sa.text("10")),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_dkp_rules_id", "dkp_rules", ["id"], unique=False)
    op.create_index("ix_dkp_rules_kingdom_id", "dkp_rules", ["kingdom_id"], unique=False)


def downgrade():
    op.drop_index("ix_dkp_rules_kingdom_id", table_name="dkp_rules")
    op.drop_index("ix_dkp_rules_id", table_name="dkp_rules")
    op.drop_table("dkp_rules")

    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.drop_constraint("uq_ingest_hash", "ingest_files", type_="unique")
    op.drop_column("ingest_files", "ingest_hash")
