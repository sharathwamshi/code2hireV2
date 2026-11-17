"""Resume files (V02.00.11, CAN-002 / CAN-014).

The original file is kept, not only its text, so the candidate and the hiring team can see which resume is on file,
download it, and replace it. Every upload is a version: reading a resume stores it as "pending"; saving it makes it
"current" and the previous one "old". A resume pasted as text has no file, so saving it retires the old file.

Files live on the server's disk under UPLOAD_DIR/resumes/<user id>/. Back that folder up with the database.
Old Word files (.doc) are converted with LibreOffice and scanned PDFs are read with Tesseract OCR when those tools are
installed on the server; without them the candidate gets a clear message instead."""
import io
import os
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime, timedelta

from flask import current_app

from extensions import db

MIME = {"pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "doc": "application/msword", "txt": "text/plain"}
EXT = {"pdf": ".pdf", "docx": ".docx", "doc": ".doc", "txt": ".txt"}


def _problem(msg):
    from services.files import FileProblem
    return FileProblem(msg)


def _pdf_text(data):
    from pypdf import PdfReader
    return "\n".join((pg.extract_text() or "") for pg in PdfReader(io.BytesIO(data)).pages[:20])


def _ocr_pdf(data, pages=5):
    """Scanned PDF -> text with pdftoppm + tesseract, when both are installed. Returns "" otherwise."""
    if not (shutil.which("pdftoppm") and shutil.which("tesseract")):
        return ""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "in.pdf")
        with open(src, "wb") as fh:
            fh.write(data)
        try:
            subprocess.run(["pdftoppm", "-r", "200", "-l", str(pages), "-png", src, os.path.join(d, "p")], check=True, timeout=60,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            out = []
            for img in sorted(x for x in os.listdir(d) if x.endswith(".png")):
                r = subprocess.run(["tesseract", os.path.join(d, img), "-", "--psm", "3"], capture_output=True, timeout=60)
                out.append(r.stdout.decode("utf-8", "ignore"))
            return "\n".join(out)
        except (subprocess.SubprocessError, OSError):
            return ""


def _doc_text(data):
    """Old Word (.doc) -> text with LibreOffice, when installed."""
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe:
        raise _problem("Old Word files (.doc) can't be read on this server. Save it as DOCX or PDF and upload again.")
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "resume.doc")
        with open(src, "wb") as fh:
            fh.write(data)
        try:
            subprocess.run([exe, "--headless", f"-env:UserInstallation=file://{d}/profile", "--convert-to", "txt:Text", "--outdir", d, src],
                           check=True, timeout=90, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with open(os.path.join(d, "resume.txt"), encoding="utf-8", errors="ignore") as fh:
                return fh.read()
        except (subprocess.SubprocessError, OSError, FileNotFoundError):
            raise _problem("We couldn't read that Word file. Save it as DOCX or PDF and upload again.")


def text_of(kind, data):
    from services.files import FileProblem
    try:
        if kind == "pdf":
            text = _pdf_text(data)
            if len(text.strip()) < 20:
                text = _ocr_pdf(data)
                if len(text.strip()) < 20:
                    raise _problem("This looks like a scanned PDF and we couldn't read its text. Upload a PDF with selectable text, or a Word file.")
        elif kind == "docx":
            import docx
            d = docx.Document(io.BytesIO(data))
            parts = [p.text for p in d.paragraphs]
            for t in d.tables:
                for row in t.rows:
                    parts.append(" | ".join(c.text for c in row.cells))
            text = "\n".join(parts)
        elif kind == "doc":
            text = _doc_text(data)
        else:
            text = data.decode("utf-8", errors="ignore")
    except FileProblem:
        raise
    except Exception:  # noqa: BLE001 - a damaged file
        raise _problem("We couldn't read that file. Try a PDF, Word or TXT file.")
    text = text.replace("\x00", "").strip()
    if len(text) < 20:
        raise _problem("We couldn't find any text in that file.")
    return text[:30000]


def _folder(user_id):
    f = os.path.join(current_app.config["UPLOAD_DIR"], "resumes", str(int(user_id)))
    os.makedirs(f, exist_ok=True)
    return f


def store_pending(user_id, name, kind, data, text, by_id):
    """Keeps an uploaded file until the person saves (or drops) the preview. Old unsaved uploads are cleared."""
    from models import ResumeFile
    for old in ResumeFile.query.filter(ResumeFile.user_id == user_id, ResumeFile.status == "pending",
                                       ResumeFile.created_at < datetime.utcnow() - timedelta(hours=6)).all():
        _remove(old)
    key = f"{uuid.uuid4().hex}{EXT[kind]}"
    with open(os.path.join(_folder(user_id), key), "wb") as fh:
        fh.write(data)
    base = os.path.basename(name)
    if not os.path.splitext(base)[1]:
        base += EXT[kind]
    rf = ResumeFile(user_id=user_id, filename=base[:200], kind=kind, size=len(data), file_key=key, chars=len(text),
                    status="pending", uploaded_by=by_id)
    db.session.add(rf)
    db.session.flush()
    return rf


def _remove(rf):
    try:
        os.remove(os.path.join(_folder(rf.user_id), rf.file_key))
    except OSError:
        pass
    db.session.delete(rf)


def make_current(user_id, upload_id):
    """Called when a resume is saved. upload_id = the file read for the preview, or None for pasted text."""
    from models import ResumeFile
    new = ResumeFile.query.filter_by(id=upload_id, user_id=user_id).first() if upload_id else None
    for rf in ResumeFile.query.filter_by(user_id=user_id, status="current").all():
        if not new or rf.id != new.id:
            rf.status = "old"
    if new:
        new.status = "current"
    return new


def current(user_id):
    from models import ResumeFile
    rf = ResumeFile.query.filter_by(user_id=user_id, status="current").order_by(ResumeFile.id.desc()).first()
    return rf


def info(rf):
    if not rf:
        return None
    from models import User
    by = db.session.get(User, rf.uploaded_by) if rf.uploaded_by else None
    return {"id": rf.id, "filename": rf.filename, "kind": rf.kind, "size": rf.size, "uploaded_at": rf.created_at.isoformat() + "Z",
            "by_staff": bool(by and by.id != rf.user_id), "by": by.name if by and by.id != rf.user_id else None}


def history(user_id, n=10):
    from models import ResumeFile
    return [info(r) | {"status": r.status} for r in ResumeFile.query.filter(ResumeFile.user_id == user_id, ResumeFile.status != "pending")
            .order_by(ResumeFile.id.desc()).limit(n).all()]


def send(rf):
    from flask import send_file
    return send_file(os.path.join(_folder(rf.user_id), rf.file_key), mimetype=MIME.get(rf.kind, "application/octet-stream"),
                     as_attachment=True, download_name=rf.filename)


def erase_all(user_id):
    """When a candidate deletes their account."""
    from models import ResumeFile
    for rf in ResumeFile.query.filter_by(user_id=user_id).all():
        _remove(rf)
    shutil.rmtree(os.path.join(current_app.config["UPLOAD_DIR"], "resumes", str(int(user_id))), ignore_errors=True)
