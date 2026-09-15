from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.backtest import sync_gate_universe_history_to_b2 as core  # noqa: E402
from scripts.backtest import sync_gate_universe_monthly_archive_to_b2 as monthly  # noqa: E402


def _configure_hf_storage() -> None:
    required = (
        "HF_S3_ENDPOINT",
        "HF_S3_BUCKET",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
    )
    missing = [name for name in required if not os.environ.get(name, "").strip()]
    if missing:
        raise RuntimeError("missing HF storage environment: " + ", ".join(missing))
    # The mature Gate writer accepts an S3-compatible endpoint through these
    # legacy variable names. Credentials remain in the standard AWS variables.
    os.environ["B2_S3_ENDPOINT"] = os.environ["HF_S3_ENDPOINT"].strip()
    os.environ["B2_BUCKET_NAME"] = os.environ["HF_S3_BUCKET"].strip()


def _downloaded_sha256(key: str) -> str:
    with tempfile.TemporaryDirectory(prefix="gate-hf-verify-") as temp_dir:
        target = Path(temp_dir) / "object"
        core._aws(
            "s3api",
            "get-object",
            "--bucket",
            core._bucket(),
            "--key",
            key,
            str(target),
        )
        return core._sha256(target)


def _head_object_state(key: str) -> tuple[bool, str | None]:
    result = core._aws(
        "s3api",
        "head-object",
        "--bucket",
        core._bucket(),
        "--key",
        key,
        check=False,
        quiet=False,
    )
    if core._object_missing(result):
        return False, None
    if result.returncode != 0:
        raise RuntimeError(f"HF head-object failed for {key}")
    return True, _downloaded_sha256(key)


def _put_file_verified(path: Path, key: str, sha256: str, content_type: str) -> None:
    core._aws(
        "s3api",
        "put-object",
        "--bucket",
        core._bucket(),
        "--key",
        key,
        "--body",
        str(path),
        "--content-type",
        content_type,
    )
    if _downloaded_sha256(key) != sha256:
        raise RuntimeError(f"HF SHA-256 read-back verification failed for {key}")


def main() -> int:
    _configure_hf_storage()
    monthly._head_object_state = _head_object_state
    core._put_file = _put_file_verified
    return monthly.main()


if __name__ == "__main__":
    raise SystemExit(main())
