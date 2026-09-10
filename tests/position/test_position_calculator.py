from app.position.position_calculator import PositionCalculator


def test_notional_calculation():
    assert PositionCalculator.calculate_notional(2, 100) == 200


def test_average_price_calculation():
    result = PositionCalculator.calculate_average_price(1, 100, 1, 200)
    assert result == 150
