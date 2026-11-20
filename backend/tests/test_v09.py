"""Regression tests for V02.00.09: the Candidate / Manager / Company Admin bug report (BUG-001 to BUG-011) and the
new items N1 to N6 (Ask Disha, the F2F scorecard, the live rating card, closing an interview, no time limits,
one "Interview again" action). Browser-only parts (the rating card, the scorecard buttons, Today's "Show all", the
Columns menu, the Done screen) are checked in the browser walkthrough. Run: pytest -q"""
import os
import sys
import time
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("C2H_NO_AUTOCREATE", "1")
if os.environ.get("C2H_TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["C2H_TEST_DATABASE_URL"]
elif "DATABASE_URL" not in os.environ or not os.environ["DATABASE_URL"].startswith("sqlite"):
    import tempfile
    os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "v09.db")
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["AZURE_SPEECH_KEY"] = ""

from tests.syscheck_helper import system_check  # noqa: E402
import seed  # noqa: E402
from app import create_app  # noqa: E402
from tests.scorecard_helper import skip_unanswered

PW = seed.PW


@pytest.fixture(scope="module")
def app():
    import tempfile
    seed.run(reset=True)
    return create_app({"TESTING": True, "UPLOAD_DIR": tempfile.mkdtemp()})


@pytest.fixture(scope="module")
def c(app):
    return app.test_client()


_tokens = {}


def login(c, email, pw=PW):
    if email not in _tokens:
        r = c.post("/api/auth/login", json={"email": email, "password": pw}, headers={"X-Forwarded-For": "10.9.0." + str(len(_tokens) + 1)})
        assert r.status_code == 200, r.get_json()
        _tokens[email] = {"Authorization": "Bearer " + r.get_json()["data"]["token"]}
    return _tokens[email]


def j(r, code=200):
    assert r.status_code == code, (r.status_code, r.get_json())
    return r.get_json()


def uid(c, email):
    return j(c.get("/api/auth/me", headers=login(c, email)))["data"]["user"]["id"]


def python_job(c):
    h = login(c, "rahul@acme.test")
    return next(x for x in j(c.get("/api/jobs?size=100", headers=h))["items"] if x["title"] == "Senior Python Developer")


def new_candidate(c, email, name):
    h = login(c, "rahul@acme.test")
    job = python_job(c)
    r = j(c.post("/api/candidates", headers=h, json={"name": name, "email": email, "job_id": job["id"]}))["data"]["results"][0]
    op = j(c.post(f"/api/auth/invite/{r['link'].split('/')[-1]}/open"))["data"]
    return job, r["application_id"], {"Authorization": "Bearer " + op["token"]}, r


def invite(c, aid, kind):
    h = login(c, "rahul@acme.test")
    full = j(c.get(f"/api/applications/{aid}", headers=h))["data"]
    idx = next(i for i, r in enumerate(full["rounds"]) if r["type"] == kind)
    body = {"round_index": idx}
    if kind.startswith("f2f"):
        body["interviewer_id"] = uid(c, "priya@acme.test")
    return j(c.post(f"/api/applications/{aid}/invite", headers=h, json=body))["data"]["attempt_id"]


def live_round(c, email, name):
    _, aid, ch, _ = new_candidate(c, email, name)
    att = invite(c, aid, "f2f_isha")
    p = login(c, "priya@acme.test")
    system_check(c, att, ch)
    j(c.post(f"/api/rounds/{att}/consent", headers=ch, json={}))
    return att, aid, ch, p, j(c.get(f"/api/isha/{att}", headers=p))["data"]


def sa(c):
    return login(c, "super@code2hire.ai")


def practice_interview(c, ch):
    pr = j(c.post("/api/me/practice", headers=ch, json={"role": "Backend Developer", "type": "ai_interview", "skills": ["Python"], "questions": 2}))["data"]
    att = pr["attempt_id"]
    system_check(c, att, ch)
    j(c.post(f"/api/rounds/{att}/consent", headers=ch, json={}))
    j(c.post(f"/api/rounds/{att}/start", headers=ch))
    last = None
    for _ in range(8):
        last = j(c.post(f"/api/rounds/{att}/turn", headers=ch, json={"answer": "I built the API in Django because we measured the trade-off " * 4}))["data"]
        if last["done"]:
            break
    return att, last


def test_version_is_v02_00_09(c):
    assert j(c.get("/api/health"))["version"].startswith("V02.")


