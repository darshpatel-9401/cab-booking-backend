import pytest

BAD_REQUESTS = [
    ("GET", "/api/rides/estimate", None),
    ("GET", "/api/rides/estimate?origin_lat=200&origin_lng=0&dest_lat=0&dest_lng=0", None),
    ("GET", "/api/rides/estimate?origin_lat=abc&origin_lng=0&dest_lat=0&dest_lng=0", None),
    ("GET", "/api/rides/estimate?origin_lat=0&origin_lng=181&dest_lat=0&dest_lng=0", None),
    ("POST", "/api/rides/request", {}),
    (
        "POST",
        "/api/rides/request",
        {"pickup_lat": 999, "pickup_lng": 0, "drop_lat": 0, "drop_lng": 0},
    ),
    ("POST", "/api/rides/request", {"pickup_lat": 0, "pickup_lng": 0, "drop_lat": 0}),
    ("POST", "/api/drivers/register", {}),
    ("POST", "/api/drivers/register", {"vehicle_info": "x" * 201}),
    ("PUT", "/api/drivers/location", {"lat": 100, "lng": 0}),
    ("PUT", "/api/drivers/location", {"lat": 0}),
    ("PUT", "/api/drivers/status", {"status": "flying"}),
    ("PUT", "/api/drivers/status", {}),
    ("GET", "/api/drivers/nearby?lat=95&lng=0", None),
    ("GET", "/api/drivers/nearby?lat=0&lng=0&radius_meters=50", None),
    ("GET", "/api/drivers/nearby?lat=0&lng=0&radius_meters=30000", None),
    ("GET", "/api/rides/not-a-uuid/status", None),
    ("POST", "/api/rides/not-a-uuid/match", None),
    ("POST", "/api/rides/not-a-uuid/start", None),
    ("POST", "/api/rides/not-a-uuid/complete", None),
    ("POST", "/api/rides/not-a-uuid/cancel", None),
    ("GET", "/api/rides/not-a-uuid/receipt", None),
    ("GET", "/api/rides/not-a-uuid/receipt/pdf", None),
    ("POST", "/api/rides/not-a-uuid/receipt/email", None),
    ("POST", "/api/payments/rides/not-a-uuid/intent", None),
    ("GET", "/api/payments/rides/not-a-uuid", None),
    ("GET", "/api/rides/history?role=admin", None),
    ("GET", "/api/rides/history?limit=0", None),
    ("GET", "/api/rides/history?limit=100", None),
    ("GET", "/api/rides/history?offset=-1", None),
    ("GET", "/api/users/not-a-uuid/rating", None),
    ("GET", "/api/reviews/received?limit=0", None),
    ("GET", "/api/reviews/received?limit=100", None),
    ("GET", "/api/reviews/received?offset=-1", None),
    ("POST", "/api/rides/00000000-0000-0000-0000-000000000000/review", {}),
    ("POST", "/api/rides/00000000-0000-0000-0000-000000000000/review", {"rating": 0}),
    ("POST", "/api/rides/00000000-0000-0000-0000-000000000000/review", {"rating": 6}),
    ("POST", "/api/rides/00000000-0000-0000-0000-000000000000/review", {"rating": "5"}),
    ("POST", "/api/rides/00000000-0000-0000-0000-000000000000/review", {"rating": True}),
    ("POST", "/api/rides/00000000-0000-0000-0000-000000000000/review", {"rating": 4.5}),
    ("POST", "/api/rides/00000000-0000-0000-0000-000000000000/review", {"rating": 5, "comment": "x" * 501}),
    ("POST", "/api/rides/00000000-0000-0000-0000-000000000000/review", {"rating": 5, "comment": 123}),
    ("POST", "/api/promos/preview", {}),
    ("POST", "/api/promos/preview", {"ride_id": "not-a-uuid", "code": "WELCOME10"}),
    ("POST", "/api/promos/preview", {"ride_id": "00000000-0000-0000-0000-000000000000"}),
    ("POST", "/api/promos/preview", {"ride_id": "00000000-0000-0000-0000-000000000000", "code": ""}),
    ("POST", "/api/promos/preview", {"ride_id": "00000000-0000-0000-0000-000000000000", "code": "X" * 65}),
    ("POST", "/api/rides/not-a-uuid/review", {"rating": 5}),
    ("POST", "/api/payments/rides/00000000-0000-0000-0000-000000000000/intent", {"promo_code": "X" * 65}),
    ("POST", "/api/payments/rides/00000000-0000-0000-0000-000000000000/intent", {"promo_code": 123}),
    ("POST", "/api/wallet/topup", {}),
    ("POST", "/api/wallet/topup", {"amount": 0}),
    ("POST", "/api/wallet/topup", {"amount": -5}),
    ("POST", "/api/wallet/topup", {"amount": 999}),
    ("POST", "/api/wallet/topup", {"amount": 500001}),
    ("POST", "/api/wallet/topup", {"amount": "5000"}),
    ("POST", "/api/wallet/topup", {"amount": 1000.5}),
    ("POST", "/api/wallet/topup", {"amount": True}),
    ("GET", "/api/wallet/transactions?limit=0", None),
    ("GET", "/api/wallet/transactions?limit=100", None),
    ("GET", "/api/wallet/transactions?offset=-1", None),
    ("POST", "/api/payments/rides/not-a-uuid/pay-with-wallet", None),
    ("POST", "/api/payments/rides/00000000-0000-0000-0000-000000000000/pay-with-wallet", {"promo_code": "X" * 65}),
    ("POST", "/api/payments/rides/00000000-0000-0000-0000-000000000000/pay-with-wallet", {"promo_code": 123}),
]


def test_fake_login_is_used(authed_client):
    response = authed_client.get("/api/me")
    assert response.status_code == 200
    assert response.json()["user"]["email"] == "test@example.com"


@pytest.mark.parametrize("method, path, body", BAD_REQUESTS)
def test_bad_input_returns_422(authed_client, method, path, body):
    response = authed_client.request(method, path, json=body)
    assert response.status_code == 422