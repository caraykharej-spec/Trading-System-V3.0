from __future__ import annotations

import importlib
import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, Protocol, cast

from app.data.market_data import Candle
from app.data.streaming import CandleStreamEvent
from app.data.time_sync import ClockSkewMonitor, ClockSyncSnapshot

_GATE_SPOT_WS_URL = "wss://api.gateio.ws/ws/v4/"
_SUPPORTED_INTERVALS = frozenset(
    {"10s", "1m", "5m", "15m", "30m", "1h", "4h", "8h", "1d", "7d"}
)


class WebSocketConnection(Protocol):
    def send(self, payload: str) -> object: ...

    def recv(self) -> str | bytes: ...

    def close(self) -> object: ...


ConnectionFactory = Callable[[str, float], WebSocketConnection]


def _coerce_positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _normalize_subscription_name(value: str) -> str:
    interval, separator, pair = value.partition("_")
    if not separator or not interval or not pair:
        return value
    return f"{interval.lower()}_{pair.upper()}"


@dataclass(frozen=True)
class GateIOCandleSubscription:
    canonical_symbol: str
    provider_symbol: str
    timeframe: str

    def __post_init__(self) -> None:
        if not self.canonical_symbol or not self.provider_symbol:
            raise ValueError("subscription symbols cannot be empty")
        if self.timeframe not in _SUPPORTED_INTERVALS:
            raise ValueError(f"unsupported Gate.io candle interval: {self.timeframe}")


class GateIOWebSocketCandleSource:
    """Public Gate.io Spot v4 candlestick stream with reconnect and clock monitoring."""

    name = "gateio"

    def __init__(
        self,
        subscriptions: tuple[GateIOCandleSubscription, ...],
        *,
        url: str = _GATE_SPOT_WS_URL,
        connect_timeout_seconds: float = 10.0,
        reconnect_initial_seconds: float = 1.0,
        reconnect_max_seconds: float = 30.0,
        connection_factory: ConnectionFactory | None = None,
        clock_monitor: ClockSkewMonitor | None = None,
    ) -> None:
        if not subscriptions:
            raise ValueError("at least one Gate.io candle subscription is required")
        if connect_timeout_seconds <= 0:
            raise ValueError("connect_timeout_seconds must be positive")
        if reconnect_initial_seconds <= 0 or reconnect_max_seconds <= 0:
            raise ValueError("reconnect delays must be positive")
        if reconnect_initial_seconds > reconnect_max_seconds:
            raise ValueError("reconnect_initial_seconds cannot exceed reconnect_max_seconds")

        self.subscriptions = subscriptions
        self.url = url
        self.connect_timeout_seconds = connect_timeout_seconds
        self.reconnect_initial_seconds = reconnect_initial_seconds
        self.reconnect_max_seconds = reconnect_max_seconds
        self._connection_factory = connection_factory or self._default_connection_factory
        self._clock_monitor = clock_monitor or ClockSkewMonitor()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._connection: WebSocketConnection | None = None
        self._handler: Callable[[CandleStreamEvent], None] | None = None
        self._by_name = {
            _normalize_subscription_name(
                f"{item.timeframe}_{item.provider_symbol}"
            ): item
            for item in subscriptions
        }

    @staticmethod
    def _default_connection_factory(url: str, timeout: float) -> WebSocketConnection:
        websocket_module = importlib.import_module("websocket")
        create_connection = getattr(websocket_module, "create_connection")
        connection = create_connection(url, timeout=timeout)
        return cast(WebSocketConnection, connection)

    def start(self, handler: Callable[[CandleStreamEvent], None]) -> None:
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("Gate.io candle stream is already running")
        self._handler = handler
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="gateio-candle-stream",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        connection = self._connection
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)
        self._connection = None
        self._thread = None

    def clock_snapshot(self) -> ClockSyncSnapshot:
        return self._clock_monitor.snapshot()

    def _run(self) -> None:
        delay = self.reconnect_initial_seconds
        while not self._stop_event.is_set():
            try:
                connection = self._connection_factory(self.url, self.connect_timeout_seconds)
                self._connection = connection
                self._subscribe(connection)
                delay = self.reconnect_initial_seconds
                self._receive_loop(connection)
            except Exception:
                if self._stop_event.is_set():
                    break
                time.sleep(delay)
                delay = min(delay * 2.0, self.reconnect_max_seconds)
            finally:
                active_connection = self._connection
                if active_connection is not None:
                    try:
                        active_connection.close()
                    except Exception:
                        pass
                self._connection = None

    def _subscribe(self, connection: WebSocketConnection) -> None:
        for subscription in self.subscriptions:
            message = {
                "time": int(time.time()),
                "channel": "spot.candlesticks",
                "event": "subscribe",
                "payload": [subscription.timeframe, subscription.provider_symbol.upper()],
            }
            connection.send(json.dumps(message, separators=(",", ":")))

    def _receive_loop(self, connection: WebSocketConnection) -> None:
        while not self._stop_event.is_set():
            raw = connection.recv()
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            event = self._parse_message(raw)
            if event is not None and self._handler is not None:
                self._handler(event)

    def _parse_message(self, raw: str) -> CandleStreamEvent | None:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return None

        server_time_ms = self._extract_server_time_ms(payload)
        received_at = datetime.now(timezone.utc)
        if server_time_ms is not None:
            self._clock_monitor.observe(server_time_ms, received_at=received_at)

        if payload.get("channel") != "spot.candlesticks" or payload.get("event") != "update":
            return None
        result = payload.get("result")
        if not isinstance(result, dict):
            return None
        name = _normalize_subscription_name(str(result.get("n") or ""))
        subscription = self._by_name.get(name)
        if subscription is None:
            return None

        timestamp = datetime.fromtimestamp(float(result["t"]), tz=timezone.utc)
        sequence = server_time_ms or int(received_at.timestamp() * 1000)
        candle = Candle(
            symbol=subscription.canonical_symbol,
            timeframe=subscription.timeframe,
            timestamp=timestamp,
            open=Decimal(str(result["o"])),
            high=Decimal(str(result["h"])),
            low=Decimal(str(result["l"])),
            close=Decimal(str(result["c"])),
            volume=Decimal(str(result["v"])),
        )
        event_id = f"{name}:{result['t']}:{sequence}"
        event = CandleStreamEvent(
            provider=self.name,
            event_id=event_id,
            sequence=sequence,
            candle=candle,
            received_at=received_at,
            server_time_ms=server_time_ms,
        )
        event.validate()
        return event

    @staticmethod
    def _extract_server_time_ms(payload: dict[object, object]) -> int | None:
        raw_ms = _coerce_positive_int(payload.get("time_ms"))
        if raw_ms is not None:
            return raw_ms
        raw_seconds = _coerce_positive_int(payload.get("time"))
        return raw_seconds * 1000 if raw_seconds is not None else None
