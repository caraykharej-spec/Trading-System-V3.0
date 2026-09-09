from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from app.data.market_data import Candle
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
    """Event-driven multi-symbol backtest with one shared equity account.

    All symbols are processed on one chronological 15m timeline. Entries are
    generated only from completed candles and are filled on the next bar open.
    Aggregate risk, correlated risk, and futures-capital limits are evaluated
    against the same shared portfolio state.
    """

    def __init__(
        self,
        config: BacktestConfig | None = None,
        correlations: dict[tuple[str, str], Decimal] | None = None,
    ) -> None:
        self.config = config or BacktestConfig()
        self.correlations = correlations or {}
        self._helpers = BacktestEngine(self.config)

    def run(self, candles_by_symbol: dict[str, dict[str, list[Candle]]]) -> PortfolioBacktestResult:
        if not candles_by_symbol:
            raise ValueError("candles_by_symbol cannot be empty")

        prepared = {
            symbol: self._helpers._prepare(symbol, source)
            for symbol, source in candles_by_symbol.items()
        }
        timeline = sorted({bar.timestamp for data in prepared.values() for bar in data["15m"]})
        if not timeline:
            raise ValueError("No 15m candles available")

        states = {
            symbol: {"bars": data["15m"], "index": 0, "pending": None, "open": [], "trades": [], "rejected": 0}
            for symbol, data in prepared.items()
        }
        equity = self.config.initial_equity
        equity_curve: list[Decimal] = [equity]
        max_concurrent = {symbol: 0 for symbol in prepared}

        for timestamp in timeline:
            # A single event may contain bars for several symbols. Every symbol
            # observes the same portfolio equity before the event's fills.
            event_symbols = [s for s in sorted(prepared) if self._bar_at(states[s]["bars"], timestamp) is not None]

            # 1. Fill pending signals at each symbol's next 15m open.
            for symbol in event_symbols:
                state = states[symbol]
                bar = self._bar_at(state["bars"], timestamp)
                if bar is None or state["pending"] is None:
                    continue
                signal: StrategySignal = state["pending"]
                state["pending"] = None
                if signal.direction == "SHORT" and not self.config.allow_short:
                    state["rejected"] += 1
                    continue
                candidate = self._open_trade(signal, bar, equity, state["open"], states, symbol)
                if candidate is not None:
                    equity -= candidate.entry_commission
                    state["open"].append(candidate)
                    max_concurrent[symbol] = max(max_concurrent[symbol], len(state["open"]))

            # 2. Manage all positions against this event's OHLC data.
            for symbol in event_symbols:
                state = states[symbol]
                bar = self._bar_at(state["bars"], timestamp)
                if bar is None:
                    continue
                remaining: list[_OpenTrade] = []
                for trade in state["open"]:
                    exit_price, reason = self._helpers._intrabar_exit(trade, bar)
                    if exit_price is None:
                        remaining.append(trade)
                        continue
                    exit_price = self._helpers._apply_exit_slippage(trade.signal.direction, exit_price)
                    gross_pnl = self._helpers._pnl(trade, exit_price)
                    exit_commission = trade.total_amount * self.config.commission_percent / Decimal("100")
                    net_pnl = gross_pnl - exit_commission
                    equity += net_pnl
                    state["trades"].append(self._trade_record(symbol, trade, bar, exit_price, net_pnl, exit_commission, reason))
                state["open"] = remaining

            equity_curve.append(equity)

            # 3. Generate signals from completed candles. A signal becomes
            # pending and can only fill at the next 15m event for that symbol.
            decision_time = timestamp + self._helpers._duration("15m")
            for symbol in event_symbols:
                state = states[symbol]
                snapshots = self._helpers._snapshots_at(symbol, prepared[symbol], decision_time)
                if snapshots is None:
                    continue
                try:
                    signal = evaluate_strategy(
                        snapshots["1d"], snapshots["4h"], snapshots["1h"], snapshots["15m"]
                    )
                    if signal.state is StrategyState.READY_FOR_RISK_REVIEW:
                        state["pending"] = signal
                    else:
                        state["rejected"] += 1
                except (ValueError, ArithmeticError, IndexError):
                    state["rejected"] += 1

        # Mark remaining positions to the final available close for each symbol.
        for symbol, state in states.items():
            if not state["open"]:
                continue
            final_bar = state["bars"][-1]
            for trade in state["open"]:
                exit_price = self._helpers._apply_exit_slippage(trade.signal.direction, final_bar.close)
                gross_pnl = self._helpers._pnl(trade, exit_price)
                exit_commission = trade.total_amount * self.config.commission_percent / Decimal("100")
                net_pnl = gross_pnl - exit_commission
                equity += net_pnl
                state["trades"].append(self._trade_record(symbol, trade, final_bar, exit_price, net_pnl, exit_commission, "END_OF_TEST"))
            state["open"] = []
            equity_curve.append(equity)

        results: dict[str, BacktestResult] = {}
        for symbol, state in states.items():
            trades = tuple(state["trades"])
            symbol_initial = self.config.initial_equity
            symbol_pnl = sum((t.realized_pnl for t in trades), Decimal("0"))
            symbol_final = symbol_initial + symbol_pnl
            # Per-symbol metrics are descriptive only; portfolio constraints were
            # enforced on the shared account above.
            win_rate, profit_factor, max_dd, total_return = calculate_metrics(
                symbol_initial, symbol_final, trades, [symbol_initial]
            )
            results[symbol] = BacktestResult(
                initial_equity=symbol_initial,
                final_equity=symbol_final,
                trades=trades,
                rejected_signals=state["rejected"],
                open_positions_at_end=0,
                max_drawdown_percent=max_dd,
                win_rate_percent=win_rate,
                profit_factor=profit_factor,
                total_return_percent=total_return,
                max_concurrent_positions=max_concurrent[symbol],
            )

        net_pnl = equity - self.config.initial_equity
        _, _, max_drawdown, total_return = calculate_metrics(
            self.config.initial_equity, equity, tuple(t for s in states.values() for t in s["trades"]), equity_curve
        )
        return PortfolioBacktestResult(
            results=results,
            initial_equity=self.config.initial_equity,
            final_equity=equity,
            total_return_percent=total_return,
            max_drawdown_percent=max_drawdown,
            total_trades=sum(len(s["trades"]) for s in states.values()),
            equity_curve=tuple(equity_curve),
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
        # One live position per symbol prevents duplicated exposure from repeated
        # signals while preserving the user's no-position-count-cap requirement.
        if existing:
            return None
        entry = self._helpers._apply_entry_slippage(signal.direction, bar.open)
        distance = abs(entry - signal.stop_loss) / entry
        if distance <= 0 or signal.stop_loss <= 0 or equity <= 0:
            return None

        risk_cash = equity * self.config.risk_per_trade_percent / Decimal("100")
        aggregate_budget = equity * self.config.max_aggregate_risk_percent / Decimal("100")
        current_risk = sum(
            self._helpers._risk_cash(trade)
            for state in states.values()
            for trade in state["open"]
        )
        if current_risk + risk_cash > aggregate_budget:
            return None

        correlated_risk = self._correlated_risk(symbol, risk_cash, states)
        if correlated_risk > equity * Decimal("2") / Decimal("100"):
            return None

        amount = risk_cash / distance
        current_capital = sum(
            trade.total_amount
            for state in states.values()
            for trade in state["open"]
        )
        capital_budget = equity * self.config.max_futures_capital_percent / Decimal("100")
        if current_capital + amount > capital_budget:
            return None

        leverage = Decimal("1")
        quantity = amount / entry
        commission = amount * self.config.commission_percent / Decimal("100")
        return _OpenTrade(str(uuid4()), signal, bar.timestamp, entry, quantity, amount, leverage, commission)

    def _correlated_risk(self, symbol: str, new_risk: Decimal, states: dict[str, dict]) -> Decimal:
        total = Decimal("0")
        for other, state in states.items():
            if other == symbol:
                continue
            correlation = self.correlations.get((symbol, other), self.correlations.get((other, symbol), Decimal("0")))
            correlation = max(Decimal("-1"), min(Decimal("1"), correlation))
            if correlation <= 0:
                continue
            existing_risk = sum(self._helpers._risk_cash(t) for t in state["open"])
            total += new_risk * correlation + existing_risk * correlation
        return total

    @staticmethod
    def _bar_at(bars: list[Candle], timestamp: datetime) -> Candle | None:
        # Bars are small in a backtest, and the explicit lookup avoids assumptions
        # about contiguous timestamps or identical calendars across symbols.
        for bar in bars:
            if bar.timestamp == timestamp:
                return bar
        return None

    @staticmethod
    def _trade_record(symbol: str, trade: _OpenTrade, bar: Candle, exit_price: Decimal, net_pnl: Decimal, exit_commission: Decimal, reason: str) -> TradeRecord:
        return TradeRecord(
            position_id=trade.position_id,
            symbol=symbol,
            direction=trade.signal.direction,
            setup=trade.signal.setup,
            entry_time=trade.entry_time,
            entry_price=trade.entry_price,
            exit_time=bar.timestamp,
            exit_price=exit_price,
            stop_loss=trade.signal.stop_loss,
            target=trade.signal.target,
            quantity=trade.quantity,
            total_amount=trade.total_amount,
            leverage=trade.leverage,
            realized_pnl=net_pnl,
            commission=trade.entry_commission + exit_commission,
            exit_reason=reason,
        )
