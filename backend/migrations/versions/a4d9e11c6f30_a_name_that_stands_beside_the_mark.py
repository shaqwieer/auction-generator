"""a name that stands beside the mark

«يكون اسم المزاد على سطرين إذا تم إستخدام الأيقونة يمين الاسم» -- the guide
sets the auction's name on two lines wherever the mark stands to the right of
it, which on this template is every cover. The name was drawn on one line
whatever the box it was given, because a client types «مزاد أعيان حائل» as one
line and nothing asked for it to be broken.

``two_lines`` is that rule: the value is set with its first word on a line of
its own and the rest beneath, which is how the designer's own two samples break
-- «مزاد» over «أعيان حائل» and «مـزاد» over «درة البحر». A break rather than a
narrower box, because narrowing until the text wraps puts the break wherever
the line happens to run out and the box a cover gives its title is the
designer's, not ours to shrink.

Revision ID: a4d9e11c6f30
Revises: f2c8a5013b77
Create Date: 2026-09-10 18:20:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'a4d9e11c6f30'
down_revision = 'f2c8a5013b77'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'template_fields',
        sa.Column(
            'two_lines',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column('template_fields', 'two_lines')
