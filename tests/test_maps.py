import httpx
import pytest

import maps
from maps import RouteError, get_route


class FakeResponse:
    def __init__(self, data=None, status_code=200, json_error=False):
        self.data = data
        self.status_code = status_code
        self.json_error = json_error

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "bad status",
                request=httpx.Request("GET", "http://example.com"),
                response=httpx.Response(self.status_code),
            )

    def json(self):
        if self.json_error:
            raise ValueError("not json")
        return self.data


def patch_get(monkeypatch, response=None, error=None):
    calls = []

    def fake_get(url, **kwargs):
        calls.append({"url": url, **kwargs})
        if error is not None:
            raise error
        return response

    monkeypatch.setattr(maps.httpx, "get", fake_get)
    return calls


def test_route_success_rounds_to_whole_numbers(monkeypatch):
    data = {"code": "Ok", "routes": [{"distance": 4741.6, "duration": 771.9}]}
    patch_get(monkeypatch, FakeResponse(data))

    assert get_route(51.5, -0.1, 52.5, 0.2) == {
        "distance_meters": 4742,
        "duration_secs": 772,
    }


def test_route_url_puts_longitude_before_latitude(monkeypatch):
    data = {"code": "Ok", "routes": [{"distance": 1, "duration": 1}]}
    calls = patch_get(monkeypatch, FakeResponse(data))

    get_route(51.5, -0.1, 52.5, 0.2)

    assert calls[0]["url"].endswith("/-0.1,51.5;0.2,52.5")


def test_route_uses_a_timeout(monkeypatch):
    data = {"code": "Ok", "routes": [{"distance": 1, "duration": 1}]}
    calls = patch_get(monkeypatch, FakeResponse(data))

    get_route(1, 1, 2, 2)

    assert calls[0]["timeout"] == 10


def test_no_route_found_raises_route_error(monkeypatch):
    patch_get(monkeypatch, FakeResponse({"code": "NoRoute", "routes": []}))

    with pytest.raises(RouteError, match="No route"):
        get_route(1, 1, 2, 2)


def test_empty_routes_list_raises_route_error(monkeypatch):
    patch_get(monkeypatch, FakeResponse({"code": "Ok", "routes": []}))

    with pytest.raises(RouteError, match="No route"):
        get_route(1, 1, 2, 2)


def test_network_failure_raises_route_error(monkeypatch):
    patch_get(monkeypatch, error=httpx.ConnectError("boom"))

    with pytest.raises(RouteError, match="Routing service failed"):
        get_route(1, 1, 2, 2)


def test_http_error_status_raises_route_error(monkeypatch):
    patch_get(monkeypatch, FakeResponse(status_code=500))

    with pytest.raises(RouteError, match="Routing service failed"):
        get_route(1, 1, 2, 2)


def test_unreadable_json_raises_route_error(monkeypatch):
    patch_get(monkeypatch, FakeResponse(json_error=True))

    with pytest.raises(RouteError, match="Routing service failed"):
        get_route(1, 1, 2, 2)