"""fixed wording around a field's value, and what prints when it is empty

خطوات المشاركة is the guide's own sentence with one changing phrase inside it:
«إختيار مزاد ( أعيان حائل ) والدخول للمشاركة» names this auction, «تسجيل الدخول
في منصة مباشر للمزادات» names this platform, and the rest is the design. Asking
the client for the whole caption invited them to mistype the design; asking for
nothing left the page blank, because baking clears whatever a field will draw
over. So a field can carry the fixed halves itself and ask only for the middle.

``default_value`` is what prints when nothing has been typed, and ``{key}``
inside it takes the value from elsewhere in the booklet -- the auction and the
platform are already named on the auction-info page, and naming them again here
would be asking twice for one fact.

Revision ID: c1f7a3e28b04
Revises: 78ba02601d48
Create Date: 2026-09-07 16:45:03.114927
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'c1f7a3e28b04'
down_revision = '78ba02601d48'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'template_fields',
        sa.Column('prefix', sa.Text(), server_default='', nullable=False),
    )
    op.add_column(
        'template_fields',
        sa.Column('suffix', sa.Text(), server_default='', nullable=False),
    )
    op.add_column(
        'template_fields',
        sa.Column('default_value', sa.Text(), server_default='', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('template_fields', 'default_value')
    op.drop_column('template_fields', 'suffix')
    op.drop_column('template_fields', 'prefix')
