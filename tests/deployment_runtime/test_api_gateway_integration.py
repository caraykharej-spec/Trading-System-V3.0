from app.deployment_runtime.api_gateway_integration import APIGatewayIntegration, APIRoute


def test_route_registration():
    gateway = APIGatewayIntegration()
    gateway.register_route(APIRoute(name="health", target="health_service"))

    assert len(gateway.get_routes()) == 1


def test_gateway_health():
    gateway = APIGatewayIntegration()
    assert gateway.health()["status"] == "healthy"
