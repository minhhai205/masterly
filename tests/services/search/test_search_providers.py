"""Provider-level tests: the resolved search config must reach the HTTP call.

`web_search` hands every provider the same `max_results` / `proxy` knobs from the
active search profile. A provider that names its parameter differently silently
drops them, which is how Jina used to return every result it got.
"""

from __future__ import annotations

from typing import Any

import pytest

from masterly.services.search.providers.brave import BraveProvider
from masterly.services.search.providers.jina import JinaProvider
from masterly.services.search.providers.tavily import TavilyProvider

PROXY = "http://127.0.0.1:7890"


class _FakeResponse:
    status_code = 200
    text = ""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


@pytest.fixture
def calls(monkeypatch):
    """Capture requests made by any provider module."""
    captured: list[dict[str, Any]] = []
    payloads: dict[str, Any] = {
        "results": [],
        "web": {"results": []},
        "data": [],
    }

    def _record(method: str):
        def _call(url: str, **kwargs: Any) -> _FakeResponse:
            captured.append({"method": method, "url": url, **kwargs})
            return _FakeResponse(payloads)

        return _call

    for module in ("tavily", "brave", "jina"):
        target = f"masterly.services.search.providers.{module}.requests"

        class _FakeRequests:
            get = staticmethod(_record("GET"))
            post = staticmethod(_record("POST"))

        monkeypatch.setattr(target, _FakeRequests)
    return captured


def test_tavily_and_brave_already_carry_the_shared_knobs(calls) -> None:
    TavilyProvider(api_key="k", proxy=PROXY).search("q", max_results=3)
    assert calls[-1]["json"]["max_results"] == 3
    assert calls[-1]["proxies"] == {"http": PROXY, "https": PROXY}

    BraveProvider(api_key="k", proxy=PROXY).search("q", max_results=3)
    assert calls[-1]["params"]["count"] == 3
    assert calls[-1]["proxies"] == {"http": PROXY, "https": PROXY}


def test_jina_truncates_results_to_max_results(monkeypatch) -> None:
    rows = [
        {"title": f"t{i}", "url": f"https://e/{i}", "description": "d", "content": "c"}
        for i in range(6)
    ]

    class _FakeRequests:
        @staticmethod
        def get(url: str, **kwargs: Any) -> _FakeResponse:
            return _FakeResponse({"data": rows})

    monkeypatch.setattr("masterly.services.search.providers.jina.requests", _FakeRequests)

    capped = JinaProvider(api_key="k").search("q", max_results=2)
    assert len(capped.search_results) == 2
    assert len(capped.citations) == 2
    assert [c.id for c in capped.citations] == [1, 2]

    uncapped = JinaProvider(api_key="k").search("q")
    assert len(uncapped.search_results) == len(rows)


def test_provider_metadata_comes_from_the_spec_table() -> None:
    from masterly.services.config import SEARCH_PROVIDERS

    for cls in (TavilyProvider, BraveProvider, JinaProvider):
        spec = SEARCH_PROVIDERS[cls.name]
        assert cls.display_name == spec.label
        assert cls.requires_api_key == spec.requires_api_key
        assert cls.supports_answer == spec.supports_answer

