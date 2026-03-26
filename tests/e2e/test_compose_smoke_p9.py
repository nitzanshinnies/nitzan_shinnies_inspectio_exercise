"""P9 E2E smoke test (runs only when explicit env gate is set)."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

SMOKE_SCRIPT = "scripts/p9_compose_smoke.py"


@pytest.mark.e2e
def test_e2e_compose_smoke_script() -> None:
    if os.environ.get("RUN_P9_E2E_SMOKE") != "1":
        pytest.skip("Set RUN_P9_E2E_SMOKE=1 to run compose smoke")
    completed = subprocess.run(
        [sys.executable, SMOKE_SCRIPT],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
