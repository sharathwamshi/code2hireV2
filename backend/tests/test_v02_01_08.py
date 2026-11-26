"""Regression tests for V02.01.04: auto-start, live ratings, File under, the candidate's end screen, MCQ and the
question bank. Run: pytest -q"""
import os
import random
import sys
from collections import Counter

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("C2H_NO_AUTOCREATE", "1")
if os.environ.get("C2H_TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["C2H_TEST_DATABASE_URL"]
elif "DATABASE_URL" not in os.environ or not os.environ["DATABASE_URL"].startswith("sqlite"):
    import tempfile
    os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "v020104.db")
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
        r = c.post("/api/auth/login", json={"email": email, "password": pw}, headers={"X-Forwarded-For": "10.37.0." + str(len(_tokens) + 1)})
        assert r.status_code == 200, r.get_json()
        _tokens[email] = {"Authorization": "Bearer " + r.get_json()["data"]["token"]}
    return _tokens[email]


def j(r, code=200):
    assert r.status_code == code, (r.status_code, r.get_json())
    return r.get_json()


def d(r, code=200):
    return j(r, code)["data"]


REC = "rahul@acme.test"
IV = "priya@acme.test"


def uid(c, email):
    return d(c.get("/api/auth/me", headers=login(c, email)))["user"]["id"]


def python_job(c):
    return next(x for x in j(c.get("/api/jobs?size=100", headers=login(c, REC)))["items"] if x["title"] == "Senior Python Developer")


def live_round(c, email, name, cfg=None):
    job = python_job(c)
    r = d(c.post("/api/candidates", headers=login(c, REC), json={"name": name, "email": email, "job_id": job["id"]}))["results"][0]
    op = d(c.post(f"/api/auth/invite/{r['link'].split('/')[-1]}/open"))
    full = d(c.get(f"/api/jobs/{job['id']}", headers=login(c, REC)))
    f2f = next(i for i, x in enumerate(full["rounds"]) if x["type"] == "f2f_isha")
    if cfg:
        rounds = [{**x, "config": {**(x.get("config") or {}), **cfg}} if i == f2f else x for i, x in enumerate(full["rounds"])]
        j(c.patch(f"/api/jobs/{job['id']}", headers=login(c, REC), json={"rounds": rounds}))
    att = d(c.post(f"/api/applications/{r['application_id']}/invite", headers=login(c, REC),
                   json={"round_index": f2f, "interviewer_id": uid(c, IV)}))["attempt_id"]
    return att, {"Authorization": "Bearer " + op["token"]}, job




def _started(c, email, name):
    att, ch, job = live_round(c, email, name)
    h = login(c, IV)
    room = d(c.get(f"/api/isha/{att}", headers=h))
    d(c.post(f"/api/isha/{att}/start", headers=h))
    return att, h, [a for a in room["brief"]["areas"] if a["area"] != "Wrap-up"], ch


def _turns(app, att, rows):
    from extensions import db
    from models import Turn
    with app.app_context():
        seq = (db.session.query(db.func.max(Turn.seq)).filter_by(attempt_id=att).scalar() or 0)
        for i, (who, text) in enumerate(rows):
            db.session.add(Turn(attempt_id=att, seq=seq + i + 1, speaker=who, text=text, at_seconds=10 * (i + 1)))
        db.session.commit()



# ---------------------------------------------------------------------------------------------------- V02.01.08
ADMIN = "admin@acme.test"


def test_version_is_v02_01_08(c):
    assert j(c.get("/api/health"))["version"] == "V02.01.08"


TALK = ["In my last role I built the payments API in Python with Django because the old service kept timing out.",
        "We measured it: errors fell by 40 percent and p95 latency went from 900 to 300 milliseconds.",
        "I personally designed the retry logic and the idempotency keys, which meant no double charges.",
        "The hard part was a bad migration that locked the orders table, so I rolled it back and split it in batches.",
        "I also set up the SQL indexes for the reports, which made the monthly export about ten times faster.",
        "On AWS I moved the workers to ECS and added alarms on the queue depth."]


def _taken(c, app, email, name, submit=True, minutes=42):
    """An interview that ran for `minutes`, started at 10:00 IST today (04:30 UTC)."""
    from datetime import datetime, timedelta
    att, h, areas, ch = _started(c, email, name)
    a = next(x for x in areas if x["type"] not in ("intro",))
    d(c.post(f"/api/isha/{att}/ask", headers=h, json={"q": a["q"], "area": a["area"]}))
    for t in TALK:
        d(c.post(f"/api/isha/{att}/sentence", headers=h, json={"text": t, "defer": True}))
    from extensions import db
    from models import RoundAttempt
    with app.app_context():
        x = db.session.get(RoundAttempt, att)
        today = datetime.utcnow().date()
        x.started_at = datetime(today.year, today.month, today.day, 4, 30)
        db.session.commit()
    d(c.post(f"/api/isha/{att}/end", headers=h))
    with app.app_context():
        x = db.session.get(RoundAttempt, att)
        res = dict(x.result)
        res["ended_at"] = minutes * 60
        x.result = res
        db.session.commit()
    if submit:
        d(c.post(f"/api/isha/{att}/scorecard", headers=h, json={"agree": True, "recommendation": "proceed"}))
    return att, h


