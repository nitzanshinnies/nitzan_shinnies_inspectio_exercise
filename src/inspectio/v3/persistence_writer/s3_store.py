"""S3 object-store adapter for persistence writer (P12.3)."""

from __future__ import annotations

import json
from typing import Any

from botocore.exceptions import ClientError

from inspectio.v3.persistence_writer.object_store import PersistenceObjectStore


class S3PersistenceObjectStore(PersistenceObjectStore):
    def __init__(self, *, client: Any, bucket: str, prefix: str) -> None:
        self._client = client
        self._bucket = bucket
        self._prefix = prefix.strip("/")

    def resolve_key(self, key: str) -> str:
        logical = key.lstrip("/")
        if not self._prefix:
            return logical
        prefixed = f"{self._prefix}/"
        if logical.startswith(prefixed):
            return logical
        return f"{prefixed}{logical}"

    def _to_logical_key(self, resolved_key: str) -> str:
        if not self._prefix:
            return resolved_key.lstrip("/")
        prefixed = f"{self._prefix}/"
        if resolved_key.startswith(prefixed):
            return resolved_key[len(prefixed) :]
        return resolved_key.lstrip("/")

    async def put_bytes(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str,
        content_encoding: str | None = None,
    ) -> None:
        params: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": self.resolve_key(key),
            "Body": data,
            "ContentType": content_type,
        }
        if content_encoding:
            params["ContentEncoding"] = content_encoding
        await self._client.put_object(**params)

    async def put_json(self, *, key: str, data: dict[str, Any]) -> None:
        payload = json.dumps(data).encode("utf-8")
        await self.put_bytes(
            key=key,
            data=payload,
            content_type="application/json",
            content_encoding=None,
        )

    async def get_json(self, *, key: str) -> dict[str, Any] | None:
        raw = await self.get_bytes(key=key)
        if raw is None:
            return None
        return json.loads(raw.decode("utf-8"))

    async def get_bytes(self, *, key: str) -> bytes | None:
        try:
            resp = await self._client.get_object(
                Bucket=self._bucket,
                Key=self.resolve_key(key),
            )
            return await resp["Body"].read()
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"NoSuchKey", "404", "NotFound"}:
                return None
            raise

    async def list_keys(self, *, prefix: str) -> list[str]:
        keys: list[str] = []
        continuation_token: str | None = None
        resolved_prefix = self.resolve_key(prefix)
        while True:
            params: dict[str, Any] = {
                "Bucket": self._bucket,
                "Prefix": resolved_prefix,
            }
            if continuation_token is not None:
                params["ContinuationToken"] = continuation_token
            response = await self._client.list_objects_v2(**params)
            for item in response.get("Contents", []):
                key = str(item.get("Key", ""))
                if key:
                    keys.append(self._to_logical_key(key))
            if not response.get("IsTruncated", False):
                break
            continuation_token = str(response.get("NextContinuationToken", ""))
        return sorted(keys)
