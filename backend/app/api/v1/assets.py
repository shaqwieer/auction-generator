"""The client asset library: upload photographs once, reuse them across booklets."""

from __future__ import annotations

import io
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from PIL import Image
from sqlalchemy import select

from app.api.deps import DB, CurrentUser, owned_or_403, scope_client_id
from app.api.http import content_disposition
from app.core.config import get_settings
from app.models import Asset
from app.schemas import AssetWithDpi
from app.services.storage import get_storage

router = APIRouter(prefix="/assets", tags=["assets"])
settings = get_settings()

A4_WIDTH_PT = 595.28
ALLOWED = {"image/jpeg", "image/png", "image/webp", "image/tiff"}


def _with_dpi(asset: Asset) -> AssetWithDpi:
    dpi = asset.dpi_at(A4_WIDTH_PT)
    return AssetWithDpi.model_validate(asset).model_copy(
        update={"print_dpi_a4": dpi, "below_min_dpi": dpi < settings.min_image_dpi}
    )


@router.get("", response_model=list[AssetWithDpi])
def list_assets(
    db: DB,
    user: CurrentUser,
    client_id: uuid.UUID | None = None,
    role: str | None = Query(None),
) -> list[AssetWithDpi]:
    owner = scope_client_id(user, client_id) if not user.is_staff else client_id
    query = select(Asset)
    if owner is not None:
        query = query.where(Asset.client_id == owner)
    if role:
        query = query.where(Asset.role == role)
    rows = db.scalars(query.order_by(Asset.created_at.desc())).all()
    return [_with_dpi(row) for row in rows]


@router.post("", response_model=AssetWithDpi, status_code=status.HTTP_201_CREATED)
async def upload_asset(
    db: DB,
    user: CurrentUser,
    file: UploadFile = File(...),
    role: str = Form("extra"),
    client_id: uuid.UUID | None = Form(None),
) -> AssetWithDpi:
    """Store an image and record its true pixel size.

    The dimensions matter: the library screen warns about anything that would
    print below 300 dpi at its placed size, and that check needs real numbers
    rather than whatever the uploader believes.
    """
    owner = scope_client_id(user, client_id)
    payload = await file.read()
    if not payload:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "الملف فارغ.")
    if len(payload) > settings.max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"حجم الصورة يتجاوز {settings.max_upload_bytes // (1024 * 1024)} ميجابايت.",
        )

    try:
        with Image.open(io.BytesIO(payload)) as image:
            width, height = image.size
            content_type = Image.MIME.get(image.format or "", "application/octet-stream")
    except Exception as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "تعذّرت قراءة الصورة."
        ) from exc

    if content_type not in ALLOWED:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "صيغة غير مدعومة — استخدم JPEG أو PNG أو WebP أو TIFF.",
        )

    name = file.filename or "image"
    existing = db.scalar(
        select(Asset).where(Asset.client_id == owner, Asset.filename == name)
    )
    if existing is not None:
        # Records refer to a photograph by filename, so a duplicate name would
        # make the reference ambiguous.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"يوجد أصل بنفس الاسم «{name}» — أعد تسمية الملف أو احذف القديم.",
        )

    key = get_storage().save(payload, folder=f"assets/{owner}", filename=name)
    asset = Asset(
        client_id=owner,
        filename=name,
        stored_path=key,
        content_type=content_type,
        width=width,
        height=height,
        size_bytes=len(payload),
        role=role,
        uploaded_by_id=user.id,
    )
    db.add(asset)
    db.flush()
    return _with_dpi(asset)


@router.get("/{asset_id}/file")
def download_asset(asset_id: uuid.UUID, db: DB, user: CurrentUser) -> StreamingResponse:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "الأصل غير موجود.")
    owned_or_403(user, asset.client_id)
    payload = get_storage().read(asset.stored_path)
    return StreamingResponse(
        io.BytesIO(payload),
        media_type=asset.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": content_disposition(asset.filename, inline=True)
        },
    )


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_asset(asset_id: uuid.UUID, db: DB, user: CurrentUser) -> None:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "الأصل غير موجود.")
    owned_or_403(user, asset.client_id)
    get_storage().delete(asset.stored_path)
    db.delete(asset)
