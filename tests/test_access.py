import pytest
from starlette.websockets import WebSocketDisconnect

ID = "00000000-0000-0000-0000-000000000000"

PROTECTED_ROUTES = [
    ("GET", "/api/me", None),
    ("POST", "/api/auth/session", None),
    ("GET", "/api/rides/estimate?origin_lat=1&origin_lng=1&dest_lat=2&dest_lng=2", None),
    (
        "POST",
        "/api/rides/request",
        {"pickup_lat": 1, "pickup_lng": 1, "drop_lat": 2, "drop_lng": 2},
    ),
    ("GET", f"/api/rides/{ID}/status", None),
    ("POST", f"/api/rides/{ID}/match", None),
    ("POST", f"/api/rides/{ID}/start", None),
    ("POST", f"/api/rides/{ID}/complete", None),
    ("POST", f"/api/rides/{ID}/cancel", None),
    ("GET", f"/api/rides/{ID}/receipt", None),
    ("GET", f"/api/rides/{ID}/receipt/pdf", None),
    ("POST", f"/api/rides/{ID}/receipt/email", None),
    ("POST", f"/api/rides/{ID}/review", {"rating": 5}),
    ("GET", f"/api/users/{ID}/rating", None),
    ("GET", "/api/reviews/received", None),
    ("POST", "/api/promos/preview", {"ride_id": ID, "code": "WELCOME10"}),
    ("POST", "/api/drivers/register", {"vehicle_info": "Test car"}),
    ("PUT", "/api/drivers/location", {"lat": 1, "lng": 1}),
    ("PUT", "/api/drivers/status", {"status": "offline"}),
    ("GET", "/api/drivers/nearby?lat=1&lng=1", None),
    ("GET", "/api/drivers/current-ride", None),
    ("GET", "/api/rides/history", None),
    ("POST", f"/api/payments/rides/{ID}/intent", None),
    ("GET", f"/api/payments/rides/{ID}", None),
    ("GET", "/api/wallet", None),
    ("GET", "/api/wallet/transactions", None),
    ("POST", "/api/wallet/topup", {"amount": 5000}),
    ("POST", f"/api/payments/rides/{ID}/pay-with-wallet", None),
    ("GET", "/api/drivers/me", None),
]


@pytest.mark.parametrize("method, path, body", PROTECTED_ROUTES)
def test_route_requires_login(client, method, path, body):
    response = client.request(method, path, json=body)
    assert response.status_code in (401, 403)


def test_webhook_rejects_missing_signature(client):
    response = client.post(
        "/api/webhooks/stripe",
        content=b'{"type": "payment_intent.succeeded"}',
    )
    assert response.status_code == 400


def test_webhook_rejects_wrong_signature(client):
    response = client.post(
        "/api/webhooks/stripe",
        content=b"{}",
        headers={"stripe-signature": "t=1,v1=not-a-valid-signature"},
    )
    assert response.status_code == 400


def test_websocket_rejects_message_without_token(client):
    with client.websocket_connect(f"/ws/rider/{ID}") as websocket:
        websocket.send_text('{"type": "hello"}')
        with pytest.raises(WebSocketDisconnect) as closed:
            websocket.receive_text()
    assert closed.value.code == 1008


def test_websocket_rejects_bad_token(client):
    with client.websocket_connect(f"/ws/rider/{ID}") as websocket:
        websocket.send_text('{"type": "auth", "token": "not-a-real-token"}')
        with pytest.raises(WebSocketDisconnect) as closed:
            websocket.receive_text()
    assert closed.value.code == 1008