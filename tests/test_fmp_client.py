import sys
from pathlib import Path

import pytest
import requests

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

import fmp_client  # noqa: E402


class _Response:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = [] if data is None else data
        self.headers = {}
        self.text = "error"

    def json(self):
        return self._data


def test_feed_http_failure_is_not_silently_treated_as_no_trades(monkeypatch):
    monkeypatch.setattr(fmp_client, "API_KEY", "test-key")
    monkeypatch.setattr(fmp_client.requests, "get", lambda *_args, **_kwargs: _Response(status_code=503))

    with pytest.raises(RuntimeError, match="HTTP 503"):
        fmp_client.fetch_house_trades()


def test_feed_network_failure_is_not_silently_treated_as_no_trades(monkeypatch):
    monkeypatch.setattr(fmp_client, "API_KEY", "test-key")

    def fail(*_args, **_kwargs):
        raise requests.Timeout("timed out")

    monkeypatch.setattr(fmp_client.requests, "get", fail)

    with pytest.raises(RuntimeError, match="request failed"):
        fmp_client.fetch_senate_trades()


def test_feed_requests_have_a_bounded_timeout(monkeypatch):
    monkeypatch.setattr(fmp_client, "API_KEY", "test-key")
    calls = []
    monkeypatch.setattr(
        fmp_client.requests,
        "get",
        lambda *args, **kwargs: calls.append((args, kwargs)) or _Response(data=[]),
    )

    assert fmp_client.fetch_house_trades() == []
    assert calls[0][1]["timeout"] == 30
