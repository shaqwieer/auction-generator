"""The company a client prints for, and the mark it prints with.

The booklet used to carry one selling agent's logo baked into the designer's
artwork. It is a booklet printed for whoever is selling, so the mark comes out
of the artwork (``scripts/build_infath_templates.py``) and its place becomes two
fields: ``company_logo`` where a company has uploaded a mark, ``company_name``
where it has not. There is no fallback to the old branding — a company that
supplies neither prints nothing there.

The values are computed from this record at compose time rather than copied onto
a project, so a logo uploaded this afternoon appears on the booklet somebody
started this morning, in the preview and in the PDF alike.
"""

from __future__ import annotations

import io

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from PIL import Image
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.core.config import get_settings
from app.models import Asset, Client
from app.schemas import CompanyOut, CompanyUpdate
from app.services.storage import get_storage

router = APIRouter(prefix="/company", tags=["company"])
settings = get_settings()

#: What a mark may be. Vector would be better and the designer's own is vector,
#: but the renderer places rasters, and a logo supplied at print resolution is
#: the practical answer.
ALLOWED = {"image/png", "image/jpeg", "image/webp", "image/tiff"}

#: The filename a company's mark is stored under, per company. Fixed, so
#: replacing a logo replaces it rather than leaving the old one behind for a
#: booklet that still points at it.
LOGO_NAME = "company-logo"


def _company(db: DB, user) -> Client:
    if user.client_id is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "هذا الحساب غير مرتبط بشركة — تواصل مع فريق مطبعة.",
        )
    client = db.get(Client, user.client_id)
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "الشركة غير موجودة.")
    return client


@router.get("", response_model=CompanyOut)
def get_company(db: DB, user: CurrentUser) -> Client:
    return _company(db, user)


@router.api_route("", methods=["PATCH", "POST"], response_model=CompanyOut)
def update_company(payload: CompanyUpdate, db: DB, user: CurrentUser) -> Client:
    client = _company(db, user)
    name = payload.name.strip()
    if not name:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "اسم الشركة مطلوب."
        )
    client.name = name
    db.flush()
    return client


@router.get("/logo")
def get_logo(db: DB, user: CurrentUser) -> StreamingResponse:
    """The company's mark, for the sidebar and the profile screen."""
    client = _company(db, user)
    if not client.logo_filename:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "لا يوجد شعار.")
    asset = db.scalar(
        select(Asset).where(
            Asset.client_id == client.id, Asset.filename == client.logo_filename
        )
    )
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ملف الشعار غير موجود.")
    try:
        payload = get_storage().read(asset.stored_path)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "ملف الشعار غير موجود."
        ) from exc
    return StreamingResponse(
        io.BytesIO(payload),
        media_type=asset.content_type or "application/octet-stream",
        headers={"Cache-Control": "private, max-age=0, must-revalidate"},
    )


@router.post("/logo", response_model=CompanyOut)
async def upload_logo(
    db: DB, user: CurrentUser, file: UploadFile = File(...)
) -> Client:
    """Replace the company's mark.

    Stored under a fixed filename per company and re-saved in place, so the
    booklets already pointing at it pick up the new mark rather than keeping a
    reference to a file nobody replaced.
    """
    client = _company(db, user)
    payload = await file.read()
    if not payload:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "الملف فارغ.")
    if len(payload) > settings.max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"حجم الشعار يتجاوز {settings.max_upload_bytes // (1024 * 1024)} ميجابايت.",
        )
    try:
        with Image.open(io.BytesIO(payload)) as image:
            width, height = image.size
            content_type = Image.MIME.get(image.format or "", "")
    except Exception as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "تعذّرت قراءة الشعار."
        ) from exc
    if content_type not in ALLOWED:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "صيغة غير مدعومة — استخدم PNG أو JPEG أو WebP. يفضّل PNG بخلفية شفافة.",
        )

    suffix = (file.filename or "").rsplit(".", 1)
    name = f"{LOGO_NAME}.{suffix[-1].lower()}" if len(suffix) == 2 else LOGO_NAME
    key = get_storage().save(payload, folder=f"assets/{client.id}", filename=name)

    asset = db.scalar(
        select(Asset).where(Asset.client_id == client.id, Asset.filename == name)
    )
    if asset is None:
        asset = Asset(client_id=client.id, filename=name, role="logo")
        db.add(asset)
    asset.stored_path = key
    asset.content_type = content_type
    asset.width, asset.height = width, height
    asset.size_bytes = len(payload)
    asset.uploaded_by_id = user.id

    client.logo_filename = name
    db.flush()
    return client


@router.delete("/logo", response_model=CompanyOut)
def remove_logo(db: DB, user: CurrentUser) -> Client:
    """Print the company's name instead.

    The file stays in the library; only the booklet stops pointing at it.
    """
    client = _company(db, user)
    client.logo_filename = None
    db.flush()
    return client
