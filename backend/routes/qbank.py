"""Question bank: category folders, versioned questions, usage stats, bulk actions, CSV import/export.

scope=company (default) works on the caller's company bank; scope=global works on the shared Code2Hire bank
(read-only for companies, editable by the Superadmin).
"""
import csv
import io
from collections import defaultdict
from datetime import datetime

from flask import Blueprint, Response, g, request

from extensions import db
from models import Application, Job, Question, QuestionFolder, QuestionVersion, RoundAttempt, User
from routes.utils import body, err, ok, table
from services import ai
from services.audit import log
from services.perms import can_any, deny, staff_required

bp = Blueprint("qbank", __name__, url_prefix="/api/qbank")
LETTERS = "ABCDEF"


def cid():
    if g.user.is_superadmin and request.headers.get("X-Company-Id"):
        return int(request.headers["X-Company-Id"])
    return g.user.company_id


def scope():
    """(company_id or None for global, can_write)."""
    sc = request.args.get("scope") or (request.get_json(silent=True) or {}).get("scope") or "company"
    if sc == "global":
        return None, bool(g.user.is_superadmin)
    if g.user.is_superadmin and not cid():
        return None, True
    return cid(), can_any(g.user, "questions.manage", cid())


def _owned(model, oid, company_id):
    row = db.session.get(model, oid)
    if not row or row.company_id != company_id:
        return None
    return row


# ---------------------------------------------------------------- folders

def descendants(folder_ids, company_id):
    """Folder ids plus every folder nested under them."""
    rows = QuestionFolder.query.filter(QuestionFolder.company_id.is_(company_id) if company_id is None
                                       else QuestionFolder.company_id == company_id).all()
    kids = defaultdict(list)
    for f in rows:
        kids[f.parent_id].append(f.id)
    out, stack = set(), [int(i) for i in folder_ids]
    while stack:
        x = stack.pop()
        if x in out:
            continue
        out.add(x)
        stack.extend(kids.get(x, []))
    return out


def _folder_q(company_id):
    return QuestionFolder.query.filter(QuestionFolder.company_id.is_(None) if company_id is None else QuestionFolder.company_id == company_id)


def _question_q(company_id):
    return Question.query.filter(Question.company_id.is_(None) if company_id is None else Question.company_id == company_id)


@bp.get("/folders")
@staff_required
def folders():
    company_id, writable = scope()
    rows = _folder_q(company_id).order_by(QuestionFolder.name).all()
    counts = defaultdict(int)
    pend = defaultdict(int)
    for fid, st in db.session.query(Question.folder_id, Question.status).filter(
            Question.company_id.is_(None) if company_id is None else Question.company_id == company_id).all():
        if st != "archived":
            counts[fid] += 1
        if st == "pending":
            pend[fid] += 1
    kids = defaultdict(list)
    for f in rows:
        kids[f.parent_id].append(f)

    def node(f):
        ch = [node(c) for c in kids.get(f.id, [])]
        return {"id": f.id, "name": f.name, "description": f.description, "parent_id": f.parent_id, "count": counts[f.id],
                "total": counts[f.id] + sum(c["total"] for c in ch), "pending": pend[f.id] + sum(c["pending"] for c in ch), "children": ch}
    tree = [node(f) for f in kids.get(None, [])]
    total = sum(v for v in counts.values())
    return ok({"tree": tree, "total": total, "unfiled": counts[None], "pending": sum(pend.values()), "writable": writable})


@bp.post("/folders")
@staff_required
def create_folder():
    company_id, writable = scope()
    if not writable:
        return deny()
    d = body()
    name = (d.get("name") or "").strip()
    if not name:
        return err("Give the folder a name.")
    parent = d.get("parent_id")
    if parent and not _owned(QuestionFolder, int(parent), company_id):
        return err("Parent folder not found.")
    f = QuestionFolder(company_id=company_id, parent_id=int(parent) if parent else None, name=name[:120],
                       description=(d.get("description") or "")[:255], created_by=g.user.id)
    db.session.add(f)
    log("qbank.folder.create", "folder", None, company_id=company_id, name=name)
    db.session.commit()
    return ok(f.to_dict())


@bp.patch("/folders/<int:fid>")
@staff_required
def update_folder(fid):
    company_id, writable = scope()
    f = _owned(QuestionFolder, fid, company_id)
    if not f or not writable:
        return deny()
    d = body()
    if "name" in d and d["name"].strip():
        f.name = d["name"].strip()[:120]
    if "description" in d:
        f.description = (d["description"] or "")[:255]
    if "parent_id" in d:
        p = d["parent_id"]
        if p and (int(p) in descendants([fid], company_id)):
            return err("A folder can't move inside itself.")
        if p and not _owned(QuestionFolder, int(p), company_id):
            return err("Parent folder not found.")
        f.parent_id = int(p) if p else None
    log("qbank.folder.update", "folder", fid, company_id=company_id)
    db.session.commit()
    return ok(f.to_dict())


