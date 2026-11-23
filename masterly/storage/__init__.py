"""File storage behind one interface: a local directory in development, S3 on AWS.

Callers address files by key (``<owner>/avatar``, ``<owner>/documents/<id>``…)
and never by path or bucket, so switching ``STORAGE_BACKEND`` changes nothing
else. The same key layout is used by both backends.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache
from pathlib import Path
import re
from typing import Literal, Protocol

from pydantic_settings import BaseSettings, SettingsConfigDict

from masterly.db.config import PROJECT_ROOT

_KEY_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class StorageSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    storage_backend: Literal["local", "s3"] = "local"
    storage_local_dir: Path = PROJECT_ROOT / "data" / "files"
    s3_bucket: str = ""
    aws_region: str = ""


class FileStorage(Protocol):
    async def put(self, key: str, data: bytes, content_type: str | None = None) -> None: ...

    async def get(self, key: str) -> bytes | None: ...

    async def delete(self, key: str) -> None: ...


def check_key(key: str) -> str:
    """Accept only relative keys made of plain segments (no ``..``, no leading ``/``)."""
    parts = key.split("/")
    if not all(_KEY_PART.match(part) for part in parts):
        raise ValueError(f"Invalid storage key: {key!r}")
    return key


class LocalFileStorage:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root / check_key(key)

    async def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        def write() -> None:
            target = self._path(key)
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(target)

        await asyncio.to_thread(write)

    async def get(self, key: str) -> bytes | None:
        def read() -> bytes | None:
            target = self._path(key)
            return target.read_bytes() if target.is_file() else None

        return await asyncio.to_thread(read)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path(key).unlink, missing_ok=True)


class S3FileStorage:
    def __init__(self, bucket: str, region: str | None = None, client=None) -> None:
        if not bucket:
            raise ValueError("S3_BUCKET is required when STORAGE_BACKEND=s3")
        if client is None:
            import boto3

            client = boto3.client("s3", region_name=region or None)
        self.bucket = bucket
        self.client = client

    async def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        await asyncio.to_thread(
            self.client.put_object, Bucket=self.bucket, Key=check_key(key), Body=data, **extra
        )

    async def get(self, key: str) -> bytes | None:
        def read() -> bytes | None:
            try:
                response = self.client.get_object(Bucket=self.bucket, Key=check_key(key))
            except self.client.exceptions.NoSuchKey:
                return None
            return response["Body"].read()

        return await asyncio.to_thread(read)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=check_key(key))


@lru_cache(maxsize=1)
def get_storage() -> FileStorage:
    settings = StorageSettings()
    if settings.storage_backend == "s3":
        return S3FileStorage(settings.s3_bucket, settings.aws_region)
    return LocalFileStorage(settings.storage_local_dir)


__all__ = [
    "FileStorage",
    "LocalFileStorage",
    "S3FileStorage",
    "StorageSettings",
    "check_key",
    "get_storage",
]
