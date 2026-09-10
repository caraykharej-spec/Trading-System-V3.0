"""Risk snapshot provider adapter."""


class RiskSnapshotProvider:
    def __init__(self, risk_view):
        self.risk_view = risk_view

    def get_risk_snapshot(self):
        return self.risk_view.create_snapshot()

    def get_visualization_data(self):
        snapshot = self.get_risk_snapshot()
        return {
            "equity": snapshot.equity,
            "exposure": snapshot.exposure,
            "margin_ratio": snapshot.margin_ratio,
            "drawdown": snapshot.drawdown,
            "risk_state": snapshot.risk_state,
        }
