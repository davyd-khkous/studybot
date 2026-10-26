"""Создание PDF (с кириллицей) и склейка PDF-файлов."""
import io
from pathlib import Path

from fpdf import FPDF
from pypdf import PdfReader, PdfWriter

FONT = "DejaVu"
_CANDIDATE_DIRS = [
    Path(__file__).resolve().parent.parent / "fonts",
    Path("/app/fonts"),
    Path("/usr/share/fonts/truetype/dejavu"),
]


def _find_font(filename: str):
    for d in _CANDIDATE_DIRS:
        p = d / filename
        if p.exists():
            return p
    return None


def _new_pdf() -> FPDF:
    regular = _find_font("DejaVuSans.ttf")
    if regular is None:
        raise RuntimeError("Не найден шрифт DejaVuSans.ttf (папка fonts/)")
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(True, margin=15)
    pdf.set_margins(15, 15, 15)
    pdf.add_font(FONT, "", str(regular))
    bold = _find_font("DejaVuSans-Bold.ttf")
    pdf.add_font(FONT, "B", str(bold or regular))
    return pdf


def _out(pdf: FPDF) -> bytes:
    return bytes(pdf.output())


def _line(pdf: FPDF, h: float, text: str) -> None:
    pdf.multi_cell(0, h, text, new_x="LMARGIN", new_y="NEXT")


def text_pdf_bytes(title: str, date_text: str, body: str, meta: str = "") -> bytes:
    pdf = _new_pdf()
    pdf.add_page()
    pdf.set_font(FONT, "B", 16)
    _line(pdf, 8, title)
    pdf.set_font(FONT, "", 10)
    pdf.set_text_color(110, 110, 110)
    _line(pdf, 6, f"Дата: {date_text}" + (f"   {meta}" if meta else ""))
    pdf.ln(3)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font(FONT, "", 12)
    _line(pdf, 6.5, body or " ")
    return _out(pdf)


def photo_pdf_bytes(image_bytes: bytes, heading: str) -> bytes:
    pdf = _new_pdf()
    pdf.add_page()
    pdf.set_font(FONT, "B", 11)
    _line(pdf, 6, heading)
    y = pdf.get_y() + 2
    pdf.image(
        io.BytesIO(image_bytes), x=15, y=y, w=180, h=297 - y - 15, keep_aspect_ratio=True
    )
    return _out(pdf)


def note_pdf_bytes(heading: str, message: str) -> bytes:
    """Страница-заглушка, если файл нельзя вложить."""
    pdf = _new_pdf()
    pdf.add_page()
    pdf.set_font(FONT, "B", 12)
    _line(pdf, 7, heading)
    pdf.set_font(FONT, "", 11)
    pdf.set_text_color(110, 110, 110)
    _line(pdf, 6, message)
    return _out(pdf)


def toc_pdf_bytes(title: str, lines: list[str]) -> bytes:
    pdf = _new_pdf()
    pdf.add_page()
    pdf.set_font(FONT, "B", 18)
    _line(pdf, 10, title)
    pdf.ln(2)
    pdf.set_font(FONT, "", 11)
    for line in lines:
        _line(pdf, 6, line)
    return _out(pdf)


def merge_pdfs(parts: list[tuple[str, bytes]]) -> tuple[bytes, list[str]]:
    """Склеивает PDF. Возвращает (итоговый pdf, список названий, которые не удалось вложить)."""
    writer = PdfWriter()
    failed: list[str] = []
    for label, data in parts:
        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                reader.decrypt("")
            writer.append(reader)
        except Exception:
            failed.append(label)
            writer.append(
                PdfReader(
                    io.BytesIO(
                        note_pdf_bytes(label, "Этот PDF не удалось вложить (защищён или повреждён).")
                    )
                )
            )
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue(), failed
