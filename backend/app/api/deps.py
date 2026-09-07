"""Request dependencies: session, current user, role guards."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.security import decode_token
from app.models import Client, Role, User

_bearer = HTTPBearer(auto_error=False)


def get_db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


DB = Annotated[Session, Depends(get_db)]


def current_user(
    db: DB,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "مطلوب تسجيل الدخول.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(credentials.credentials)
        user_id = uuid.UUID(payload["sub"])
    except (JWTError, KeyError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "الجلسة منتهية أو غير صالحة.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "الحساب غير مفعّل.")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_staff(user: CurrentUser) -> User:
    if not user.is_staff:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "هذه الصفحة للمشرفين فقط.")
    return user


def require_admin(user: CurrentUser) -> User:
    if user.role != Role.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "هذا الإجراء لمدير النظام فقط.")
    return user


Staff = Annotated[User, Depends(require_staff)]
Admin = Annotated[User, Depends(require_admin)]


def scope_client_id(user: User, requested: uuid.UUID | None) -> uuid.UUID:
    """Staff may act for any client; a client user only for their own."""
    if user.is_staff:
        if requested is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "يجب تحديد العميل."
            )
        return requested
    if user.client_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "الحساب غير مرتبط بعميل.")
    if requested is not None and requested != user.client_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "لا تملك صلاحية على هذا العميل.")
    return user.client_id


def owned_or_403(user: User, client_id: uuid.UUID) -> None:
    if user.is_staff:
        return
    if user.client_id != client_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "غير موجود.")


def get_client_or_404(db: Session, client_id: uuid.UUID) -> Client:
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "العميل غير موجود.")
    return client
