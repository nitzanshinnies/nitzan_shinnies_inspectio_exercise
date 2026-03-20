"""Mock SMS outcome classification — production must match `tests/reference_spec.py` + mock config bounds."""

from __future__ import annotations

import pytest

from inspectio_exercise.domain import sms_outcome
from inspectio_exercise.mock_sms import config as mock_config
from tests import reference_spec as spec


@pytest.mark.unit
def test_module_constants_are_valid() -> None:
    assert 0.0 <= mock_config.FAILURE_RATE <= 1.0
    assert 0.0 <= mock_config.UNAVAILABLE_FRACTION <= 1.0
    assert mock_config.AUDIT_LOG_MAX_ENTRIES > 0


@pytest.mark.parametrize("status", [200, 204])
@pytest.mark.unit
def test_2xx_classification_matches_spec(status: int) -> None:
    assert sms_outcome.is_successful_send(status) == spec.is_successful_send(status)
    assert sms_outcome.is_failed_send_for_lifecycle(status) == spec.is_failed_send_for_lifecycle(status)


@pytest.mark.parametrize("status", [500, 502, 503])
@pytest.mark.unit
def test_5xx_classification_matches_spec(status: int) -> None:
    assert sms_outcome.is_successful_send(status) == spec.is_successful_send(status)
    assert sms_outcome.is_failed_send_for_lifecycle(status) == spec.is_failed_send_for_lifecycle(status)
