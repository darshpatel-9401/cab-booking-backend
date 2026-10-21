import pytest
from starlette.websockets import WebSocketDisconnect

from config import ALLOWED_ORIGINS

ID = "00000000-0000-0000-0000-000000000000"


def test_responses_carry_security_headers(client):
    response = client.get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_api_responses_are_never_cached(client):
    response = client.get("/api/me")
    assert response.headers["cache-control"] == "no-store"


def test_cors_allows_a_listed_origin(client):
    origin = ALLOWED_ORIGINS[0]
    response = client.options(
        "/api/me",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_cors_refuses_an_unlisted_origin(client):
    response = client.options(
        "/api/me",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in response.headers


def test_websocket_from_an_unlisted_origin_is_refused(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/ws/rider/{ID}", headers={"origin": "https://evil.example"}
        ):
            pass


@pytest.mark.parametrize(
    "path", ["/health/db", "/health/redis", "/health/postgis", "/health/stripe"]
)
def test_detailed_health_routes_are_gone(client, path):
    assert client.get(path).status_code == 404