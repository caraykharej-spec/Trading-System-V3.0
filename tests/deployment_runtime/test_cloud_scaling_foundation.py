from app.deployment_runtime.cloud_scaling_foundation import (
    CloudScalingManager,
    ScalingService,
)


def test_service_scaling_registration():
    manager = CloudScalingManager()
    manager.register_service(ScalingService(name="trading-worker"))

    assert len(manager.list_services()) == 1


def test_service_scaling_update():
    manager = CloudScalingManager()
    manager.register_service(ScalingService(name="api"))
    manager.scale("api", 3)

    assert manager.list_services()[0].replicas == 3


def test_scaling_health():
    manager = CloudScalingManager()
    assert manager.health()["status"] == "healthy"