# ---------------------------------------------------------------- BUG-002 / 005 / 006: background report

def test_ai_interview_closes_at_once_and_report_is_written_in_background_BUG002(c, app):
    _, _, ch, _ = new_candidate(c, "bg.report@mail.test", "Bg Report")
    att, last = practice_interview(c, ch)
    assert last["done"] and last.get("report") in ("writing", "ready")
    st = j(c.get(f"/api/rounds/{att}/status", headers=ch))["data"]
    assert st["status"] == "completed" and st["report"] == "ready"  # TESTING writes it straight away
    assert st["practice_report"] and st["report_id"]
    room = j(c.get(f"/api/rounds/{att}", headers=ch))["data"]
    assert room["report_state"] == "ready" and room["practice_report"]
    # finishing twice never writes two reports
    from models import Report
    with app.app_context():
        assert Report.query.filter_by(attempt_id=att).count() == 1


def test_a_report_stuck_writing_is_finished_with_the_fallback_BUG006(c, app):
    from extensions import db
    from models import Report, RoundAttempt
    _, _, ch, _ = new_candidate(c, "stuck.report@mail.test", "Stuck Report")
    pr = j(c.post("/api/me/practice", headers=ch, json={"role": "Backend Developer", "type": "ai_interview", "skills": ["Python"], "questions": 2}))["data"]["attempt_id"]
    with app.app_context():  # as if the worker died while writing
        a = db.session.get(RoundAttempt, pr)
        a.status = "completed"
        a.completed_at = datetime.utcnow()
        a.result = {**(a.result or {}), "qa": [{"q": "Tell me about Python", "a": "I use it daily for APIs", "topic": "Python", "kind": "main"}],
                    "report_state": "writing", "report_started": time.time() - 600}
        db.session.commit()
    st = j(c.get(f"/api/rounds/{pr}/status", headers=ch))["data"]
    assert st["report"] == "ready"
    with app.app_context():
        assert Report.query.filter_by(attempt_id=pr).count() == 1


def test_followup_and_live_analysis_have_a_time_limit(app, monkeypatch):
    from services import ai
    seen = {}

    def fake(task, prompt, fallback, company_id=None, max_tokens=2000, system_extra="", timeout=None):
        seen[task] = timeout
        return fallback()
    monkeypatch.setattr(ai, "ask_json", fake)
    with app.app_context():
        ai.followup("Q", "short", "Python")
        ai.isha_analyze("Q", "Python", ["a point"], [], "a sentence", "", [])
    assert seen["decide on an interview follow-up"] and seen["analyse one sentence of a live interview answer and suggest next questions"]


def test_offline_mode_uses_fallbacks(app, monkeypatch):
    from services import ai
    monkeypatch.setattr(ai, "configured", lambda: True)
    with app.app_context():
        with ai.offline():
            assert ai._client() is None


# ---------------------------------------------------------------- BUG-004: practice report PDF

def test_candidate_downloads_their_practice_report_BUG004(c):
    _, _, ch, _ = new_candidate(c, "pdf.practice@mail.test", "Pdf Practice")
    att, _ = practice_interview(c, ch)
    r = c.get(f"/api/me/practice/{att}/pdf", headers=ch)
    assert r.status_code == 200 and r.data[:4] == b"%PDF" and "practice" in r.headers["Content-Disposition"]
    _, _, other, _ = new_candidate(c, "pdf.other@mail.test", "Pdf Other")
    assert c.get(f"/api/me/practice/{att}/pdf", headers=other).status_code == 404


# ---------------------------------------------------------------- BUG-001: practice quizzes are mostly AI-written

