import pytest

import emailer
from emailer import build_receipt_email, send_receipt_email

RECEIPT = {
    "receipt_number": "RCPT-1A2B3C4D",
    "ride_id": "00000000-0000-0000-0000-000000000000",
    "payment_id": "11111111-1111-1111-1111-111111111111",
    "ride_date": "2026-10-13T19:50:05.186237+00:00",
    "rider": {"name": None, "email": "rider@example.com"},
    "vehicle": "Toyota Etios, white, TEST-1234",
    "pickup": {"lat": 51.508, "lng": -0.1281},
    "drop": {"lat": 51.5055, "lng": -0.0754},
    "distance_meters": 4742,
    "duration_secs": 772,
    "amount": 12620,
    "currency": "inr",
}
PDF = b"%PDF-fake"


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.steps = []
        self.sent = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self, context=None):
        self.steps.append("starttls")

    def login(self, username, password):
        self.steps.append(("login", username))

    def send_message(self, message):
        self.steps.append("send")
        self.sent.append(message)


def test_email_has_recipient_subject_and_pdf_attachment():
    message = build_receipt_email(RECEIPT, PDF, "receipts@example.com")

    assert message["To"] == "rider@example.com"
    assert message["From"] == "receipts@example.com"
    assert "RCPT-1A2B3C4D" in message["Subject"]

    attachments = list(message.iter_attachments())
    assert len(attachments) == 1
    assert attachments[0].get_content_type() == "application/pdf"
    assert attachments[0].get_filename() == "RCPT-1A2B3C4D.pdf"
    assert attachments[0].get_content() == PDF


def test_email_body_shows_the_total():
    message = build_receipt_email(RECEIPT, PDF, "receipts@example.com")
    body = message.get_body(preferencelist=("plain",)).get_content()
    assert "INR 126.20" in body


def test_email_rejects_line_breaks_in_the_recipient():
    receipt = {
        **RECEIPT,
        "rider": {"name": None, "email": "a@example.com\nBcc: evil@example.com"},
    }
    with pytest.raises(ValueError):
        build_receipt_email(receipt, PDF, "receipts@example.com")


def test_send_is_skipped_when_smtp_is_not_configured(monkeypatch):
    for name in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD"):
        monkeypatch.delenv(name, raising=False)

    assert send_receipt_email(RECEIPT, PDF) is False


def test_send_uses_starttls_then_login_then_sends(monkeypatch):
    FakeSMTP.instances = []
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_USERNAME", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "pass")
    monkeypatch.setattr(emailer.smtplib, "SMTP", FakeSMTP)

    assert send_receipt_email(RECEIPT, PDF) is True

    server = FakeSMTP.instances[0]
    assert (server.host, server.port) == ("smtp.test", 2525)
    assert server.steps == ["starttls", ("login", "user"), "send"]
    assert server.sent[0]["To"] == "rider@example.com"

def test_email_body_shows_the_discount():
    receipt = {
        **RECEIPT,
        "original_amount": 12620,
        "discount_amount": 1262,
        "promo_code": "WELCOME10",
        "amount": 11358,
    }
    message = build_receipt_email(receipt, PDF, "receipts@example.com")
    body = message.get_body(preferencelist=("plain",)).get_content()

    assert "WELCOME10" in body
    assert "INR 126.20" in body
    assert "INR 12.62" in body
    assert "INR 113.58" in body


def test_email_body_without_a_discount_has_no_discount_line():
    message = build_receipt_email(RECEIPT, PDF, "receipts@example.com")
    body = message.get_body(preferencelist=("plain",)).get_content()

    assert "Discount" not in body

def test_email_with_a_discount_still_has_the_pdf_attached():
    receipt = {
        **RECEIPT,
        "original_amount": 12620,
        "discount_amount": 1262,
        "promo_code": "WELCOME10",
        "amount": 11358,
    }
    message = build_receipt_email(receipt, PDF, "receipts@example.com")

    attachments = list(message.iter_attachments())
    assert len(attachments) == 1
    assert attachments[0].get_filename() == "RCPT-1A2B3C4D.pdf"