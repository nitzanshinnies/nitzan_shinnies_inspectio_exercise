"""Sanity checks for the operational frontend bundle (plans/REST_API.md §3.0)."""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FRONTEND_PUBLIC = _REPO_ROOT / "frontend" / "public"


@pytest.mark.unit
def test_frontend_entry_and_proxy_hints_exist() -> None:
    index = (_FRONTEND_PUBLIC / "index.html").read_text(encoding="utf-8")
    assert 'id="form-send"' in index
    assert 'id="form-repeat"' in index
    assert 'id="repeat-count"' in index
    assert 'max="10000"' in index
    assert "/messages" in index
    assert "inspectio-api-base" in index

    nginx = (_REPO_ROOT / "frontend" / "nginx.conf").read_text(encoding="utf-8")
    assert "proxy_pass http://api:8000" in nginx
    assert "location /messages" in nginx
    assert "location /healthz" in nginx
