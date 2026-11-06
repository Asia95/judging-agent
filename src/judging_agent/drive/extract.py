"""
drive/extract.py — readable text from downloaded file bytes.

  - PDF          → text extracted with pypdf
  - DOCX (Word)  → paragraphs extracted with python-docx
  - XLSX (Excel) → cell values extracted with openpyxl, one line per row
  - anything else → bytes decoded as UTF-8
"""

import io


def extract_text(mime: str, name: str, raw: bytes) -> str:
    """Extract readable text from binary file content based on MIME type."""
    # PDF
    if mime == "application/pdf" or name.lower().endswith(".pdf"):
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(raw))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:
            return f"[PDF text extraction failed: {exc}]"

    # DOCX (Word)
    if (mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            or name.lower().endswith(".docx")):
        try:
            import docx
            doc = docx.Document(io.BytesIO(raw))
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception as exc:
            return f"[DOCX text extraction failed: {exc}]"

    # XLSX (Excel)
    if (mime == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            or name.lower().endswith(".xlsx")):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
            lines = []
            for sheet in wb.worksheets:
                lines.append(f"[Sheet: {sheet.title}]")
                for row in sheet.iter_rows(values_only=True):
                    line = "\t".join("" if v is None else str(v) for v in row)
                    if line.strip():
                        lines.append(line)
            return "\n".join(lines)
        except Exception as exc:
            return f"[XLSX text extraction failed: {exc}]"

    # Fallback — plain text / unknown binary
    return raw.decode("utf-8", errors="replace")
