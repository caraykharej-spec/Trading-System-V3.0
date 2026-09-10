from app.deployment_runtime.api_server_layer import APIServerLayer


def test_api_server_layer():
    api = APIServerLayer()
    api.register_route('/health', 'health_handler')
    response = api.health()

    assert '/health' in api.routes
    assert response.payload['status'] == 'ok'
