"""short links for printed codes

A code printed in a booklet cannot be edited, so it must not carry a
destination. It carries an address this system owns, and a row here says where
that address redirects to today — move the file, change the row, and the paper
already in circulation keeps working.

Unique per (project, property, slot), so regenerating a booklet reprints the
codes already out there rather than minting new ones and orphaning them.

Revision ID: 67d6a182b4fd
Revises: 03c6e17156e2
Create Date: 2026-09-05 20:30:09.033896
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '67d6a182b4fd'
down_revision = '03c6e17156e2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('short_links',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('code', sa.String(length=16), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('row_index', sa.Integer(), nullable=True),
    sa.Column('field_key', sa.String(length=80), nullable=False),
    sa.Column('target', sa.String(length=2000), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code'),
    sa.UniqueConstraint('project_id', 'row_index', 'field_key', name='uq_short_link_slot')
    )


def downgrade() -> None:
    op.drop_table('short_links')
