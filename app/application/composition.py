from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Callable

from app.analytics.service import AnalyticsService
from app.application.opportunity_pipeline import (
    GatedOpportunity,
    OpportunityPipeline,
    RiskContext,
)
from app.application.runtime_cycle import RuntimeCycleOrchestrator
from app.application.strategy_pipeline import StrategyPipeline
from app.context.context_engine import ContextEngine
from app.context.models import ContextAssessment
from app.core.enums import SystemMode
from app.data.mapped_provider import MappedMarketProvider
from app.data.market_data import MarketDataRequest
from app.data.provider_router import ProviderRouter
from app.data.providers.gateio import GateIOProvider
from app.data.providers.storm import StormProvider
from app.data.providers.yahoo import YahooFinanceProvider
from app.execution.atomic_execution import AtomicExecutionService
from app.execution.execution_engine import ExecutionEngine, ExecutionPolicy
from app.execution.models import OrderRequest
from app.execution.paper_executor import PaperExecutor
from app.execution.paper_runtime import PaperTradingRuntime
from app.execution.pending_order_manager import PendingOrderManager
from app.execution.risk_reservation import reserve_pending_order_risk
from app.execution.sqlite_pending_order_repository import SQLitePendingOrderRepository
from app.journal.sqlite_repository import SQLiteJournalRepository
from app.market.analysis import MarketSnapshot, analyze_market
from app.observability.health import SystemHealthService
from app.portfolio.account import Account
from app.portfolio.correlation import CorrelationMatrix
from app.position.settlement import PositionSettlementService
from app.recovery.reconciliation import RecoveryReconciler
from app.runtime.sqlite_audit import SQLiteCycleAuditRepository
from app.storage.account_ledger import SQLiteAccountLedgerRepository
from app.storage.database import connect
from app.storage.repositories.sqlite_account_repository import SQLiteAccountRepository
from app.storage.repositories.sqlite_fill_repository import SQLiteFillRepository
from app.storage.repositories.sqlite_order_repository import SQLiteOrderRepository
from app.storage.repositories.sqlite_position_repository import SQLitePositionRepository
from app.universe.config_loader import load_universe
from app.universe.contract_specs import ContractSpec
from app.universe.registry import InstrumentRegistry
from app.universe.symbol_mapping import SymbolMapper
from interfaces.api.service import TradingApiService


ContextLoader = Callable[[str], ContextAssessment]


@dataclass
class ExplicitPaperSelectionQueue:
    """In-memory handoff requiring explicit caller selection before paper submission."""

    _orders: list[OrderRequest] = field(default_factory=list)

    def replace(self, orders: list[OrderRequest]) -> None:
        self._orders = list(orders)

    def drain(self) -> list[OrderRequest]:
        orders = list(self._orders)
        self._orders.clear()
        return orders


@dataclass
class PaperApplication:
    """Fully wired PAPER application. No live-execution adapter exists here."""

    mode: SystemMode
    connection: sqlite3.Connection
    registry: InstrumentRegistry
    mapper: SymbolMapper
    live_router: ProviderRouter
    candle_router: ProviderRouter
    account: Account
    position_repository: SQLitePositionRepository
    pending_repository: SQLitePendingOrderRepository
    opportunity_pipeline: OpportunityPipeline
    runtime: RuntimeCycleOrchestrator
    analytics: AnalyticsService
    health: SystemHealthService
    api: TradingApiService
    selection_queue: ExplicitPaperSelectionQueue

    def close(self) -> None:
        self.connection.close()


def _initialize_account(
    connection: sqlite3.Connection, initial_equity: Decimal
) -> Decimal:
    if initial_equity <= 0:
        raise ValueError("initial_equity must be positive")
    row = connection.execute(
        "SELECT equity FROM account_state WHERE account_id = ?", ("default",)
    ).fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO account_state(account_id, equity) VALUES (?, ?)",
            ("default", str(initial_equity)),
        )
        connection.commit()
        return initial_equity
    return Decimal(str(row[0]))


