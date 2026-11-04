"""Reading uploaded files safely: size limit, allowed types by extension and by content, plain text out."""
import csv
import io

MAX_BYTES = 5 * 1024 * 1024  # 5 MB
RESUME_TYPES = (".pdf", ".docx", ".txt")
SHEET_TYPES = (".csv", ".xlsx")


class FileProblem(Exception):
    """A message the user can act on."""


def read_upload(file, allowed):
    name = (file.filename or "").lower().strip()
    if not name:
        raise FileProblem("Choose a file to upload.")
    if name.endswith(".doc") or name.endswith(".xls"):
        raise FileProblem("Old Office files (.doc, .xls) can't be read. Save it as " + ("DOCX or PDF." if name.endswith(".doc") else "XLSX or CSV."))
    if not name.endswith(allowed):
        raise FileProblem(f"Upload a {', '.join(a.upper().lstrip('.') for a in allowed)} file.")
    data = file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise FileProblem("That file is larger than 5 MB.")
    if not data:
        raise FileProblem("That file is empty.")
    return name, data


def resume_text(file):
    name, data = read_upload(file, RESUME_TYPES)
    try:
        if name.endswith(".pdf"):
            if not data.startswith(b"%PDF"):
                raise FileProblem("That file isn't a real PDF.")
            from pypdf import PdfReader
            text = "\n".join((pg.extract_text() or "") for pg in PdfReader(io.BytesIO(data)).pages[:20])
        elif name.endswith(".docx"):
            if not data.startswith(b"PK"):
                raise FileProblem("That file isn't a real DOCX.")
            import docx
            d = docx.Document(io.BytesIO(data))
            parts = [p.text for p in d.paragraphs]
            for t in d.tables:
                for row in t.rows:
                    parts.append(" | ".join(c.text for c in row.cells))
            text = "\n".join(parts)
        else:
            text = data.decode("utf-8", errors="ignore")
    except FileProblem:
        raise
    except Exception:
        raise FileProblem("We couldn't read that file. Try a PDF, DOCX or TXT.")
    text = text.replace("\x00", "").strip()
    if len(text) < 20:
        raise FileProblem("We couldn't find any text in that file. If it's a scanned image, upload a PDF with selectable text or a DOCX.")
    return text[:30000]


def sheet_rows(file, max_rows=500):
    """CSV or XLSX -> list of dicts keyed by the header row (lower-cased, trimmed). Empty rows are dropped."""
    name, data = read_upload(file, SHEET_TYPES)
    try:
        if name.endswith(".csv"):
            text = data.decode("utf-8-sig", errors="ignore")
            rows = list(csv.reader(io.StringIO(text)))
        else:
            if not data.startswith(b"PK"):
                raise FileProblem("That file isn't a real XLSX.")
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            ws = wb.worksheets[0]
            rows = [["" if v is None else str(v) for v in r] for r in ws.iter_rows(values_only=True)]
    except FileProblem:
        raise
    except Exception:
        raise FileProblem("We couldn't read that file. Use the template, saved as CSV or XLSX.")
    rows = [r for r in rows if any(str(c).strip() for c in r)]
    if len(rows) < 2:
        raise FileProblem("The file needs a header row and at least one person.")
    head = [str(h).strip().lower() for h in rows[0]]
    out = [{head[i]: str(v).strip() for i, v in enumerate(r) if i < len(head) and head[i]} for r in rows[1:max_rows + 1]]
    return out, len(rows) - 1
