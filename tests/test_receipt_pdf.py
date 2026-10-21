import pytest

from receipt_pdf import format_money, render_receipt_pdf

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


@pytest.mark.parametrize(
    "amount, currency, expected",
    [
        (12620, "inr", "INR 126.20"),
        (5, "usd", "USD 0.05"),
        (0, "inr", "INR 0.00"),
        (100000050, "inr", "INR 1,000,000.50"),
    ],
)
def test_format_money(amount, currency, expected):
    assert format_money(amount, currency) == expected


def test_pdf_has_a_pdf_header():
    pdf = render_receipt_pdf(RECEIPT)
    assert isinstance(pdf, bytes)
    assert pdf.startswith(b"%PDF")


def test_pdf_handles_missing_optional_values():
    receipt = {
        **RECEIPT,
        "vehicle": None,
        "distance_meters": None,
        "duration_secs": None,
    }
    assert render_receipt_pdf(receipt).startswith(b"%PDF")


def test_pdf_handles_text_outside_latin_1():
    receipt = {**RECEIPT, "vehicle": "Maruti 日本語 ₹ ✓", "rider": {"name": "Zoë Ångström 李", "email": "z@example.com"}}
    assert render_receipt_pdf(receipt).startswith(b"%PDF")


def test_pdf_handles_a_very_long_vehicle_description():
    receipt = {**RECEIPT, "vehicle": "x" * 200}
    assert render_receipt_pdf(receipt).startswith(b"%PDF")

def test_pdf_with_a_discount_renders():
    receipt = {
        **RECEIPT,
        "original_amount": 12620,
        "discount_amount": 1262,
        "promo_code": "WELCOME10",
        "amount": 11358,
    }
    assert render_receipt_pdf(receipt).startswith(b"%PDF")