@bp.delete("/folders/<int:fid>")
@staff_required
def delete_folder(fid):
    """Deletes the folder; its questions and sub-folders move up to the parent, so nothing is lost."""
    company_id, writable = scope()
    f = _owned(QuestionFolder, fid, company_id)
    if not f or not writable:
        return deny()
    Question.query.filter_by(folder_id=fid).update({"folder_id": f.parent_id})
    QuestionFolder.query.filter_by(parent_id=fid).update({"parent_id": f.parent_id})
    db.session.delete(f)
    log("qbank.folder.delete", "folder", fid, company_id=company_id, name=f.name)
    db.session.commit()
    return ok()


def folder_path(fid, company_id, cache=None):
    if not fid:
        return ""
    cache = cache if cache is not None else {f.id: f for f in _folder_q(company_id).all()}
    parts, x, guard = [], cache.get(fid), 0
    while x and guard < 20:
        parts.append(x.name)
        x = cache.get(x.parent_id)
        guard += 1
    return " / ".join(reversed(parts))


# ---------------------------------------------------------------- questions

def q_row(q, cache=None):
    d = q.to_dict()
    d["folder"] = folder_path(q.folder_id, q.company_id, cache)
    d["tags"] = q.tags or []
    d["version"] = q.version or 1
    return d


@bp.get("/questions")
@staff_required
def questions():
    company_id, _ = scope()
    query = _question_q(company_id)
    fid = request.args.get("folder_id")
    if fid == "unfiled":
        query = query.filter(Question.folder_id.is_(None))
    elif fid:
        ids = descendants([int(fid)], company_id) if request.args.get("sub", "1") == "1" else {int(fid)}
        query = query.filter(Question.folder_id.in_(ids))
    st = request.args.get("status")
    if not st:
        query = query.filter(Question.status != "archived")
    tag = (request.args.get("tag") or "").strip().lower()
    cache = {f.id: f for f in _folder_q(company_id).all()}
    rows_filter = {"status": lambda q, v: q.filter(Question.status == v), "skill": lambda q, v: q.filter(Question.skill == v),
                   "level": lambda q, v: q.filter(Question.level == int(v)), "source": lambda q, v: q.filter(Question.source == v)}
    if tag:
        ids = [q.id for q in query.all() if tag in [t.lower() for t in (q.tags or [])]]
        query = query.filter(Question.id.in_(ids or [0]))
    return table(query, [Question.text, Question.skill, Question.explanation],
                 {"skill": Question.skill, "level": Question.level, "created": Question.created_at, "updated": Question.updated_at,
                  "version": Question.version, "status": Question.status}, "updated", lambda q: q_row(q, cache), rows_filter)


@bp.get("/facets")
@staff_required
def facets():
    company_id, _ = scope()
    qs = _question_q(company_id).filter(Question.status != "archived").all()
    skills, tags = defaultdict(int), defaultdict(int)
    for q in qs:
        skills[q.skill or "General"] += 1
        for t in q.tags or []:
            tags[t] += 1
    return ok({"skills": sorted(skills.items(), key=lambda x: -x[1]), "tags": sorted(tags.items(), key=lambda x: -x[1])[:40],
               "statuses": {s: sum(1 for q in qs if q.status == s) for s in ("approved", "pending", "rejected")},
               "archived": _question_q(company_id).filter(Question.status == "archived").count()})


def stats_for(q):
    """How the question performs: times asked, correct rate, option spread, by version."""
    asked = correct = 0
    spread = defaultdict(int)
    by_version = defaultdict(lambda: [0, 0])
    used_jobs = set()
    atts = RoundAttempt.query.filter(RoundAttempt.round_type == "mcq", RoundAttempt.completed_at.isnot(None)).all()
    for a in atts:
        res = a.result or {}
        if q.id not in (res.get("question_ids") or []):
            continue
        snap = (res.get("qsnap") or {}).get(str(q.id)) or {}
        ver = snap.get("version", 1)
        key = snap.get("answer", q.answer)
        ch = (res.get("answers") or {}).get(str(q.id))
        asked += 1
        by_version[ver][1] += 1
        if ch is not None:
            spread[int(ch)] += 1
            if int(ch) == key:
                correct += 1
                by_version[ver][0] += 1
        else:
            spread["skipped"] += 1
        if a.application_id:
            app = db.session.get(Application, a.application_id)
            if app:
                used_jobs.add(app.job_id)
    jobs = [{"id": j.id, "title": j.title} for j in Job.query.filter(Job.id.in_(used_jobs or [0])).all()]
    pct = round(100 * correct / asked, 1) if asked else None
    flag = ""
    if asked >= 3 and pct is not None:
        flag = "too easy" if pct > 95 else ("too hard" if pct < 15 else "")
    return {"asked": asked, "correct_pct": pct, "spread": {str(k): v for k, v in spread.items()}, "flag": flag,
            "by_version": [{"version": v, "asked": n, "correct_pct": round(100 * c / n, 1) if n else None} for v, (c, n) in sorted(by_version.items())],
            "jobs": jobs}


