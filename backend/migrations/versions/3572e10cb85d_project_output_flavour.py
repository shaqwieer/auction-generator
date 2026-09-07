"""project output flavour

Whether the booklet is for paper or for a screen. On paper a link has to be a
code somebody scans; on screen a code is useless and the chip should simply be
clickable. The pages are identical either way -- only which half of each link
chip gets drawn changes -- so this rides on the project and a regenerate repeats
the choice rather than asking again.

Revision ID: 3572e10cb85d
Revises: 67d6a182b4fd
Create Date: 2026-09-05 20:37:27.229625
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '3572e10cb85d'
down_revision = '67d6a182b4fd'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('output_flavour', sa.String(length=20), server_default='print', nullable=False))


def downgrade() -> None:
    op.drop_column('projects', 'output_flavour')
