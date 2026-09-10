"""a chip cut off the artwork

«معلومات الإيجار» leads to بيان عقود الإيجار, and the guide uses that page «في
حال وجود عقود إيجارية للأصل». A property with no leases has no such page, so
the chip that leads to it should not be printed -- but a chip is a bar, a
caption reversed out of it and an arrow beside it, all of it ink, and only the
link was ever a field. The link stopped being drawn and the chip stayed.

``part`` is that chip, cut whole onto a page of its own inside the background
PDF at build time and placed back with ``show_pdf_page`` when the page it leads
to is in the booklet. A cutting rather than a recording, because the bar is a
raster and the caption is type -- outlines on the برج drawing -- and neither is
something a redrawing would reproduce.

Revision ID: f2c8a5013b77
Revises: e5b71c904a12
Create Date: 2026-09-10 01:10:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'f2c8a5013b77'
down_revision = 'e5b71c904a12'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'template_fields',
        sa.Column('part', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('template_fields', 'part')