def _validate_universe(
    registry: InstrumentRegistry,
    mapper: SymbolMapper,
    contract_specs: dict[str, ContractSpec],
) -> None:
    instruments = registry.all(tradable_only=True)
    if not instruments:
        raise ValueError("configured tradable universe must not be empty")
    for instrument in instruments:
        symbol = instrument.symbol
        if symbol.upper() not in contract_specs:
            raise ValueError(f"missing contract specification for {symbol}")
        if not any(
            mapper.has_mapping(symbol, provider)
            for provider in ("storm", "gateio", "yahoo")
        ):
            raise ValueError(f"missing market-data mapping for {symbol}")


def build_paper_application(
    *,
    db_path: str | Path = "data/trading_system_v3.db",
    universe_path: str | Path = "config/universe.json",
    initial_equity: Decimal = Decimal("10000"),
    leverage_by_symbol: dict[str, Decimal] | None = None,
    correlation_matrix: CorrelationMatrix | None = None,
    context_loader: ContextLoader | None = None,
) -> PaperApplication:
    """Build the real V3 application boundary without performing network I/O.

    Network calls occur only when a price/candle/cycle/opportunity operation is
    explicitly requested. Paper order submission is additionally gated by the
    explicit selection queue; Top-10 opportunities are never auto-submitted.
    """
    connection = connect(db_path)
    registry, mapper, contract_specs = load_universe(universe_path)
    _validate_universe(registry, mapper, contract_specs)
    persisted_equity = _initialize_account(connection, initial_equity)
    account = Account(starting_equity=persisted_equity)

    storm = MappedMarketProvider(StormProvider(), mapper)
    gateio = MappedMarketProvider(GateIOProvider(), mapper)
    yahoo = MappedMarketProvider(YahooFinanceProvider(), mapper)
    live_router = ProviderRouter(
        (storm, gateio, yahoo), max_live_age_seconds=120
    )
    candle_router = ProviderRouter((gateio, yahoo))

    position_repository = SQLitePositionRepository(connection)
    position_writer = SQLitePositionRepository(connection, auto_commit=False)
    account_repository = SQLiteAccountRepository(connection)
    account_writer = SQLiteAccountRepository(connection, auto_commit=False)
    order_repository = SQLiteOrderRepository(connection)
    order_writer = SQLiteOrderRepository(connection, auto_commit=False)
    fill_repository = SQLiteFillRepository(connection)
    fill_writer = SQLiteFillRepository(connection, auto_commit=False)
    pending_repository = SQLitePendingOrderRepository(connection)
    journal_repository = SQLiteJournalRepository(connection)
    journal_writer = SQLiteJournalRepository(connection, auto_commit=False)
    ledger_writer = SQLiteAccountLedgerRepository(connection, auto_commit=False)
    audit_repository = SQLiteCycleAuditRepository(connection)

    def live_price(symbol: str) -> Decimal:
        return live_router.get_live_price(symbol).price

    def snapshot_loader(
        symbol: str,
    ) -> tuple[
        MarketSnapshot,
        MarketSnapshot,
        MarketSnapshot,
        MarketSnapshot,
    ]:
        snapshots: dict[str, MarketSnapshot] = {}
        for timeframe in ("1d", "4h", "1h", "15m"):
            candles = candle_router.get_candles(
                MarketDataRequest(
                    symbol=symbol, timeframe=timeframe, limit=260
                )
            )
            snapshots[timeframe] = analyze_market(
                symbol, timeframe, candles
            )
        return (
            snapshots["1d"],
            snapshots["4h"],
            snapshots["1h"],
            snapshots["15m"],
        )

    strategy_pipeline = StrategyPipeline(snapshot_loader)
    context_engine = ContextEngine()
    effective_context_loader = context_loader or (
        lambda symbol: context_engine.assess(symbol)
    )
    leverage_map = {
        key.upper(): value
        for key, value in (leverage_by_symbol or {}).items()
    }
    matrix = correlation_matrix or CorrelationMatrix()

    def risk_context_loader(symbol: str) -> RiskContext:
        instrument = registry.get(symbol)
        contract = contract_specs[symbol.upper()]
        leverage = leverage_map.get(symbol.upper(), Decimal("1"))
        if leverage <= 0:
            raise ValueError(f"invalid configured leverage for {symbol}")
        active_pending = [
            pending.order for pending in pending_repository.list_active()
        ]
        reservation = reserve_pending_order_risk(
            active_pending, market_price_provider=live_price
        )
        if reservation.unresolved_order_ids:
            raise ValueError(
                "cannot quantify pending order risk: "
                + ",".join(reservation.unresolved_order_ids)
            )
        execution_venue = (
            "STORM" if mapper.has_mapping(symbol, "storm") else None
        )
        return RiskContext(
            account=account,
            positions=position_repository.list_open(),
            instrument=instrument,
            contract=contract,
            leverage=leverage,
            provider=execution_venue,
            reserved_pending_risk=reservation.total_risk,
            correlation_matrix=matrix,
        )

    opportunity_pipeline = OpportunityPipeline(
        strategy_pipeline,
        risk_context_loader,
        context_loader=effective_context_loader,
    )

    paper_executor = PaperExecutor(live_price)
    execution_engine = ExecutionEngine(
        paper_executor,
        ExecutionPolicy(paper_enabled=True, shadow_enabled=True),
    )
    atomic_execution = AtomicExecutionService(
        connection,
        order_writer,
        fill_writer,
        position_writer,
    )
    paper_runtime = PaperTradingRuntime(
        execution_engine,
        order_repository,
        pending_repository,
        atomic_execution,
    )
    pending_manager = PendingOrderManager(
        pending_repository, paper_executor
    )
    recovery = RecoveryReconciler(
        order_repository, fill_repository, position_repository
    )
    settlement = PositionSettlementService(
        connection=connection,
        position_repository=position_writer,
        account_repository=account_writer,
        ledger_repository=ledger_writer,
        journal_repository=journal_writer,
        account=account,
    )
    selection_queue = ExplicitPaperSelectionQueue()

    symbols = [
        instrument.symbol
        for instrument in registry.all(tradable_only=True)
    ]
    runtime = RuntimeCycleOrchestrator(
        position_repository=position_repository,
        live_price_provider=live_price,
        account=account,
        audit_repository=audit_repository,
        pending_order_manager=pending_manager,
        recovery_reconciler=recovery,
        recovery_order_ids_provider=lambda: [
            str(row[0])
            for row in connection.execute(
                "SELECT order_id FROM orders ORDER BY order_id"
            )
        ],
        atomic_execution_service=atomic_execution,
        opportunity_pipeline=opportunity_pipeline,
        universe_provider=lambda: symbols,
        opportunity_top_n=10,
        paper_runtime=paper_runtime,
        selected_orders_provider=selection_queue.drain,
        account_repository=account_repository,
        settlement_service=settlement,
    )

    analytics = AnalyticsService(journal_repository)
    health = SystemHealthService(
        connection=connection,
        registry=registry,
        contract_specs=contract_specs,
        provider_routers=(live_router, candle_router),
        audit_repository=audit_repository,
        position_repository=position_repository,
        pending_repository=pending_repository,
    )

    def opportunities() -> list[GatedOpportunity]:
        return list(
            opportunity_pipeline.evaluate(symbols, top_n=10).qualified
        )

    api = TradingApiService(
        mode=SystemMode.PAPER,
        version="3.0.0-dev2",
        cycle_runner=runtime.run,
        positions_provider=position_repository.list_open,
        opportunities_provider=opportunities,
        analytics_provider=lambda: analytics.detailed_performance(
            starting_equity=initial_equity
        ),
        readiness_provider=health.readiness,
    )

    return PaperApplication(
        mode=SystemMode.PAPER,
        connection=connection,
        registry=registry,
        mapper=mapper,
        live_router=live_router,
        candle_router=candle_router,
        account=account,
        position_repository=position_repository,
        pending_repository=pending_repository,
        opportunity_pipeline=opportunity_pipeline,
        runtime=runtime,
        analytics=analytics,
        health=health,
        api=api,
        selection_queue=selection_queue,
    )
