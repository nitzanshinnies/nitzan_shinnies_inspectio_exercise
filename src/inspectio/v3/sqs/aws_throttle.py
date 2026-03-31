"""Detect AWS / SQS errors that should be retried with backoff."""

from __future__ import annotations

from botocore.exceptions import ClientError

_THROTTLE_CODES = frozenset(
    {
        "Throttling",
        "ThrottlingException",
        "RequestThrottled",
        "SlowDown",
        "ServiceUnavailable",
        "PriorRequestNotComplete",
    },
)


def is_aws_throttle_error(exc: BaseException) -> bool:
    if not isinstance(exc, ClientError):
        return False
    err = exc.response.get("Error", {})
    code = str(err.get("Code", ""))
    if code in _THROTTLE_CODES:
        return True
    status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return status == 503
