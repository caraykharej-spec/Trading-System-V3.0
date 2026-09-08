from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Iterable
from uuid import uuid4

from app.core.enums import CycleStatus
from app.core.models import CycleResult, Position
from app.core.position_monitor import LivePriceProvider, monitor_open_positions


@dataclass
class ApplicationRunner:
    positions: list[Position]
    live_price_provider: LivePriceProvider

    def run_cycle(self) -> CycleResult:
        started_at = datetime.now().astimezone()
        cycle_id = str(uuid4())

        monitor = monitor_open_positions(self.positions, self.live_price_provider)
        finished_at = datetime.now().astimezone()

        notes = tuple(
            f"Stopped {result.position_id} at {result.exit_price}; P&L={result.realized_pnl}"
            for result in monitor.results
        )

        return CycleResult(
            cycle_id=cycle_id,
            status=CycleStatus.COMPLETED,
            started_at=started_at,
            finished_at=finished_at,
            monitored_positions=monitor.monitored,
            stopped_positions=monitor.stopped_out,
            notes=notes,
        )


def demo_price_provider(symbol: str) -> Decimal:
    """Safe deterministic provider for local PyCharm smoke tests only."""
    demo_prices = {"BTC/USDT": Decimal("70000")}
    return demo_prices.get(symbol, Decimal("1"))


def build_demo_runner() -> ApplicationRunner:
    from app.core.enums import PositionSide

    positions = [
        Position(
            position_id="DEMO-001",
            symbol="BTC/USDT",
            side=PositionSide.LONG,
            entry_price=Decimal("79497.8"),
            stop_loss=Decimal("70000"),
            total_amount=Decimal("100"),
            quantity=Decimal("0.0082"),
            leverage=Decimal("7"),
        )
    ]
    return ApplicationRunner(positions=positions, live_price_provider=demo_price_provider)
