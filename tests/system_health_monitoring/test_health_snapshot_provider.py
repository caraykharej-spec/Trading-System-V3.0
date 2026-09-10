from app.system_health_monitoring.health_snapshot_provider import HealthSnapshotProvider


def test_health_snapshot_creation():
    provider = HealthSnapshotProvider()
    snapshot = provider.create_snapshot({"runtime": True, "api": True})

    assert snapshot.status == "healthy"
    assert snapshot.components["runtime"] is True


def test_degraded_health_snapshot():
    provider = HealthSnapshotProvider()
    snapshot = provider.create_snapshot({"runtime": True, "api": False})

    assert snapshot.status == "degraded"
