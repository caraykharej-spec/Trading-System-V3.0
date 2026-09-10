from app.deployment_runtime.environment_runtime import (
    EnvironmentConfig,
    EnvironmentRuntime,
)


def test_environment_registration():
    runtime = EnvironmentRuntime()
    runtime.register_environment(
        EnvironmentConfig(name="development", variables={"MODE": "paper"})
    )

    assert runtime.validate("development") is True


def test_environment_health():
    runtime = EnvironmentRuntime()
    assert runtime.health()["status"] == "healthy"
