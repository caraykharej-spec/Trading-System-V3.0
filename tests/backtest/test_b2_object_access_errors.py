import subprocess

import pytest

from scripts.backtest import sync_gate_tradfi_history_to_b2 as tradfi
from scripts.backtest import sync_gate_universe_history_to_b2 as core
from scripts.backtest import sync_gate_universe_monthly_archive_to_b2 as monthly


@pytest.mark.parametrize("code", ["403", "AccessDenied", "500", "download_cap_exceeded"])
@pytest.mark.parametrize("lookup", [core._object_exists, monthly._head_object_state, tradfi._remote_sha256])
def test_access_and_service_errors_never_mean_missing(monkeypatch, code, lookup) -> None:
    def denied(*args, **kwargs):
        return subprocess.CompletedProcess(args, 254, "", f"An error occurred ({code})")

    monkeypatch.setattr(core, "_aws", denied)
    monkeypatch.setattr(tradfi, "_aws", denied)
    monkeypatch.setattr(core, "_bucket", lambda: "test-bucket")
    monkeypatch.setattr(tradfi, "_bucket", lambda: "test-bucket")
    with pytest.raises(RuntimeError, match="not a missing object"):
        lookup("test-key")


@pytest.mark.parametrize("code", ["404", "NoSuchKey", "NotFound"])
def test_only_explicit_object_absence_is_retryable(code) -> None:
    assert core._object_missing(subprocess.CompletedProcess([], 254, "", f"An error occurred ({code})"))


def test_unknown_network_failure_is_not_missing() -> None:
    with pytest.raises(RuntimeError, match="unclassified"):
        core._object_missing(subprocess.CompletedProcess([], 255, "", "Connection timed out"))
