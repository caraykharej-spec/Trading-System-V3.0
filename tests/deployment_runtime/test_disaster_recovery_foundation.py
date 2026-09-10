from app.deployment_runtime.disaster_recovery_foundation import (
    DisasterRecoveryManager,
    RecoveryRule,
)


def test_recovery_rule_registration():
    manager = DisasterRecoveryManager()
    manager.register_rule(
        RecoveryRule(
            name="restart_worker",
            service="trading-worker",
            action="restart",
        )
    )

    assert len(manager.list_rules()) == 1


def test_service_recovery():
    manager = DisasterRecoveryManager()
    state = manager.recover_service("api-service")

    assert state.status == "RECOVERED"
    assert "api-service" in state.restored_services