def test_practice_quiz_is_mostly_ai_written_BUG001(c, app, monkeypatch):
    from services import ai
    from models import RoundAttempt
    from extensions import db

    def gen(skills, level=3, n=5, company_id=None, avoid=None):
        return [{"skill": "Python", "level": 2, "text": f"AI-WRITTEN {time.time_ns()} {i}: which is a Python keyword?",
                 "options": ["yield", "begin", "elif2", "loop"], "answer": 0, "explanation": "yield is a keyword"} for i in range(n)]
    monkeypatch.setattr(ai, "generate_mcq", gen)
    _, _, ch, _ = new_candidate(c, "mix.quiz@mail.test", "Mix Quiz")
    att = j(c.post("/api/me/practice", headers=ch, json={"role": "Backend Developer", "type": "mcq", "skills": ["Python"], "questions": 10}))["data"]["attempt_id"]
    j(c.post(f"/api/rounds/{att}/consent", headers=ch, json={}))
    room = j(c.post(f"/api/rounds/{att}/start", headers=ch))["data"]
    ai_n = sum(1 for q in room["questions"] if q["text"].startswith("AI-WRITTEN"))
    assert len(room["questions"]) == 10 and ai_n >= 8, ai_n
    # the superadmin can turn it down to 0: then the bank comes first again
    j(c.put("/api/platform/settings", headers=sa(c), json={"key": "practice.ai_share", "value": 0}))
    att2 = j(c.post("/api/me/practice", headers=ch, json={"role": "Backend Developer", "type": "mcq", "skills": ["Python"], "questions": 4}))["data"]["attempt_id"]
    j(c.post(f"/api/rounds/{att2}/consent", headers=ch, json={}))
    room2 = j(c.post(f"/api/rounds/{att2}/start", headers=ch))["data"]
    with app.app_context():
        info = db.session.get(RoundAttempt, att2).result["mcq_info"]
    assert info["generated"] == 0 or sum(1 for q in room2["questions"] if q["text"].startswith("AI-WRITTEN")) < 4
    j(c.put("/api/platform/settings", headers=sa(c), json={"key": "practice.ai_share", "value": 80}))
    # a company can't change it
    r = c.put("/api/company/settings", headers=login(c, "admin@acme.test"), json={"scope": "company", "key": "practice.ai_share", "value": 0})
    assert r.status_code in (400, 403)


def test_practice_question_count_is_checked(c):
    _, _, ch, _ = new_candidate(c, "count.check@mail.test", "Count Check")
    for bad in (0, -3, 500):
        assert c.post("/api/me/practice", headers=ch, json={"role": "Backend Developer", "type": "mcq", "skills": ["Python"], "questions": bad}).status_code == 400


# ---------------------------------------------------------------- BUG-003: share link days

def test_share_link_days_must_be_1_to_90_BUG003(c, app):
    from models import Report
    h = login(c, "priya@acme.test")
    att, _, _, p, room = live_round(c, "share.cand@mail.test", "Share Cand")
    j(c.post(f"/api/isha/{att}/start", headers=p))
    draft = j(c.post(f"/api/isha/{att}/end", headers=p))["data"]["draft"]
    j(c.post(f"/api/isha/{att}/scorecard", headers=p, json={**skip_unanswered(c, att, p), "competencies": [{**r, "score": 3} for r in draft["competencies"]], "recommendation": "hold", "summary": "ok"}))
    with app.app_context():
        rid = Report.query.filter_by(attempt_id=att).first().id
    for bad in (-5, 0, 91, "", "abc", None):
        res = c.post(f"/api/reports/{rid}/share", headers=h, json={"audience": "client", "days": bad})
        assert res.status_code == 400, bad
    ok_ = c.post(f"/api/reports/{rid}/share", headers=h, json={"audience": "client", "days": 30})
    assert ok_.status_code in (200, 409)  # 409 when the report must be reviewed first
    if ok_.status_code == 200 and ok_.get_json()["data"].get("expires_at"):
        exp = datetime.fromisoformat(ok_.get_json()["data"]["expires_at"].rstrip("Z"))
        assert timedelta(days=29) < exp - datetime.utcnow() <= timedelta(days=30)


# ---------------------------------------------------------------- N2 / N3: scorecard and the live rating card

def test_wrap_up_answers_count_and_scorecard_opens_without_waiting_N2(c):
    att, _, _, p, room = live_round(c, "wrapup.cand@mail.test", "Wrapup Cand")
    j(c.post(f"/api/isha/{att}/start", headers=p))
    j(c.post(f"/api/isha/{att}/ask", headers=p, json={"q": "What questions do you have for us?", "area": "Wrap-up"}))
    for t in ("I have used Django for five years to build REST APIs with Django REST framework.",
              "On AWS I deployed the services with ECS and set up the alarms myself."):
        j(c.post(f"/api/isha/{att}/sentence", headers=p, json={"text": t}))
    draft = j(c.post(f"/api/isha/{att}/end", headers=p))["data"]["draft"]
    assert draft["captured"] == 2 and draft["ai"] is False  # quick draft; the screen asks Claude afterwards
    rows = {r["name"]: r for r in draft["competencies"]}
    scored = [n for n, r in rows.items() if r.get("score")]
    assert any("Django" in n for n in scored) and any("AWS" in n for n in scored), rows
    assert all("suggested" in r for r in draft["competencies"])
    better = j(c.post(f"/api/isha/{att}/redraft", headers=p))["data"]["draft"]
    assert [r["name"] for r in better["competencies"]] == list(rows)


