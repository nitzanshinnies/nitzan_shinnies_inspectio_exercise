"""AWS S3 ``PersistencePort`` (plans/SYSTEM_OVERVIEW.md §1.3 — AWS mode).

Uses **boto3** (blocking client) with ``asyncio.to_thread`` for each call, matching the
thread-offload pattern in ``LocalS3Provider``. That keeps the public API async, avoids
blocking the event loop, and works with **moto** in tests. The project still lists
``aioboto3`` in ``pyproject.toml`` per ``plans/PLAN.md`` for a future pure-async path
or other components.
"""

from __future__ import annotations

import asyncio
from typing import Any

import boto3
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import ClientError

from inspectio_exercise.persistence import config
from inspectio_exercise.persistence.key_policy import (
    validate_list_prefix,
    validate_max_keys,
    validate_object_key,
)

_NOSUCHKEY_CODES = frozenset({"NoSuchKey", "404"})


class AwsS3Provider:
    """``PersistencePort`` backed by a single S3 bucket."""

    def __init__(
        self,
        bucket: str,
        *,
        client: BaseClient | None = None,
        endpoint_url: str | None = None,
        region_name: str | None = None,
    ) -> None:
        if not bucket.strip():
            raise ValueError("S3 bucket name must be non-empty")
        self._bucket = bucket
        if client is not None:
            self._client = client
        else:
            botocore_config = Config(
                connect_timeout=config.S3_BOTOCORE_CONNECT_TIMEOUT_SEC,
                read_timeout=config.S3_BOTOCORE_READ_TIMEOUT_SEC,
                retries={
                    "max_attempts": config.S3_BOTOCORE_MAX_RETRY_ATTEMPTS,
                    "mode": "standard",
                },
            )
            session = boto3.session.Session()
            resolved_region = region_name or session.region_name
            self._client = session.client(
                "s3",
                config=botocore_config,
                endpoint_url=endpoint_url,
                region_name=resolved_region,
            )

    def _delete_object_sync(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def _get_object_sync(self, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in _NOSUCHKEY_CODES:
                raise KeyError(key) from exc
            raise
        body = response["Body"]
        raw: bytes = body.read()
        return raw

    def _list_prefix_sync(self, prefix: str, max_keys: int | None) -> list[dict[str, Any]]:
        keys: list[str] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            for row in page.get("Contents") or []:
                keys.append(row["Key"])
        keys.sort()
        if max_keys is not None:
            keys = keys[:max_keys]
        return [{"Key": k} for k in keys]

    def _put_object_sync(self, key: str, body: bytes, content_type: str) -> None:
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )

    async def delete_object(self, key: str) -> None:
        validate_object_key(key)
        await asyncio.to_thread(self._delete_object_sync, key)

    async def get_object(self, key: str) -> bytes:
        validate_object_key(key)
        return await asyncio.to_thread(self._get_object_sync, key)

    async def list_prefix(self, prefix: str, max_keys: int | None = None) -> list[dict[str, Any]]:
        validate_list_prefix(prefix)
        validate_max_keys(max_keys)
        return await asyncio.to_thread(self._list_prefix_sync, prefix, max_keys)

    async def put_object(
        self, key: str, body: bytes, content_type: str = "application/json"
    ) -> None:
        validate_object_key(key)
        await asyncio.to_thread(self._put_object_sync, key, body, content_type)
