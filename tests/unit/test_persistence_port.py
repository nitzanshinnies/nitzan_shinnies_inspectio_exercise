"""PersistencePort adapter in src (plans/TESTS.md §4.10).

TDD: fails until `inspectio_exercise.persistence` exposes a real adapter; then replace with contract tests.
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_persistence_port_adapter_implemented_in_src() -> None:
    pytest.fail(
        "Implement PersistencePort (HTTP client or in-proc) under "
        "src/inspectio_exercise/persistence/, then replace this test with "
        "put/get/list/delete contract tests against that adapter."
    )
