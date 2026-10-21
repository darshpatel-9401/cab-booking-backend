from datetime import datetime

from fpdf import FPDF
from fpdf.enums import XPos, YPos


def safe_text(value) -> str:
    """Built-in PDF fonts only support Latin-1, so anything else becomes '?'."""
    if value is None:
        return "-"
    return str(value).encode("latin-1", "replace").decode("latin-1")


def format_money(amount: int, currency: str) -> str:
    return f"{currency.upper()} {amount // 100:,}.{amount % 100:02d}"


def format_date(iso_text) -> str:
    try:
        moment = datetime.fromisoformat(iso_text)
        return moment.strftime("%d %b %Y, %H:%M UTC")
    except (TypeError, ValueError):
        return safe_text(iso_text)


def format_distance(meters) -> str:
    if meters is None:
        return "-"
    return f"{meters / 1000:.1f} km"


def format_duration(secs) -> str:
    if secs is None:
        return "-"
    return f"{secs // 60} min"


def format_point(point: dict) -> str:
    return f"{point['lat']:.5f}, {point['lng']:.5f}"


def render_receipt_pdf(receipt: dict) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 12, "Cab Booking", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 8, "Payment receipt", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(6)

    def row(label, value, bold=False):
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(50, 8, safe_text(label), new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.set_font("Helvetica", "B" if bold else "", 11)
        pdf.multi_cell(0, 8, safe_text(value), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    rider = receipt["rider"]
    row("Receipt number", receipt["receipt_number"])
    row("Ride date", format_date(receipt["ride_date"]))
    row("Rider", rider["name"] or rider["email"])
    row("Vehicle", receipt["vehicle"])
    row("Pickup (lat, lng)", format_point(receipt["pickup"]))
    row("Drop-off (lat, lng)", format_point(receipt["drop"]))
    row("Distance", format_distance(receipt["distance_meters"]))
    row("Duration", format_duration(receipt["duration_secs"]))

    discount = receipt.get("discount_amount", 0)
    if discount > 0:
        row("Fare", format_money(receipt["original_amount"], receipt["currency"]))
        promo_code = receipt.get("promo_code")
        label = f"Discount ({promo_code})" if promo_code else "Discount"
        row(label, "- " + format_money(discount, receipt["currency"]))

    pdf.ln(2)
    y = pdf.get_y()
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(50, 10, "Total paid", new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(
        0,
        10,
        safe_text(format_money(receipt["amount"], receipt["currency"])),
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )

    pdf.ln(8)
    pdf.set_font("Helvetica", "", 9)
    pdf.multi_cell(
        0,
        5,
        "Locations are shown as latitude and longitude. Thank you for riding with us.",
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )

    return bytes(pdf.output())