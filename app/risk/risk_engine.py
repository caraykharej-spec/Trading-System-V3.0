from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.models import Position
from app.portfolio.account import Account
from app.strategy.strategy_engine import StrategySignal, StrategyState
from app.universe.contract_specs import ContractSpec
from app.universe.instrument import AssetClass, Instrument
from app.risk.position_sizing import calculate_position_size
from app.risk.risk_policy import RiskPolicy
from app.risk.storm import storm_sl_loss_percent


@dataclass(frozen=True)
class RiskAssessment:
    approved: bool
    reasons: tuple[str, ...]
    equity: Decimal
    existing_open_risk: Decimal
    new_risk: Decimal
    aggregate_risk: Decimal
    risk_percent: Decimal
    quantity: Decimal
    total_amount: Decimal
    storm_sl_loss_percent: Decimal | None
    futures_capital_percent: Decimal


def _candidate_risk(*, total_amount: Decimal, entry: Decimal, stop_loss: Decimal, leverage: Decimal) -> Decimal:
    distance = abs(entry - stop_loss) / entry
    return total_amount * distance * leverage


def assess_risk(*, account: Account, positions: list[Position], signal: StrategySignal, instrument: Instrument, contract: ContractSpec, leverage: Decimal, policy: RiskPolicy = RiskPolicy(), provider: str | None = None, correlated_open_risk: Decimal = Decimal("0")) -> RiskAssessment:
    policy.validate()
    if signal.state is not StrategyState.READY_FOR_RISK_REVIEW:
        return RiskAssessment(False, ("strategy signal is not READY_FOR_RISK_REVIEW",), account.equity, Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), None, Decimal("0"))
    if account.equity <= 0:
        raise ValueError("account equity must be positive")
    if leverage <= 0:
        raise ValueError("leverage must be positive")
    contract.validate()
    if contract.max_leverage is not None and leverage > contract.max_leverage:
        return RiskAssessment(False, ("leverage exceeds contract maximum",), account.equity, Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), None, Decimal("0"))
    if signal.entry <= 0 or signal.stop_loss <= 0 or signal.entry == signal.stop_loss:
        raise ValueError("invalid signal levels")

    equity = account.equity
    existing = account.aggregate_open_risk(positions)
    risk_budget = equity * policy.max_risk_per_trade_percent / Decimal("100")
    aggregate_budget = equity * policy.max_aggregate_open_risk_percent / Decimal("100")
    available_aggregate = aggregate_budget - existing
    if available_aggregate <= 0:
        return RiskAssessment(False, ("aggregate open-risk budget exhausted",), equity, existing, Decimal("0"), existing, existing / equity * Decimal("100"), Decimal("0"), Decimal("0"), None, Decimal("0"))

    effective_risk_budget = min(risk_budget, available_aggregate)
    sizing_percent = effective_risk_budget / equity * Decimal("100")
    quantity, total_amount = calculate_position_size(equity=equity, entry=signal.entry, stop_loss=signal.stop_loss, leverage=leverage, risk_percent=sizing_percent, contract=contract)
    reasons: list[str] = []
    if quantity <= 0 or total_amount <= 0:
        reasons.append("minimum quantity/contract step prevents a valid position")
    new_risk = _candidate_risk(total_amount=total_amount, entry=signal.entry, stop_loss=signal.stop_loss, leverage=leverage)
    aggregate = existing + new_risk
    risk_percent = new_risk / equity * Decimal("100")

    storm_loss: Decimal | None = None
    if provider and provider.upper() == "STORM":
        storm_loss = storm_sl_loss_percent(entry=signal.entry, stop_loss=signal.stop_loss, leverage=leverage)
        if storm_loss > policy.max_storm_sl_loss_percent_of_position_amount:
            reasons.append("Storm SL loss exceeds hard 10% position-amount limit")

    futures_capital = Decimal("0")
    if instrument.asset_class is AssetClass.CRYPTO and leverage > 1:
        futures_capital = total_amount / equity * Decimal("100")
        existing_futures = sum(p.total_amount for p in positions if p.leverage > 1 and p.status.value == "OPEN")
        futures_capital = (existing_futures + total_amount) / equity * Decimal("100")
        if futures_capital > policy.max_futures_capital_percent:
            reasons.append("futures capital exceeds portfolio limit")

    if risk_percent > policy.max_risk_per_trade_percent:
        reasons.append("new trade risk exceeds per-trade limit")
    if aggregate > aggregate_budget:
        reasons.append("aggregate open risk exceeds portfolio limit")
    if correlated_open_risk + new_risk > equity * policy.max_correlated_risk_percent / Decimal("100"):
        reasons.append("correlated risk exceeds portfolio limit")
    if contract.min_notional is not None and total_amount < contract.min_notional:
        reasons.append("position notional is below contract minimum")

    return RiskAssessment(not reasons, tuple(reasons), equity, existing, new_risk, aggregate, risk_percent, quantity, total_amount, storm_loss, futures_capital)
