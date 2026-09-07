"""The permanent addresses a booklet's printed codes lead through.

A code printed on paper cannot be edited. So it never carries a destination:
it carries an address this system owns, and a row here says where that address
redirects to today. Move the survey file, change the row — the booklets already
printed keep working, which is the whole reason the indirection exists.

The code is minted once per slot per property and reused for ever after, so
regenerating a booklet reprints the codes already in circulation instead of
minting new ones and orphaning the paper.
"""

from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Project, ShortLink
from app.rendering.base import PageInstance

#: Every code the booklet prints, and the addresses behind them. Four belong to
#: a property — the survey, the lease, the extra photographs, the map — and two
#: belong to the auction itself: the platform to bid on, and where it is held.
#: The build script names the fields; this is the same list, for the values.
LINK_KEYS = (
    "link_survey",
    "link_photos",
    "link_map",
    "platform_link",
    "venue_link",
)

#: Keeps the minted address out of the builder: a client supplies where a code
#: should lead, never the code itself.
QR_PREFIX = "__qr_"

CODE_BYTES = 5


def short_url(code: str) -> str:
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}/r/{code}"


def _mint(session: Session, project: Project, row: int | None, key: str) -> ShortLink:
    link = session.scalar(
        select(ShortLink).where(
            ShortLink.project_id == project.id,
            ShortLink.row_index == row,
            ShortLink.field_key == key,
        )
    )
    if link is None:
        link = ShortLink(
            project_id=project.id,
            row_index=row,
            field_key=key,
            code=secrets.token_urlsafe(CODE_BYTES)[:8],
        )
        session.add(link)
    return link


def apply_codes(
    session: Session, project: Project, pages: list[PageInstance]
) -> None:
    """Give every page the codes for the addresses it carries.

    Called after composing and before rendering, because the code belongs to the
    property rather than to the page, and the page is where it gets drawn.
    """
    for page in pages:
        for key in LINK_KEYS:
            target = str(page.values.get(key, "") or "").strip()
            if not target:
                continue
            link = _mint(session, project, page.record_index, key)
            link.target = target
            page.values[f"{QR_PREFIX}{key}"] = short_url(link.code)
    session.flush()


def resolve(session: Session, code: str) -> str | None:
    link = session.scalar(select(ShortLink).where(ShortLink.code == code))
    return (link.target or None) if link else None
