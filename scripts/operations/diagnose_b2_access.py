"""Diagnose the configured B2 key without logging credentials or native tokens."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


def safe_code(value: object) -> str:
    text = str(value)
    return text if re.fullmatch(r"[A-Za-z0-9_]+", text) else "unclassified"


def authorize() -> tuple[dict, dict]:
    pair = os.environ["AWS_ACCESS_KEY_ID"] + ":" + os.environ["AWS_SECRET_ACCESS_KEY"]
    header = "Basic " + base64.b64encode(pair.encode()).decode()
    request = urllib.request.Request(
        "https://api.backblazeb2.com/b2api/v4/b2_authorize_account",
        headers={"Authorization": header},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
        return payload, {"ok": True}
    except urllib.error.HTTPError as exc:
        try:
            code = json.load(exc).get("code", "unknown")
        except (ValueError, AttributeError):
            code = "unclassified"
        return {}, {"ok": False, "http_status": exc.code, "code": safe_code(code)}
    except (OSError, ValueError):
        return {}, {"ok": False, "code": "transport_or_response_error"}


def aws_probe(args: list[str], endpoint: str, env: dict[str, str]) -> tuple[dict, dict]:
    result = subprocess.run(
        ["aws", *args, "--endpoint-url", endpoint],
        env=env, capture_output=True, text=True, timeout=90,
    )
    match = re.search(r"An error occurred \(([^)]+)\)", result.stderr)
    evidence = {"ok": result.returncode == 0, "returncode": result.returncode}
    if match:
        evidence["code"] = safe_code(match.group(1))
    try:
        payload = json.loads(result.stdout) if result.returncode == 0 else {}
    except ValueError:
        payload = {}
    return evidence, payload


def main() -> int:
    names = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "B2_S3_ENDPOINT", "B2_BUCKET_NAME")
    report: dict = {"schema_version": 1, "missing": [n for n in names if not os.environ.get(n)]}
    if report["missing"]:
        print(json.dumps(report))
        return 1
    report["surrounding_whitespace"] = {n: os.environ[n] != os.environ[n].strip() for n in names}
    endpoint = os.environ["B2_S3_ENDPOINT"].strip().rstrip("/")
    if not endpoint.startswith("https://"):
        endpoint = "https://" + endpoint
    parsed = urllib.parse.urlparse(endpoint)
    if not re.fullmatch(r"s3\.[a-z0-9-]+\.backblazeb2\.com", parsed.netloc) or parsed.path:
        report["invalid_endpoint_shape"] = True
        print(json.dumps(report))
        return 1
    bucket = os.environ["B2_BUCKET_NAME"].strip()
    payload, report["native_authorization"] = authorize()
    storage = payload.get("apiInfo", {}).get("storageApi", {})
    allowed = storage.get("allowed", {})
    caps = allowed.get("capabilities", [])
    prefix = allowed.get("namePrefix") or ""
    buckets = allowed.get("buckets")
    report["capabilities"] = sorted(caps)
    report["bucket_scope_matches"] = (
        None if not storage else buckets is None or any(b.get("name") == bucket for b in buckets)
    )
    report["endpoint_matches_native"] = endpoint == storage.get("s3ApiUrl", "").rstrip("/")
    report["region_matches_endpoint"] = os.environ.get("AWS_DEFAULT_REGION") == parsed.netloc.split(".")[1]
    report["has_prefix_restriction"] = bool(prefix)
    report["project_prefixes_allowed"] = {
        p: p.startswith(prefix) for p in ("_connectivity/", "bronze/gate-history/v2/", "manifests/gate-history/v2/")
    }
    key = "_connectivity/b2-diagnostics/" + uuid.uuid4().hex + ".txt"
    env = dict(os.environ)
    env["AWS_PAGER"] = ""
    report["aws_version"] = subprocess.run(["aws", "--version"], capture_output=True, text=True).stdout.strip()
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "source.txt"
        source.write_bytes(b"Trading System B2 access and integrity diagnostic\n")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        report["put"], put = aws_probe([
            "s3api", "put-object", "--bucket", bucket, "--key", key, "--body", str(source),
            "--metadata", "sha256=" + digest,
        ], endpoint, env)
        if report["put"]["ok"]:
            try:
                report["head"], _ = aws_probe([
                    "s3api", "head-object", "--bucket", bucket, "--key", key,
                ], endpoint, env)
                for mode in ("get", "copy"):
                    target = Path(tmp) / (mode + ".txt")
                    args = (["s3api", "get-object", "--bucket", bucket, "--key", key, str(target)]
                            if mode == "get" else ["s3", "cp", f"s3://{bucket}/{key}", str(target)])
                    report[mode], _ = aws_probe(args, endpoint, env)
                    report[mode]["sha256_matches"] = target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == digest
                if payload.get("authorizationToken") and storage.get("downloadUrl"):
                    url = storage["downloadUrl"] + "/file/" + urllib.parse.quote(bucket, safe="") + "/" + urllib.parse.quote(key, safe="/")
                    request = urllib.request.Request(url, headers={"Authorization": payload["authorizationToken"]})
                    try:
                        with urllib.request.urlopen(request, timeout=30) as response:
                            data = response.read()
                        report["native_get"] = {"ok": True, "sha256_matches": hashlib.sha256(data).hexdigest() == digest}
                    except urllib.error.HTTPError as exc:
                        try:
                            code = json.load(exc).get("code", "unknown")
                        except (ValueError, AttributeError):
                            code = "unclassified"
                        report["native_get"] = {"ok": False, "http_status": exc.code, "code": safe_code(code)}
            finally:
                args = ["s3api", "delete-object", "--bucket", bucket, "--key", key]
                if put.get("VersionId"):
                    args += ["--version-id", put["VersionId"]]
                report["delete"], _ = aws_probe(args, endpoint, env)
    report["status"] = "PASS" if all(report.get(k, {}).get("ok") for k in ("put", "head", "get", "copy", "delete")) and all(report.get(k, {}).get("sha256_matches") for k in ("get", "copy")) else "FAIL"
    output = Path("artifacts/b2-access-diagnostics.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
