"""Add Frida live-capture tables (frida_sessions, chat_messages, frida_players, frida_coordinates)

Revision ID: 0011
Revises: 0010
Create Date: 2025-01-25

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def _table_exists(name):
    bind = op.get_bind()
    insp = inspect(bind)
    return name in insp.get_table_names()


def upgrade():
    if not _table_exists("frida_sessions"):
        op.create_table(
            "frida_sessions",
            sa.Column("id", sa.Integer, primary_key=True, index=True),
            sa.Column("kingdom_id", sa.Integer, sa.ForeignKey("kingdoms.id"), nullable=True),
            sa.Column("session_id", sa.String(64), unique=True, nullable=False, index=True),
            sa.Column("started_at", sa.DateTime, nullable=True, index=True),
            sa.Column("ended_at", sa.DateTime, nullable=True),
            sa.Column("duration_sec", sa.Integer, nullable=True),
            sa.Column("chat_count", sa.Integer, default=0),
            sa.Column("player_count", sa.Integer, default=0),
            sa.Column("coord_count", sa.Integer, default=0),
            sa.Column("burst_count", sa.Integer, default=0),
        )

    if not _table_exists("chat_messages"):
        op.create_table(
            "chat_messages",
            sa.Column("id", sa.Integer, primary_key=True, index=True),
            sa.Column("session_fk", sa.Integer, sa.ForeignKey("frida_sessions.id"), nullable=True),
            sa.Column("kingdom_id", sa.Integer, sa.ForeignKey("kingdoms.id"), nullable=True),
            sa.Column("msg_hash", sa.String(64), nullable=True, index=True),
            sa.Column("channel", sa.String(30), nullable=True),
            sa.Column("server_id", sa.Integer, nullable=True),
            sa.Column("nickname", sa.String(100), nullable=True, index=True),
            sa.Column("alliance_tag", sa.String(10), nullable=True),
            sa.Column("governor_id", sa.BigInteger, nullable=True, index=True),
            sa.Column("text", sa.String(2000), nullable=True),
            sa.Column("share_type", sa.String(20), nullable=True),
            sa.Column("extra", sa.String(1000), nullable=True),
            sa.Column("x_coord", sa.Integer, nullable=True),
            sa.Column("y_coord", sa.Integer, nullable=True),
            sa.Column("location", sa.String(10), nullable=True),
            sa.Column("kvk_side", sa.Integer, nullable=True),
            sa.Column("captured_at", sa.DateTime, nullable=True, index=True),
        )

    if not _table_exists("frida_players"):
        op.create_table(
            "frida_players",
            sa.Column("id", sa.Integer, primary_key=True, index=True),
            sa.Column("session_fk", sa.Integer, sa.ForeignKey("frida_sessions.id"), nullable=True),
            sa.Column("kingdom_id", sa.Integer, sa.ForeignKey("kingdoms.id"), nullable=True),
            sa.Column("governor_id", sa.BigInteger, nullable=False, index=True),
            sa.Column("nickname", sa.String(100), nullable=True),
            sa.Column("alliance_tag", sa.String(10), nullable=True),
            sa.Column("vip_level", sa.Integer, nullable=True),
            sa.Column("is_online", sa.Boolean, nullable=True),
            sa.Column("power", sa.BigInteger, nullable=True),
            sa.Column("kill_points", sa.BigInteger, nullable=True),
            sa.Column("location", sa.String(10), nullable=True),
            sa.Column("source", sa.String(20), nullable=True),
            sa.Column("captured_at", sa.DateTime, nullable=True, index=True),
            sa.UniqueConstraint("session_fk", "governor_id", name="uq_frida_player_session"),
        )

    if not _table_exists("frida_coordinates"):
        op.create_table(
            "frida_coordinates",
            sa.Column("id", sa.Integer, primary_key=True, index=True),
            sa.Column("session_fk", sa.Integer, sa.ForeignKey("frida_sessions.id"), nullable=True),
            sa.Column("kingdom_id", sa.Integer, sa.ForeignKey("kingdoms.id"), nullable=True),
            sa.Column("x_coord", sa.Integer, nullable=False),
            sa.Column("y_coord", sa.Integer, nullable=False),
            sa.Column("shared_by", sa.String(100), nullable=True),
            sa.Column("target_type", sa.String(20), nullable=True),
            sa.Column("location", sa.String(10), nullable=True),
            sa.Column("captured_at", sa.DateTime, nullable=True, index=True),
        )


def downgrade():
    op.drop_table("frida_coordinates")
    op.drop_table("frida_players")
    op.drop_table("chat_messages")
    op.drop_table("frida_sessions")
