"""PDF report templates foundation."""

from typing import Any, Mapping


class TradingReportTemplate:
    def render(self, data: Mapping[str, Any]) -> dict[str, Any]:
        return {"title": "Daily Trading Report", "sections": dict(data)}


class RiskReportTemplate:
    def render(self, data: Mapping[str, Any]) -> dict[str, Any]:
        return {"title": "Risk Report", "sections": dict(data)}


class PerformanceReportTemplate:
    def render(self, data: Mapping[str, Any]) -> dict[str, Any]:
        return {"title": "Performance Report", "sections": dict(data)}


class StrategyReportTemplate:
    def render(self, data: Mapping[str, Any]) -> dict[str, Any]:
        return {"title": "Strategy Report", "sections": dict(data)}