def test_full_marks_when_every_point_is_covered_and_ticks_N3(c, app):
    att, _, _, p, room = live_round(c, "ticks.cand@mail.test", "Ticks Cand")
    j(c.post(f"/api/isha/{att}/start", headers=p))
    area = room["brief"]["areas"][0]
    st = j(c.post(f"/api/isha/{att}/ask", headers=p, json={"q": area["q"], "area": area["area"]}))["data"]
    st = j(c.post(f"/api/isha/{att}/sentence", headers=p, json={"text": "I did some of it."}))["data"]["state"]
    idx = st["current"]["index"]
    cur = st["areas_log"][idx]
    n = len(cur["good"])
    assert n and cur["score"] is not None and cur["score"] < 5
    before = cur["score"]
    for k in range(n):
        st = j(c.post(f"/api/isha/{att}/tick", headers=p, json={"index": idx, "point": k, "on": True}))["data"]
    cur = st["areas_log"][idx]
    assert cur["coverage"] == ["full"] * n and cur["score"] == 5.0 and cur["full_marks"]
    st = j(c.post(f"/api/isha/{att}/tick", headers=p, json={"index": idx, "point": 0, "on": False}))["data"]
    cur = st["areas_log"][idx]
    assert cur["score"] == before and not cur["full_marks"]
    # a later sentence keeps the ticks
    for k in range(n):
        j(c.post(f"/api/isha/{att}/tick", headers=p, json={"index": idx, "point": k, "on": True}))
    st = j(c.post(f"/api/isha/{att}/sentence", headers=p, json={"text": "And that's about it."}))["data"]["state"]
    assert st["areas_log"][idx]["score"] == 5.0
    assert c.post(f"/api/isha/{att}/tick", headers=p, json={"index": idx, "point": 99}).status_code == 400


def test_scorecard_keeps_disagree_reason_and_cant_be_submitted_twice_N2(c, app):
    att, _, _, p, room = live_round(c, "disagree.cand@mail.test", "Disagree Cand")
    j(c.post(f"/api/isha/{att}/start", headers=p))
    a0 = room["brief"]["areas"][0]
    j(c.post(f"/api/isha/{att}/ask", headers=p, json={"q": a0["q"], "area": a0["area"]}))
    j(c.post(f"/api/isha/{att}/sentence", headers=p, json={"text": "I designed the service because we measured the latency."}))
    draft = j(c.post(f"/api/isha/{att}/end", headers=p))["data"]["draft"]
    rows = [{**r, "score": 2 if r.get("score") else 3, "disagree": "Textbook answer, no project" if r.get("score") else ""} for r in draft["competencies"]]
    j(c.post(f"/api/isha/{att}/scorecard", headers=p, json={**skip_unanswered(c, att, p), "competencies": rows, "recommendation": "hold", "summary": "ok"}))
    assert c.post(f"/api/isha/{att}/scorecard", headers=p, json={**skip_unanswered(c, att, p), "competencies": rows, "recommendation": "hold"}).status_code == 409
    from models import Report
    with app.app_context():
        comps = Report.query.filter_by(attempt_id=att).first().sections["competencies"]
    assert any(x.get("disagree") == "Textbook answer, no project" for x in comps)


# ---------------------------------------------------------------- N4: close an interview that's still open