@bp.get("/questions/<int:qid>")
@staff_required
def question(qid):
    company_id, writable = scope()
    q = _owned(Question, qid, company_id)
    if not q:
        return err("Not found", 404)
    versions = []
    for v in QuestionVersion.query.filter_by(question_id=qid).order_by(QuestionVersion.version.desc()).all():
        u = db.session.get(User, v.changed_by) if v.changed_by else None
        versions.append({"version": v.version, "snapshot": v.snapshot, "note": v.note, "by": u.name if u else "Hira" if q.source == "ai" else "—",
                         "at": v.created_at.isoformat() + "Z"})
    if not versions:  # questions created before versioning
        versions = [{"version": q.version or 1, "snapshot": q.snapshot(), "note": "Original", "by": "—", "at": q.created_at.isoformat() + "Z"}]
    return ok({"question": q_row(q), "versions": versions, "stats": stats_for(q), "writable": writable})


def _clean(d, q=None):
    out = {}
    if "text" in d:
        out["text"] = (d["text"] or "").strip()
    if "code" in d:
        out["code"] = (d["code"] or "").strip() or None
    if "options" in d:
        out["options"] = [str(o).strip() for o in d["options"] if str(o).strip()][:6]
    if "answer" in d:
        out["answer"] = int(d["answer"])
    for k in ("explanation", "skill"):
        if k in d:
            out[k] = (d[k] or "").strip() or None
    if "level" in d:
        out["level"] = max(1, min(5, int(d["level"])))
    if "tags" in d:
        out["tags"] = sorted({t.strip() for t in (d["tags"] or []) if t and t.strip()})[:15]
    if "time_seconds" in d:
        out["time_seconds"] = int(d["time_seconds"]) if d["time_seconds"] else None
    opts = out.get("options", q.options if q else [])
    ans = out.get("answer", q.answer if q else 0)
    if "text" in out and not out["text"]:
        raise ValueError("The question needs text.")
    if len(opts) < 2:
        raise ValueError("Give at least two options.")
    if not 0 <= ans < len(opts):
        raise ValueError("Choose which option is correct.")
    return out


def _save_version(q, note):
    db.session.add(QuestionVersion(question_id=q.id, version=q.version, snapshot=q.snapshot(), note=(note or "")[:255], changed_by=g.user.id))


@bp.post("/questions")
@staff_required
def create_question():
    company_id, writable = scope()
    if not writable:
        return deny()
    d = body()
    try:
        data = _clean({"options": d.get("options", []), "answer": d.get("answer", 0), **d})
    except ValueError as e:
        return err(str(e))
    if not data.get("text"):
        return err("The question needs text.")
    fid = d.get("folder_id")
    if fid and not _owned(QuestionFolder, int(fid), company_id):
        return err("Folder not found.")
    q = Question(company_id=company_id, folder_id=int(fid) if fid else None, version=1, status=d.get("status", "approved"),
                 source="manual", updated_by=g.user.id, **{k: v for k, v in data.items()})
    q.skill = q.skill or "General"
    db.session.add(q)
    db.session.flush()
    _save_version(q, d.get("note") or "Created")
    log("qbank.create", "question", q.id, company_id=company_id)
    db.session.commit()
    return ok(q_row(q))


