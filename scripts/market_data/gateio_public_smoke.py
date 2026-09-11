from __future__ import annotations

import json
import time
from decimal import Decimal

import websocket

GATEIO_WS_URL = "wss://api.gateio.ws/ws/v4/"
CHANNEL = "spot.candlesticks"
TIMEFRAME = "15m"
PAIR = "BTC_USDT"
TIMEOUT_SECONDS = 25.0


def _valid_candle(result: object) -> bool:
    if not isinstance(result, dict):
        return False
    if str(result.get("n") or "") != f"{TIMEFRAME}_{PAIR}":
        return False
    required = ("o", "h", "l", "c", "v", "t")
    if any(key not in result for key in required):
        return False
    try:
        open_price = Decimal(str(result["o"]))
        high = Decimal(str(result["h"]))
        low = Decimal(str(result["l"]))
        close = Decimal(str(result["c"]))
        volume = Decimal(str(result["v"]))
        timestamp = int(str(result["t"]))
    except (ArithmeticError, ValueError):
        return False
    return (
        open_price > 0
        and high > 0
        and low > 0
        and close > 0
        and volume >= 0
        and timestamp > 0
        and low <= min(open_price, close, high)
        and high >= max(open_price, close, low)
    )


def main() -> int:
    connection = websocket.create_connection(GATEIO_WS_URL, timeout=10)
    try:
        connection.send(
            json.dumps(
                {
                    "time": int(time.time()),
                    "channel": CHANNEL,
                    "event": "subscribe",
                    "payload": [TIMEFRAME, PAIR],
                },
                separators=(",", ":"),
            )
        )

        saw_subscription_ack = False
        saw_market_update = False
        deadline = time.monotonic() + TIMEOUT_SECONDS
        while time.monotonic() < deadline and not saw_market_update:
            raw = connection.recv()
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, dict) or payload.get("channel") != CHANNEL:
                continue

            if payload.get("event") == "subscribe":
                result = payload.get("result")
                if isinstance(result, dict) and result.get("status") == "success":
                    saw_subscription_ack = True
                continue

            if payload.get("event") == "update" and _valid_candle(payload.get("result")):
                saw_market_update = True

        if not saw_subscription_ack:
            raise RuntimeError("Gate.io did not confirm the public candlestick subscription")
        if not saw_market_update:
            raise RuntimeError("Gate.io did not deliver a valid public candlestick update")

        print("Gate.io public WebSocket smoke: PASS")
        print(f"channel={CHANNEL} pair={PAIR} timeframe={TIMEFRAME}")
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
