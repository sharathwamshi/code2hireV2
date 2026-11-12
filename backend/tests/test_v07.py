"""Regression tests for V02.00.07: the 10 Nov bug report (bugs 1 to 8) and its gaps. Each test names what it covers.
The browser-only items (the room fitting the screen, the cover message, the CC button, the Upcoming card) are checked
in the browser walkthrough. Run: pytest -q"""
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("C2H_NO_AUTOCREATE", "1")
if os.environ.get("C2H_TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["C2H_TEST_DATABASE_URL"]
elif "DATABASE_URL" not in os.environ or not os.environ["DATABASE_URL"].startswith("sqlite"):
    import tempfile
    os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "v07.db")
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["AZURE_SPEECH_KEY"] = ""

from tests.syscheck_helper import system_check  # noqa: E402
import seed  # noqa: E402
from app import create_app  # noqa: E402

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
        r = c.post("/api/auth/login", json={"email": email, "password": pw}, headers={"X-Forwarded-For": "10.7.0." + str(len(_tokens) + 1)})
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
    return job, r["application_id"], {"Authorization": "Bearer " + op["token"]}


def invite(c, aid, kind):
    h = login(c, "rahul@acme.test")
    full = j(c.get(f"/api/applications/{aid}", headers=h))["data"]
    idx = next(i for i, r in enumerate(full["rounds"]) if r["type"] == kind)
    body = {"round_index": idx}
    if kind.startswith("f2f"):
        body["interviewer_id"] = uid(c, "priya@acme.test")
    return j(c.post(f"/api/applications/{aid}/invite", headers=h, json=body))["data"]["attempt_id"]


def status(c, att):
    return j(c.get(f"/api/isha/{att}/candidate-status", headers=login(c, "priya@acme.test")))["data"]


def pdf_text(data):
    import pypdf
    return " ".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(data)).pages)



def ask_room(c, att, ch, p):
    system_check(c, att, ch)
    j(c.post(f"/api/rounds/{att}/consent", headers=ch, json={}))
    return j(c.get(f"/api/isha/{att}", headers=p))["data"]


# ---------------------------------------------------------------- bug 3 / gap 7: answers are never lost

def test_answer_without_a_question_goes_to_the_next_plan_question_bug3_gap7(c):
    job, aid, ch = new_candidate(c, "v7.assumed@mail.test", "Vseven Assumed")
    att = invite(c, aid, "f2f_isha")
    p = login(c, "priya@acme.test")
    room = ask_room(c, att, ch, p)
    areas = room["brief"]["areas"]
    j(c.post(f"/api/isha/{att}/start", headers=p))
    st = j(c.post(f"/api/isha/{att}/sentence", headers=p, json={"text": "I have five years of Python and Django experience."}))["data"]
    cur = st["state"]["areas_log"][-1] if "state" in st else st["areas_log"][-1]
    assert cur["area"] == areas[0]["area"] and cur["assumed"] is True and cur["good"]
    # the interviewer moves it to the right question
    idx = (st.get("state") or st)["current"]["index"]
    moved = j(c.post(f"/api/isha/{att}/relabel", headers=p, json={"index": idx, "area": areas[2]["area"]}))["data"]
    e = moved["areas_log"][idx]
    assert e["area"] == areas[2]["area"] and e["assumed"] is False and e["sentences"] and moved["current"]["area"] == areas[2]["area"]
    assert c.post(f"/api/isha/{att}/relabel", headers=p, json={"index": 99, "area": areas[0]["area"]}).status_code == 400
    assert c.post(f"/api/isha/{att}/relabel", headers=p, json={"index": idx, "area": "Not in plan"}).status_code == 400
    assert c.post(f"/api/isha/{att}/relabel", headers=ch, json={"index": idx, "area": areas[0]["area"]}).status_code in (403, 404)
    # the report keeps the flag for an answer that stayed assumed
    j(c.post(f"/api/isha/{att}/ask", headers=p, json={"q": "", "area": areas[3]["area"]}))
    draft = j(c.post(f"/api/isha/{att}/end", headers=p))["data"]["draft"]
    j(c.post(f"/api/isha/{att}/scorecard", headers=p, json={"competencies": [{**x, "score": 3} for x in draft["competencies"]], "recommendation": "hold"}))
    v = j(c.get(f"/api/reports/by-attempt/{att}", headers=login(c, "rahul@acme.test")))["data"]
    q = next(q for q in v["sections"]["questions"] if q["a"])
    assert q["topic"] == areas[2]["area"] and q["assumed"] is False


# ---------------------------------------------------------------- bug 5: interviewer subtitles

def test_interviewer_subtitles_reach_the_candidate_only_from_the_interviewer_bug5(c):
    job, aid, ch = new_candidate(c, "v7.cc@mail.test", "Vseven Cc")
    att = invite(c, aid, "f2f_isha")
    p = login(c, "priya@acme.test")
    ask_room(c, att, ch, p)
    cur = j(c.get(f"/api/call/{att}", headers=ch))["data"]["cursor"]
    j(c.post(f"/api/call/{att}/signal", headers=p, json={"kind": "iv_caption", "payload": {"text": "Tell me about a project " + "x" * 900, "final": 1, "x": 2}}))
    assert c.post(f"/api/call/{att}/signal", headers=ch, json={"kind": "iv_caption", "payload": {"text": "fake"}}).status_code == 403
    sig = j(c.get(f"/api/call/{att}/signal?after={cur}", headers=ch))["data"]["signals"]
    s = next(x for x in sig if x["kind"] == "iv_caption")
    assert s["payload"]["final"] is True and len(s["payload"]["text"]) == 500 and set(s["payload"]) == {"text", "final"}


