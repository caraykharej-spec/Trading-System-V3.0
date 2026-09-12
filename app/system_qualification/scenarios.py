from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import sqlite3
from typing import ClassVar

from app.core.enums import PositionSide
from app.data.market_data import Candle, LivePrice, MarketDataRequest
from app.data.provider_router import ProviderRouter
from app.data.providers.http import ProviderError
from app.execution.atomic_execution import AtomicExecutionService
from app.execution.models import OrderRequest, OrderResult, OrderStatus, OrderType
from app.live_operation.activation import LiveActivationGate, LiveActivationRequest
from app.live_operation.circuit_breaker import LiveTradingCircuitBreaker
from app.live_operation.exchange_connector import (
    ConnectorStatus,
    ExchangeProductionConnector,
    VenuePosition,
)
from app.live_operation.execution_gateway import LiveExecutionGateway
from app.shadow_operation.repository import ShadowEvidenceRepository
from app.shadow_validation.validation import ShadowReport
from app.system_qualification.framework import (
    QualificationCase,
    QualificationReport,
    QualificationRunner,
    ScenarioObservation,
)
from interfaces.api.config import FastApiSettings

NOW = datetime(2026, 9, 12, 12, tzinfo=timezone.utc)


class PriceProvider:
    requires_credentials: ClassVar[bool] = False

    def __init__(self, name: str, *, fail: bool = False, stale: bool = False) -> None:
        self.name = name
        self.fail = fail
        self.stale = stale
        self.calls = 0

    def get_live_price(self, symbol: str) -> LivePrice:
        self.calls += 1
        if self.fail:
            raise ProviderError("injected provider outage")
        observed = NOW - timedelta(hours=1) if self.stale else NOW
        return LivePrice(symbol, Decimal("100"), observed, self.name)

    def get_candles(self, request: MarketDataRequest) -> list[Candle]:
        del request
        raise NotImplementedError


class CountingConnector(ExchangeProductionConnector):
    def __init__(self) -> None:
        self.submissions = 0

    def status(self) -> ConnectorStatus:
        return ConnectorStatus("INJECTED", True, True, True)

    def submit_order(self, order: OrderRequest) -> OrderResult:
        self.submissions += 1
        return OrderResult(order.order_id, OrderStatus.ACCEPTED, order.symbol)

    def open_positions(self) -> list[VenuePosition]:
        return []


class TransactionProbe:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class Writer:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.writes = 0

    def save_result(self, value: object) -> None:
        self._save(value)

    def save(self, value: object) -> None:
        self._save(value)

    def _save(self, value: object) -> None:
        del value
        self.writes += 1
        if self.fail:
            raise OSError("injected persistence failure")


def order() -> OrderRequest:
    return OrderRequest(
        "QUALIFICATION-ONLY", "BTC/USDT", PositionSide.LONG, OrderType.MARKET,
        Decimal("0.001"), None, Decimal("90"), Decimal("125"), Decimal("1"),
    )


def active_request(*, explicit: bool) -> LiveActivationRequest:
    return LiveActivationRequest(
        "production", True, True, True, True, True, True, explicit
    )


def primary_provider_outage_falls_back() -> ScenarioObservation:
    primary = PriceProvider("primary", fail=True)
    fallback = PriceProvider("fallback")
    price = ProviderRouter((primary, fallback), retry_attempts=1).get_live_price(
        "BTC/USDT", now=NOW
    )
    passed = price.provider == "fallback" and primary.calls == fallback.calls == 1
    return ScenarioObservation(
        passed, "fallback provides validated price", price.provider,
        ("provider_order", "retry_bound", "freshness_validation"),
    )


def all_providers_out_fail_closed() -> ScenarioObservation:
    router = ProviderRouter(
        (PriceProvider("one", fail=True), PriceProvider("two", fail=True)),
        retry_attempts=1,
    )
    try:
        router.get_live_price("BTC/USDT", now=NOW)
    except ProviderError:
        return ScenarioObservation(
            True, "no synthetic price is returned", "ProviderError",
            ("fail_closed", "no_default_price"),
        )
    return ScenarioObservation(False, "ProviderError", "unexpected price")


def stale_data_is_rejected() -> ScenarioObservation:
    router = ProviderRouter((PriceProvider("stale", stale=True),), retry_attempts=1)
    try:
        router.get_live_price("BTC/USDT", now=NOW)
    except ProviderError:
        return ScenarioObservation(
            True, "stale input is rejected", "ProviderError",
            ("freshness_gate",),
        )
    return ScenarioObservation(False, "ProviderError", "stale input accepted")