@bp.patch("/questions/<int:qid>")
@staff_required
def update_question(qid):
    """Content changes create a new version. Status and folder changes don't."""
    company_id, writable = scope()
    q = _owned(Question, qid, company_id)
    if not q or not writable:
        return deny()
    d = body()
    try:
        data = _clean(d, q)
    except ValueError as e:
        return err(str(e))
    changed = [k for k, v in data.items() if getattr(q, k) != v]
    if changed:
        if not QuestionVersion.query.filter_by(question_id=q.id).first():
            _save_version(q, "Original")
        for k in changed:
            setattr(q, k, data[k])
        q.version = (q.version or 1) + 1
        _save_version(q, d.get("note") or "Edited " + ", ".join(changed))
    if "status" in d and d["status"] in ("approved", "pending", "rejected", "archived"):
        q.status = d["status"]
    if "folder_id" in d:
        fid = d["folder_id"]
        if fid and not _owned(QuestionFolder, int(fid), company_id):
            return err("Folder not found.")
        q.folder_id = int(fid) if fid else None
    q.updated_by = g.user.id
    q.updated_at = datetime.utcnow()
    log("qbank.update", "question", qid, company_id=company_id, changed=changed, status=d.get("status"), version=q.version)
    db.session.commit()
    return question(qid)


@bp.post("/questions/<int:qid>/restore")
@staff_required
def restore(qid):
    company_id, writable = scope()
    q = _owned(Question, qid, company_id)
    if not q or not writable:
        return deny()
    v = int(body().get("version") or 0)
    old = QuestionVersion.query.filter_by(question_id=qid, version=v).first()
    if not old:
        return err("That version doesn't exist.")
    if not QuestionVersion.query.filter_by(question_id=q.id, version=q.version).first():
        _save_version(q, "Before restore")
    for k, val in (old.snapshot or {}).items():
        if k in Question.CONTENT:
            setattr(q, k, val)
    q.version = (q.version or 1) + 1
    _save_version(q, f"Restored version {v}")
    q.updated_by = g.user.id
    log("qbank.restore", "question", qid, company_id=company_id, version=v)
    db.session.commit()
    return question(qid)


@bp.post("/questions/<int:qid>/duplicate")
@staff_required
def duplicate(qid):
    """Copy a question. With to_company, copies a global question into your own bank (where you can edit it)."""
    company_id, writable = scope()
    src = _owned(Question, qid, company_id)
    if not src:
        return err("Not found", 404)
    d = body()
    if d.get("to_company"):
        target = cid()
        if not target or not can_any(g.user, "questions.manage", target):
            return deny()
        fid = d.get("folder_id")
        if fid and not _owned(QuestionFolder, int(fid), target):
            return err("Folder not found.")
        status, note = "approved", f"Copied from the Code2Hire bank (#{src.id} v{src.version or 1})"
    else:
        if not writable:
            return deny()
        target, fid, status, note = company_id, src.folder_id, "pending", f"Duplicated from #{src.id}"
    q = Question(company_id=target, folder_id=int(fid) if fid else None, version=1, status=status, source="manual",
                 updated_by=g.user.id, **{k: getattr(src, k) for k in Question.CONTENT})
    if not d.get("to_company"):
        q.text = q.text + " (copy)"
    db.session.add(q)
    db.session.flush()
    _save_version(q, note)
    log("qbank.duplicate", "question", q.id, company_id=target, source=src.id)
    db.session.commit()
    return ok(q_row(q))


@bp.post("/questions/bulk")
@staff_required
def bulk():
    company_id, writable = scope()
    if not writable:
        return deny()
    d = body()
    ids = [int(i) for i in d.get("ids", [])]
    action = d.get("action")
    qs = _question_q(company_id).filter(Question.id.in_(ids or [0])).all()
    if action == "move":
        fid = d.get("folder_id")
        if fid and not _owned(QuestionFolder, int(fid), company_id):
            return err("Folder not found.")
        for q in qs:
            q.folder_id = int(fid) if fid else None
    elif action in ("approved", "rejected", "archived", "pending"):
        for q in qs:
            q.status = action
    elif action == "tag":
        t = (d.get("tag") or "").strip()
        if not t:
            return err("Give a tag.")
        for q in qs:
            q.tags = sorted(set((q.tags or []) + [t]))
    elif action == "level":
        for q in qs:
            q.level = max(1, min(5, int(d.get("level", 3))))
    else:
        return err("Unknown action.")
    log(f"qbank.bulk.{action}", "question", None, company_id=company_id, n=len(qs))
    db.session.commit()
    return ok({"done": len(qs)})


@bp.post("/questions/generate")
@staff_required
def generate():
    company_id, writable = scope()
    if not writable:
        return deny()
    d = body()
    skills = d.get("skills") or ["General"]
    fid = d.get("folder_id")
    if fid and not _owned(QuestionFolder, int(fid), company_id):
        return err("Folder not found.")
    items = ai.generate_mcq(skills, int(d.get("level", 3)), min(20, int(d.get("n", 5))), company_id=company_id)
    out = []
    for it in items:
        q = Question(company_id=company_id, folder_id=int(fid) if fid else None, skill=it.get("skill") or skills[0], level=it.get("level", 3),
                     text=it["text"], code=it.get("code") or None, options=it["options"][:6], answer=int(it.get("answer", 0)),
                     explanation=it.get("explanation"), tags=d.get("tags") or [], status="pending", source="ai", version=1)
        db.session.add(q)
        db.session.flush()
        db.session.add(QuestionVersion(question_id=q.id, version=1, snapshot=q.snapshot(), note="Drafted by Hira"))
        out.append(q.id)
    log("qbank.generate", "question", None, company_id=company_id, n=len(out))
    db.session.commit()
    return ok({"created": len(out), "ids": out})


