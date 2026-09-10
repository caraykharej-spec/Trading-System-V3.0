from app.deployment_runtime.database_runtime import DatabaseRuntime, DatabaseConfig


def test_database_registration_and_health():
    runtime = DatabaseRuntime()
    runtime.register_database(DatabaseConfig(name="trading"))
    runtime.connect("trading")

    result = runtime.health_check("trading")

    assert result["connected"] is True
