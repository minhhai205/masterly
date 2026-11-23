"""Both storage backends store, return and delete by key, and refuse unsafe keys."""

from __future__ import annotations

import boto3
from moto import mock_aws
import pytest

from masterly.storage import LocalFileStorage, S3FileStorage, check_key


@pytest.mark.parametrize("key", ["a/../b", "/abs/key", "", "a//", "a/.hidden", "a b"])
def test_unsafe_keys_are_refused(key):
    with pytest.raises(ValueError):
        check_key(key)


def test_plain_keys_are_accepted():
    assert check_key("u_1/avatar") == "u_1/avatar"
    assert check_key("g/a/documents/d1.pdf") == "g/a/documents/d1.pdf"


async def _round_trip(storage) -> None:
    assert await storage.get("u_1/avatar") is None
    await storage.put("u_1/avatar", b"one", "image/png")
    assert await storage.get("u_1/avatar") == b"one"
    await storage.put("u_1/avatar", b"two", "image/png")
    assert await storage.get("u_1/avatar") == b"two"
    await storage.delete("u_1/avatar")
    assert await storage.get("u_1/avatar") is None
    await storage.delete("u_1/avatar")  # deleting a missing key is not an error


@pytest.mark.asyncio
async def test_local_storage_round_trip(tmp_path):
    storage = LocalFileStorage(tmp_path)
    await _round_trip(storage)
    assert not any(tmp_path.rglob("*.tmp"))


@pytest.mark.asyncio
async def test_s3_storage_round_trip():
    with mock_aws():
        client = boto3.client("s3", region_name="ap-southeast-1")
        client.create_bucket(
            Bucket="masterly-test",
            CreateBucketConfiguration={"LocationConstraint": "ap-southeast-1"},
        )
        await _round_trip(S3FileStorage("masterly-test", client=client))


def test_s3_storage_needs_a_bucket():
    with pytest.raises(ValueError):
        S3FileStorage("")
