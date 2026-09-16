from __future__ import annotations

import subprocess

from scripts.backtest import hf_s3


def test_retryable_throttle_retries_until_success(monkeypatch) -> None:
    monkeypatch.setenv("HF_S3_ENDPOINT", "https://s3.hf.co/example")
    monkeypatch.setenv("HF_S3_MAX_ATTEMPTS", "4")
    monkeypatch.setenv("HF_S3_RETRY_BASE_SECONDS", "1")
    monkeypatch.setenv("HF_S3_RETRY_MAX_SECONDS", "300")
    monkeypatch.setenv("HF_S3_MIN_REQUEST_INTERVAL_SECONDS", "0")
    calls = 0

    def fake_run(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls < 3:
            return subprocess.CompletedProcess([], 1, "", "429 Too Many Requests")
        return subprocess.CompletedProcess([], 0, "ok", "")

    sleeps: list[float] = []
    monkeypatch.setattr(hf_s3.subprocess, "run", fake_run)
    result = hf_s3.aws("s3api", "head-object", sleep=sleeps.append)

    assert result.returncode == 0
    assert calls == 3
    assert sleeps == [1.0, 2.0]


def test_non_retryable_error_is_not_retried(monkeypatch) -> None:
    monkeypatch.setenv("HF_S3_ENDPOINT", "https://s3.hf.co/example")
    monkeypatch.setenv("HF_S3_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("HF_S3_MIN_REQUEST_INTERVAL_SECONDS", "0")
    calls = 0

    def fake_run(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess([], 1, "", "AccessDenied")

    monkeypatch.setattr(hf_s3.subprocess, "run", fake_run)
    result = hf_s3.aws("s3api", "head-object", check=False, sleep=lambda _: None)

    assert result.returncode == 1
    assert calls == 1


def test_five_minute_cap_is_supported(monkeypatch) -> None:
    monkeypatch.setenv("HF_S3_ENDPOINT", "https://s3.hf.co/example")
    monkeypatch.setenv("HF_S3_MAX_ATTEMPTS", "10")
    monkeypatch.setenv("HF_S3_RETRY_BASE_SECONDS", "60")
    monkeypatch.setenv("HF_S3_RETRY_MAX_SECONDS", "300")
    monkeypatch.setenv("HF_S3_MIN_REQUEST_INTERVAL_SECONDS", "0")
    calls = 0

    def fake_run(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls < 5:
            return subprocess.CompletedProcess([], 1, "", "503 Service Unavailable")
        return subprocess.CompletedProcess([], 0, "ok", "")

    sleeps: list[float] = []
    monkeypatch.setattr(hf_s3.subprocess, "run", fake_run)
    hf_s3.aws("s3api", "put-object", sleep=sleeps.append)

    assert sleeps == [60.0, 120.0, 240.0, 300.0]
