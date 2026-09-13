from __future__ import annotations

import csv
import gzip
import io
import urllib.error
import urllib.request

BASE_URL = "https://download.gatedata.org"
MARKET = "BTC_USDT"
CANDLE_MONTHS = (
    "202304",
    "202412",
    "202501",
    "202503",
    "202506",
    "202509",
    "202512",
    "202603",
    "202606",
)
DEAL_MONTHS = ("202509", "202512", "202603", "202606")


def _url(type_: str, month: str) -> str:
    return f"{BASE_URL}/spot/{type_}/{month}/{MARKET}-{month}.csv.gz"


def _request(url: str, *, method: str = "GET") -> urllib.request.Request:
    headers = {"User-Agent": "Trading-System-V3 historical-data-probe/1.0"}
    if method == "GET":
        headers["Range"] = "bytes=0-0"
    return urllib.request.Request(url, headers=headers, method=method)


def _status(url: str) -> tuple[int, str | None, str | None]:
    try:
        with urllib.request.urlopen(_request(url, method="HEAD"), timeout=20) as response:
            return (
                response.status,
                response.headers.get("Content-Type"),
                response.headers.get("Content-Length"),
            )
    except urllib.error.HTTPError as exc:
        if exc.code not in {405, 501}:
            return exc.code, None, None
    try:
        with urllib.request.urlopen(_request(url), timeout=20) as response:
            return (
                response.status,
                response.headers.get("Content-Type"),
                response.headers.get("Content-Range")
                or response.headers.get("Content-Length"),
            )
    except urllib.error.HTTPError as exc:
        return exc.code, None, None


def _download(url: str) -> tuple[int, str | None, bytes]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Trading-System-V3 historical-data-probe/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status, response.headers.get("Content-Type"), response.read()


def main() -> int:
    print("GATE HISTORICAL ARCHIVE AVAILABILITY PROBE")
    available_candle_months: list[str] = []
    for month in CANDLE_MONTHS:
        url = _url("candlesticks_5m", month)
        status, content_type, size = _status(url)
        print(
            f"type=candlesticks_5m month={month} status={status} "
            f"content_type={content_type} size={size} url={url}"
        )
        if status in {200, 206}:
            available_candle_months.append(month)

    available_deal_months: list[str] = []
    for month in DEAL_MONTHS:
        url = _url("deals", month)
        status, content_type, size = _status(url)
        print(
            f"type=deals month={month} status={status} "
            f"content_type={content_type} size={size} url={url}"
        )
        if status in {200, 206}:
            available_deal_months.append(month)

    if not available_candle_months:
        raise RuntimeError("no documented Gate monthly candlestick archive URL was reachable")

    schema_month = available_candle_months[0]
    url = _url("candlesticks_5m", schema_month)
    status, content_type, payload = _download(url)
    decoded = gzip.decompress(payload).decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(decoded)))
    if not rows:
        raise RuntimeError("historical archive CSV is empty")

    print("GATE HISTORICAL ARCHIVE SCHEMA PROBE COMPLETE")
    print(f"available_candle_months={available_candle_months!r}")
    print(f"available_deal_months={available_deal_months!r}")
    print(f"schema_month={schema_month}")
    print(f"http_status={status}")
    print(f"content_type={content_type}")
    print(f"row_count={len(rows)}")
    print(f"first_row_field_count={len(rows[0])}")
    print("first_row=" + repr(rows[0]))
    if len(rows) > 1:
        print("second_row=" + repr(rows[1]))
    print("last_row=" + repr(rows[-1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
