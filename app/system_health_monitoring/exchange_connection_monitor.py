"""Exchange connection monitoring foundation."""

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class ExchangeConnectionStatus:
    exchange: str
    connected: bool
    authenticated: bool
    checked_at: str = ""


class ExchangeConnectionMonitor:
    def check(
        self,
        exchange: str,
        connected: bool = True,
        authenticated: bool = False,
    ) -> ExchangeConnectionStatus:
        return ExchangeConnectionStatus(
            exchange=exchange,
            connected=connected,
            authenticated=authenticated,
            checked_at=datetime.now(timezone.utc).isoformat(),
        )
