"""Text extraction for every supported file type (C10)."""

import io

from judging_agent.drive.extract import extract_text

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_pdf():
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Courier", size=10)
    pdf.cell(0, 5, "Invoice INV-2024-001 Total: $3,725.73")
    assert "INV-2024-001" in extract_text(PDF, "inv.pdf", bytes(pdf.output()))


def test_docx():
    import docx
    doc = docx.Document()
    doc.add_paragraph("Supplier agreement: Net 45")
    buf = io.BytesIO()
    doc.save(buf)
    assert "Net 45" in extract_text(DOCX, "agreement.docx", buf.getvalue())


def test_xlsx_lists_every_sheet():
    import openpyxl
    wb = openpyxl.Workbook()
    wb.active.title = "P&L"
    wb.active.append(["Revenue", 587500])
    wb.create_sheet("Products").append(["Furniture", 95000])
    buf = io.BytesIO()
    wb.save(buf)
    text = extract_text(XLSX, "q3.xlsx", buf.getvalue())
    assert "[Sheet: P&L]" in text and "Revenue\t587500" in text and "[Sheet: Products]" in text


def test_plain_text_and_unknown_types_are_decoded():
    assert extract_text("text/plain", "a.txt", "héllo".encode()) == "héllo"


def test_a_broken_file_gives_a_message_not_an_exception():
    assert extract_text(PDF, "broken.pdf", b"not a pdf").startswith("[PDF text extraction failed")
