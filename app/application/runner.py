from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from app.core.enums import CycleStatus, PositionSide
from app.core.models import CycleResult, Position
from app.core.position_monitor import LivePriceProvider
from app.portfolio.account import Account
from app.position.manager import ExitPolicy, manage_open_positions
from app.storage.repositories.position_repository import PositionRepository


@dataclass
class ApplicationRunner:
    position_repository: PositionRepository
    live_price_provider: LivePriceProvider
    account: Account
    exit_policy: ExitPolicy = ExitPolicy()

    def run_cycle(self) -> CycleResult:
        """Run position exits before any future market/strategy phases."""
        started_at = datetime.now(timezone.utc)
        cycle_id = str(uuid4())
        positions = self.position_repository.list_open()

        management = manage_open_positions(positions, self.live_price_provider, self.exit_policy)
        for position in positions:
            self.position_repository.save(position)
        for result in management.results:
            self.account.apply_realized_pnl(result.realized_pnl)

        finished_at = datetime.now(timezone.utc)
        notes = tuple(
            f"Exit {result.position_id} reason={result.reason} at {result.exit_price}; "
            f"P&L={result.realized_pnl}; equity={self.account.equity}"
            for result in management.results
        )
        if management.trailing_updates:
            notes += (f"Updated {management.trailing_updates} trailing stop(s)",)

        return CycleResult(
            cycle_id=cycle_id,
            status=CycleStatus.COMPLETED,
            started_at=started_at,
            finished_at=finished_at,
            monitored_positions=management.monitored,
            stopped_positions=management.stop_loss_exits,
            notes=notes,
        )


def demo_price_provider(symbol: str) -> Decimal:
    """Safe deterministic provider for local PyCharm smoke tests only."""
    demo_prices = {"BTC/USDT": Decimal("70000")}
    return demo_prices.get(symbol, Decimal("1"))


def build_demo_runner() -> ApplicationRunner:
    from app.storage.repositories.in_memory_position_repository import InMemoryPositionRepository

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
        position_repository=InMemoryPositionRepository(positions),
        live_price_provider=demo_price_provider,
        account=Account(starting_equity=Decimal("10000")),
    )
