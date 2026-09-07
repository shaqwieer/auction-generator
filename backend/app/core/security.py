"""Password hashing and JWT issuing."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Literal

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings
from app.core.db import utcnow

settings = get_settings()
_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

TokenKind = Literal["access", "refresh"]


def hash_password(raw: str) -> str:
    return _pwd.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return _pwd.verify(raw, hashed)
    except ValueError:
        return False


def create_token(subject: str, kind: TokenKind = "access", **claims: Any) -> str:
    lifetime = (
        timedelta(minutes=settings.access_token_minutes)
        if kind == "access"
        else timedelta(days=settings.refresh_token_days)
    )
    now = utcnow()
    payload: dict[str, Any] = {
        "sub": subject,
        "kind": kind,
        "iat": now,
        "exp": now + lifetime,
        **claims,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str, expect: TokenKind = "access") -> dict[str, Any]:
    """Raises JWTError if the token is invalid, expired or the wrong kind."""
    payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    if payload.get("kind") != expect:
        raise JWTError(f"expected a {expect} token")
    return payload
