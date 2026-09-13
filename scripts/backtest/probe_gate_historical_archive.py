from __future__ import annotations

import csv
import gzip
import io
import urllib.error
import urllib.request

BASE_URL = "https://download.gatedata.org"
MONTHS = ("202304", "202509", "202603", "202606")
TYPE = "candlesticks_5m"
MARKET = "BTC_USDT"


def _url(month: str) -> str:
    return f"{BASE_URL}/spot/{TYPE}/{month}/{MARKET}-{month}.csv.gz"


def _download(url: str) -> tuple[int, str | None, bytes]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Trading-System-V3 historical-data-probe/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status, response.headers.get("Content-Type"), response.read()


def main() -> int:
    successes: list[tuple[str, int, str | None, bytes]] = []
    print("GATE HISTORICAL ARCHIVE AVAILABILITY PROBE")
    for month in MONTHS:
        url = _url(month)
        try:
            status, content_type, payload = _download(url)
        except urllib.error.HTTPError as exc:
            print(f"month={month} status={exc.code} url={url}")
            continue
        except urllib.error.URLError as exc:
            print(f"month={month} transport_error={exc.reason!r} url={url}")
            continue
        print(
            f"month={month} status={status} content_type={content_type} "
            f"compressed_bytes={len(payload)} url={url}"
        )
        successes.append((month, status, content_type, payload))

    if not successes:
        raise RuntimeError("no documented Gate monthly candlestick archive URL was reachable")

    month, status, content_type, payload = successes[0]
    decoded = gzip.decompress(payload).decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(decoded)))
    if not rows:
        raise RuntimeError("historical archive CSV is empty")

    print("GATE HISTORICAL ARCHIVE SCHEMA PROBE COMPLETE")
    print(f"schema_month={month}")
    print(f"http_status={status}")
    print(f"content_type={content_type}")
    print(f"row_count={len(rows)}")
    print(f"first_row_field_count={len(rows[0])}")
    print("first_row=" + repr(rows[0]))
    if len(rows) > 1:
        print(f"second_row_field_count={len(rows[1])}")
        print("second_row=" + repr(rows[1]))
    print("last_row=" + repr(rows[-1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
