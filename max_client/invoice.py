"""Генерация PDF инвойсов для платежей."""
import io
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, black
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

# Регистрируем шрифт с кириллицей
try:
    pdfmetrics.registerFont(UnicodeCIDFont('HeiseiKakuGo-W5'))
    FONT_NAME = "HeiseiKakuGo-W5"
except Exception:
    FONT_NAME = "Helvetica"

# Fallback: использовать встроенный HeiseiKakuGo-W5 для кириллицы не работает.
# Используем DejaVuSans если доступен (обычно есть в Linux)
import os
for font_path in [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
]:
    if os.path.exists(font_path):
        try:
            pdfmetrics.registerFont(TTFont("DejaVuSans", font_path))
            pdfmetrics.registerFont(TTFont(
                "DejaVuSans-Bold",
                font_path.replace("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
            ))
            FONT_NAME = "DejaVuSans"
            FONT_BOLD = "DejaVuSans-Bold"
            break
        except Exception:
            pass
else:
    FONT_BOLD = "Helvetica-Bold"


def generate_invoice_pdf(
    payment_id: str,
    plan_name: str,
    amount: float,
    email: str,
    paid_at: datetime,
    description: str = "",
) -> bytes:
    """Генерирует PDF инвойс."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    # Colors
    primary = HexColor("#6366f1")
    dark = HexColor("#0f172a")
    muted = HexColor("#64748b")
    light = HexColor("#e2e8f0")

    # Header gradient bar
    c.setFillColor(primary)
    c.rect(0, height - 25 * mm, width, 25 * mm, fill=1, stroke=0)

    # Logo + brand
    c.setFillColor(HexColor("#ffffff"))
    c.setFont(FONT_BOLD, 20)
    c.drawString(20 * mm, height - 15 * mm, "⚡ MaxSurge")
    c.setFont(FONT_NAME, 9)
    c.drawString(20 * mm, height - 20 * mm, "maxsurge.ru")

    # Invoice title
    c.setFont(FONT_BOLD, 10)
    c.drawRightString(width - 20 * mm, height - 15 * mm, "СЧЁТ-КВИТАНЦИЯ")
    c.setFont(FONT_NAME, 9)
    c.drawRightString(width - 20 * mm, height - 20 * mm, f"№ {payment_id[:20]}")

    # Body
    y = height - 45 * mm

    c.setFillColor(dark)
    c.setFont(FONT_BOLD, 14)
    c.drawString(20 * mm, y, "Чек об оплате")
    y -= 8 * mm

    c.setFont(FONT_NAME, 10)
    c.setFillColor(muted)
    c.drawString(20 * mm, y, f"Дата: {paid_at.strftime('%d.%m.%Y %H:%M')}")
    y -= 10 * mm

    # Info block
    c.setFillColor(HexColor("#f1f5f9"))
    c.roundRect(20 * mm, y - 30 * mm, width - 40 * mm, 30 * mm, 4, fill=1, stroke=0)

    c.setFillColor(dark)
    c.setFont(FONT_BOLD, 10)
    c.drawString(25 * mm, y - 6 * mm, "Плательщик:")
    c.setFont(FONT_NAME, 10)
    c.drawString(55 * mm, y - 6 * mm, email)

    c.setFont(FONT_BOLD, 10)
    c.drawString(25 * mm, y - 14 * mm, "Тариф:")
    c.setFont(FONT_NAME, 10)
    c.drawString(55 * mm, y - 14 * mm, plan_name)

    if description:
        c.setFont(FONT_BOLD, 10)
        c.drawString(25 * mm, y - 22 * mm, "Услуга:")
        c.setFont(FONT_NAME, 10)
        c.drawString(55 * mm, y - 22 * mm, description[:70])

    y -= 40 * mm

    # Amount
    c.setFillColor(light)
    c.setLineWidth(0.5)
    c.line(20 * mm, y, width - 20 * mm, y)
    y -= 10 * mm

    c.setFillColor(dark)
    c.setFont(FONT_BOLD, 12)
    c.drawString(20 * mm, y, "Итого к оплате:")

    c.setFillColor(primary)
    c.setFont(FONT_BOLD, 18)
    c.drawRightString(width - 20 * mm, y, f"{amount:.2f} ₽")
    y -= 8 * mm

    c.setFillColor(muted)
    c.setFont(FONT_NAME, 8)
    c.drawRightString(width - 20 * mm, y, "НДС не облагается")

    # Status
    y -= 20 * mm
    c.setFillColor(HexColor("#10b981"))
    c.roundRect(20 * mm, y - 6 * mm, 50 * mm, 10 * mm, 3, fill=1, stroke=0)
    c.setFillColor(HexColor("#ffffff"))
    c.setFont(FONT_BOLD, 10)
    c.drawString(25 * mm, y - 2 * mm, "✓ ОПЛАЧЕНО")

    # Footer
    c.setFillColor(muted)
    c.setFont(FONT_NAME, 8)
    footer_y = 20 * mm
    c.drawCentredString(width / 2, footer_y, "MaxSurge — сервис для бизнес-коммуникаций в мессенджере MAX")
    c.drawCentredString(width / 2, footer_y - 4 * mm, "https://maxsurge.ru  •  support@maxsurge.ru")
    c.drawCentredString(width / 2, footer_y - 8 * mm, f"Документ сформирован автоматически {datetime.utcnow().strftime('%d.%m.%Y %H:%M')} UTC")

    c.showPage()
    c.save()
    return buf.getvalue()
