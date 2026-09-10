"""a mark that belongs to its value

معلومات التواصل draws two telephone numbers, each under a mark of its own -- a
handset for رقم التواصل, the WhatsApp bubble for واتساب. The number was a field
and the mark beside it was ink on the page, so a seller with no WhatsApp printed
a WhatsApp icon with nothing beside it, and the remaining number stayed off to
one side of a space drawn for two.

``ornament`` is that mark, lifted off the artwork at build time as the
designer's own segments in the ink the file states them in, and drawn again only
when the value it belongs to is drawn. ``row_group`` names the centred row the
values sit in, so whatever is left of the row re-centres on the extent the
designer gave it -- and a full row moves not at all.

Revision ID: e5b71c904a12
Revises: c1f7a3e28b04
Create Date: 2026-09-09 22:05:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'e5b71c904a12'
down_revision = 'c1f7a3e28b04'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'template_fields',
        sa.Column('ornament', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        'template_fields',
        sa.Column(
            'row_group',
            sa.String(length=40),
            nullable=False,
            server_default='',
        ),
    )


def downgrade() -> None:
    op.drop_column('template_fields', 'row_group')
    op.drop_column('template_fields', 'ornament')
