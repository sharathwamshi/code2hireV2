"""Regression tests for V02.00.12: the consolidated gap analysis of the General UI, AI F2F and 17 Nov bug reports,
plus the "every answer is option B" finding. Browser-only parts (camera blink, colours, tabs, Clear filters, the
clickable numbers) are checked in walk12. Run: pytest -q"""
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
    os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "v13.db")
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
        r = c.post("/api/auth/login", json={"email": email, "password": pw}, headers={"X-Forwarded-For": "10.31.0." + str(len(_tokens) + 1)})
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


def test_version_is_v02_00_13(c):
    assert j(c.get("/api/health"))["version"].startswith("V02.")


# ---------------------------------------------------------------- the rating error

def test_scorecard_with_a_skipped_competency_no_longer_fails(c):
    att, _, _ = live_round(c, "rate1@demo.test", "Rate One")
    h = login(c, IV)
    d(c.get(f"/api/isha/{att}", headers=h))
    d(c.post(f"/api/isha/{att}/start", headers=h))
    # nothing rated: a clear message, not "Something went wrong"
    r = c.post(f"/api/isha/{att}/scorecard", headers=h, json={**skip_unanswered(c, att, h), "competencies": [{"name": "Python", "score": None}], "recommendation": "hold"})
    assert r.status_code == 400 and r.get_json()["error"].startswith("Rating not received for: Python")   # V02.01.01
    r = c.post(f"/api/isha/{att}/scorecard", headers=h, json={**skip_unanswered(c, att, h), "competencies": [{"name": "Python", "score": None, "skipped": True}], "recommendation": "hold"})
    assert r.status_code == 400 and "Rate at least one competency" in r.get_json()["error"]
    r = c.post(f"/api/isha/{att}/scorecard", headers=h, json={**skip_unanswered(c, att, h), "competencies": [{"name": "Python", "score": "x"}], "recommendation": "hold"})
    assert r.status_code == 400 and "number from 1 to 5" in r.get_json()["error"]
    r = c.post(f"/api/isha/{att}/scorecard", headers=h, json={**skip_unanswered(c, att, h), "competencies": [{"name": "Python", "score": 4}], "recommendation": "maybe"})
    assert r.status_code == 400 and "Choose a recommendation" in r.get_json()["error"]
    # one rated, one left on Skip: this used to crash
    out = d(c.post(f"/api/isha/{att}/scorecard", headers=h, json={**skip_unanswered(c, att, h), "competencies": [{"name": "Python", "score": 4}, {"name": "SQL", "score": None, "skipped": True, "show_on_report": True}],
                                                                  "recommendation": "proceed", "summary": "Good"}))
    assert out["overall"] == 4.0
    rep = d(c.get(f"/api/reports/{out['report_id']}", headers=login(c, REC)))
    comps = {x["name"]: x for x in (rep.get("sections") or rep.get("report", {}).get("sections", {})).get("competencies", [])}
    assert comps["SQL"]["level"] == "Skipped" and comps["Python"]["level"] == "Strong"   # V02.01.01: an explicit Skip


# ---------------------------------------------------------------- sections, types and levels

def test_level_mix_table_adds_up():
    from services.isha_prep import LEVELS, TYPES
    for k, L in LEVELS.items():
        assert sum(L["mix"].values()) == 100, k
        assert set(L["mix"]) <= set(TYPES)


def test_level_is_guessed_from_the_resume_then_the_job():
    from types import SimpleNamespace as N
    from services.isha_prep import guess_level
    assert guess_level(N(level="Senior"), N(experience_years=1)) == "fresher"
    assert guess_level(N(level="Mid"), N(experience_years=5)) == "mid"
    assert guess_level(N(level=""), N(experience_years=9)) == "senior"
    assert guess_level(N(level="Engineering Manager"), N(experience_years=10)) == "lead"
    assert guess_level(N(level="Junior"), None) == "fresher"


