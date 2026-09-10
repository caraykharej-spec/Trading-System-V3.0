"""PDF report templates foundation."""


class TradingReportTemplate:
    def render(self, data: dict) -> dict:
        return {"title": "Daily Trading Report", "sections": data}


class RiskReportTemplate:
    def render(self, data: dict) -> dict:
        return {"title": "Risk Report", "sections": data}


class PerformanceReportTemplate:
    def render(self, data: dict) -> dict:
        return {"title": "Performance Report", "sections": data}


class StrategyReportTemplate:
    def render(self, data: dict) -> dict:
        return {"title": "Strategy Report", "sections": data}
