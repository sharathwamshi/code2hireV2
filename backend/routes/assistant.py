"""Ask Hira (V02.00.05): the hiring team's assistant. Answers come only from data the person's role can see.

POST   /api/assistant/ask      {q, page: {job_id?, application_id?}}
GET    /api/assistant/history  the person's own chat, newest last
DELETE /api/assistant/history  clears it
"""
from flask import Blueprint, g

from extensions import db
from models import AssistantMessage
from routes.utils import body, err, ok
from services import assistant
from services.audit import log
from services.perms import staff_required

bp = Blueprint("assistant", __name__, url_prefix="/api/assistant")
KEEP = 200  # messages kept per person


def _ser(m):
    return {"id": m.id, "role": m.role, "text": m.text, "intent": m.intent, "items": (m.data or {}).get("items", []),
            "at": m.created_at.isoformat() + "Z"}


@bp.post("/ask")
@staff_required
def ask():
    d = body()
    q = str(d.get("q") or "").strip()
    if not q:
        return err("Type a question for Hira.")
    if len(q) > 500:
        return err("Keep the question under 500 characters.")
    page = d.get("page") if isinstance(d.get("page"), dict) else {}
    from routes.jobs import cid
    out = assistant.answer(q, page)
    db.session.add(AssistantMessage(user_id=g.user.id, company_id=cid(), role="user", text=q))
    m = AssistantMessage(user_id=g.user.id, company_id=cid(), role="hira", text=out["text"], intent=out["intent"],
                         data={"items": out["items"], "job_id": out["job_id"]})
    db.session.add(m)
    log("assistant.ask", "assistant", None, company_id=cid(), intent=out["intent"], engine=out["engine"], q=q[:200])
    db.session.flush()
    old = (AssistantMessage.query.filter_by(user_id=g.user.id).order_by(AssistantMessage.id.desc()).offset(KEEP).all())
    for x in old:
        db.session.delete(x)
    db.session.commit()
    return ok({**_ser(m), "engine": out["engine"], "job_id": out["job_id"]})


@bp.get("/history")
@staff_required
def history():
    rows = AssistantMessage.query.filter_by(user_id=g.user.id).order_by(AssistantMessage.id.desc()).limit(60).all()
    return ok({"messages": [_ser(m) for m in reversed(rows)], "examples": assistant.EXAMPLES})


@bp.delete("/history")
@staff_required
def clear():
    AssistantMessage.query.filter_by(user_id=g.user.id).delete()
    db.session.commit()
    return ok({"cleared": True})