def test_sections_from_the_job_and_resume():
    from types import SimpleNamespace as N
    from services.isha_prep import build_sections
    job = N(skills=[{"name": "Python", "must": True}, {"name": "SQL"}, {"name": "Celery"}], description="Build payment APIs.", title="Backend Dev")
    prof = N(skills=[{"name": "Django", "years": 4}, {"name": "PostgreSQL"}, {"name": "Kafka"}])
    secs = build_sections(job, prof)
    kinds = {s["name"]: s["kind"] for s in secs}
    assert secs[0]["kind"] == "intro"
    assert kinds["Python"] == "core" and kinds["SQL"] == "core"       # Django counts for Python, PostgreSQL for SQL
    assert kinds["Celery"] == "gap" and kinds["Kafka"] == "claim"
    assert any(s["kind"] == "domain" for s in secs) and secs[-1]["kind"] == "behaviour"
    py = next(s for s in secs if s["name"] == "Python")
    assert py["must"] and py["years"] == 4


def test_types_follow_the_level():
    from services.isha_prep import types_for
    core = {"kind": "core"}
    assert "design" in types_for(core, "senior") and "design" not in types_for(core, "fresher")
    assert types_for({"kind": "gap"}, "senior")[:2] == ["basics", "hands_on"]       # unknown skill: start basic
    assert "basics" not in types_for({"kind": "core", "verified": True}, "fresher")  # already proven
    assert types_for({"kind": "claim"}, "mid") == ["experience"]


def test_builtin_questions_are_never_bare_definitions(app):
    from types import SimpleNamespace as N
    from services.isha_prep import TYPES, _builtin
    job = N(title="Backend Dev", description="Process card payments for merchants.", skills=[])
    prof = N(resume_text="Built a payments retry service in Python that reduced failures by 30%.")
    with app.app_context():
        for t in TYPES:
            q = _builtin({"skill": "Python", "name": "Python"}, t, job, prof, 0)
            assert not q["q"].lower().startswith("what is"), q["q"]
            assert len(q["good"]) >= 3 and len(q["followups"]) >= 3
        assert "payments" in _builtin({"skill": "Python", "name": "Python"}, "real_world", job, prof, 0)["q"]
        assert "retry service" in _builtin({"skill": "Python", "name": "Python"}, "experience", job, prof, 0)["q"]


# ---------------------------------------------------------------- Prepare questions

def test_prepare_proposes_sections_and_saves_the_choice(c):
    att, _, _ = live_round(c, "prep1@demo.test", "Prep One")
    h = login(c, IV)
    room = d(c.get(f"/api/isha/{att}", headers=h))
    assert room["brief"]["areas"][0]["type"] == "intro" and room["brief"]["areas"][-1]["area"] == "Wrap-up"
    out = d(c.get(f"/api/isha/{att}/prepare", headers=h))
    prep = out["prep"]
    assert prep["sections"][0]["kind"] == "intro" and prep["level"] in out["levels"]
    assert all(q["source"] in ("claude", "builtin", "own") for q in prep["questions"])
    assert all(q["followups"] for q in prep["questions"] if q["source"] != "own")
    assert {"basics", "scenario"} & {q["type"] for q in prep["questions"]}
    assert out["summary"]["checks"] and out["types"]["real_world"]["label"] == "Real situation"
    # choose three in a new order
    pick = [prep["questions"][0]["id"], prep["questions"][3]["id"], prep["questions"][1]["id"]]
    saved = d(c.post(f"/api/isha/{att}/prepare", headers=h, json={"selected": pick}))
    areas = saved["brief"]["areas"]
    assert [a.get("qid") for a in areas[:3]] == pick and areas[-1]["area"] == "Wrap-up" and len(areas) == 4
    assert saved["prep"]["saved"]
    # opening the room again keeps the interviewer's choice (no rebuild to the round's 7 questions)
    again = d(c.get(f"/api/isha/{att}", headers=h))
    assert [a.get("qid") for a in again["brief"]["areas"][:3]] == pick
    # own question, Isha's picks, rewrite a section, change level
    o = d(c.post(f"/api/isha/{att}/prepare", headers=h, json={"add": {"q": "How do you review a teammate's pull request?", "section": "own"}}))
    assert any(q["source"] == "own" and "pull request" in q["q"] for q in o["prep"]["questions"])
    assert c.post(f"/api/isha/{att}/prepare", headers=h, json={"add": {"q": "short"}}).status_code == 400
    r = d(c.post(f"/api/isha/{att}/prepare", headers=h, json={"reset": True}))
    assert len(r["prep"]["selected"]) >= 3
    sec = next(s for s in r["prep"]["sections"] if s["kind"] in ("core", "gap"))
    keep = [q["id"] for q in r["prep"]["questions"] if q["section"] == sec["key"] and q["id"] in r["prep"]["selected"]]
    rw = d(c.post(f"/api/isha/{att}/prepare", headers=h, json={"refresh": sec["key"]}))
    assert set(keep) <= {q["id"] for q in rw["prep"]["questions"]}
    lv = d(c.post(f"/api/isha/{att}/prepare", headers=h, json={"level": "fresher"}))
    assert lv["prep"]["level"] == "fresher" and not any(q["type"] == "design" for q in lv["prep"]["questions"])
    assert c.post(f"/api/isha/{att}/prepare", headers=h, json={"level": "wizard"}).status_code == 400
    assert c.post(f"/api/isha/{att}/prepare", headers=h, json={"selected": []}).status_code == 400
    # the candidate can't see any of it
    assert c.get(f"/api/isha/{att}/prepare", headers=login(c, "vikram@acme.test")).status_code in (401, 403)
    # once the interview starts, the choice is locked
    d(c.post(f"/api/isha/{att}/start", headers=h))
    assert c.post(f"/api/isha/{att}/prepare", headers=h, json={"selected": pick}).status_code == 409
    assert d(c.get(f"/api/isha/{att}/prepare", headers=h))["locked"] is True