def test_teams_is_for_company_admins_only(c, app):
    for who in (REC, IV):
        assert c.get("/api/teams", headers=login(c, who)).status_code == 403
        assert c.get("/api/teams/export.csv", headers=login(c, who)).status_code == 403
    assert c.get("/api/teams", headers=login(c, ADMIN)).status_code == 200
    assert c.get("/api/teams?from=2026-11-30&to=2026-11-01", headers=login(c, ADMIN)).status_code == 400
    assert c.get("/api/teams?from=nope", headers=login(c, ADMIN)).status_code == 400


def test_teams_counts_each_interviewers_interviews(c, app):
    h_ad = login(c, ADMIN)
    before = d(c.get("/api/teams", headers=h_ad))
    a1, h = _taken(c, app, "team1@demo.test", "Team One")                 # completed, Proceed
    a2, _ = _taken(c, app, "team2@demo.test", "Team Two", submit=False)   # ended, no scorecard: feedback pending
    from datetime import datetime, timedelta
    att3, ch3, job = live_round(c, "team3@demo.test", "Team Three")       # upcoming
    from extensions import db
    from models import RoundAttempt, User
    with app.app_context():
        x = db.session.get(RoundAttempt, att3)
        x.scheduled_at = datetime.utcnow() + timedelta(hours=2)
        x.status = "scheduled"
        db.session.commit()
        priya = User.query.filter_by(email=IV).first().id
    after = d(c.get("/api/teams", headers=h_ad))
    assert after["tiles"]["taken"] - before["tiles"]["taken"] == 2
    assert after["tiles"]["pending"] - before["tiles"]["pending"] == 1
    assert after["tiles"]["upcoming"] - before["tiles"]["upcoming"] >= 1
    me = next(p for p in after["people"] if p["id"] == priya)
    assert me["completed"] >= 2 and me["pending"] >= 1 and me["avg_minutes"] == 42 and me["last"]
    assert after["period"]["zone"] == "IST" and after["weeks"] and sum(w["count"] for w in after["weeks"]) >= 2
    assert any(u["candidate"] == "Team Three" and u["time"] for u in after["upcoming"]["items"])
    assert any(t["id"] == priya for t in after["top"])
    # one person's page
    p = d(c.get(f"/api/teams/{priya}", headers=h_ad))
    assert p["person"]["email"] == IV and p["person"]["active"] and p["person"]["roles"]
    rows = {r["candidate"]: r for r in p["interviews"]}
    one = rows["Team One"]
    assert one["time"] == "10:00 AM – 10:42 AM" and one["duration"] == "42 min" and one["status"] == "Completed" and one["result"] == "Proceed"
    assert rows["Team Two"]["result"] == "Feedback pending"
    three = rows["Team Three"]
    assert three["status"] == "Upcoming" and three["duration"].endswith("min planned") and three["result"] == "—"
    assert p["tiles"]["time_spent"].endswith("m") and p["person"]["next"]
    assert c.get("/api/teams/999999", headers=h_ad).status_code == 404
    # CSV, for everyone or one person
    r = c.get(f"/api/teams/export.csv?person={priya}", headers=h_ad)
    assert r.status_code == 200 and r.mimetype == "text/csv"
    text = r.get_data(as_text=True)
    assert "Time (IST)" in text.splitlines()[0] and "Team One" in text and "10:00 AM – 10:42 AM" in text


def test_the_report_says_when_the_interview_was_taken_in_ist_and_how_long(c, app):
    att, h = _taken(c, app, "when1@demo.test", "When One", minutes=37)
    from extensions import db
    from models import Report
    with app.app_context():
        rid = Report.query.filter_by(attempt_id=att).first().id
    rep = d(c.get(f"/api/reports/{rid}", headers=login(c, REC)))
    t = rep["taken"]
    assert t["time"] == "10:00 AM – 10:37 AM IST" and t["length"] == "37 min" and t["zone"] == "IST" and t["minutes"] == 37
    assert t["date"] and t["label"] == f"{t['date']} · {t['time']} · {t['length']}"
    pdf = c.get(f"/api/reports/{rid}/pdf", headers=login(c, REC))
    assert pdf.status_code == 200 and pdf.data[:4] == b"%PDF"
