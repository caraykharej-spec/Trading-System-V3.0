from __future__ import annotations

import csv
import gzip
import io
import sys
import urllib.request

URL = (
    "https://download.gatedata.org/spot/candlesticks_5m/202509/"
    "BTC_USDT-202509.csv.gz"
)


def main() -> int:
    request = urllib.request.Request(
        URL,
        headers={"User-Agent": "Trading-System-V3 historical-data-probe/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = response.read()
        status = response.status
        content_type = response.headers.get("Content-Type")

    decoded = gzip.decompress(payload).decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(decoded)))
    if not rows:
        raise RuntimeError("historical archive CSV is empty")

    print("GATE HISTORICAL ARCHIVE PROBE COMPLETE")
    print(f"url={URL}")
    print(f"http_status={status}")
    print(f"content_type={content_type}")
    print(f"compressed_bytes={len(payload)}")
    print(f"row_count={len(rows)}")
    print(f"first_row_field_count={len(rows[0])}")
    print("first_row=" + repr(rows[0]))
    if len(rows) > 1:
        print(f"second_row_field_count={len(rows[1])}")
        print("second_row=" + repr(rows[1]))
    if len(rows) > 2:
        print("last_row=" + repr(rows[-1]))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"archive_probe_error={exc!r}", file=sys.stderr)
        raise
