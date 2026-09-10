from app.deployment_runtime.process_manager import ProcessManager


def test_process_lifecycle():
    manager = ProcessManager()
    manager.register("execution_engine")

    assert manager.start("execution_engine").status == "RUNNING"
    assert manager.stop("execution_engine").status == "STOPPED"
    assert manager.restart("execution_engine").status == "RUNNING"
