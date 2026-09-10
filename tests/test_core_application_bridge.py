from app.core.application_bridge import build_core_container


class DummyApplication:
    account = object()
    position_repository = object()
    opportunity_pipeline = object()
    runtime = object()
    analytics = object()
    health = object()
    api = object()


def test_build_core_container_registers_application_services():
    container = build_core_container(DummyApplication())

    assert container.get("runtime_engine") is not None
    assert container.get("analytics_engine") is not None
    assert container.get("api_service") is not None