def persistence_failure_rolls_back() -> ScenarioObservation:
    transaction = TransactionProbe()
    orders, fills, positions = Writer(), Writer(fail=True), Writer()
    service = AtomicExecutionService(transaction, orders, fills, positions)
    request = order()
    result = OrderResult(
        request.order_id, OrderStatus.FILLED, request.symbol,
        filled_price=Decimal("100"), filled_at=NOW,
    )
    try:
        service.apply_fill(request, result, fill_id="INJECTED-FILL")
    except OSError:
        passed = transaction.rollbacks == 1 and transaction.commits == 0 and positions.writes == 0
        return ScenarioObservation(
            passed, "one rollback, no commit or position write",
            f"rollback={transaction.rollbacks},commit={transaction.commits},position={positions.writes}",
            ("atomic_execution", "transaction_rollback"),
        )
    return ScenarioObservation(False, "persistence exception", "unexpected commit")


def disabled_live_activation_blocks_submission() -> ScenarioObservation:
    connector = CountingConnector()
    activation = LiveActivationGate().evaluate(active_request(explicit=False))
    result = LiveExecutionGateway(connector).submit(
        order(), activation=activation, risk_approved=True
    )
    return ScenarioObservation(
        not result.accepted and connector.submissions == 0,
        "gateway rejects before connector call",
        f"accepted={result.accepted},connector_calls={connector.submissions}",
        ("explicit_enable", "execution_gateway"),
    )


def emergency_circuit_blocks_submission() -> ScenarioObservation:
    connector = CountingConnector()
    circuit = LiveTradingCircuitBreaker()
    circuit.trip("qualification injection")
    activation = LiveActivationGate().evaluate(active_request(explicit=True))
    result = LiveExecutionGateway(connector, circuit).submit(
        order(), activation=activation, risk_approved=True
    )
    return ScenarioObservation(
        not result.accepted and connector.submissions == 0,
        "open circuit rejects before connector call",
        f"accepted={result.accepted},connector_calls={connector.submissions}",
        ("emergency_halt", "execution_gateway"),
    )


def evidence_tampering_is_detected() -> ScenarioObservation:
    connection = sqlite3.connect(":memory:")
    repository = ShadowEvidenceRepository(connection)
    report = ShadowReport(
        "PASS", NOW.isoformat(), ("BTC/USDT",), ({"status": "PASS"},),
        decisions={"qualified": []},
    )
    stored = repository.append(report, run_id="qualification")
    connection.execute(
        "UPDATE shadow_evidence SET report_json='{}' WHERE sequence=?", (stored.sequence,)
    )
    connection.commit()
    valid = repository.verify_chain()
    connection.close()
    return ScenarioObservation(
        not valid, "modified ledger fails verification", f"chain_valid={valid}",
        ("report_digest", "hash_chain"),
    )


def evidence_backup_restores_valid_chain() -> ScenarioObservation:
    source = sqlite3.connect(":memory:")
    repository = ShadowEvidenceRepository(source)
    repository.append(
        ShadowReport("HOLD", NOW.isoformat(), ("BTC/USDT",), ({"status": "HOLD"},)),
        run_id="backup-source",
    )
    restored = sqlite3.connect(":memory:")
    source.backup(restored)
    summary = ShadowEvidenceRepository(restored).summary()
    source.close()
    restored.close()
    return ScenarioObservation(
        summary.total == 1 and summary.chain_valid,
        "online backup restores one valid chained record",
        f"records={summary.total},chain_valid={summary.chain_valid}",
        ("sqlite_online_backup", "post_restore_integrity"),
    )


def production_config_fails_closed() -> ScenarioObservation:
    try:
        FastApiSettings.from_env(
            {"TRADING_API_ENV": "production", "TRADING_API_ALLOWED_HOSTS": "api.example.com"}
        )
    except ValueError:
        return ScenarioObservation(
            True, "production without secret is rejected", "ValueError",
            ("production_auth", "fail_closed_configuration"),
        )
    return ScenarioObservation(False, "ValueError", "unsafe config accepted")


def default_cases() -> tuple[QualificationCase, ...]:
    return (
        QualificationCase("DATA-PRIMARY-OUTAGE", "market_data", True, primary_provider_outage_falls_back),
        QualificationCase("DATA-TOTAL-OUTAGE", "market_data", True, all_providers_out_fail_closed),
        QualificationCase("DATA-STALE", "market_data", True, stale_data_is_rejected),
        QualificationCase("EXEC-PERSISTENCE-ROLLBACK", "atomicity", True, persistence_failure_rolls_back),
        QualificationCase("LIVE-DISABLED", "live_safety", True, disabled_live_activation_blocks_submission),
        QualificationCase("LIVE-CIRCUIT-OPEN", "live_safety", True, emergency_circuit_blocks_submission),
        QualificationCase("EVIDENCE-TAMPER", "evidence", True, evidence_tampering_is_detected),
        QualificationCase("EVIDENCE-RESTORE", "recovery", True, evidence_backup_restores_valid_chain),
        QualificationCase("CONFIG-MISSING-SECRET", "security", True, production_config_fails_closed),
    )


def run_default_qualification() -> QualificationReport:
    return QualificationRunner(default_cases()).run()
