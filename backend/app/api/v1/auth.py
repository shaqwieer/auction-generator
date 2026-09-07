"""Sign in, refresh, and who-am-I."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from jose import JWTError
from sqlalchemy import select

from app.api.deps import DB, Admin, CurrentUser
from app.core.config import get_settings
from app.core.db import utcnow
from app.core.security import create_token, decode_token, hash_password, verify_password
from app.models import User
from app.schemas import LoginRequest, RefreshRequest, TokenPair, UserCreate, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


def _tokens(user: User) -> TokenPair:
    claims = {"role": user.role, "client_id": str(user.client_id or "")}
    return TokenPair(
        access_token=create_token(str(user.id), "access", **claims),
        refresh_token=create_token(str(user.id), "refresh"),
        expires_in=settings.access_token_minutes * 60,
    )


@router.post("/login", response_model=TokenPair)
def login(payload: LoginRequest, db: DB) -> TokenPair:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    # Same message either way: never reveal which half was wrong.
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "البريد الإلكتروني أو كلمة المرور غير صحيحة."
        )
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "الحساب موقوف.")
    user.last_seen_at = utcnow()
    return _tokens(user)


@router.post("/refresh", response_model=TokenPair)
def refresh(payload: RefreshRequest, db: DB) -> TokenPair:
    try:
        claims = decode_token(payload.refresh_token, expect="refresh")
        user_id = uuid.UUID(claims["sub"])
    except (JWTError, KeyError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "رمز التحديث غير صالح."
        ) from exc

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "الحساب غير مفعّل.")
    return _tokens(user)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user


@router.get("/users", response_model=list[UserOut])
def list_users(db: DB, _: Admin) -> list[User]:
    return list(db.scalars(select(User).order_by(User.created_at)).all())


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, db: DB, _: Admin) -> User:
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "البريد الإلكتروني مستخدم بالفعل.")
    # A client account without a company has no name and no mark to print, so
    # every booklet it makes would come out unbranded. Staff accounts make
    # booklets on somebody else's behalf and pick the company per project.
    if payload.role == "client" and payload.client_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "حساب العميل يحتاج إلى شركة — اسم الشركة هو ما يُطبع على الكتيّب.",
        )
    user = User(
        email=email,
        name=payload.name,
        password_hash=hash_password(payload.password),
        role=payload.role,
        client_id=payload.client_id,
    )
    db.add(user)
    db.flush()
    return user
