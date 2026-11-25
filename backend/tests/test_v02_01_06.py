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
        r = c.post("/api/auth/login", json={"email": email, "password": pw}, headers={"X-Forwarded-For": "10.36.0." + str(len(_tokens) + 1)})
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



# ---------------------------------------------------------------------------------------------------- V02.01.06
def test_version_is_v02_01_06(c):
    assert j(c.get("/api/health"))["version"] == "V02.01.06"


GOOD = ["In my last role I built the payments API in Python with Django because the old service kept timing out.",
        "We measured it: errors fell by 40 percent and p95 latency went from 900 to 300 milliseconds.",
        "I personally designed the retry logic and the idempotency keys, which meant no double charges.",
        "The hard part was a bad migration that locked the orders table, so I rolled it back and split it in batches.",
        "I also set up the SQL indexes for the reports, which made the monthly export about ten times faster.",
        "On AWS I moved the workers to ECS and added alarms on the queue depth.",
        "Outside work I maintain a small open source Kafka consumer library that a few teams use."]


def _talk(c, app, email, name, lines=GOOD):
    att, h, areas, ch = _started(c, email, name)
    a = next(x for x in areas if x["type"] not in ("intro",))
    d(c.post(f"/api/isha/{att}/ask", headers=h, json={"q": a["q"], "area": a["area"]}))
    for t in lines:
        d(c.post(f"/api/isha/{att}/sentence", headers=h, json={"text": t, "defer": True}))
    return att, h, areas, ch


def test_end_answers_at_once_and_isha_wraps_up_step_by_step(c, app):
    att, h, areas, ch = _talk(c, app, "wrap1@demo.test", "Wrap One")
    out = d(c.post(f"/api/isha/{att}/end", headers=h))
    w = out["state"]["wrapup"]
    assert w["state"] == "done" and w["finished"]
    assert [k for k in ("transcript", "scores", "topics", "competencies", "decision", "thanks") if w["steps"][k]["state"] != "done"] == []
    assert w["steps"]["scores"]["items"] and all("score" in x for x in w["steps"]["scores"]["items"])
    assert "of" in w["steps"]["transcript"]["detail"]
    isha = out["draft"]["isha"]
    assert isha["recommendation"] in ("proceed", "hold", "reject") and isha["confidence"] in ("high", "medium", "low") and isha["reason"]
    # the candidate's call closed and they were thanked, from the background steps
    info = d(c.get(f"/api/call/{att}", headers=ch))
    assert info["ended"]
    # ending twice changes nothing
    again = d(c.post(f"/api/isha/{att}/end", headers=h))
    assert again["state"]["wrapup"]["finished"] == w["finished"]
    # retry runs the steps again
    r = d(c.post(f"/api/isha/{att}/wrapup", headers=h, json={"ai": False}))
    assert r["state"]["wrapup"]["state"] == "done" and r["state"]["wrapup"]["attempt"] == 2


def test_retry_needs_an_ended_interview(c, app):
    att, h, areas, ch = _started(c, "wrap2@demo.test", "Wrap Two")
    assert c.post(f"/api/isha/{att}/wrapup", headers=h).status_code == 409


def test_isha_consolidates_the_whole_conversation_not_only_the_plan(c, app):
    att, h, areas, ch = _talk(c, app, "topics1@demo.test", "Topics One")
    out = d(c.post(f"/api/isha/{att}/end", headers=h))
    topics = out["draft"]["isha"]["topics"]
    names = {t["topic"].lower() for t in topics}
    assert {"python", "sql", "aws"} & names
    for t in topics:
        assert 1 <= t["score"] <= 5 and t["evidence"] and any(t["evidence"] in s for s in GOOD)
    st = d(c.get(f"/api/isha/{att}", headers=h))["state"]
    assert st["review"]["topics"] == topics
    # Review again keeps them
    st = d(c.post(f"/api/isha/{att}/review", headers=h, json={"ai": False}))["state"]
    assert st["review"]["topics"] == topics


def test_not_enough_evidence_isha_says_so_and_wont_be_agreed_with(c, app):
    att, h, areas, ch = _talk(c, app, "thin1@demo.test", "Thin One", lines=GOOD[:2])
    out = d(c.post(f"/api/isha/{att}/end", headers=h))
    isha = out["draft"]["isha"]
    assert isha["insufficient"] is True and isha["recommendation"] is None and "Not enough evidence" in isha["reason"]
    assert c.post(f"/api/isha/{att}/scorecard", headers=h, json={"agree": True}).status_code == 409


def test_agree_with_isha_submits_her_decision(c, app):
    att, h, areas, ch = _talk(c, app, "agree1@demo.test", "Agree One")
    draft = d(c.post(f"/api/isha/{att}/end", headers=h))["draft"]
    rid = d(c.post(f"/api/isha/{att}/scorecard", headers=h, json={"agree": True, "note": "Good call."}))["report_id"]
    rep = d(c.get(f"/api/reports/{rid}", headers=login(c, REC)))
    s = rep["sections"]
    assert s["isha"]["recommendation"] == draft["isha"]["recommendation"] == rep["recommendation"]
    assert s["interviewer"]["confirmed"] and s["interviewer"]["agreed"] and s["interviewer"]["by"]
    assert c.post(f"/api/isha/{att}/scorecard", headers=h, json={"agree": True}).status_code == 409


