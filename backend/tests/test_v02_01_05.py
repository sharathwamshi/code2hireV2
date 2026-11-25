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
        r = c.post("/api/auth/login", json={"email": email, "password": pw}, headers={"X-Forwarded-For": "10.35.0." + str(len(_tokens) + 1)})
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



# ---------------------------------------------------------------------------------------------------- V02.01.05
def test_version_is_v02_01_05(c):
    assert j(c.get("/api/health"))["version"].startswith("V02.01.")


def test_a_long_question_becomes_one_spoken_question():
    from services.isha_prep import SPEAK_MAX, _words, speakable
    q, more, long_ = speakable("Explain Python the way you would to a new teammate, in about a minute. Then give one case where using it is the wrong choice.")
    assert q == "Explain Python the way you would to a new teammate, in about a minute." and not long_
    assert more == ["Give one case where using it is the wrong choice."]
    q, more, _ = speakable("You join the team and the Python part of the orders system has become slow and fragile. You have two weeks and "
                           "can't stop new features. What do you do first, and why?")
    assert q.endswith("What do you do first, and why?") and _words(q) <= SPEAK_MAX
    assert more and more[0].startswith("You have two weeks") and more[0].endswith("How does that change your answer?")
    q, more, _ = speakable("Without code in front of you: talk me through how you'd use SQL to find the 10 orders that took longest "
                           "to process yesterday, including the ones with missing timestamps and any ties. Say each step out loud.")
    assert q.startswith("Talk me through") and "out loud" not in " ".join(more)
    short = "How would you speed up a slow page that lists 10,000 orders?"
    assert speakable(short) == (short, [], False)


def test_isha_proposes_short_questions(c, app):
    att, h, areas, ch = _started(c, "short1@demo.test", "Short One")
    from services.isha_prep import SPEAK_MAX, _words
    p = d(c.get(f"/api/isha/{att}/prepare", headers=h))["prep"]
    for q in p["questions"]:
        if q["type"] == "own":
            continue
        assert _words(q["q"]) <= SPEAK_MAX, q["q"]
        assert len([x for x in q["q"].replace("?", "?|").split("|") if x.strip()]) <= 2, q["q"]
        assert all(_words(f["q"]) <= 24 for f in q["followups"]), q["followups"]


def _new(c, email, name):
    att, ch, job = live_round(c, email, name)
    h = login(c, IV)
    d(c.get(f"/api/isha/{att}", headers=h))
    return att, h, job


def test_questions_kept_for_a_job_come_first_for_the_next_candidate(c, app):
    att, h, job = _new(c, "set1@demo.test", "Set One")
    p = d(c.get(f"/api/isha/{att}/prepare", headers=h))["prep"]
    # one question quotes this candidate's resume: it is never kept for others
    from extensions import db
    from models import RoundAttempt
    with app.app_context():
        x = db.session.get(RoundAttempt, att)
        b = dict(x.brief)
        pr = dict(b["prep"])
        qs = [dict(q) for q in pr["questions"]]
        tech = next(q for q in qs if q["type"] not in ("intro", "own") and q["id"] in pr["selected"])
        tech["q"] = 'Your resume says "Moved billing to Kafka": what was your part?'
        pr["questions"] = qs
        b["prep"] = pr
        x.brief = b
        db.session.commit()
    p = d(c.get(f"/api/isha/{att}/prepare", headers=h))["prep"]
    assert next(q for q in p["questions"] if q["id"] == tech["id"])["personal"] is True
    out = d(c.post(f"/api/isha/{att}/keep", headers=h, json={"ids": "selected"}))
    n_sel = len(p["selected"])
    assert f"Kept {n_sel - 1} questions" in out["message"] and "resume wasn't kept" in out["message"]
    again = d(c.post(f"/api/isha/{att}/keep", headers=h, json={"ids": "selected"}))
    assert "already in the job's set" in again["message"]
    hr = login(c, REC)
    s = d(c.get(f"/api/jobs/{job['id']}/interview-set", headers=hr))
    assert len(s["items"]) == n_sel - 1 and not any("Kafka" in i["q"] for i in s["items"])
    # the next candidate for the same job: the kept questions first, already selected
    att2, h2, _ = _new(c, "set2@demo.test", "Set Two")
    p2 = d(c.get(f"/api/isha/{att2}/prepare", headers=h2))["prep"]
    mine = [q for q in p2["questions"] if q["source"] == "job"]
    assert len(mine) >= n_sel - 2 and all(q["id"] in p2["selected"] for q in mine)
    assert {q["q"] for q in mine} <= {i["q"] for i in s["items"]}
    # edit and remove in the job's set
    first = s["items"][0]
    s2 = d(c.post(f"/api/jobs/{job['id']}/interview-set/{first['id']}", headers=hr, json={"q": "How would you explain Python to a new teammate, briefly?"}))
    assert s2["items"][0]["q"].endswith("briefly?")
    s3 = d(c.post(f"/api/jobs/{job['id']}/interview-set/{first['id']}", headers=hr, json={"remove": True}))
    assert len(s3["items"]) == len(s["items"]) - 1
    from models import Question
    with app.app_context():
        q = db.session.get(Question, first["id"])
        assert q.job_id is None and q.kind == "interview" and q.version == 2   # still in the bank, with its history
    assert c.post(f"/api/jobs/{job['id']}/interview-set/{first['id']}", headers=hr, json={"remove": True}).status_code == 404


