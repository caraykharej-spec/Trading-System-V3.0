from dataclasses import dataclass


@dataclass
class PositionMetrics:
    quantity: float
    average_price: float
    notional_value: float


class PositionCalculator:
    """Calculates core position metrics."""

    @staticmethod
    def calculate_notional(quantity: float, price: float) -> float:
        return quantity * price

    @staticmethod
    def calculate_average_price(existing_quantity: float, existing_price: float, added_quantity: float, added_price: float) -> float:
        total_quantity = existing_quantity + added_quantity
        if total_quantity == 0:
            return 0.0
        return ((existing_quantity * existing_price) + (added_quantity * added_price)) / total_quantity

    @classmethod
    def snapshot(cls, quantity: float, price: float) -> PositionMetrics:
        return PositionMetrics(
            quantity=quantity,
            average_price=price,
            notional_value=cls.calculate_notional(quantity, price),
        )
