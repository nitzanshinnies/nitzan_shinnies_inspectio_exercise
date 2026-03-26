"""Plaintext performance lines to stdout (one line per event)."""

from __future__ import annotations


def perf_line(component: str, **fields: object) -> None:
    """Emit `[inspectio-perf] component=... key=value ...` for log aggregation."""
    parts = " ".join(f"{k}={v}" for k, v in fields.items())
    print(f"[inspectio-perf] component={component} {parts}")
