"""initial tables

Revision ID: 0001_init
Revises: 
Create Date: 2025-12-10
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ingest_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scan_type", sa.String(length=50), nullable=False),
        sa.Column("source_file", sa.String(length=255), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True, index=True),
        sa.UniqueConstraint("scan_type", "source_file", name="uq_ingest_source"),
    )

    op.create_table(
        "kingdoms",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("number", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=True),
        sa.Column("password_hash", sa.String(length=64), nullable=True),
        sa.Column("access_code", sa.String(length=20), nullable=True),
        sa.Column("kvk_active", sa.String(length=50), nullable=True),
        sa.Column("kvk_start", sa.DateTime(), nullable=True),
        sa.Column("kvk_end", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_kingdoms_id", "kingdoms", ["id"], unique=False)
    op.create_index("ix_kingdoms_number", "kingdoms", ["number"], unique=True)

    op.create_table(
        "alliances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tag", sa.String(length=10), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=True),
        sa.Column("kingdom_id", sa.Integer(), sa.ForeignKey("kingdoms.id")),
    )
    op.create_index("ix_alliances_id", "alliances", ["id"], unique=False)
    op.create_index("ix_alliances_tag", "alliances", ["tag"], unique=False)

    op.create_table(
        "governors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("governor_id", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=True),
        sa.Column("kingdom_id", sa.Integer(), sa.ForeignKey("kingdoms.id")),
        sa.Column("alliance_id", sa.Integer(), sa.ForeignKey("alliances.id"), nullable=True),
        sa.UniqueConstraint("governor_id", name="uq_governor_governor_id"),
    )
    op.create_index("ix_governors_id", "governors", ["id"], unique=False)
    op.create_index("ix_governors_governor_id", "governors", ["governor_id"], unique=False)
    op.create_index("ix_governors_name", "governors", ["name"], unique=False)

    op.create_table(
        "governor_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("governor_id_fk", sa.Integer(), sa.ForeignKey("governors.id")),
        sa.Column("ingest_file_id", sa.Integer(), sa.ForeignKey("ingest_files.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("power", sa.BigInteger(), default=0),
        sa.Column("kill_points", sa.BigInteger(), default=0),
        sa.Column("t1_kills", sa.BigInteger(), default=0),
        sa.Column("t2_kills", sa.BigInteger(), default=0),
        sa.Column("t3_kills", sa.BigInteger(), default=0),
        sa.Column("t4_kills", sa.BigInteger(), default=0),
        sa.Column("t5_kills", sa.BigInteger(), default=0),
        sa.Column("dead", sa.BigInteger(), default=0),
        sa.Column("rss_gathered", sa.BigInteger(), default=0),
        sa.Column("rss_assistance", sa.BigInteger(), default=0),
        sa.Column("helps", sa.BigInteger(), default=0),
    )
    op.create_index("ix_governor_snapshots_id", "governor_snapshots", ["id"], unique=False)
    # created_at index already handled if needed; avoid duplicate creation


def downgrade():
    op.drop_table("governor_snapshots")
    op.drop_table("governors")
    op.drop_table("alliances")
    op.drop_table("kingdoms")
    op.drop_table("ingest_files")
