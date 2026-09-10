from app.deployment_runtime.application_runtime import ApplicationRuntime
from app.deployment_runtime.environment_manager import EnvironmentManager


def test_runtime_lifecycle():
    runtime = ApplicationRuntime()
    assert runtime.start().status == "RUNNING"
    assert runtime.stop().status == "STOPPED"


def test_environment_manager():
    manager = EnvironmentManager()
    assert manager.get("MISSING_KEY", "default") == "default"
