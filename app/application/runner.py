from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from app.core.enums import CycleStatus
from app.core.models import CycleResult, Position
from app.core.position_monitor import LivePriceProvider, monitor_open_positions
from app.portfolio.account import Account


@dataclass
class ApplicationRunner:
    positions: list[Position]
    live_price_provider: LivePriceProvider
    account: Account

    def run_cycle(self) -> CycleResult:
        """Run the mandatory position-safety phase before future strategy phases."""
        started_at = datetime.now(timezone.utc)
        cycle_id = str(uuid4())

        monitor = monitor_open_positions(self.positions, self.live_price_provider)
        for result in monitor.results:
            self.account.apply_realized_pnl(result.realized_pnl)

        finished_at = datetime.now(timezone.utc)
        notes = tuple(
            f"Stopped {result.position_id} at {result.exit_price}; "
            f"P&L={result.realized_pnl}; equity={self.account.equity}"
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
    return ApplicationRunner(
        positions=positions,
        live_price_provider=demo_price_provider,
        account=Account(starting_equity=Decimal("10000")),
    )
