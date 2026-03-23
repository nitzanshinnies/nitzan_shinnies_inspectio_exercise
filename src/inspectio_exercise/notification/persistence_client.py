"""HTTP client for the persistence microservice (JSON + base64 bodies)."""

from __future__ import annotations

import base64
from collections.abc import Sequence
from typing import Any

import httpx

from inspectio_exercise.persistence.object_write import ObjectWrite


class PersistenceHttpClient:
    """Thin wrapper around persistence ``POST /internal/v1/*`` routes."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def aclose(self) -> None:
        await self._client.aclose()

    async def delete_object(self, key: str) -> None:
        response = await self._client.post("/internal/v1/delete-object", json={"key": key})
        response.raise_for_status()

    async def get_object(self, key: str) -> bytes:
        response = await self._client.post("/internal/v1/get-object", json={"key": key})
        if response.status_code == 404:
            raise KeyError(key)
        response.raise_for_status()
        data = response.json()
        return base64.b64decode(data["body_b64"])

    async def list_prefix(self, prefix: str, max_keys: int | None = None) -> list[dict[str, Any]]:
        response = await self._client.post(
            "/internal/v1/list-prefix",
            json={"prefix": prefix, "max_keys": max_keys},
        )
        response.raise_for_status()
        return response.json()["keys"]

    async def put_object(
        self, key: str, body: bytes, content_type: str = "application/json"
    ) -> None:
        payload = {
            "key": key,
            "body_b64": base64.b64encode(body).decode("ascii"),
            "content_type": content_type,
        }
        response = await self._client.post("/internal/v1/put-object", json=payload)
        response.raise_for_status()

    async def put_objects(self, items: Sequence[ObjectWrite]) -> None:
        materialized = list(items)
        if not materialized:
            return
        payload = {
            "objects": [
                {
                    "key": ow.key,
                    "body_b64": base64.b64encode(ow.body).decode("ascii"),
                    "content_type": ow.content_type,
                }
                for ow in materialized
            ],
        }
        response = await self._client.post("/internal/v1/put-objects", json=payload)
        response.raise_for_status()
