from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from app.data.market_data import Candle
from app.risk.risk_math import risk_budget_amount
from app.strategy.strategy_engine import StrategySignal, StrategyState, evaluate_strategy

from .engine import BacktestEngine, _OpenTrade
from .metrics import calculate_metrics
from .models import BacktestConfig, BacktestResult, TradeRecord


@dataclass(frozen=True)
class PortfolioBacktestResult:
    results: dict[str, BacktestResult]
    initial_equity: Decimal
    final_equity: Decimal
    total_return_percent: Decimal
    max_drawdown_percent: Decimal
    total_trades: int
    equity_curve: tuple[Decimal, ...]


class PortfolioBacktestEngine:
    """Event-driven multi-symbol backtest with shared equity and cost accounting."""

    def __init__(
        self,
        config: BacktestConfig | None = None,
        correlations: dict[tuple[str, str], Decimal] | None = None,
    ) -> None:
        self.config = config or BacktestConfig()
        self.correlations = correlations or {}
        self._helpers = BacktestEngine(self.config)

    def run(
        self, candles_by_symbol: dict[str, dict[str, list[Candle]]]
    ) -> PortfolioBacktestResult:
        if not candles_by_symbol:
            raise ValueError("candles_by_symbol cannot be empty")
        prepared = {
            symbol: self._helpers._prepare(symbol, source)
            for symbol, source in candles_by_symbol.items()
        }
        timeline = sorted(
            {candle.timestamp for data in prepared.values() for candle in data["15m"]}
        )
        if not timeline:
            raise ValueError("No 15m candles available")
        states = {
            symbol: {
                "bars": data["15m"],
                "pending": None,
                "open": [],
                "trades": [],
                "rejected": 0,
            }
            for symbol, data in prepared.items()
        }
        equity = self.config.initial_equity
        equity_curve = [equity]
        max_concurrent = {symbol: 0 for symbol in prepared}

        for timestamp in timeline:
            events = {
                symbol: self._bar_at(state["bars"], timestamp)
                for symbol, state in states.items()
            }
            events = {symbol: bar for symbol, bar in events.items() if bar is not None}

            for symbol in sorted(events):
                state = states[symbol]
                signal = state["pending"]
                state["pending"] = None
                if signal is None or (
                    signal.direction == "SHORT" and not self.config.allow_short
                ):
                    if signal is not None:
                        state["rejected"] += 1
                    continue
                candidate = self._open_trade(
                    signal, events[symbol], equity, state["open"], states, symbol
                )
                if candidate is not None:
                    equity -= candidate.entry_commission
                    state["open"].append(candidate)
                    max_concurrent[symbol] = max(
                        max_concurrent[symbol], len(state["open"])
                    )

            for symbol in sorted(events):
                state = states[symbol]
                bar = events[symbol]
                remaining: list[_OpenTrade] = []
                for trade in state["open"]:
                    funding = self._helpers.costs.funding(
                        trade.signal.direction, trade.total_amount, 15
                    )
                    trade.funding_cost += funding
                    equity -= funding
                    raw_exit, reason = self._helpers._intrabar_exit(trade, bar)
                    if raw_exit is None:
                        remaining.append(trade)
                        continue
                    exit_price = self._helpers._apply_exit_slippage(
                        trade.signal.direction, raw_exit
                    )
                    gross = self._helpers._pnl(trade, exit_price)
                    exit_commission = self._helpers.costs.commission(trade.total_amount)
                    net = (
                        gross
                        - trade.entry_commission
                        - exit_commission
                        - trade.funding_cost
                    )
                    equity += gross - exit_commission
                    state["trades"].append(
                        self._trade_record(
                            symbol,
                            trade,
                            bar,
                            exit_price,
                            net,
                            exit_commission,
                            reason,
                        )
                    )
                state["open"] = remaining

            equity_curve.append(equity)
            decision_time = timestamp + self._helpers._duration("15m")
            for symbol in sorted(events):
                snapshots = self._helpers._snapshots_at(
                    symbol, prepared[symbol], decision_time
                )
                if snapshots is None:
                    continue
                try:
                    signal = evaluate_strategy(
                        snapshots["1d"],
                        snapshots["4h"],
                        snapshots["1h"],
                        snapshots["15m"],
                    )
                    if signal.state is StrategyState.READY_FOR_RISK_REVIEW:
                        states[symbol]["pending"] = signal
                    else:
                        states[symbol]["rejected"] += 1
                except (ValueError, ArithmeticError, IndexError):
                    states[symbol]["rejected"] += 1

        for symbol, state in states.items():
            if not state["open"]:
                continue
            final_bar = state["bars"][-1]
            for trade in state["open"]:
                exit_price = self._helpers._apply_exit_slippage(
                    trade.signal.direction, final_bar.close
                )
                gross = self._helpers._pnl(trade, exit_price)
                exit_commission = self._helpers.costs.commission(trade.total_amount)
                net = (
                    gross
                    - trade.entry_commission
                    - exit_commission
                    - trade.funding_cost
                )
                equity += gross - exit_commission
                state["trades"].append(
                    self._trade_record(
                        symbol,
                        trade,
                        final_bar,
                        exit_price,
                        net,
                        exit_commission,
                        "END_OF_TEST",
                    )
                )
            state["open"] = []
            equity_curve.append(equity)

        results: dict[str, BacktestResult] = {}
        all_trades: list[TradeRecord] = []
        for symbol, state in states.items():
            trades = tuple(state["trades"])
            all_trades.extend(trades)
            pnl = sum((trade.realized_pnl for trade in trades), Decimal("0"))
            final = self.config.initial_equity + pnl
            win, profit_factor, drawdown, total_return = calculate_metrics(
                self.config.initial_equity,
                final,
                trades,
                [self.config.initial_equity, final],
            )
            results[symbol] = BacktestResult(
                self.config.initial_equity,
                final,
                trades,
                state["rejected"],
                0,
                drawdown,
                win,
                profit_factor,
                total_return,
                max_concurrent[symbol],
            )

        _, _, drawdown, total_return = calculate_metrics(
            self.config.initial_equity, equity, tuple(all_trades), equity_curve
        )
        return PortfolioBacktestResult(
            results,
            self.config.initial_equity,
            equity,
            total_return,
            drawdown,
            len(all_trades),
            tuple(equity_curve),
        )

    def _open_trade(
        self,
        signal: StrategySignal,
        bar: Candle,
        equity: Decimal,
        existing: list[_OpenTrade],
        states: dict[str, dict],
        symbol: str,
    ) -> _OpenTrade | None:
        if existing or equity <= 0:
            return None
        entry = self._helpers._apply_entry_slippage(signal.direction, bar.open)
        distance = abs(entry - signal.stop_loss) / entry
        if distance <= 0 or signal.stop_loss <= 0:
            return None
        risk_cash = risk_budget_amount(equity, self.config.risk_per_trade_percent)
        current_risk = sum(
            (
                self._helpers._risk_cash(trade)
                for state in states.values()
                for trade in state["open"]
            ),
            Decimal("0"),
        )
        if current_risk + risk_cash > risk_budget_amount(
            equity, self.config.max_aggregate_risk_percent
        ):
            return None
        correlated = self._correlated_risk(symbol, risk_cash, states)
        if correlated > risk_budget_amount(equity, Decimal("2")):
            return None
        amount = risk_cash / distance
        capital = sum(
            (
                trade.total_amount
                for state in states.values()
                for trade in state["open"]
            ),
            Decimal("0"),
        )
        if capital + amount > risk_budget_amount(
            equity, self.config.max_futures_capital_percent
        ):
            return None
        leverage = Decimal("1")
        return _OpenTrade(
            str(uuid4()),
            signal,
            bar.timestamp,
            entry,
            amount / entry,
            amount,
            leverage,
            self._helpers.costs.commission(amount),
        )

    def _correlated_risk(
        self, symbol: str, new_risk: Decimal, states: dict[str, dict]
    ) -> Decimal:
        total = new_risk
        for other, state in states.items():
            if other == symbol:
                continue
            correlation = self.correlations.get(
                (symbol, other), self.correlations.get((other, symbol), Decimal("0"))
            )
            correlation = max(Decimal("-1"), min(Decimal("1"), correlation))
            if correlation <= 0:
                continue
            existing = sum(
                (self._helpers._risk_cash(trade) for trade in state["open"]),
                Decimal("0"),
            )
            total += existing * correlation
        return total

    @staticmethod
    def _bar_at(bars: list[Candle], timestamp: datetime) -> Candle | None:
        for bar in bars:
            if bar.timestamp == timestamp:
                return bar
        return None

    @staticmethod
    def _trade_record(
        symbol: str,
        trade: _OpenTrade,
        bar: Candle,
        exit_price: Decimal,
        net: Decimal,
        exit_commission: Decimal,
        reason: str,
    ) -> TradeRecord:
        return TradeRecord(
            trade.position_id,
            symbol,
            trade.signal.direction,
            trade.signal.setup,
            trade.entry_time,
            trade.entry_price,
            bar.timestamp,
            exit_price,
            trade.signal.stop_loss,
            trade.signal.target,
            trade.quantity,
            trade.total_amount,
            trade.leverage,
            net,
            trade.entry_commission + exit_commission,
            reason,
            trade.funding_cost,
        )
