import hashlib
import hmac
import json
import time

import routers.webhooks as webhooks_module


def signed_headers(payload: bytes) -> dict:
    timestamp = int(time.time())
    signed = f"{timestamp}.".encode() + payload
    signature = hmac.new(
        webhooks_module.WEBHOOK_SECRET.encode(), signed, hashlib.sha256
    ).hexdigest()
    return {"stripe-signature": f"t={timestamp},v1={signature}"}


def make_event(event_type: str, obj=None) -> bytes:
    event = {
        "id": "evt_test",
        "object": "event",
        "type": event_type,
        "data": {"object": obj or {}},
    }
    return json.dumps(event).encode()


def test_valid_signature_with_unhandled_event_is_accepted(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        webhooks_module, "apply_payment_event", lambda *args: calls.append(args)
    )
    payload = make_event("customer.created")

    response = client.post(
        "/api/webhooks/stripe", content=payload, headers=signed_headers(payload)
    )

    assert response.status_code == 200
    assert response.json() == {"received": True}
    assert calls == []


def test_tampered_body_is_rejected(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        webhooks_module, "apply_payment_event", lambda *args: calls.append(args)
    )
    signed_payload = make_event("payment_intent.succeeded", {"id": "pi_test", "amount": 100})
    tampered_payload = make_event("payment_intent.succeeded", {"id": "pi_test", "amount": 1})

    response = client.post(
        "/api/webhooks/stripe",
        content=tampered_payload,
        headers=signed_headers(signed_payload),
    )

    assert response.status_code == 400
    assert calls == []


def test_valid_payment_event_reaches_the_handler(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        webhooks_module, "apply_payment_event", lambda *args: calls.append(args)
    )
    intent = {"id": "pi_test", "amount": 12620}
    payload = make_event("payment_intent.succeeded", intent)

    response = client.post(
        "/api/webhooks/stripe", content=payload, headers=signed_headers(payload)
    )

    assert response.status_code == 200
    assert calls == [("payment_intent.succeeded", intent)]


def test_failed_payment_event_reaches_the_handler(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        webhooks_module, "apply_payment_event", lambda *args: calls.append(args)
    )
    intent = {"id": "pi_test", "amount": 12620}
    payload = make_event("payment_intent.payment_failed", intent)

    response = client.post(
        "/api/webhooks/stripe", content=payload, headers=signed_headers(payload)
    )

    assert response.status_code == 200
    assert calls == [("payment_intent.payment_failed", intent)]

def test_newly_paid_ride_queues_a_receipt_email(client, monkeypatch):
    sent = []
    job = ("ride-1", "rider-1")
    monkeypatch.setattr(webhooks_module, "apply_payment_event", lambda *args: job)
    monkeypatch.setattr(
        webhooks_module, "send_receipt_for_ride", lambda *args: sent.append(args)
    )
    payload = make_event("payment_intent.succeeded", {"id": "pi_test", "amount": 12620})

    response = client.post(
        "/api/webhooks/stripe", content=payload, headers=signed_headers(payload)
    )

    assert response.status_code == 200
    assert sent == [job]


def test_no_email_when_the_payment_did_not_change(client, monkeypatch):
    sent = []
    monkeypatch.setattr(webhooks_module, "apply_payment_event", lambda *args: None)
    monkeypatch.setattr(
        webhooks_module, "send_receipt_for_ride", lambda *args: sent.append(args)
    )
    payload = make_event("payment_intent.succeeded", {"id": "pi_test", "amount": 12620})

    response = client.post(
        "/api/webhooks/stripe", content=payload, headers=signed_headers(payload)
    )

    assert response.status_code == 200
    assert sent == []