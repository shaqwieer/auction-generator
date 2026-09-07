"""shapes drawn over a photo frame

The property number's badge and the closing-time chip are printed across the
bottom corners of the photograph. A photograph is placed on top of the baked
artwork, so unless it is masked out of them it covers them -- which is how
«تغلق المزايدة على العقار» came out as half a photograph.

Revision ID: ad6ab924b2c2
Revises: 3572e10cb85d
Create Date: 2026-09-05 23:38:02.496852
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'ad6ab924b2c2'
down_revision = '3572e10cb85d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('template_fields', sa.Column('clip_holes', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('template_fields', 'clip_holes')
