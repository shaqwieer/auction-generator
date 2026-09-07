"""field clip outline

A photo frame is not always a rectangle. The lot page cuts a corner out of its
frame for the property number, and a photograph placed in the bounding box
printed a square corner straight over the badge. The shape is stored in 0..1 of
the field's own box, so it moves and scales with the box the way every other
piece of geometry here does.

Revision ID: 03c6e17156e2
Revises: 72468dca2a9a
Create Date: 2026-09-05 19:38:40.041136
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '03c6e17156e2'
down_revision = '72468dca2a9a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('template_fields', sa.Column('clip', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('template_fields', 'clip')
