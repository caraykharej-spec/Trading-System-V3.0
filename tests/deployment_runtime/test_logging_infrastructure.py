from app.deployment_runtime.logging_infrastructure import StructuredLogger


def test_structured_logger():
    logger = StructuredLogger()
    record = logger.info("runtime started", "application_runtime")

    assert record.level == "INFO"
    assert len(logger.get_logs()) == 1


def test_error_logging():
    logger = StructuredLogger()
    logger.error("service failed", "process_manager")

    logs = logger.get_logs()
    assert logs[0]["level"] == "ERROR"