def test_changing_isha_needs_a_reason_and_both_views_reach_the_report(c, app):
    att, h, areas, ch = _talk(c, app, "change1@demo.test", "Change One")
    draft = d(c.post(f"/api/isha/{att}/end", headers=h))["draft"]
    rows = [dict(x, skipped=x.get("score") is None) for x in draft["competencies"]]
    k = next(i for i, x in enumerate(rows) if x.get("score"))
    rows[k]["score"] = 1 if rows[k]["score"] != 1 else 5
    other = next(x for x in ("proceed", "hold", "reject") if x != draft["isha"]["recommendation"])
    payload = {**skip_unanswered(c, att, h), "competencies": rows, "recommendation": draft["isha"]["recommendation"]}
    payload.pop("rec_reason")
    r = c.post(f"/api/isha/{att}/scorecard", headers=h, json=payload)
    assert r.status_code == 400 and r.get_json()["fields"]["why"] == [rows[k]["name"]]
    rows[k]["disagree"] = "No real project behind it."
    r = c.post(f"/api/isha/{att}/scorecard", headers=h, json={**payload, "competencies": rows, "recommendation": other})
    assert r.status_code == 400 and "recommendation" in r.get_json()["error"]
    rid = d(c.post(f"/api/isha/{att}/scorecard", headers=h, json={**payload, "competencies": rows, "recommendation": other, "rec_reason": "Weak ownership."}))["report_id"]
    v = d(c.get(f"/api/reports/{rid}", headers=login(c, REC)))["sections"]["interviewer"]
    assert not v["agreed"] and v["changes"][0]["name"] == rows[k]["name"] and v["changes"][0]["why"] == "No real project behind it."
    assert v["rec_change"] == {"isha": draft["isha"]["recommendation"], "yours": other, "why": "Weak ownership."}


def test_isha_publishes_her_review_after_24_hours_and_the_interviewer_can_still_confirm(c, app):
    att, h, areas, ch = _talk(c, app, "auto24@demo.test", "Auto Twentyfour")
    d(c.post(f"/api/isha/{att}/end", headers=h))
    from extensions import db
    from models import Report, RoundAttempt
    from routes.isha import publish_unconfirmed
    with app.app_context():
        assert publish_unconfirmed() == 0   # not yet
        x = db.session.get(RoundAttempt, att)
        res = dict(x.result)
        res["wrapup"] = {**res["wrapup"], "finished": "2026-01-01T00:00:00Z"}
        x.result = res
        db.session.commit()
        assert publish_unconfirmed() == 1
        r = Report.query.filter_by(attempt_id=att).first()
        assert r.sections["interviewer"]["confirmed"] is False and db.session.get(RoundAttempt, att).status == "completed"
        assert publish_unconfirmed() == 0   # once
    d(c.post(f"/api/isha/{att}/scorecard", headers=h, json={"agree": True}))
    with app.app_context():
        r = Report.query.filter_by(attempt_id=att).first()
        assert r.sections["interviewer"]["confirmed"] is True and r.reviewer_id
    assert c.post(f"/api/isha/{att}/scorecard", headers=h, json={"agree": True}).status_code == 409


def test_rank_among_the_jobs_candidates(c, app):
    a1, h, _, _ = _talk(c, app, "rank1@demo.test", "Rank One")
    d(c.post(f"/api/isha/{a1}/end", headers=h))
    a2, h, _, _ = _talk(c, app, "rank2@demo.test", "Rank Two", lines=GOOD[:6])
    isha = d(c.post(f"/api/isha/{a2}/end", headers=h))["draft"]["isha"]
    assert isha["rank"] and isha["rank"]["of"] >= 2 and 1 <= isha["rank"]["place"] <= isha["rank"]["of"]


# ---------------------------------------------------------------------------------------------------- follow-ups
def test_follow_ups_come_per_answer_with_different_purposes(c, app):
    att, h, areas, ch = _started(c, "pur1@demo.test", "Pur One")
    a = next(x for x in areas if x["type"] not in ("intro",))
    d(c.post(f"/api/isha/{att}/ask", headers=h, json={"q": a["q"], "area": a["area"]}))
    before = d(c.get(f"/api/isha/{att}", headers=h))["state"]
    r = d(c.post(f"/api/isha/{att}/sentence", headers=h, json={"text": "We built the new billing service with our team last year.", "defer": True}))
    assert r["options"] == (before.get("options") or [])   # while talking: no new follow-ups
    sets = []
    for t in ("We moved it to the cloud and our team tuned it over a few months to make it better for everyone.", None, None):
        if t:
            d(c.post(f"/api/isha/{att}/sentence", headers=h, json={"text": t, "defer": True}))
        sets.append([o for o in d(c.post(f"/api/isha/{att}/followups", headers=h))["options"] if o.get("type") != "Move on"])
    for s_ in sets:
        ps = [o["purpose"] for o in s_]
        assert s_ and len(ps) == len(set(ps)) and len(s_) <= 3, ps   # each a different purpose
        assert all(o["type"] and o["why"] for o in s_)
    for prev, nxt in zip(sets, sets[1:]):   # never the same purpose twice in a row (except a still-missing point)
        assert not ({o["purpose"] for o in prev} & {o["purpose"] for o in nxt}) - {"missing"}
    owns = [o for s_ in sets for o in s_ if o["purpose"] == "ownership"]
    assert len(owns) <= 1   # "your part" at most once per topic
    qs = [o["q"] for s_ in sets for o in s_ if o["purpose"] != "missing"]
    assert len(qs) == len(set(qs))   # no wording twice


def test_purposes_follow_what_the_answer_misses():
    from services.ai import purposes_for
    p = purposes_for("We built it with our team and it was good, everyone liked it a lot.", ["none"])
    assert p[0] == "missing" and {"proof", "ownership", "why"} <= set(p)
    p = purposes_for("I chose Postgres because we needed transactions; it cut failures by 40 percent and handled 2 million users "
                     "without trouble, compared to the old store, which had problems with load and failed twice a week before.", ["full"])
    assert "challenge" in p and "proof" not in p and "missing" not in p
