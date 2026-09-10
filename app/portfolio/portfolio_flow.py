class PortfolioFlow:
    def __init__(self, position_manager, portfolio_manager):
        self.position_manager = position_manager
        self.portfolio_manager = portfolio_manager

    def process_execution_result(self, execution_result):
        position = self.position_manager.update_from_execution(execution_result)
        return self.portfolio_manager.update_position(position)
