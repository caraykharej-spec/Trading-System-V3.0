"""Resilient AWS CLI transport for Hugging Face Storage Buckets.

Hugging Face applies fixed-window rate limits and its S3 gateway can also
return transient 5xx/throttling failures. This module centralizes pacing and
bounded retry behavior so research-data workflows remain idempotent instead
of failing or duplicating objects during transient limits.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Callable

_RETRYABLE_MARKERS = (
    "429",
    "too many requests",
    "slowdown",
    "throttl",
    "requesttimeout",
    "request timeout",
    "internalerror",
    "internal error",
    "serviceunavailable",
    "service unavailable",
    "temporarily unavailable",
    "connection reset",
    "connection aborted",
    "connection closed",
    "503",
    "504",
    "gateway timeout",
    "500",
)

_last_request_monotonic = 0.0


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    value = float(raw)
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    value = int(raw)
    if value < 1:
        raise ValueError(f"{name} must be >= 1")
    return value


def endpoint() -> str:
    value = os.environ.get("HF_S3_ENDPOINT", "").strip().rstrip("/")
    if not value:
        raise RuntimeError("HF_S3_ENDPOINT is required")
    return value if value.startswith(("http://", "https://")) else "https://" + value


def is_retryable(stderr: str) -> bool:
    normalized = stderr.lower()
    return any(marker in normalized for marker in _RETRYABLE_MARKERS)


def _pace(*, sleep: Callable[[float], None], monotonic: Callable[[], float]) -> None:
    global _last_request_monotonic
    minimum = _float_env("HF_S3_MIN_REQUEST_INTERVAL_SECONDS", 0.0)
    if minimum <= 0:
        return
    now = monotonic()
    remaining = minimum - (now - _last_request_monotonic)
    if remaining > 0:
        sleep(remaining)
        now = monotonic()
    _last_request_monotonic = now


def aws(
    *args: str,
    check: bool = True,
    quiet: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> subprocess.CompletedProcess[str]:
    """Run one HF S3 operation with fixed-window-safe retry behavior.

    The AWS CLI already performs SDK-level retries when AWS_RETRY_MODE and
    AWS_MAX_ATTEMPTS are configured. This outer loop covers gateway-level
    429/5xx responses and connection failures that still escape the CLI.
    The maximum delay defaults to 300 seconds so a retry can cross a full
    five-minute Hugging Face rate-limit window.
    """

    attempts = _int_env("HF_S3_MAX_ATTEMPTS", 10)
    base_delay = _float_env("HF_S3_RETRY_BASE_SECONDS", 5.0)
    max_delay = _float_env("HF_S3_RETRY_MAX_SECONDS", 300.0)
    command = ["aws", *args, "--endpoint-url", endpoint()]

    last: subprocess.CompletedProcess[str] | None = None
    for attempt in range(1, attempts + 1):
        _pace(sleep=sleep, monotonic=monotonic)
        result = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        last = result
        if result.returncode == 0:
            return result
        retryable = is_retryable(result.stderr or "")
        if not retryable or attempt == attempts:
            if check:
                raise subprocess.CalledProcessError(
                    result.returncode,
                    command,
                    output=result.stdout,
                    stderr=result.stderr,
                )
            return result
        delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
        if not quiet:
            print(
                f"HF_S3_RETRY attempt={attempt}/{attempts} delay_seconds={delay:g}",
                file=sys.stderr,
            )
        sleep(delay)

    assert last is not None
    return last