def test_follow_ups_say_what_they_pick_up_on(c, app):
    att, h, areas, ch = _started(c, "ev1@demo.test", "Ev One")
    a = areas[1]
    d(c.post(f"/api/isha/{att}/ask", headers=h, json={"q": a["q"], "area": a["area"]}))
    r = d(c.post(f"/api/isha/{att}/sentence", headers=h, json={"text": "At my last company I led the migration of the billing service to Kafka."}))
    assert r["options"] and all(o["evidence"]["from"] in ("conversation", "resume", "job", "plan") for o in r["options"])
    conv = [o for o in r["options"] if o["evidence"]["from"] == "conversation"]
    assert conv and all(len(o["evidence"]["quote"].split()) <= 11 for o in conv)
    out = d(c.post(f"/api/isha/{att}/followups", headers=h))
    assert out["options"] and all("evidence" in o for o in out["options"])
    # follow-ups written from the conversation are new each time; the prepared ones stay until they're asked
    was = {o["q"] for o in r["options"] if o.get("source") != "prepared" and o.get("type") != "Move on"}
    now = {o["q"] for o in out["options"] if o.get("source") != "prepared" and o.get("type") != "Move on"}
    assert now and not was & now, "refresh brings new follow-ups"


def test_refresh_needs_a_running_interview(c, app):
    att, h, _ = _new(c, "ev2@demo.test", "Ev Two")
    assert c.post(f"/api/isha/{att}/followups", headers=h).status_code == 409


def test_caption_gaps_are_recorded_for_the_scorecard(c, app):
    att, h, areas, ch = _started(c, "gap1@demo.test", "Gap One")
    d(c.post(f"/api/isha/{att}/caption-gap", headers=h, json={"seconds": 4}))
    st = d(c.post(f"/api/isha/{att}/caption-gap", headers=h, json={"seconds": 42, "at": "2026-11-24T10:00:00Z", "who": "candidate"}))
    assert st["gaps"] == [{"at": "2026-11-24T10:00:00Z", "seconds": 42, "who": "candidate"}]
    d(c.post(f"/api/call/{att}/caption-gap", headers=ch, json={"seconds": 15}))
    room = d(c.get(f"/api/isha/{att}", headers=h))
    assert [g["seconds"] for g in room["state"]["caption_gaps"]] == [42, 15]
    assert c.post(f"/api/isha/{att}/caption-gap", headers=ch, json={"seconds": 20}).status_code in (403, 404)
    assert c.post(f"/api/call/{att}/caption-gap", headers=h, json={"seconds": 20}).status_code == 403
    assert c.post(f"/api/isha/{att}/caption-gap", headers=h, json={"seconds": "x"}).status_code == 400
