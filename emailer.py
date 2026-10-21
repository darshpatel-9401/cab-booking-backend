import os
import smtplib
import ssl
import uuid
from email.message import EmailMessage

from dotenv import load_dotenv
from sqlmodel import Session

from database import engine
from receipt_pdf import format_money, render_receipt_pdf
from receipts import build_receipt

load_dotenv()


def build_receipt_email(receipt: dict, pdf_bytes: bytes, sender: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = f"Your receipt {receipt['receipt_number']}"
    message["From"] = sender
    message["To"] = receipt["rider"]["email"]

    total = format_money(receipt["amount"], receipt["currency"])
    discount = receipt.get("discount_amount", 0)
    discount_lines = ""
    if discount > 0:
        promo_code = receipt.get("promo_code")
        label = f"Discount ({promo_code})" if promo_code else "Discount"
        discount_lines = (
            f"Fare: {format_money(receipt['original_amount'], receipt['currency'])}\n"
            f"{label}: -{format_money(discount, receipt['currency'])}\n"
        )

    message.set_content(
        "Hello,\n\n"
        "Thank you for riding with us. Your payment was received.\n\n"
        f"Receipt number: {receipt['receipt_number']}\n"
        f"{discount_lines}"
        f"Total paid: {total}\n\n"
        "Your receipt is attached as a PDF.\n"
    )
    message.add_attachment(
        pdf_bytes,
        maintype="application",
        subtype="pdf",
        filename=f"{receipt['receipt_number']}.pdf",
    )
    return message


def send_receipt_email(receipt: dict, pdf_bytes: bytes) -> bool:
    host = os.getenv("SMTP_HOST")
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    port = int(os.getenv("SMTP_PORT", "2525"))
    sender = os.getenv("EMAIL_FROM", "receipts@example.com")

    if not (host and username and password):
        print("Email is not configured (SMTP_* in backend/.env). Skipping.")
        return False

    message = build_receipt_email(receipt, pdf_bytes, sender)

    with smtplib.SMTP(host, port, timeout=15) as server:
        server.starttls(context=ssl.create_default_context())
        server.login(username, password)
        server.send_message(message)
    return True


def send_receipt_for_ride(ride_id: uuid.UUID, rider_id: uuid.UUID) -> None:
    """Runs in the background. Never raises, so it can't affect a payment."""
    try:
        with Session(engine) as db:
            receipt = build_receipt(db, ride_id, rider_id)
        pdf_bytes = render_receipt_pdf(receipt)
        if send_receipt_email(receipt, pdf_bytes):
            print("Receipt email sent for ride", ride_id)
    except Exception as e:
        print("Receipt email failed:", repr(e))