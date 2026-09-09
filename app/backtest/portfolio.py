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
    """Event-driven multi-symbol backtest with one shared equity account."""

    def __init__(self, config: BacktestConfig | None = None, correlations: dict[tuple[str, str], Decimal] | None = None) -> None:
        self.config = config or BacktestConfig()
        self.correlations = correlations or {}
        self._helpers = BacktestEngine(self.config)

    def run(self, candles_by_symbol: dict[str, dict[str, list[Candle]]]) -> PortfolioBacktestResult:
        if not candles_by_symbol:
            raise ValueError("candles_by_symbol cannot be empty")
        prepared = {s: self._helpers._prepare(s, src) for s, src in candles_by_symbol.items()}
        timeline = sorted({c.timestamp for d in prepared.values() for c in d["15m"]})
        if not timeline:
            raise ValueError("No 15m candles available")
        states = {s: {"bars": d["15m"], "pending": None, "open": [], "trades": [], "rejected": 0} for s, d in prepared.items()}
        equity = self.config.initial_equity
        equity_curve = [equity]
        max_concurrent = {s: 0 for s in prepared}

        for timestamp in timeline:
            events = {s: self._bar_at(state["bars"], timestamp) for s, state in states.items()}
            events = {s: b for s, b in events.items() if b is not None}

            # Entries are evaluated against the same pre-event portfolio state.
            for symbol in sorted(events):
                state = states[symbol]
                signal = state["pending"]
                state["pending"] = None
                if signal is None or (signal.direction == "SHORT" and not self.config.allow_short):
                    if signal is not None:
                        state["rejected"] += 1
                    continue
                candidate = self._open_trade(signal, events[symbol], equity, state["open"], states, symbol)
                if candidate is not None:
                    equity -= candidate.entry_commission
                    state["open"].append(candidate)
                    max_concurrent[symbol] = max(max_concurrent[symbol], len(state["open"]))

            for symbol in sorted(events):
                state = states[symbol]
                bar = events[symbol]
                remaining = []
                for trade in state["open"]:
                    exit_price, reason = self._helpers._intrabar_exit(trade, bar)
                    if exit_price is None:
                        remaining.append(trade)
                        continue
                    exit_price = self._helpers._apply_exit_slippage(trade.signal.direction, exit_price)
                    gross = self._helpers._pnl(trade, exit_price)
                    exit_commission = trade.total_amount * self.config.commission_percent / Decimal("100")
                    net = gross - exit_commission
                    equity += net
                    state["trades"].append(self._trade_record(symbol, trade, bar, exit_price, net, exit_commission, reason))
                state["open"] = remaining

            equity_curve.append(equity)
            decision_time = timestamp + self._helpers._duration("15m")
            for symbol in sorted(events):
                snapshots = self._helpers._snapshots_at(symbol, prepared[symbol], decision_time)
                if snapshots is None:
                    continue
                try:
                    signal = evaluate_strategy(snapshots["1d"], snapshots["4h"], snapshots["1h"], snapshots["15m"])
                    if signal.state is StrategyState.READY_FOR_RISK_REVIEW:
                        states[symbol]["pending"] = signal
                    else:
                        states[symbol]["rejected"] += 1
                except (ValueError, ArithmeticError, IndexError):
                    states[symbol]["rejected"] += 1

        # Finalize remaining trades once, at each symbol's final close.
        for symbol, state in states.items():
            if not state["open"]:
                continue
            final_bar = state["bars"][-1]
            for trade in state["open"]:
                exit_price = self._helpers._apply_exit_slippage(trade.signal.direction, final_bar.close)
                gross = self._helpers._pnl(trade, exit_price)
                exit_commission = trade.total_amount * self.config.commission_percent / Decimal("100")
                net = gross - exit_commission
                equity += net
                state["trades"].append(self._trade_record(symbol, trade, final_bar, exit_price, net, exit_commission, "END_OF_TEST"))
            state["open"] = []
            equity_curve.append(equity)

        results = {}
        all_trades = []
        for symbol, state in states.items():
            trades = tuple(state["trades"])
            all_trades.extend(trades)
            # Symbol metrics are descriptive; execution used the shared portfolio account.
            pnl = sum((t.realized_pnl for t in trades), Decimal("0"))
            final = self.config.initial_equity + pnl
            win, pf, dd, ret = calculate_metrics(self.config.initial_equity, final, trades, [self.config.initial_equity])
            results[symbol] = BacktestResult(self.config.initial_equity, final, trades, state["rejected"], 0, dd, win, pf, ret, max_concurrent[symbol])

        _, _, dd, ret = calculate_metrics(self.config.initial_equity, equity, tuple(all_trades), equity_curve)
        return PortfolioBacktestResult(results, self.config.initial_equity, equity, ret, dd, len(all_trades), tuple(equity_curve))

    def _open_trade(self, signal: StrategySignal, bar: Candle, equity: Decimal, existing: list[_OpenTrade], states: dict[str, dict], symbol: str) -> _OpenTrade | None:
        if existing or equity <= 0:
            return None
        entry = self._helpers._apply_entry_slippage(signal.direction, bar.open)
        distance = abs(entry - signal.stop_loss) / entry
        if distance <= 0 or signal.stop_loss <= 0:
            return None
        risk_cash = equity * self.config.risk_per_trade_percent / Decimal("100")
        current_risk = sum(self._helpers._risk_cash(t) for s in states.values() for t in s["open"])
        if current_risk + risk_cash > equity * self.config.max_aggregate_risk_percent / Decimal("100"):
            return None
        correlated = self._correlated_risk(symbol, risk_cash, states)
        if correlated > equity * Decimal("2") / Decimal("100"):
            return None
        amount = risk_cash / distance
        capital = sum(t.total_amount for s in states.values() for t in s["open"])
        if capital + amount > equity * self.config.max_futures_capital_percent / Decimal("100"):
            return None
        leverage = Decimal("1")
        return _OpenTrade(str(uuid4()), signal, bar.timestamp, entry, amount / entry, amount, leverage, amount * self.config.commission_percent / Decimal("100"))

    def _correlated_risk(self, symbol: str, new_risk: Decimal, states: dict[str, dict]) -> Decimal:
        total = Decimal("0")
        for other, state in states.items():
            if other == symbol:
                continue
            corr = self.correlations.get((symbol, other), self.correlations.get((other, symbol), Decimal("0")))
            corr = max(Decimal("-1"), min(Decimal("1"), corr))
            if corr > 0:
                total += (new_risk + sum(self._helpers._risk_cash(t) for t in state["open"])) * corr
        return total

    @staticmethod
    def _bar_at(bars: list[Candle], timestamp: datetime) -> Candle | None:
        for bar in bars:
            if bar.timestamp == timestamp:
                return bar
        return None

    @staticmethod
    def _trade_record(symbol: str, trade: _OpenTrade, bar: Candle, exit_price: Decimal, net: Decimal, exit_commission: Decimal, reason: str) -> TradeRecord:
        return TradeRecord(trade.position_id, symbol, trade.signal.direction, trade.signal.setup, trade.entry_time, trade.entry_price, bar.timestamp, exit_price, trade.signal.stop_loss, trade.signal.target, trade.quantity, trade.total_amount, trade.leverage, net, trade.entry_commission + exit_commission, reason)
