"""lease table colourway

بيان عقود الإيجار is drawn in the brand's navy. بيان العقارات proves both navy
and teal are the brand's, so the other colour is offered by rewriting the colour
the page itself asks for -- one choice for the whole booklet, so its lease pages
cannot disagree with each other.

Revision ID: 78ba02601d48
Revises: ad6ab924b2c2
Create Date: 2026-09-06 10:40:12.877786
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '78ba02601d48'
down_revision = 'ad6ab924b2c2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('lease_colourway', sa.String(length=20), server_default='blue', nullable=False))


def downgrade() -> None:
    op.drop_column('projects', 'lease_colourway')
