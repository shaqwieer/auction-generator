"""company branding: client logo, field preserve_aspect

The booklet used to carry one company's mark baked into the artwork. It is a
booklet printed for whoever is selling, so the mark comes out of the artwork and
becomes a field: a client's own logo where they have uploaded one, their name
set in the same colour and place where they have not.

``preserve_aspect`` is what tells the renderer a logo apart from a photograph.
A photograph is cropped to fill the frame the designer drew, which is what a
frame is for; a logo cropped to a frame is a broken logo and one stretched to it
is worse.

Revision ID: 72468dca2a9a
Revises: 911d9236219f
Create Date: 2026-09-05 16:48:53.447791
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '72468dca2a9a'
down_revision = '911d9236219f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('clients', sa.Column('logo_filename', sa.String(length=255), nullable=True))
    op.add_column('template_fields', sa.Column('preserve_aspect', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    op.drop_column('template_fields', 'preserve_aspect')
    op.drop_column('clients', 'logo_filename')
