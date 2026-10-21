import routers.rides as rides_module
from maps import RouteError
from stripe_client import CURRENCY

URL = (
    "/api/rides/estimate"
    "?origin_lat=51.508&origin_lng=-0.1281&dest_lat=51.5055&dest_lng=-0.0754"
)


def test_estimate_returns_route_and_fare(authed_client, monkeypatch):
    monkeypatch.setattr(
        rides_module,
        "get_route",
        lambda *args: {"distance_meters": 5000, "duration_secs": 900},
    )

    response = authed_client.get(URL)

    assert response.status_code == 200
    assert response.json() == {
        "distance_meters": 5000,
        "duration_secs": 900,
        "fare_estimate": 13250,
        "currency": CURRENCY,
    }

def test_estimate_passes_coordinates_in_the_right_order(authed_client, monkeypatch):
    seen = {}

    def fake_get_route(*args):
        seen["args"] = args
        return {"distance_meters": 1000, "duration_secs": 100}

    monkeypatch.setattr(rides_module, "get_route", fake_get_route)

    authed_client.get(URL)

    assert seen["args"] == (51.508, -0.1281, 51.5055, -0.0754)


def test_estimate_returns_502_when_routing_fails(authed_client, monkeypatch):
    def failing_get_route(*args):
        raise RouteError("secret internal detail")

    monkeypatch.setattr(rides_module, "get_route", failing_get_route)

    response = authed_client.get(URL)

    assert response.status_code == 502
    assert response.json() == {"detail": "Could not calculate a route right now"}
    assert "secret internal detail" not in response.text