from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from PIL import Image, ImageDraw, ImageFont
import qrcode
import io
from datetime import datetime


def compute_rank_percentile(score: int):
    """Return rank string and percentile (int) based on score."""
    if score >= 95:
        return "S (Elite)", 99
    elif score >= 90:
        return "A+ (Exceptional)", 95
    elif score >= 80:
        return "A (Excellent)", 88
    elif score >= 70:
        return "B (Strong)", 74
    elif score >= 60:
        return "C (Average)", 63
    else:
        return "D (Needs Improvement)", 35


def make_qr_image(data: str, size: int = 300):
    """Return a PIL Image object containing a QR code for `data`."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    img = img.resize((size, size), Image.Resampling.LANCZOS)
    return img


def draw_decorative_border(c, w, h, margin=20 * mm):
    """Draw a thin decorative border with small corner flourishes."""

    c.setStrokeColor(colors.HexColor("#3310a7"))  # deep slate
    c.setLineWidth(3)
    c.roundRect(margin / 2, margin / 2, w - margin, h - margin, 12 * mm, stroke=1, fill=0)

    # inner thin rect
    c.setLineWidth(1)
    inset = 12
    c.setStrokeColor(colors.HexColor("#13419d"))
    c.roundRect(
        margin / 2 + inset,
        margin / 2 + inset,
        w - margin - 2 * inset,
        h - margin - 2 * inset,
        8 * mm,
        stroke=1,
        fill=0,
    )

def generate_certificate_pdf(
    name: str,
    score: int,
    output_filename: str = "certificate.pdf",
    issuer: str = "",
    verification_url: str = None,  
    credits_text: str = "LinkedIn AI Reviewer - Sparsh Agarwal",
    date: str = None,
):
    """
    Generate a certificate PDF with a QR code and credits.

    - name: recipient name
    - score: integer 0-100
    - output_filename: filename to save
    - issuer: small issuer label
    - verification_url: URL encoded into QR (if None, QR contains a verification summary string)
    - credits_text: text printed at the bottom
    - date: optional date string, defaults to today
    """
    if date is None:
        date = datetime.now().strftime("%d %B %Y")

    rank, percentile = compute_rank_percentile(score)

    sentence = (
        f"has achieved a LinkedIn Profile Performance Score of {score} using our AI-powered LinkedIn Profile Reviewer on {date}. Based on the evaluated parameters of content clarity, headline structure, achievement representation, and relevant industry keywords, the candidate secures an estimated {rank} standing, placing them in the top {percentile}% of professional LinkedIn profiles in our evaluation. This certificate reflects an analytical review of the provided information and serves as a benchmark report for future optimization and professional positioning."
    )

    if verification_url:
        qr_data = verification_url
    else:
        qr_data = f"cert|name:{name}|score:{score}|rank:{rank}|date:{date}"

    qr_img = make_qr_image(qr_data, size=420)

    page_size = landscape(A4)  
    w, h = page_size
    c = canvas.Canvas(output_filename, pagesize=page_size)

    draw_decorative_border(c, w, h)

    title_y = h - 30 * mm
    c.setFont("Helvetica-Bold", 30)
    c.setFillColor(colors.HexColor("#000000"))  
    c.drawCentredString(w / 2, title_y, "LinkedIn Profile Performance")

    c.setFont("Helvetica", 16)
    c.setFillColor(colors.HexColor("#4b5563"))
    c.drawCentredString(w / 2, title_y - 10 * mm, "This is to certify that")

    name_y = title_y - 26 * mm
    c.setFont("Helvetica-Bold", 26)
    c.setFillColor(colors.HexColor("#111827"))
    c.drawCentredString(w / 2, name_y, name)

    badge_w = 70 * mm
    badge_h = 28 * mm
    badge_x = w - 25 * mm - badge_w
    badge_y = name_y - 34 * mm
    c.setFillColor(colors.HexColor("#22b470"))  
    c.setStrokeColor(colors.HexColor("#afe2a9"))
    c.setLineWidth(1)
    c.roundRect(badge_x, badge_y, badge_w, badge_h, 6 * mm, stroke=1, fill=1)

    c.setFillColor(colors.HexColor("#16a34a"))
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(badge_x + badge_w / 2, badge_y + 14 * mm, f"{score} / 100")

    c.setFillColor(colors.HexColor("#4b5563"))
    c.setFont("Helvetica", 9)
    c.drawCentredString(
        badge_x + badge_w / 2,
        badge_y + 5 * mm,
        f"Rank: {rank} • Approx. top {percentile}% profiles",
    )

    margin_x = 30 * mm
    text_width = w - margin_x * 2 - 120 * mm  
    text_start_x = margin_x
    text_start_y = title_y - 40 * mm

    text = c.beginText()
    text.setTextOrigin(text_start_x, text_start_y)
    text.setFont("Helvetica", 12)
    text.setFillColor(colors.HexColor("#374151"))
    
    words = sentence.split()
    line = ""
    max_chars_per_line = 85  
    for word in words:
        if len(line) + 1 + len(word) <= max_chars_per_line:
            if line:
                line += " " + word
            else:
                line = word
        else:
            text.textLine(line)
            line = word
    if line:
        text.textLine(line)
    c.drawText(text)

    qr_reader = ImageReader(qr_img)
    qr_size_mm = 60 * mm
    qr_x = w - margin_x - qr_size_mm
    qr_y = text_start_y - 100 * mm 
    c.drawImage(qr_reader, qr_x, qr_y, width=qr_size_mm, height=qr_size_mm, mask='auto')

    c.setFont("Helvetica-Oblique", 9)
    c.setFillColor(colors.HexColor("#34495e"))
    c.drawCentredString(qr_x + qr_size_mm/2, qr_y - 6 * mm, "Scan to verify this certificate")

    sig_x = margin_x + 20 * mm
    sig_y = qr_y - 10 * mm
    c.setStrokeColor(colors.HexColor("#7f8c8d"))
    c.setLineWidth(1)
    c.line(sig_x, sig_y, sig_x + 70 * mm, sig_y)  
    c.setFont("Helvetica", 11)
    c.setFillColor(colors.HexColor("#2c3e50"))
    c.drawString(sig_x, sig_y - 8 * mm, "Authorized Signatory")

    c.setFont("Helvetica", 10)
    c.setFillColor(colors.HexColor("#7f8c8d"))
    c.drawString(sig_x, sig_y - 15 * mm, f"Issuer: {issuer}")
    c.drawString(sig_x + 80 * mm, sig_y - 15 * mm, f"Date: {date}")

    c.setFont("Helvetica", 7)
    c.setFillColor(colors.HexColor("#26b2bc"))
    c.drawCentredString(w/2, 12 * mm, credits_text)

    c.showPage()
    c.save()