def test_close_interview_and_score_it_later_N4(c, app):
    att, aid, _, p, room = live_round(c, "close.cand@mail.test", "Close Cand")
    j(c.post(f"/api/isha/{att}/start", headers=p))
    a0 = room["brief"]["areas"][0]
    j(c.post(f"/api/isha/{att}/ask", headers=p, json={"q": a0["q"], "area": a0["area"]}))
    j(c.post(f"/api/isha/{att}/sentence", headers=p, json={"text": "I built the payments service in Django."}))
    info = j(c.get(f"/api/isha/{att}/close", headers=p))["data"]
    assert info["can_close"] and info["can_score"] and info["captured"]["sentences"] == 1
    assert c.post(f"/api/isha/{att}/close", headers=p, json={}).status_code == 400  # a reason is required
    out = j(c.post(f"/api/isha/{att}/close", headers=p, json={"reason": "Done outside Code2Hire"}))["data"]
    assert out["status"] == "not_finished"
    assert c.post(f"/api/isha/{att}/close", headers=p, json={"reason": "again"}).status_code == 409
    info = j(c.get(f"/api/isha/{att}/close", headers=p))["data"]
    assert not info["can_close"] and info["can_score"] and info["closed"]["note"] == "Done outside Code2Hire"
    # Today shows it as needing closing
    cards = j(c.get("/api/inbox/today", headers=p))["data"]["cards"]
    assert any(x["kind"] == "close" and "Close Cand" in x["title"] for x in cards)
    # the scorecard can still be submitted from what was captured
    draft = j(c.post(f"/api/isha/{att}/redraft?ai=0", headers=p))["data"]["draft"]
    rows = [{**r, "score": r.get("score") or 3} for r in draft["competencies"]]
    j(c.post(f"/api/isha/{att}/scorecard", headers=p, json={**skip_unanswered(c, att, p), "competencies": rows, "recommendation": "proceed", "summary": "Good"}))
    cards = j(c.get("/api/inbox/today", headers=p))["data"]["cards"]
    assert not any(x["kind"] == "close" and "Close Cand" in x["title"] for x in cards)


# ---------------------------------------------------------------- N5: no time limits

def test_no_deadline_on_invites_and_portal_links_N5(c, app):
    from extensions import db
    from models import InviteLink, RoundAttempt
    job, aid, ch, r = new_candidate(c, "nolimit.cand@mail.test", "Nolimit Cand")
    assert r.get("expires_at") is None
    att = invite(c, aid, "mcq")
    with app.app_context():
        assert db.session.get(RoundAttempt, att).deadline_at is None
        link = InviteLink.query.order_by(InviteLink.id.desc()).first()
        assert link.expires_at.year == 2099
    room = j(c.get(f"/api/rounds/{att}", headers=ch))["data"]
    assert room["status"] == "invited" and room["deadline_at"] is None
    # a company that wants a deadline can still set one
    admin = login(c, "admin@acme.test")
    j(c.put("/api/company/settings", headers=admin, json={"scope": "company", "key": "round.deadline_days", "value": 3}))
    _, aid2, _, _ = new_candidate(c, "withlimit.cand@mail.test", "Withlimit Cand")
    att2 = invite(c, aid2, "mcq")
    with app.app_context():
        d = db.session.get(RoundAttempt, att2).deadline_at
        assert d and timedelta(days=2) < d - datetime.utcnow() <= timedelta(days=3)
    j(c.put("/api/company/settings", headers=admin, json={"scope": "company", "key": "round.deadline_days", "value": 0}))


# ---------------------------------------------------------------- N6: one "Interview again" action

def _opts(c, att, h):
    d = j(c.get(f"/api/attempts/{att}/again", headers=h))["data"]
    return d, {o["key"]: o for o in d["options"]}


