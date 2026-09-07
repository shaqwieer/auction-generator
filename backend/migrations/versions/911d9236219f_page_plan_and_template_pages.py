"""Page plan and template pages.

Adds what the step-by-step builder needs and nothing else:

``template_pages``   what each page of a template is -- its role, whether it is
                     optional, and which other pages it is an alternative to.
``projects.page_plan``  the booklet a client assembled. Nullable on purpose: a
                     project without one composes exactly as it did before, so
                     nothing existing needs backfilling.

Revision ID: 911d9236219f
Revises: d4330e4cbc9c
Create Date: 2026-09-04 06:36:40.838850
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '911d9236219f'
down_revision = 'd4330e4cbc9c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('template_pages',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('template_id', sa.Uuid(), nullable=False),
    sa.Column('page_index', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=30), nullable=False),
    sa.Column('slot', sa.String(length=40), nullable=False),
    sa.Column('layout', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('is_optional', sa.Boolean(), nullable=False),
    sa.Column('default_on', sa.Boolean(), nullable=False),
    sa.Column('options', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['template_id'], ['templates.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('template_id', 'page_index', name='uq_template_page')
    )
    op.create_index('ix_template_pages', 'template_pages', ['template_id', 'position'], unique=False)
    op.add_column('projects', sa.Column('page_plan', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('projects', 'page_plan')
    op.drop_index('ix_template_pages', table_name='template_pages')
    op.drop_table('template_pages')
