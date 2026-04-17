"""Add kvk_contribution and civilization columns to governor_snapshots and governor_profiles

Revision ID: 0013
Revises: 0012
Create Date: 2026-03-05

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def _col_exists(table, column):
    bind = op.get_bind()
    insp = inspect(bind)
    try:
        cols = [c['name'] for c in insp.get_columns(table)]
        return column in cols
    except Exception:
        return False


def _table_exists(name):
    bind = op.get_bind()
    insp = inspect(bind)
    return name in insp.get_table_names()


def upgrade():
    # governor_snapshots — add kvk_contribution and civilization
    if not _col_exists('governor_snapshots', 'kvk_contribution'):
        op.add_column('governor_snapshots',
                       sa.Column('kvk_contribution', sa.BigInteger, default=0, server_default='0'))
    if not _col_exists('governor_snapshots', 'civilization'):
        op.add_column('governor_snapshots',
                       sa.Column('civilization', sa.String(30), nullable=True))

    # governor_profiles — add kvk_contribution (civilization already exists)
    if _table_exists('governor_profiles'):
        if not _col_exists('governor_profiles', 'kvk_contribution'):
            op.add_column('governor_profiles',
                           sa.Column('kvk_contribution', sa.BigInteger, nullable=True))

    # linked_accounts — create if not exists (was in models.py but may not have migration)
    if not _table_exists('linked_accounts'):
        op.create_table(
            'linked_accounts',
            sa.Column('id', sa.Integer, primary_key=True, index=True),
            sa.Column('main_governor_id', sa.BigInteger, nullable=False, index=True),
            sa.Column('main_governor_name', sa.String(100), nullable=False),
            sa.Column('linked_governor_id', sa.BigInteger, nullable=False, index=True),
            sa.Column('linked_governor_name', sa.String(100), nullable=False),
            sa.Column('kingdom_id', sa.Integer, sa.ForeignKey('kingdoms.id'), nullable=True),
            sa.Column('created_at', sa.DateTime, nullable=True),
            sa.Column('verified', sa.Boolean, default=False),
            sa.UniqueConstraint('main_governor_id', 'linked_governor_id', name='uq_linked_accounts'),
        )

    # player_locations — create if not exists
    if not _table_exists('player_locations'):
        op.create_table(
            'player_locations',
            sa.Column('id', sa.Integer, primary_key=True, index=True),
            sa.Column('governor_id', sa.BigInteger, nullable=False, index=True),
            sa.Column('governor_name', sa.String(100), nullable=True),
            sa.Column('kingdom_id', sa.Integer, sa.ForeignKey('kingdoms.id'), nullable=True),
            sa.Column('x_coord', sa.Integer, nullable=False),
            sa.Column('y_coord', sa.Integer, nullable=False),
            sa.Column('shield_type', sa.String(20), nullable=True),
            sa.Column('shield_expires_at', sa.DateTime, nullable=True),
            sa.Column('updated_at', sa.DateTime, nullable=True),
            sa.UniqueConstraint('governor_id', 'kingdom_id', name='uq_player_location'),
        )

    # governor_profiles — create if not exists (full table)
    if not _table_exists('governor_profiles'):
        op.create_table(
            'governor_profiles',
            sa.Column('id', sa.Integer, primary_key=True, index=True),
            sa.Column('kingdom_id', sa.Integer, sa.ForeignKey('kingdoms.id'), nullable=True),
            sa.Column('governor_id', sa.BigInteger, nullable=False, index=True),
            sa.Column('governor_name', sa.String(100), nullable=True),
            sa.Column('alliance_tag', sa.String(10), nullable=True),
            sa.Column('power', sa.BigInteger, nullable=True),
            sa.Column('kill_points', sa.BigInteger, nullable=True),
            sa.Column('t1_kills', sa.BigInteger, nullable=True),
            sa.Column('t2_kills', sa.BigInteger, nullable=True),
            sa.Column('t3_kills', sa.BigInteger, nullable=True),
            sa.Column('t4_kills', sa.BigInteger, nullable=True),
            sa.Column('t5_kills', sa.BigInteger, nullable=True),
            sa.Column('t1_deaths', sa.BigInteger, nullable=True),
            sa.Column('t2_deaths', sa.BigInteger, nullable=True),
            sa.Column('t3_deaths', sa.BigInteger, nullable=True),
            sa.Column('t4_deaths', sa.BigInteger, nullable=True),
            sa.Column('t5_deaths', sa.BigInteger, nullable=True),
            sa.Column('dead', sa.BigInteger, nullable=True),
            sa.Column('victories', sa.BigInteger, nullable=True),
            sa.Column('defeats', sa.BigInteger, nullable=True),
            sa.Column('scout_times', sa.BigInteger, nullable=True),
            sa.Column('healed', sa.BigInteger, nullable=True),
            sa.Column('rss_gathered', sa.BigInteger, nullable=True),
            sa.Column('rss_assistance', sa.BigInteger, nullable=True),
            sa.Column('helps', sa.BigInteger, nullable=True),
            sa.Column('acclaims', sa.BigInteger, nullable=True),
            sa.Column('highest_acclaims', sa.BigInteger, nullable=True),
            sa.Column('civilization', sa.String(30), nullable=True),
            sa.Column('vip_level', sa.Integer, nullable=True),
            sa.Column('city_hall_level', sa.Integer, nullable=True),
            sa.Column('commander_count', sa.Integer, nullable=True),
            sa.Column('highest_power', sa.BigInteger, nullable=True),
            sa.Column('kvk_contribution', sa.BigInteger, nullable=True),
            sa.Column('shield_active', sa.Boolean, nullable=True),
            sa.Column('shield_type', sa.String(20), nullable=True),
            sa.Column('shield_remaining_sec', sa.Integer, nullable=True),
            sa.Column('shield_expires_at', sa.DateTime, nullable=True),
            sa.Column('linked_characters', sa.String(2000), nullable=True),
            sa.Column('is_online', sa.Boolean, nullable=True),
            sa.Column('source', sa.String(20), nullable=True),
            sa.Column('captured_at', sa.DateTime, nullable=True, index=True),
            sa.Column('updated_at', sa.DateTime, nullable=True),
            sa.UniqueConstraint('governor_id', 'kingdom_id', name='uq_governor_profile'),
        )

    # ranking tables — create if not exist
    if not _table_exists('ranking_snapshots'):
        op.create_table(
            'ranking_snapshots',
            sa.Column('id', sa.Integer, primary_key=True, index=True),
            sa.Column('kingdom_id', sa.Integer, sa.ForeignKey('kingdoms.id'), nullable=True),
            sa.Column('ranking_type', sa.String(30), nullable=False, index=True),
            sa.Column('total_governors', sa.Integer, nullable=True),
            sa.Column('source', sa.String(20), server_default='frida'),
            sa.Column('captured_at', sa.DateTime, nullable=True, index=True),
        )

    if not _table_exists('ranking_entries'):
        op.create_table(
            'ranking_entries',
            sa.Column('id', sa.Integer, primary_key=True, index=True),
            sa.Column('snapshot_id', sa.Integer, sa.ForeignKey('ranking_snapshots.id'), nullable=False, index=True),
            sa.Column('rank', sa.Integer, nullable=False),
            sa.Column('governor_id', sa.BigInteger, nullable=False, index=True),
            sa.Column('governor_name', sa.String(100), nullable=True),
            sa.Column('alliance_tag', sa.String(10), nullable=True),
            sa.Column('value', sa.BigInteger, nullable=True),
            sa.Column('power', sa.BigInteger, nullable=True),
            sa.Column('kill_points', sa.BigInteger, nullable=True),
            sa.Column('vip_level', sa.Integer, nullable=True),
        )


def downgrade():
    # Drop new columns
    if _col_exists('governor_snapshots', 'kvk_contribution'):
        op.drop_column('governor_snapshots', 'kvk_contribution')
    if _col_exists('governor_snapshots', 'civilization'):
        op.drop_column('governor_snapshots', 'civilization')
    if _table_exists('governor_profiles') and _col_exists('governor_profiles', 'kvk_contribution'):
        op.drop_column('governor_profiles', 'kvk_contribution')
