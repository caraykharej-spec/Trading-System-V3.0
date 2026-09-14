from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from app.data.market_data import Candle
from app.market.analysis import MarketSnapshot, analyze_market
from app.risk.risk_math import candidate_risk_amount, risk_budget_amount
from app.strategy.rules import DEFAULT_RULES, StrategyRules
from app.strategy.strategy_engine import StrategySignal, StrategyState, evaluate_strategy

from .costs import BacktestCostModel
from .diagnostics import BacktestDiagnosticEvent
from .incremental_snapshots import IncrementalSnapshotCursor
from .metrics import calculate_metrics
from .models import BacktestConfig, BacktestResult, TradeRecord


_TIMEFRAME_MINUTES = {"15m": 15, "1h": 60, "4h": 240, "1d": 1440}
DiagnosticObserver = Callable[[BacktestDiagnosticEvent], None]


@dataclass
class _OpenTrade:
    position_id: str
    signal: StrategySignal
    entry_time: datetime
    entry_price: Decimal
    quantity: Decimal
    total_amount: Decimal
    leverage: Decimal
    entry_commission: Decimal
    funding_cost: Decimal = Decimal("0")


class BacktestEngine:
    """Deterministic OHLC backtester sharing strategy and core risk arithmetic."""

    def __init__(
        self,
        config: BacktestConfig | None = None,
        *,
        rules: StrategyRules = DEFAULT_RULES,
    ) -> None:
        self.config = config or BacktestConfig()
        self.rules = rules
        self.costs = BacktestCostModel(
            commission_percent=self.config.commission_percent,
            spread_percent=self.config.spread_percent,
            slippage_percent=self.config.slippage_percent,
            funding_rate_percent_per_day=self.config.funding_rate_percent_per_day,
        )
        self._snapshot_cursors: dict[
            tuple[str, int],
            IncrementalSnapshotCursor,
        ] = {}

    def _reset_snapshot_cache(self) -> None:
        self._snapshot_cursors.clear()

    @staticmethod
    def _emit(
        observer: DiagnosticObserver | None,
        timestamp: datetime,
        code: str,
        *,
        signal: StrategySignal | None = None,
        reasons: tuple[str, ...] = (),
    ) -> None:
        if observer is None:
            return
        observer(
            BacktestDiagnosticEvent(
                timestamp=timestamp,
                code=code,
                reasons=reasons,
                direction=getattr(signal, "direction", None),
                setup=getattr(signal, "setup", None),
                rr=getattr(signal, "rr", None),
                score=getattr(signal, "score", None),
                confidence=getattr(signal, "confidence", None),
            )
        )

    @staticmethod
    def _strategy_failure_reason(exc: BaseException) -> str:
        message = str(exc)
        if message == "No aligned HTF direction":
            return "NO_ALIGNED_HTF_DIRECTION"
        if message == "No approved setup":
            return "NO_APPROVED_SETUP"
        if message == "No valid entry/SL/target levels":
            return "NO_VALID_LEVELS"
        return "STRATEGY_EVALUATION_ERROR"

    def run(
        self,
        symbol: str,
        candles_by_timeframe: dict[str, list[Candle]],
        evaluation_start: datetime | None = None,
        *,
        diagnostic_observer: DiagnosticObserver | None = None,
    ) -> BacktestResult:
        self._reset_snapshot_cache()
        candles = self._prepare(symbol, candles_by_timeframe)
        fifteen = candles["15m"]
        equity = self.config.initial_equity
        equity_curve: list[Decimal] = [equity]
        trades: list[TradeRecord] = []
        open_trades: list[_OpenTrade] = []
        pending_signal: StrategySignal | None = None
        rejected = 0
        max_concurrent = 0

        for bar in fifteen:
            in_test = evaluation_start is None or bar.timestamp >= evaluation_start

            if in_test and pending_signal is not None:
                if pending_signal.direction == "SHORT" and not self.config.allow_short:
                    rejected += 1
                    self._emit(
                        diagnostic_observer,
                        bar.timestamp,
                        "ENTRY_REJECT",
                        signal=pending_signal,
                        reasons=("SHORT_DISABLED",),
                    )
                else:
                    candidate, entry_reject_reason = self._open_trade_with_reason(
                        pending_signal, bar, equity, open_trades
                    )
                    if candidate is not None:
                        equity -= candidate.entry_commission
                        open_trades.append(candidate)
                        max_concurrent = max(max_concurrent, len(open_trades))
                        self._emit(
                            diagnostic_observer,
                            bar.timestamp,
                            "TRADE_OPENED",
                            signal=pending_signal,
                        )
                    elif entry_reject_reason is not None:
                        self._emit(
                            diagnostic_observer,
                            bar.timestamp,
                            "ENTRY_REJECT",
                            signal=pending_signal,
                            reasons=(entry_reject_reason,),
                        )
                pending_signal = None

            remaining: list[_OpenTrade] = []
            for trade in open_trades:
                funding = self.costs.funding(trade.signal.direction, trade.total_amount, 15)
                trade.funding_cost += funding
                equity -= funding
                exit_price, reason = self._intrabar_exit(trade, bar)
                if exit_price is None:
                    remaining.append(trade)
                    continue
                adjusted_exit = self.costs.exit_price(trade.signal.direction, exit_price)
                gross_pnl = self._pnl(trade, adjusted_exit)
                exit_commission = self.costs.commission(trade.total_amount)
                net_pnl = (
                    gross_pnl
                    - trade.entry_commission
                    - exit_commission
                    - trade.funding_cost
                )
                equity += gross_pnl - exit_commission
                trades.append(
                    self._trade_record(
                        symbol,
                        trade,
                        bar,
                        adjusted_exit,
                        net_pnl,
                        exit_commission,
                        reason,
                    )
                )
            open_trades = remaining
            equity_curve.append(equity)

            decision_time = bar.timestamp + self._duration("15m")
            snapshots = self._snapshots_at(symbol, candles, decision_time)

            # Pre-evaluation candles are indicator warm-up only. Advancing the
            # snapshot cursor here is required for EMA200 and other stateful
            # indicators, but no strategy decision/rejection is measured yet.
            if not in_test:
                continue

            if snapshots is None:
                self._emit(
                    diagnostic_observer,
                    decision_time,
                    "DECISION_NO_SNAPSHOT",
                )
                continue

            try:
                signal = evaluate_strategy(
                    snapshots["1d"],
                    snapshots["4h"],
                    snapshots["1h"],
                    snapshots["15m"],
                    rules=self.rules,
                )
                if signal.state is StrategyState.READY_FOR_RISK_REVIEW:
                    pending_signal = signal
                    self._emit(
                        diagnostic_observer,
                        decision_time,
                        "READY_FOR_RISK_REVIEW",
                        signal=signal,
                    )
                else:
                    rejected += 1
                    self._emit(
                        diagnostic_observer,
                        decision_time,
                        "STRATEGY_SIGNAL_REJECT",
                        signal=signal,
                        reasons=tuple(signal.reasons),
                    )
            except (ValueError, ArithmeticError, IndexError) as exc:
                rejected += 1
                self._emit(
                    diagnostic_observer,
                    decision_time,
                    "STRATEGY_PRE_SIGNAL_REJECT",
                    reasons=(self._strategy_failure_reason(exc),),
                )

        if pending_signal is not None:
            final_decision_time = fifteen[-1].timestamp + self._duration("15m")
            self._emit(
                diagnostic_observer,
                final_decision_time,
                "PENDING_SIGNAL_END_OF_TEST",
                signal=pending_signal,
            )

        if open_trades:
            final_bar = fifteen[-1]
            for trade in open_trades:
                exit_price = self.costs.exit_price(trade.signal.direction, final_bar.close)
                gross_pnl = self._pnl(trade, exit_price)
                exit_commission = self.costs.commission(trade.total_amount)
                net_pnl = (
                    gross_pnl
                    - trade.entry_commission
                    - exit_commission
                    - trade.funding_cost
                )
                equity += gross_pnl - exit_commission
                trades.append(
                    self._trade_record(
                        symbol,
                        trade,
                        final_bar,
                        exit_price,
                        net_pnl,
                        exit_commission,
                        "END_OF_TEST",
                    )
                )
            open_trades = []
            equity_curve.append(equity)

        win_rate, profit_factor, max_drawdown, total_return = calculate_metrics(
            self.config.initial_equity, equity, tuple(trades), equity_curve
        )
        return BacktestResult(
            initial_equity=self.config.initial_equity,
            final_equity=equity,
            trades=tuple(trades),
            rejected_signals=rejected,
            open_positions_at_end=len(open_trades),
            max_drawdown_percent=max_drawdown,
            win_rate_percent=win_rate,
            profit_factor=profit_factor,
            total_return_percent=total_return,
            max_concurrent_positions=max_concurrent,
        )

    @staticmethod
    def _prepare(
        symbol: str, source: dict[str, list[Candle]]
    ) -> dict[str, list[Candle]]:
        missing = set(_TIMEFRAME_MINUTES) - set(source)
        if missing:
            raise ValueError(f"Missing required timeframes: {sorted(missing)}")
        prepared: dict[str, list[Candle]] = {}
        for timeframe in _TIMEFRAME_MINUTES:
            rows = sorted(
                (candle for candle in source[timeframe] if candle.symbol == symbol),
                key=lambda candle: candle.timestamp,
            )
            if not rows:
                raise ValueError(f"No candles for {symbol} at {timeframe}")
            prepared[timeframe] = rows
        return prepared

    def _snapshots_at(
        self,
        symbol: str,
        candles: dict[str, list[Candle]],
        decision_time: datetime,
    ) -> dict[str, MarketSnapshot] | None:
        key = (symbol, id(candles))
        cursor = self._snapshot_cursors.get(key)
        if cursor is None:
            cursor = IncrementalSnapshotCursor(symbol, candles)
            self._snapshot_cursors[key] = cursor
        return cursor.snapshots_at(decision_time)

    def _snapshots_at_reference(
        self,
        symbol: str,
        candles: dict[str, list[Candle]],
        decision_time: datetime,
    ) -> dict[str, MarketSnapshot] | None:
        """Pre-checkpoint reference implementation used by equivalence tests."""
        snapshots: dict[str, MarketSnapshot] = {}
        for timeframe in ("1d", "4h", "1h", "15m"):
            duration = self._duration(timeframe)
            completed = [
                candle
                for candle in candles[timeframe]
                if candle.timestamp + duration <= decision_time
            ]
            if len(completed) < 2:
                return None
            snapshots[timeframe] = analyze_market(symbol, timeframe, completed)
        return snapshots

    def _open_trade_with_reason(
        self,
        signal: StrategySignal,
        bar: Candle,
        equity: Decimal,
        existing: list[_OpenTrade],
    ) -> tuple[_OpenTrade | None, str | None]:
        entry = self.costs.entry_price(signal.direction, bar.open)
        distance = abs(entry - signal.stop_loss) / entry
        if distance <= 0 or signal.stop_loss <= 0:
            return None, "INVALID_STOP_DISTANCE"
        risk_cash = risk_budget_amount(equity, self.config.risk_per_trade_percent)
        current_risk = sum((self._risk_cash(trade) for trade in existing), Decimal("0"))
        aggregate_budget = risk_budget_amount(equity, self.config.max_aggregate_risk_percent)
        if current_risk + risk_cash > aggregate_budget:
            return None, "AGGREGATE_RISK_LIMIT"
        amount = risk_cash / distance
        current_capital = sum((trade.total_amount for trade in existing), Decimal("0"))
        max_capital = risk_budget_amount(equity, self.config.max_futures_capital_percent)
        if current_capital + amount > max_capital:
            return None, "FUTURES_CAPITAL_LIMIT"
        leverage = Decimal("1")
        quantity = amount / entry
        commission = self.costs.commission(amount)
        return (
            _OpenTrade(
                str(uuid4()),
                signal,
                bar.timestamp,
                entry,
                quantity,
                amount,
                leverage,
                commission,
            ),
            None,
        )

    def _open_trade(
        self,
        signal: StrategySignal,
        bar: Candle,
        equity: Decimal,
        existing: list[_OpenTrade],
    ) -> _OpenTrade | None:
        candidate, _ = self._open_trade_with_reason(signal, bar, equity, existing)
        return candidate

    @staticmethod
    def _risk_cash(trade: _OpenTrade) -> Decimal:
        return candidate_risk_amount(
            total_amount=trade.total_amount,
            entry=trade.entry_price,
            stop_loss=trade.signal.stop_loss,
            leverage=trade.leverage,
        )

    @staticmethod
    def _pnl(trade: _OpenTrade, exit_price: Decimal) -> Decimal:
        move = (exit_price - trade.entry_price) / trade.entry_price
        if trade.signal.direction == "SHORT":
            move = -move
        return trade.total_amount * move * trade.leverage

    @staticmethod
    def _intrabar_exit(trade: _OpenTrade, bar: Candle) -> tuple[Decimal | None, str]:
        sl = trade.signal.stop_loss
        tp = trade.signal.target
        if trade.signal.direction == "LONG":
            if bar.low <= sl:
                return sl, "STOP_LOSS"
            if tp > 0 and bar.high >= tp:
                return tp, "TAKE_PROFIT"
        else:
            if bar.high >= sl:
                return sl, "STOP_LOSS"
            if tp > 0 and bar.low <= tp:
                return tp, "TAKE_PROFIT"
        return None, ""

    def _apply_entry_slippage(self, direction: str, price: Decimal) -> Decimal:
        return self.costs.entry_price(direction, price)

    def _apply_exit_slippage(self, direction: str, price: Decimal) -> Decimal:
        return self.costs.exit_price(direction, price)

    @staticmethod
    def _trade_record(
        symbol: str,
        trade: _OpenTrade,
        bar: Candle,
        exit_price: Decimal,
        net_pnl: Decimal,
        exit_commission: Decimal,
        reason: str,
    ) -> TradeRecord:
        return TradeRecord(
            position_id=trade.position_id,
            symbol=symbol,
            direction=trade.signal.direction,
            setup=trade.signal.setup,
            entry_time=trade.entry_time,
            entry_price=trade.entry_price,
            exit_time=bar.timestamp + timedelta(minutes=15),
            exit_price=exit_price,
            stop_loss=trade.signal.stop_loss,
            target=trade.signal.target,
            quantity=trade.quantity,
            total_amount=trade.total_amount,
            leverage=trade.leverage,
            realized_pnl=net_pnl,
            commission=trade.entry_commission + exit_commission,
            exit_reason=reason,
            funding_cost=trade.funding_cost,
        )

    @staticmethod
    def _duration(timeframe: str) -> timedelta:
        return timedelta(minutes=_TIMEFRAME_MINUTES[timeframe])
