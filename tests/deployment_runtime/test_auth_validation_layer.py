from app.deployment_runtime.auth_validation_layer import (
    APIKey,
    AuthenticationManager,
    RequestValidator,
)


def test_api_key_validation():
    manager = AuthenticationManager()
    manager.register_key(APIKey(key="test-key", name="mobile"))
    assert manager.validate_key("test-key")


def test_request_validation():
    validator = RequestValidator()
    result = validator.validate({"route": "/health"})
    assert result.valid