# ---------------------------------------------------------------- live: hearing, prepared follow-ups, ratings, chat

def _started(c, email, name):
    att, ch, job = live_round(c, email, name)
    h = login(c, IV)
    room = d(c.get(f"/api/isha/{att}", headers=h))
    d(c.post(f"/api/isha/{att}/start", headers=h))
    return att, h, room["brief"]["areas"]


def test_prepared_follow_ups_are_offered_when_claude_is_down(c):
    att, h, areas = _started(c, "fu1@demo.test", "Fu One")
    a = next(x for x in areas if x.get("followups"))
    d(c.post(f"/api/isha/{att}/ask", headers=h, json={"area": a["area"]}))
    out = d(c.post(f"/api/isha/{att}/sentence", headers=h, json={"text": "I would just restart the server and see what happens next."}))
    srcs = [o.get("source") for o in out["options"]]
    assert "prepared" in srcs
    assert any(o["q"] in [f["q"] for f in a["followups"]] for o in out["options"])


def test_prepared_follow_ups_stay_until_covered_or_asked(c):
    att, h, areas = _started(c, "fu2@demo.test", "Fu Two")
    a = next(x for x in areas if len(x.get("followups") or []) >= 2)
    d(c.post(f"/api/isha/{att}/ask", headers=h, json={"area": a["area"]}))
    first = d(c.post(f"/api/isha/{att}/sentence", headers=h, json={"text": "Honestly I am not sure about that one."}))["options"]
    again = d(c.post(f"/api/isha/{att}/sentence", headers=h, json={"text": "Maybe I would try something simple."}))["options"]
    prep1 = {o["q"] for o in first if o.get("source") == "prepared"}
    assert prep1 and prep1 & {o["q"] for o in again if o.get("source") == "prepared"}   # still offered
    q = sorted(prep1)[0]
    d(c.post(f"/api/isha/{att}/ask", headers=h, json={"q": q, "area": a["area"], "type": "Probe"}))
    later = d(c.post(f"/api/isha/{att}/sentence", headers=h, json={"text": "I would check the logs first."}))["options"]
    assert q not in {o["q"] for o in later}                                              # asked: never again


