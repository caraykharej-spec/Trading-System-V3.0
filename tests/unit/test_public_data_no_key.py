from __future__ import annotations

import io
import inspect
import tokenize
from pathlib import Path

from app.context.events.biquote import BiQuoteCalendarProvider
from app.context.news.rss import RSSNewsProvider
from app.data.providers.base import require_public_no_key
from app.data.providers.gateio import GateIOProvider
from app.data.providers.http import HttpClient
from app.data.providers.storm import StormProvider
from app.data.providers.yahoo import YahooFinanceProvider


FORBIDDEN_PARAMETER_NAMES = {
    "api_key",
    "apikey",
    "access_token",
    "client_secret",
    "password",
    "credential",
    "credentials",
    "authorization",
}


def _parameter_names(callable_object: object) -> set[str]:
    return set(inspect.signature(callable_object).parameters)


def _python_identifiers(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    return {
        token.string.lower()
        for token in tokenize.generate_tokens(io.StringIO(text).readline)
        if token.type == tokenize.NAME
    }


def test_market_data_providers_are_explicitly_public_no_key() -> None:
    providers = (StormProvider(), GateIOProvider(), YahooFinanceProvider())
    for provider in providers:
        assert provider.requires_credentials is False
        assert require_public_no_key(provider) is provider
        parameters = _parameter_names(type(provider))
        assert not (parameters & FORBIDDEN_PARAMETER_NAMES)


def test_context_providers_are_explicitly_public_no_key() -> None:
    news = RSSNewsProvider("test", "https://example.com/feed")
    calendar = BiQuoteCalendarProvider()
    assert news.requires_credentials is False
    assert calendar.requires_credentials is False
    assert not (_parameter_names(RSSNewsProvider) & FORBIDDEN_PARAMETER_NAMES)
    assert not (_parameter_names(BiQuoteCalendarProvider) & FORBIDDEN_PARAMETER_NAMES)


def test_public_http_client_does_not_accept_arbitrary_headers() -> None:
    assert tuple(inspect.signature(HttpClient.get_json).parameters) == ("self", "url")


def test_public_provider_code_has_no_credential_identifiers_or_auth_headers() -> None:
    roots = (Path("app/data/providers"), Path("app/context/news"), Path("app/context/events"))
    for root in roots:
        for path in root.rglob("*.py"):
            identifiers = _python_identifiers(path)
            assert not (identifiers & FORBIDDEN_PARAMETER_NAMES), path
            text = path.read_text(encoding="utf-8")
            assert '"Authorization"' not in text, path
            assert "'Authorization'" not in text, path
            assert "Bearer " not in text, path
            assert "os.getenv" not in text, path
            assert "os.environ" not in text, path


def test_data_configuration_declares_public_no_key_access() -> None:
    text = Path("config/data.yaml").read_text(encoding="utf-8")
    assert "access_policy: public_no_key" in text
    for forbidden in ("api_key:", "access_token:", "client_secret:", "password:"):
        assert forbidden not in text.lower()
