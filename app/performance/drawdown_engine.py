"""Drawdown engine for portfolio performance analytics."""

from dataclasses import dataclass


@dataclass
class DrawdownSnapshot:
    peak_equity: float
    current_equity: float
    drawdown: float
    max_drawdown: float


class DrawdownEngine:
    def __init__(self):
        self.peak_equity = 0.0
        self.max_drawdown = 0.0

    def update(self, equity: float) -> DrawdownSnapshot:
        if equity > self.peak_equity:
            self.peak_equity = equity

        drawdown = 0.0
        if self.peak_equity:
            drawdown = (self.peak_equity - equity) / self.peak_equity

        self.max_drawdown = max(self.max_drawdown, drawdown)

        return DrawdownSnapshot(
            peak_equity=self.peak_equity,
            current_equity=equity,
            drawdown=drawdown,
            max_drawdown=self.max_drawdown,
        )
