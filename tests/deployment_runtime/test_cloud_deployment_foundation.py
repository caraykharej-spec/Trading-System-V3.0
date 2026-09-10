from app.deployment_runtime.cloud_deployment_foundation import (
    CloudDeploymentManager,
    CloudProfile,
)


def test_cloud_profile_registration():
    manager = CloudDeploymentManager()
    manager.register_profile(
        CloudProfile(
            name="development-vps",
            provider="generic",
            region="global",
            services=["api", "worker"],
        )
    )

    assert manager.get_profile("development-vps") is not None


def test_cloud_health():
    manager = CloudDeploymentManager()
    assert manager.health()["status"] == "healthy"
