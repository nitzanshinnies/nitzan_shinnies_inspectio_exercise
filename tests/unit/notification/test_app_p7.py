"""P7 notification app tests for internal outcomes routes."""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from inspectio.notification.app import create_app


class _FakeOutcomesStore:
    def __init__(self) -> None:
        self.saved: list[dict] = []
        self.success: list[dict] = []
        self.failed: list[dict] = []

    async def add_terminal(self, payload: dict) -> None:
        self.saved.append(payload)

    async def get_success(self, *, limit: int) -> list[dict]:
        return self.success[:limit]

    async def get_failed(self, *, limit: int) -> list[dict]:
        return self.failed[:limit]


@pytest.mark.unit
def test_notification_internal_terminal_write_and_read_paths() -> None:
    app = create_app()
    fake = _FakeOutcomesStore()
    fake.success = [
        {
            "messageId": "m-1",
            "attemptCount": 1,
            "finalTimestamp": 1000,
            "reason": None,
        }
    ]
    app.state.outcomes_store = fake
    client = TestClient(app)

    write = client.post(
        "/internal/v1/outcomes/terminal",
        json={
            "messageId": "m-1",
            "terminalStatus": "success",
            "attemptCount": 1,
            "finalTimestampMs": 1000,
            "reason": None,
        },
    )
    assert write.status_code == 204
    assert len(fake.saved) == 1

    read = client.get("/internal/v1/outcomes/success?limit=1")
    assert read.status_code == 200
    assert read.json()["items"][0]["messageId"] == "m-1"