def test_isha_hears_questions_follow_ups_and_asks_when_unsure(c):
    att, h, areas = _started(c, "hear1@demo.test", "Hear One")
    a1 = next(x for x in areas if x["type"] not in ("intro", "wrap") and len(x["q"].split()) > 12)
    # said in full: moves by itself
    r = d(c.post(f"/api/isha/{att}/said", headers=h, json={"text": a1["q"]}))
    assert r["moved"] and r["moved"]["area"] == a1["area"]
    # half of another question: Isha asks
    a2 = next(x for x in areas if x["area"] not in (a1["area"], "Wrap-up") and x["type"] != "intro" and len(x["q"].split()) > 14)
    words = a2["q"].split()
    r = d(c.post(f"/api/isha/{att}/said", headers=h, json={"text": " ".join(words[: len(words) // 2 + 1])}))
    assert r["moved"] is None or r["moved"]["area"] == a2["area"]
    # a pinned follow-up said out loud is filed as a follow-up of the current question
    pin = "What would you roll back first if the release broke the payments page?"
    r = d(c.post(f"/api/isha/{att}/said", headers=h, json={"text": pin, "pinned": [pin]}))
    assert r["moved"] and r["moved"].get("followup")
    last = r["state"]["areas_log"][-1]
    assert last["q"] == pin and last["followup_of"] is not None


def test_rating_a_question_feeds_the_scorecard(c):
    att, h, areas = _started(c, "rq1@demo.test", "Rq One")
    a = next(x for x in areas if x.get("competency"))
    st = d(c.post(f"/api/isha/{att}/ask", headers=h, json={"area": a["area"]}))
    i = st["current"]["index"]
    d(c.post(f"/api/isha/{att}/sentence", headers=h, json={"text": "I used it in production for two years and measured latency every week."}))
    assert c.post(f"/api/isha/{att}/rate", headers=h, json={"index": i, "score": 9}).status_code == 400
    assert c.post(f"/api/isha/{att}/rate", headers=h, json={"index": 99, "score": 3}).status_code == 400
    st = d(c.post(f"/api/isha/{att}/rate", headers=h, json={"index": i, "score": 2}))
    assert st["areas_log"][i]["rating"] == 2
    draft = d(c.post(f"/api/isha/{att}/redraft?ai=0", headers=h))["draft"]
    row = next(r for r in draft["competencies"] if r["name"] == a["competency"])
    assert row["score"] == 2 and row.get("rated")
    st = d(c.post(f"/api/isha/{att}/rate", headers=h, json={"index": i, "score": None}))
    assert "rating" not in st["areas_log"][i]


def test_ask_isha_answers_offline_from_the_plan(c):
    att, h, areas = _started(c, "chat1@demo.test", "Chat One")
    a = next(x for x in areas if x.get("followups"))
    d(c.post(f"/api/isha/{att}/ask", headers=h, json={"area": a["area"]}))
    out = d(c.post(f"/api/isha/{att}/chat", headers=h, json={"message": "Did they cover the points?"}))
    assert out["reply"]["who"] == "isha" and out["reply"]["source"] == "offline"
    assert out["reply"]["questions"] and "missing" in out["reply"]["text"].lower() or "covered" in out["reply"]["text"].lower()
    assert len(out["chat"]) == 2
    assert c.post(f"/api/isha/{att}/chat", headers=h, json={"message": ""}).status_code == 400
    assert d(c.get(f"/api/isha/{att}", headers=h))["chat"][0]["who"] == "you"


def test_report_says_where_each_question_came_from(c):
    att, h, areas = _started(c, "src1@demo.test", "Src One")
    d(c.post(f"/api/isha/{att}/ask", headers=h, json={"area": areas[0]["area"]}))
    d(c.post(f"/api/isha/{att}/sentence", headers=h, json={"text": "I lead a team of four building payment services in Python."}))
    out = d(c.post(f"/api/isha/{att}/scorecard", headers=h, json={**skip_unanswered(c, att, h), "competencies": [{"name": "Python", "score": 3}], "recommendation": "hold"}))
    rep = d(c.get(f"/api/reports/{out['report_id']}", headers=login(c, REC)))
    sec = rep.get("sections") or rep.get("report", {}).get("sections", {})
    q = sec["questions"][0]
    assert q["qtype"] == "Introduction" and q["source"] in ("builtin", "claude")
    assert sec["sources"]


def test_interview_length_setting():
    from services.settings import DEFAULTS, check_value
    assert DEFAULTS["f2f.minutes"][0] == 45
    assert check_value("f2f.minutes", 5)[1]