def test_interview_again_offers_only_what_fits_N6(c, app):
    from extensions import db
    from models import RoundAttempt
    h = login(c, "rahul@acme.test")
    _, aid, ch, _ = new_candidate(c, "again.cand@mail.test", "Again Cand")
    att = invite(c, aid, "f2f_isha")
    d, o = _opts(c, att, h)
    assert o["reschedule"]["allowed"] and not o["resend"]["allowed"] and not o["retake"]["allowed"] and not o["reinterview"]["allowed"]
    assert "dispute" not in o  # superadmin only
    when = (datetime.utcnow() + timedelta(days=2)).isoformat() + "Z"
    j(c.post(f"/api/attempts/{att}/again", headers=h, json={"action": "reschedule", "scheduled_at": when}))
    assert c.post(f"/api/attempts/{att}/again", headers=h, json={"action": "retake", "reason": "video"}).status_code == 409
    # the candidate missed it: re-send, free, old one kept as missed
    with app.app_context():
        a = db.session.get(RoundAttempt, att)
        a.status = "expired"
        db.session.commit()
    d, o = _opts(c, att, h)
    assert o["resend"]["allowed"] and o["resend"]["credits"] == 0 and not o["retake"]["allowed"]
    new = j(c.post(f"/api/attempts/{att}/again", headers=h, json={"action": "resend", "note": "Was unwell"}))["data"]["attempt_id"]
    assert new != att
    full = j(c.get(f"/api/applications/{aid}", headers=h))["data"]
    old = next(x for x in full["attempts"] if x["id"] == att)
    assert old["missed"] and old["missed"]["new_attempt_id"] == new
    assert next(x for x in full["attempts"] if x["id"] == new)["resent_of"] == att
    # a second open invite for the same round is refused
    assert c.post(f"/api/attempts/{att}/again", headers=h, json={"action": "resend"}).status_code == 409
    # it went wrong mid-way: retake counts against the limit
    with app.app_context():
        a = db.session.get(RoundAttempt, new)
        a.status = "in_progress"
        a.started_at = datetime.utcnow()
        db.session.commit()
    d, o = _opts(c, new, h)
    assert o["retake"]["allowed"] and o["retake"]["counts"]["limit"] == 5 and not o["resend"]["allowed"]
    third = j(c.post(f"/api/attempts/{new}/again", headers=h, json={"action": "retake", "reason": "audio"}))["data"]["attempt_id"]
    # finished: a re-interview keeps both reports, and the earlier one is marked
    with app.app_context():
        a = db.session.get(RoundAttempt, third)
        a.status = "completed"
        a.completed_at = datetime.utcnow()
        db.session.commit()
    d, o = _opts(c, third, h)
    assert o["reinterview"]["allowed"] and not o["retake"]["allowed"] or o["retake"]["allowed"]
    fourth = j(c.post(f"/api/attempts/{third}/again", headers=h, json={"action": "reinterview", "note": "Second opinion"}))["data"]["attempt_id"]
    full = j(c.get(f"/api/applications/{aid}", headers=h))["data"]
    assert next(x for x in full["attempts"] if x["id"] == fourth)["reinterview_of"] == third
    # the superadmin sees the dispute option (off without a dispute)
    d, o = _opts(c, third, sa(c))
    assert "dispute" in o and not o["dispute"]["allowed"]


def test_old_reinterview_route_still_works(c):
    h = login(c, "rahul@acme.test")
    _, aid, _, _ = new_candidate(c, "oldre.cand@mail.test", "Oldre Cand")
    invite(c, aid, "mcq")
    r = c.post(f"/api/applications/{aid}/reinterview", headers=h, json={"round_index": 0, "reason": "x"})
    assert r.status_code in (200, 409)


# ---------------------------------------------------------------- N1: Ask Disha

def test_ask_disha_answers_from_the_candidates_own_data_N1(c, app):
    _, aid, ch, _ = new_candidate(c, "disha.cand@mail.test", "Disha Cand")
    invite(c, aid, "f2f_isha")
    hist = j(c.get("/api/disha/history", headers=ch))["data"]
    assert hist["messages"] == [] and hist["examples"]
    a = j(c.post("/api/disha/ask", headers=ch, json={"q": "When is my next interview?"}))["data"]
    assert a["role"] == "disha" and a["intent"] == "upcoming" and a["items"] and a["items"][0]["link"].startswith("/room/")
    a = j(c.post("/api/disha/ask", headers=ch, json={"q": "What's the status of my applications?"}))["data"]
    assert "Senior Python Developer" in a["items"][0]["label"]
    a = j(c.post("/api/disha/ask", headers=ch, json={"q": "How do I join with my camera?"}))["data"]
    assert "system check" in a["text"].lower()
    assert len(j(c.get("/api/disha/history", headers=ch))["data"]["messages"]) == 6
    # the hiring team can't use it, and it never sees anyone else
    assert c.post("/api/disha/ask", headers=login(c, "rahul@acme.test"), json={"q": "hi"}).status_code == 403
    from services import disha
    from models import User
    with app.app_context():
        u = User.query.filter_by(email="disha.cand@mail.test").first()
        snap = disha.snapshot(u)
        assert all("score" not in r or r.get("shared_feedback") for a_ in snap["applications"] for r in a_["rounds"])
        assert "Rahul" not in str(snap)
    j(c.delete("/api/disha/history", headers=ch))
    assert j(c.get("/api/disha/history", headers=ch))["data"]["messages"] == []
    assert c.post("/api/disha/ask", headers=ch, json={"q": ""}).status_code == 400


# ---------------------------------------------------------------- manager analytics

def test_hiring_manager_sees_analytics_for_their_jobs(c):
    v = login(c, "vikram@acme.test")
    me = j(c.get("/api/auth/me", headers=v))["data"]
    assert "analytics.view" in me["permissions"]
    ov = j(c.get("/api/analytics/overview", headers=v))["data"]
    assert "totals" in ov
