def test_root_returns_running_message(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Cab Booking API is running"}


def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_protected_route_rejects_missing_token(client):
    response = client.get("/api/me")
    assert response.status_code in (401, 403)