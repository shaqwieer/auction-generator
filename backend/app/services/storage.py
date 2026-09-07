"""File storage behind a small interface, so local disk can become S3 later."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import BinaryIO, Protocol

from app.core.config import get_settings


class StorageBackend(Protocol):
    def save(self, data: bytes | BinaryIO, *, folder: str, filename: str) -> str: ...
    def read(self, key: str) -> bytes: ...
    def path(self, key: str) -> Path: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...


class LocalDiskStorage:
    """Keys are relative posix paths under the storage root."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or get_settings().storage_root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        target = (self.root / key).resolve()
        if not str(target).startswith(str(self.root.resolve())):
            raise ValueError(f"key escapes the storage root: {key!r}")
        return target

    def save(self, data: bytes | BinaryIO, *, folder: str, filename: str) -> str:
        safe = Path(filename).name or "file"
        key = f"{folder.strip('/')}/{uuid.uuid4().hex[:12]}_{safe}"
        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            target.write_bytes(data)
        else:
            with target.open("wb") as handle:
                shutil.copyfileobj(data, handle)
        return key

    def read(self, key: str) -> bytes:
        return self._resolve(key).read_bytes()

    def path(self, key: str) -> Path:
        return self._resolve(key)

    def delete(self, key: str) -> None:
        target = self._resolve(key)
        if target.exists():
            target.unlink()

    def exists(self, key: str) -> bool:
        return self._resolve(key).exists()


_default: LocalDiskStorage | None = None


def get_storage() -> StorageBackend:
    global _default
    if _default is None:
        _default = LocalDiskStorage()
    return _default
