"""Probe a Hugging Face Storage Bucket without exposing credentials."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.parse
import uuid
from pathlib import Path


_REQUIRED_ENV = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "HF_S3_ENDPOINT",
    "HF_S3_BUCKET",
)


def _safe_code(value: object) -> str:
    text = str(value)
    return text if re.fullmatch(r"[A-Za-z0-9_.-]+", text) else "unclassified"


def _normalize_endpoint(value: str) -> str:
    endpoint = value.strip().rstrip("/")
    if not endpoint.startswith("https://"):
        endpoint = "https://" + endpoint
    parsed = urllib.parse.urlparse(endpoint)
    namespace = parsed.path.strip("/")
    if (
        parsed.scheme != "https"
        or parsed.netloc != "s3.hf.co"
        or not namespace
        or "/" in namespace
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("endpoint must match https://s3.hf.co/<namespace>")
    return endpoint


def _aws_probe(
    args: list[str], endpoint: str, env: dict[str, str]
) -> tuple[dict[str, object], dict[str, object]]:
    try:
        result = subprocess.run(
            ["aws", *args, "--endpoint-url", endpoint],
            env=env,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"ok": False, "code": "transport_or_timeout_error"}, {}

    match = re.search(r"An error occurred \(([^)]+)\)", result.stderr)
    evidence: dict[str, object] = {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
    }
    if match:
        evidence["code"] = _safe_code(match.group(1))
    elif result.returncode:
        evidence["code"] = "command_failed"
    try:
        payload = json.loads(result.stdout) if result.returncode == 0 else {}
    except ValueError:
        payload = {}
    return evidence, payload


def main() -> int:
    report: dict[str, object] = {
        "schema_version": 1,
        "provider": "huggingface_storage_bucket",
        "missing": [name for name in _REQUIRED_ENV if not os.environ.get(name)],
    }
    if report["missing"]:
        report["status"] = "FAIL"
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1

    report["surrounding_whitespace"] = {
        name: os.environ[name] != os.environ[name].strip() for name in _REQUIRED_ENV
    }
    try:
        endpoint = _normalize_endpoint(os.environ["HF_S3_ENDPOINT"])
    except ValueError:
        report["invalid_endpoint_shape"] = True
        report["status"] = "FAIL"
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1

    bucket = os.environ["HF_S3_BUCKET"].strip()
    region = os.environ.get("AWS_DEFAULT_REGION", "")
    report["endpoint_shape_valid"] = True
    report["region_is_us_east_1"] = region == "us-east-1"
    report["access_key_shape_valid"] = os.environ["AWS_ACCESS_KEY_ID"].strip().startswith("HFAK")

    env = dict(os.environ)
    env.update(
        {
            "AWS_PAGER": "",
            "AWS_EC2_METADATA_DISABLED": "true",
            "AWS_REQUEST_CHECKSUM_CALCULATION": "when_required",
            "AWS_RESPONSE_CHECKSUM_VALIDATION": "when_required",
        }
    )
    key = "_connectivity/hf-diagnostics/" + uuid.uuid4().hex + ".txt"
    expected = b"Trading System Hugging Face S3 integrity diagnostic\n"

    with tempfile.TemporaryDirectory(prefix="hf-s3-diagnostic-") as tmp:
        source = Path(tmp) / "source.txt"
        target = Path(tmp) / "downloaded.txt"
        source.write_bytes(expected)
        digest = hashlib.sha256(expected).hexdigest()
        put_ok = False
        try:
            report["put"], _ = _aws_probe(
                [
                    "s3api",
                    "put-object",
                    "--bucket",
                    bucket,
                    "--key",
                    key,
                    "--body",
                    str(source),
                    "--content-type",
                    "text/plain",
                ],
                endpoint,
                env,
            )
            put_ok = bool(report["put"].get("ok"))  # type: ignore[union-attr]
            if put_ok:
                report["head"], _ = _aws_probe(
                    ["s3api", "head-object", "--bucket", bucket, "--key", key],
                    endpoint,
                    env,
                )
                report["get"], _ = _aws_probe(
                    [
                        "s3api",
                        "get-object",
                        "--bucket",
                        bucket,
                        "--key",
                        key,
                        str(target),
                    ],
                    endpoint,
                    env,
                )
                report["get"]["sha256_matches"] = (  # type: ignore[index]
                    target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == digest
                )
        finally:
            if put_ok:
                report["delete"], _ = _aws_probe(
                    ["s3api", "delete-object", "--bucket", bucket, "--key", key],
                    endpoint,
                    env,
                )

    operations = ("put", "head", "get", "delete")
    passed = (
        report["region_is_us_east_1"]
        and report["access_key_shape_valid"]
        and all(bool(report.get(name, {}).get("ok")) for name in operations)  # type: ignore[union-attr]
        and bool(report.get("get", {}).get("sha256_matches"))  # type: ignore[union-attr]
    )
    report["status"] = "PASS" if passed else "FAIL"
    output = Path("artifacts/hf-s3-access-diagnostics.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