# ---------------------------------------------------------------- bug 4 / gap 4: leaving shows at once

def test_leaving_clears_presence_immediately_bug4_gap4(c):
    job, aid, ch = new_candidate(c, "v7.leave@mail.test", "Vseven Leave")
    att = invite(c, aid, "f2f_isha")
    p = login(c, "priya@acme.test")
    ask_room(c, att, ch, p)
    j(c.post(f"/api/call/{att}/signal", headers=p, json={"kind": "join"}))
    assert j(c.get(f"/api/call/{att}/signal?after=0", headers=ch))["data"]["peer_online"] is True
    # the tab closed: the page sends bye on the way out (keepalive)
    j(c.post(f"/api/call/{att}/signal", headers=p, json={"kind": "bye", "payload": {"closed": True, "evil": "x"}}))
    r = j(c.get(f"/api/call/{att}/signal?after=0", headers=ch))["data"]
    assert r["peer_online"] is False
    bye = [x for x in r["signals"] if x["kind"] == "bye"][-1]
    assert bye["payload"] == {"closed": True}
    # a candidate's bye can never end the interview for both
    j(c.post(f"/api/call/{att}/signal", headers=ch, json={"kind": "bye", "payload": {"ended": True}}))
    r = j(c.get(f"/api/call/{att}/signal?after=0", headers=p))["data"]
    assert [x for x in r["signals"] if x["kind"] == "bye"][-1]["payload"] == {}


# ---------------------------------------------------------------- gaps 1, 2, 11: caption health, headphones, Azure

def test_caption_state_headphones_and_azure_flag_gaps_1_2_11(c):
    job, aid, ch = new_candidate(c, "v7.health@mail.test", "Vseven Health")
    att = invite(c, aid, "f2f_isha")
    p = login(c, "priya@acme.test")
    req = j(c.get(f"/api/syscheck/requirements?attempt={att}", headers=ch))["data"]
    steps = {s["key"]: {"status": "pass"} for s in req["steps"]}
    j(c.post("/api/syscheck", headers=ch, json={"attempt_id": att, "steps": steps, "instructions_read": True, "device": {"headphones": False}}))
    st = j(c.get(f"/api/isha/{att}/candidate-status", headers=p))["data"]
    assert "No headphones (echo possible)" in st["check"]["text"]
    j(c.post(f"/api/rounds/{att}/consent", headers=ch, json={}))
    info = j(c.get(f"/api/call/{att}", headers=p))["data"]
    assert info["azure_speech"] is False                        # no key in tests: the room says captions are Chrome/Edge only
    cur = info["cursor"]
    j(c.post(f"/api/call/{att}/signal", headers=ch, json={"kind": "device", "payload": {"captions": "browser", "cap_state": "paused", "x": 1}}))
    sig = j(c.get(f"/api/call/{att}/signal?after={cur}", headers=p))["data"]["signals"]
    assert next(x for x in sig if x["kind"] == "device")["payload"] == {"captions": "browser", "cap_state": "paused"}
    assert c.get("/api/health").get_json()["azure_speech"] is False


# ---------------------------------------------------------------- bug 7: jobs list

def test_jobs_list_can_show_live_only_or_all_bug7(c):
    h = login(c, "rahul@acme.test")
    all_jobs = j(c.get("/api/jobs?size=100", headers=h))["items"]
    live = j(c.get("/api/jobs?size=100&status=live", headers=h))["items"]
    assert live and all(x["status"] == "live" for x in live)
    assert len(all_jobs) >= len(live)


# ---------------------------------------------------------------- bug 8: scheduled interview on the home page

def test_scheduled_interview_is_on_the_home_page_bug8(c, app):
    from datetime import datetime, timedelta
    from models import Notification
    job, aid, ch = new_candidate(c, "v7.sched@mail.test", "Vseven Sched")
    h = login(c, "rahul@acme.test")
    full = j(c.get(f"/api/applications/{aid}", headers=h))["data"]
    idx = next(i for i, r in enumerate(full["rounds"]) if r["type"] == "f2f_isha")
    when = (datetime.utcnow() + timedelta(days=2)).replace(microsecond=0).isoformat() + "Z"
    att = j(c.post(f"/api/applications/{aid}/invite", headers=h, json={"round_index": idx, "interviewer_id": uid(c, "priya@acme.test"), "scheduled_at": when}))["data"]["attempt_id"]
    home = j(c.get("/api/me", headers=ch))["data"]
    inv = next(i for i in home["invites"] if i["attempt_id"] == att)
    assert inv["scheduled_at"] and inv["status"] == "scheduled" and inv["interviewer"] == "Priya Nair" and inv["company"] == "Acme Technologies"
    assert inv["rescheduled"] is False
    with app.app_context():
        uid_c = j(c.get("/api/auth/me", headers=ch))["data"]["user"]["id"]
        n = Notification.query.filter_by(user_id=uid_c).order_by(Notification.id.desc()).first()
        assert n.title.startswith("Interview scheduled") and n.link == "/me#upcoming" and "home page" in n.body
    # rescheduling shows on the card
    later = (datetime.utcnow() + timedelta(days=3)).replace(microsecond=0).isoformat() + "Z"
    j(c.post(f"/api/applications/{aid}/invite", headers=h, json={"round_index": idx, "interviewer_id": uid(c, "priya@acme.test"), "scheduled_at": later}))
    inv = next(i for i in j(c.get("/api/me", headers=ch))["data"]["invites"] if i["attempt_id"] == att)
    assert inv["rescheduled"] is True and inv["scheduled_at"].startswith(later[:13])


def test_version_V02_00_07(c):
    assert c.get("/api/health").get_json()["version"].startswith("V02.00.")  # exact version: test_v08
