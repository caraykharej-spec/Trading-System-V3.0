from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from app.data.market_data import Candle
from app.market.analysis import MarketSnapshot, analyze_market
from app.strategy.strategy_engine import StrategySignal, StrategyState, evaluate_strategy

from .costs import BacktestCostModel
from .metrics import calculate_metrics
from .models import BacktestConfig, BacktestResult, TradeRecord


_TIMEFRAME_MINUTES = {"15m": 15, "1h": 60, "4h": 240, "1d": 1440}


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
    """Deterministic OHLC backtester with explicit transaction-cost modeling."""

    def __init__(self, config: BacktestConfig | None = None) -> None:
        self.config = config or BacktestConfig()
        self.costs = BacktestCostModel(
            commission_percent=self.config.commission_percent,
            spread_percent=self.config.spread_percent,
            slippage_percent=self.config.slippage_percent,
            funding_rate_percent_per_day=self.config.funding_rate_percent_per_day,
        )

    def run(self, symbol: str, candles_by_timeframe: dict[str, list[Candle]], evaluation_start: datetime | None = None) -> BacktestResult:
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
                else:
                    candidate = self._open_trade(pending_signal, bar, equity, open_trades)
                    if candidate is not None:
                        equity -= candidate.entry_commission
                        open_trades.append(candidate)
                        max_concurrent = max(max_concurrent, len(open_trades))
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
                exit_price = self.costs.exit_price(trade.signal.direction, exit_price)
                gross_pnl = self._pnl(trade, exit_price)
                exit_commission = self.costs.commission(trade.total_amount)
                net_pnl = gross_pnl - exit_commission - trade.funding_cost
                equity += gross_pnl - exit_commission
                trades.append(self._trade_record(symbol, trade, bar, exit_price, net_pnl, exit_commission, reason))
            open_trades = remaining
            equity_curve.append(equity)

            if not in_test:
                continue

            decision_time = bar.timestamp + self._duration("15m")
            snapshots = self._snapshots_at(symbol, candles, decision_time)
            if snapshots is not None:
                try:
                    signal = evaluate_strategy(snapshots["1d"], snapshots["4h"], snapshots["1h"], snapshots["15m"])
                    if signal.state is StrategyState.READY_FOR_RISK_REVIEW:
                        pending_signal = signal
                    else:
                        rejected += 1
                except (ValueError, ArithmeticError, IndexError):
                    rejected += 1

        if open_trades:
            final_bar = fifteen[-1]
            for trade in open_trades:
                exit_price = self.costs.exit_price(trade.signal.direction, final_bar.close)
                gross_pnl = self._pnl(trade, exit_price)
                exit_commission = self.costs.commission(trade.total_amount)
                net_pnl = gross_pnl - exit_commission - trade.funding_cost
                equity += gross_pnl - exit_commission
                trades.append(self._trade_record(symbol, trade, final_bar, exit_price, net_pnl, exit_commission, "END_OF_TEST"))
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
    def _prepare(symbol: str, source: dict[str, list[Candle]]) -> dict[str, list[Candle]]:
        missing = set(_TIMEFRAME_MINUTES) - set(source)
        if missing:
            raise ValueError(f"Missing required timeframes: {sorted(missing)}")
        prepared: dict[str, list[Candle]] = {}
        for timeframe in _TIMEFRAME_MINUTES:
            rows = sorted((c for c in source[timeframe] if c.symbol == symbol), key=lambda c: c.timestamp)
            if not rows:
                raise ValueError(f"No candles for {symbol} at {timeframe}")
            prepared[timeframe] = rows
        return prepared

    def _snapshots_at(self, symbol: str, candles: dict[str, list[Candle]], decision_time: datetime) -> dict[str, MarketSnapshot] | None:
        snapshots: dict[str, MarketSnapshot] = {}
        for timeframe in ("1d", "4h", "1h", "15m"):
            duration = self._duration(timeframe)
            completed = [c for c in candles[timeframe] if c.timestamp + duration <= decision_time]
            if len(completed) < 2:
                return None
            snapshots[timeframe] = analyze_market(symbol, timeframe, completed)
        return snapshots

    def _open_trade(self, signal: StrategySignal, bar: Candle, equity: Decimal, existing: list[_OpenTrade]) -> _OpenTrade | None:
        entry = self.costs.entry_price(signal.direction, bar.open)
        distance = abs(entry - signal.stop_loss) / entry
        if distance <= 0 or signal.stop_loss <= 0:
            return None
        risk_cash = equity * self.config.risk_per_trade_percent / Decimal("100")
        current_risk = sum(self._risk_cash(t) for t in existing)
        if current_risk + risk_cash > equity * self.config.max_aggregate_risk_percent / Decimal("100"):
            return None
        amount = risk_cash / distance
        current_capital = sum(t.total_amount for t in existing)
        if current_capital + amount > equity * self.config.max_futures_capital_percent / Decimal("100"):
            return None
        leverage = Decimal("1")
        quantity = amount / entry
        commission = self.costs.commission(amount)
        return _OpenTrade(str(uuid4()), signal, bar.timestamp, entry, quantity, amount, leverage, commission)

    @staticmethod
    def _risk_cash(trade: _OpenTrade) -> Decimal:
        distance = abs(trade.entry_price - trade.signal.stop_loss) / trade.entry_price
        return trade.total_amount * distance * trade.leverage

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
    def _trade_record(symbol: str, trade: _OpenTrade, bar: Candle, exit_price: Decimal, net_pnl: Decimal, exit_commission: Decimal, reason: str) -> TradeRecord:
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
