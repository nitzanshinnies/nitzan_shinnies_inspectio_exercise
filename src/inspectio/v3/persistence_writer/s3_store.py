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
        if not self._prefix:
            return key.lstrip("/")
        return f"{self._prefix}/{key.lstrip('/')}"

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
        try:
            resp = await self._client.get_object(
                Bucket=self._bucket,
                Key=self.resolve_key(key),
            )
            raw = await resp["Body"].read()
            return json.loads(raw.decode("utf-8"))
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"NoSuchKey", "404", "NotFound"}:
                return None
            raise
