from app.system_health_monitoring.health_validation_matrix import HealthValidationMatrix


def test_health_validation_matrix_pass():
    matrix = HealthValidationMatrix()
    matrix.add_check("runtime", True)
    matrix.add_check("api", True)
    report = matrix.generate_report()
    assert report.passed


def test_health_validation_matrix_fail():
    matrix = HealthValidationMatrix()
    matrix.add_check("exchange", False)
    report = matrix.generate_report()
    assert not report.passed