CSV_HEAD = ["folder", "skill", "level", "question", "code", "A", "B", "C", "D", "E", "F", "answer", "explanation", "tags", "status"]


def _ensure_path(path, company_id, cache):
    parent = None
    for part in [p.strip() for p in (path or "").split("/") if p.strip()]:
        key = (parent, part.lower())
        if key not in cache:
            f = QuestionFolder.query.filter(QuestionFolder.parent_id.is_(parent) if parent is None else QuestionFolder.parent_id == parent,
                                            db.func.lower(QuestionFolder.name) == part.lower(),
                                            QuestionFolder.company_id.is_(None) if company_id is None else QuestionFolder.company_id == company_id).first()
            if not f:
                f = QuestionFolder(company_id=company_id, parent_id=parent, name=part, created_by=g.user.id)
                db.session.add(f)
                db.session.flush()
            cache[key] = f.id
        parent = cache[key]
    return parent


@bp.post("/questions/import")
@staff_required
def import_csv():
    """CSV columns: folder (A / B / C path), skill, level, question, code, A–F options, answer (letter), explanation, tags (;), status."""
    company_id, writable = scope()
    if not writable:
        return deny()
    text = body().get("csv") or (request.files["file"].read().decode("utf-8-sig") if "file" in request.files else "")
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        return err("No rows found. The first line must be the header.")
    created, problems, cache = 0, [], {}
    for i, r in enumerate(rows, start=2):
        r = {(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
        opts = [r.get(x.lower(), "") for x in LETTERS]
        opts = [o for o in opts if o]
        ans = r.get("answer", "").upper()
        ai_ = LETTERS.index(ans) if ans in LETTERS else (int(ans) - 1 if ans.isdigit() else -1)
        if not r.get("question") or len(opts) < 2 or not 0 <= ai_ < len(opts):
            problems.append(f"Row {i}: needs a question, at least two options and a valid answer letter.")
            continue
        fid = _ensure_path(r.get("folder"), company_id, cache)
        q = Question(company_id=company_id, folder_id=fid, skill=r.get("skill") or "General", level=int(r.get("level") or 3),
                     text=r["question"], code=r.get("code") or None, options=opts, answer=ai_, explanation=r.get("explanation") or None,
                     tags=[t.strip() for t in (r.get("tags") or "").split(";") if t.strip()],
                     status=r.get("status") if r.get("status") in ("approved", "pending") else "pending", source="import", version=1)
        db.session.add(q)
        db.session.flush()
        db.session.add(QuestionVersion(question_id=q.id, version=1, snapshot=q.snapshot(), note="Imported from CSV", changed_by=g.user.id))
        created += 1
    log("qbank.import", "question", None, company_id=company_id, created=created, problems=len(problems))
    db.session.commit()
    return ok({"created": created, "problems": problems[:20]})


@bp.get("/questions/export")
@staff_required
def export_csv():
    company_id, _ = scope()
    query = _question_q(company_id).filter(Question.status != "archived")
    fid = request.args.get("folder_id")
    if fid and fid != "unfiled":
        query = query.filter(Question.folder_id.in_(descendants([int(fid)], company_id)))
    cache = {f.id: f for f in _folder_q(company_id).all()}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_HEAD)
    for q in query.all():
        opts = (q.options or []) + [""] * 6
        w.writerow([folder_path(q.folder_id, company_id, cache), q.skill, q.level, q.text, q.code or "", *opts[:6],
                    LETTERS[q.answer] if q.answer is not None and q.answer < 6 else "", q.explanation or "", ";".join(q.tags or []), q.status])
    log("qbank.export", "question", None, company_id=company_id)
    db.session.commit()
    return Response(buf.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=code2hire-questions.csv"})


@bp.get("/csv-template")
@staff_required
def csv_template():
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_HEAD)
    w.writerow(["Engineering / Backend / Python", "Python", 3, "Which structure gives O(1) average membership tests?", "", "list", "tuple", "set", "str", "", "",
                "C", "Sets are hash-based.", "data-structures;core", "approved"])
    return Response(buf.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=question-template.csv"})
