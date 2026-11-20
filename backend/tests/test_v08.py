"""Regression tests for V02.00.08: video calls that connect (relay, retries, the connection step, the connection
record), the F2F bug report (F2F-001 to F2F-004, CD-005), the superadmin bug report (SA-001 to SA-010), and the AI
key status. Each test names what it covers. Browser-only parts (the call watchdog, the cover wording, the chat states,
the login page) are checked in the browser walkthrough. Run: pytest -q"""
import base64
import hashlib
import hmac
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("C2H_NO_AUTOCREATE", "1")
if os.environ.get("C2H_TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["C2H_TEST_DATABASE_URL"]
elif "DATABASE_URL" not in os.environ or not os.environ["DATABASE_URL"].startswith("sqlite"):
    import tempfile
    os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "v08.db")
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
        r = c.post("/api/auth/login", json={"email": email, "password": pw}, headers={"X-Forwarded-For": "10.8.0." + str(len(_tokens) + 1)})
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


def new_candidate(c, email, name, resume=None):
    h = login(c, "rahul@acme.test")
    job = python_job(c)
    body = {"name": name, "email": email, "job_id": job["id"]}
    if resume:
        body["resume_text"] = resume
    r = j(c.post("/api/candidates", headers=h, json=body))["data"]["results"][0]
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


def live_round(c, email, name, resume=None):
    """A joined live interview: (attempt id, candidate headers, interviewer headers, the room data)."""
    _, aid, ch = new_candidate(c, email, name, resume)
    att = invite(c, aid, "f2f_isha")
    p = login(c, "priya@acme.test")
    system_check(c, att, ch)
    j(c.post(f"/api/rounds/{att}/consent", headers=ch, json={}))
    return att, ch, p, j(c.get(f"/api/isha/{att}", headers=p))["data"]


def sa(c):
    return login(c, "super@code2hire.ai")


# ---------------------------------------------------------------- version

def test_version_is_v02_00_08(c):
    assert j(c.get("/api/health"))["version"].startswith("V02.")


# ---------------------------------------------------------------- AI keys: a saved key is used, and a failing one shows

def test_health_reports_whether_the_keys_work(c):
    h = j(c.get("/api/health"))
    for k in ("anthropic", "anthropic_working", "anthropic_error", "azure_speech", "azure_speech_working", "azure_speech_error"):
        assert k in h, k


def test_saved_key_failure_is_recorded_and_shown_on_the_overview(c, app, monkeypatch):
    from services import ai
    from services.settings import set_secret
    from extensions import db

    class Boom(Exception):
        pass
    Boom.__name__ = "AuthenticationError"

    class FakeMsgs:
        def create(self, **kw):
            raise Boom("bad key")

    class FakeClient:
        messages = FakeMsgs()
    with app.app_context():
        set_secret("anthropic_api_key", "sk-ant-test-key")
        db.session.commit()
        monkeypatch.setattr(ai, "_client", lambda: FakeClient())
        out = ai.ask_json("t", "p", lambda: {"fallback": True})
        assert out == {"fallback": True}
        st = ai.status()
        assert st["configured"] and not st["working"] and st["recent_error"] and "rejected the API key" in st["error"]
    d = j(c.get("/api/platform/overview", headers=sa(c)))["data"]
    assert d["ai_status"]["recent_error"] and "rejected" in d["ai_status"]["error"]
    with app.app_context():
        set_secret("anthropic_api_key", "")
        db.session.commit()


def test_an_old_model_name_falls_back_to_the_default_model(app, monkeypatch):
    from services import ai
    seen = []

    class NotFoundError(Exception):
        pass

    class FakeMsgs:
        def create(self, model, **kw):
            seen.append(model)
            if model != app.config["ANTHROPIC_MODEL"]:
                raise NotFoundError("no such model")

            class R:
                content = [type("B", (), {"text": '{"ok": 1}'})()]
            return R()

    class FakeClient:
        messages = FakeMsgs()
    from services.settings import set_secret
    from extensions import db
    with app.app_context():
        set_secret("anthropic_api_key", "sk-ant-test-key")
        db.session.commit()
        monkeypatch.setattr(ai, "_client", lambda: FakeClient())
        monkeypatch.setattr(ai, "_model", lambda company_id=None: "claude-old-model")
        assert ai.ask_json("t", "p", lambda: None) == {"ok": 1}
        assert seen == ["claude-old-model", app.config["ANTHROPIC_MODEL"]]
        assert ai.status()["working"]
        set_secret("anthropic_api_key", "")
        db.session.commit()


# ---------------------------------------------------------------- video call relay and connection

def test_platform_relay_gives_each_call_its_own_expiring_login(c, app):
    h = sa(c)
    r = c.put("/api/platform/integrations", headers=h, json={"turn_urls": "not-a-url"})
    assert r.status_code == 400
    d = j(c.put("/api/platform/integrations", headers=h, json={
        "turn_urls": "turn:relay.test:3478, turn:relay.test:3478?transport=tcp\nturns:relay.test:5349?transport=tcp",
        "turn_secret": "s3cret"}))["data"]
    assert d["turn_ok"] and d["turn_secret"] != "s3cret"  # masked
    att, ch, p, _ = live_round(c, "relay.cand@mail.test", "Relay Cand")
    info = j(c.get(f"/api/call/{att}", headers=ch))["data"]
    assert info["relay"] is True
    turn = next(s for s in info["ice_servers"] if isinstance(s["urls"], list))
    assert turn["urls"] == ["turn:relay.test:3478", "turn:relay.test:3478?transport=tcp", "turns:relay.test:5349?transport=tcp"]
    expiry, label = turn["username"].split(":")
    import time
    assert int(expiry) > time.time() + 3600 and label == f"att{att}"
    want = base64.b64encode(hmac.new(b"s3cret", turn["username"].encode(), hashlib.sha1).digest()).decode()
    assert turn["credential"] == want
    # the browser test for the superadmin
    assert j(c.get("/api/platform/integrations/turn-test", headers=h))["data"]["ice_servers"][0]["urls"][0] == "turn:relay.test:3478"
    # a company's own TURN server wins over the platform relay
    admin = login(c, "admin@acme.test")
    for k, v in (("call.turn_url", "turn:own.acme.test:3478"), ("call.turn_username", "u"), ("call.turn_credential", "pw")):
        j(c.put("/api/company/settings", headers=admin, json={"scope": "company", "key": k, "value": v}))
    info = j(c.get(f"/api/call/{att}", headers=ch))["data"]
    turn = next(s for s in info["ice_servers"] if isinstance(s["urls"], list))
    assert turn["urls"] == ["turn:own.acme.test:3478"] and turn["username"] == "u" and turn["credential"] == "pw"
    for k in ("call.turn_url", "call.turn_username", "call.turn_credential"):
        j(c.put("/api/company/settings", headers=admin, json={"scope": "company", "key": k, "reset": True}))
    j(c.put("/api/platform/integrations", headers=h, json={"turn_urls": "", "clear_turn_secret": True, "turn_secret": ""}))


def test_live_rounds_check_the_video_call_connection(c):
    _, aid, ch = new_candidate(c, "conn.step@mail.test", "Conn Step")
    att = invite(c, aid, "f2f_isha")
    req = j(c.get(f"/api/syscheck/requirements?attempt={att}&role=candidate&mode=full", headers=ch))["data"]
    keys = [s["key"] for s in req["steps"]]
    assert "connection" in keys and next(s for s in req["steps"] if s["key"] == "connection")["blocking"]
    assert isinstance(req["ice_servers"], list) and "relay" in req
    # a failed connection test blocks the start, like any other required step
    steps = {k: {"status": "pass"} for k in keys}
    steps["connection"] = {"status": "fail", "detail": "network blocks video calls"}
    out = j(c.post("/api/syscheck", headers=ch, json={"attempt_id": att, "role": "candidate", "mode": "full", "steps": steps, "instructions_read": True}))["data"]
    assert not out["passed"] and "connection" in out["failed"]
    # rejoining re-tests the connection too
    system_check(c, att, ch)
    assert "connection" in [s["key"] for s in j(c.get(f"/api/syscheck/requirements?attempt={att}&role=candidate&mode=recheck", headers=ch))["data"]["steps"]]
    # MCQ rounds have no call, so no connection step
    mcq = invite(c, aid, "mcq")
    assert "connection" not in [s["key"] for s in j(c.get(f"/api/syscheck/requirements?attempt={mcq}&role=candidate", headers=ch))["data"]["steps"]]


def test_connection_path_is_recorded_and_reported(c):
    att, ch, p, room = live_round(c, "path.cand@mail.test", "Path Cand")
    assert c.post(f"/api/call/{att}/path", headers=p, json={"state": "nonsense"}).status_code == 400
    j(c.post(f"/api/call/{att}/path", headers=p, json={"state": "retry"}))
    j(c.post(f"/api/call/{att}/path", headers=p, json={"state": "relay_only"}))
    j(c.post(f"/api/call/{att}/path", headers=p, json={"state": "connected", "path": "relay", "local": "relay", "remote": "srflx", "protocol": "udp", "rtt": 0.08}))
    j(c.post(f"/api/call/{att}/path", headers=ch, json={"state": "connected", "path": "relay"}))
    # started before the video connected: the report says so
    j(c.post(f"/api/isha/{att}/start", headers=p, json={"video": "not_connected"}))
    j(c.post(f"/api/isha/{att}/sentence", headers=p, json={"text": "I built a payments API in Django and tested it with pytest."}))
    draft = j(c.post(f"/api/isha/{att}/end", headers=p))["data"]["draft"]
    j(c.post(f"/api/isha/{att}/scorecard", headers=p, json={"competencies": [{**x, "score": x.get("score") or 3} for x in draft["competencies"]], "recommendation": "hold"}))
    rep = j(c.get(f"/api/reports/by-attempt/{att}", headers=login(c, "rahul@acme.test")))["data"]
    conn = rep["connection"]
    assert conn["connected"] and conn["used_relay"] and conn["path"] == "relay" and conn["retries"] == 2
    assert conn["started_without_video"] == "not_connected"
    # someone else can't write to this call
    assert c.post(f"/api/call/{att}/path", headers=login(c, "arjun@demo.test"), json={"state": "connected"}).status_code == 403


# ---------------------------------------------------------------- F2F-004 / SA-010: the scorecard is filled in

def test_scorecard_is_scored_against_the_job_competencies_and_prefilled_F2F004_SA010(c):
    att, ch, p, room = live_round(c, "score.cand@mail.test", "Score Cand")
    rubric = [r["name"] for r in room["job"]["rubric"]]
    assert all(a.get("competency") in rubric for a in room["brief"]["areas"] if a["area"] != "Wrap-up" and a.get("competency"))
    linked = [a for a in room["brief"]["areas"] if a.get("competency")]
    assert linked, "plan questions are linked to competencies"
    j(c.post(f"/api/isha/{att}/start", headers=p))
    first = linked[0]
    j(c.post(f"/api/isha/{att}/ask", headers=p, json={"q": first["q"], "area": first["area"]}))
    for t in ("I designed the service and chose PostgreSQL because we needed transactions.",
              "We measured latency and cut it by 40 percent after adding caching."):
        j(c.post(f"/api/isha/{att}/sentence", headers=p, json={"text": t}))
    draft = j(c.post(f"/api/isha/{att}/end", headers=p))["data"]["draft"]
    names = [x["name"] for x in draft["competencies"]]
    assert names == rubric, "one row per job competency, in order"
    row = next(x for x in draft["competencies"] if x["name"] == first["competency"])
    assert row["score"] and 1 <= row["score"] <= 5 and ("40 percent" in row["quote"] or "PostgreSQL" in row["quote"])
    others = [x for x in draft["competencies"] if x["name"] != first["competency"]]
    # V02.00.09 (N2): a competency not asked directly is scored from what was said about it elsewhere, or says why not
    assert all((x.get("not_covered") or x.get("elsewhere")) and x.get("reason") for x in others)
    assert draft["recommendation"] in ("proceed", "hold", "reject") and draft["summary"] and draft["captured"] == 2
    # re-draft after a correction, then submit: the AI score is kept
    again = j(c.post(f"/api/isha/{att}/redraft", headers=p))["data"]["draft"]
    assert [x["name"] for x in again["competencies"]] == rubric
    rows = [{**x, "score": x.get("score") or 3} for x in again["competencies"]]
    j(c.post(f"/api/isha/{att}/scorecard", headers=p, json={"competencies": rows, "recommendation": again["recommendation"], "summary": again["summary"]}))
    assert c.post(f"/api/isha/{att}/redraft", headers=p).status_code == 400


def test_scorecard_without_any_answers_says_why(c):
    att, ch, p, room = live_round(c, "noans.cand@mail.test", "Noans Cand")
    j(c.post(f"/api/isha/{att}/start", headers=p))
    draft = j(c.post(f"/api/isha/{att}/end", headers=p))["data"]["draft"]
    assert draft["captured"] == 0 and "No answers were captured" in draft["summary"]
    assert all(x["score"] is None and x["reason"] for x in draft["competencies"])


# ---------------------------------------------------------------- F2F-001: correcting captions

def test_interviewer_can_correct_or_remove_a_caption_F2F001(c):
    att, ch, p, room = live_round(c, "edit.cand@mail.test", "Edit Cand")
    j(c.post(f"/api/isha/{att}/start", headers=p))
    a0 = room["brief"]["areas"][0]
    j(c.post(f"/api/isha/{att}/ask", headers=p, json={"q": a0["q"], "area": a0["area"]}))
    j(c.post(f"/api/isha/{att}/sentence", headers=p, json={"text": "I used jango for the back end."}))
    j(c.post(f"/api/isha/{att}/sentence", headers=p, json={"text": "Can you hear me okay?"}))
    st = j(c.post(f"/api/isha/{att}/edit-sentence", headers=p, json={"index": 0, "sentence": 0, "text": "I used Django for the back end."}))["data"]
    e = st["areas_log"][0]
    assert e["sentences"][0] == "I used Django for the back end." and e["edited"] == [0]
    st = j(c.post(f"/api/isha/{att}/edit-sentence", headers=p, json={"index": 0, "sentence": 1, "text": ""}))["data"]
    assert st["areas_log"][0]["sentences"] == ["I used Django for the back end."]
    assert c.post(f"/api/isha/{att}/edit-sentence", headers=p, json={"index": 5, "sentence": 0, "text": "x"}).status_code == 400
    assert c.post(f"/api/isha/{att}/edit-sentence", headers=ch, json={"index": 0, "sentence": 0, "text": "x"}).status_code in (403, 404)
    draft = j(c.post(f"/api/isha/{att}/end", headers=p))["data"]["draft"]
    assert any("Django" in (x.get("quote") or "") for x in draft["competencies"])


# ---------------------------------------------------------------- F2F-003: varied, specific questions

RESUME = """Asha Rao, Backend developer, 6 years.
• Built a payments API in Django serving 2 million requests a day
• Reduced deploy time from 40 to 8 minutes by automating CI with GitHub Actions
• Led the migration of 30 services from EC2 to Kubernetes"""


def test_plan_is_specific_to_the_resume_and_not_one_template_F2F003(c):
    att, ch, p, room = live_round(c, "plan.cand@mail.test", "Plan Cand", resume=RESUME)
    qs = [a["q"] for a in room["brief"]["areas"]]
    assert any("Your resume says" in q or "Tell me about this from your resume" in q for q in qs), qs
    openers = [" ".join(q.split()[:4]) for q in qs]
    assert len(set(openers)) == len(openers), openers  # no two questions start the same way
    assert room["brief"]["areas"][-1]["area"] == "Wrap-up"


def test_follow_ups_use_the_candidates_words_and_never_repeat_F2F003(c):
    att, ch, p, room = live_round(c, "follow.cand@mail.test", "Follow Cand")
    j(c.post(f"/api/isha/{att}/start", headers=p))
    a0 = room["brief"]["areas"][0]
    j(c.post(f"/api/isha/{att}/ask", headers=p, json={"q": a0["q"], "area": a0["area"]}))
    seen = []
    for t in ("I think I maybe used Kafka a bit.", "I think it was kind of basically fine.", "Not sure, maybe it was another team.",
              "I think maybe the Kafka consumer was slow.", "Basically we kind of fixed it somehow."):
        opts = j(c.post(f"/api/isha/{att}/sentence", headers=p, json={"text": t}))["data"]["options"]
        # V02.00.13: prepared follow-ups stay offered until their point is covered or they're asked (by design)
        qs = [o["q"] for o in opts if o["type"] != "Move on" and o.get("source") != "prepared"]
        assert not set(qs) & set(seen), (qs, seen)
        seen += qs
    assert any("Kafka" in q for q in seen)


def test_brief_avoids_questions_from_earlier_rounds(app):
    from services import ai

    class J:
        title, level, description, skills = "Dev", "Mid", "", [{"name": "Python"}]
    with app.app_context():
        plan = ai.isha_brief(J(), "", [], n=7)["areas"]
        first = plan[0]["q"]
        again = ai.isha_brief(J(), "", [], n=7, avoid=[first])["areas"]
        assert first not in [a["q"] for a in again]


# ---------------------------------------------------------------- CD-005: practice uses the question bank

def test_practice_quiz_uses_superadmin_questions_and_never_saves_filler_CD005(c, app):
    from extensions import db
    from models import Question, RoundAttempt
    h = sa(c)
    added = j(c.post("/api/qbank/questions", headers=h, json={"skill": "Python", "level": 5, "text": "SUPERADMIN: what does the GIL protect?",
                                                               "options": ["The interpreter's internal state", "Files", "Sockets", "Nothing"], "answer": 0, "status": "approved"}))["data"]
    ch = login(c, "meera@demo.test")
    topics = j(c.get("/api/me/practice/topics", headers=ch))["data"]
    assert any(t["skill"] == "Python" and t["count"] > 0 for t in topics)
    with app.app_context():
        before = Question.query.count()
    # lower case, a level far from the question's, and more questions than the bank has: still picked, nothing saved
    att = j(c.post("/api/me/practice", headers=ch, json={"role": "Backend Developer", "type": "mcq", "skills": ["python"], "difficulty": "easy", "questions": 20}))["data"]["attempt_id"]
    j(c.post(f"/api/rounds/{att}/consent", headers=ch, json={}))
    room = j(c.post(f"/api/rounds/{att}/start", headers=ch))["data"]
    texts = [q["text"] for q in room["questions"]]
    assert "SUPERADMIN: what does the GIL protect?" in texts
    with app.app_context():
        assert Question.query.count() == before, "filler questions are not saved to any bank"
        a = db.session.get(RoundAttempt, att)
        assert a.config["level"] == 2 and a.result["mcq_info"]["filler"] >= 0
        neg = [i for i in a.result["question_ids"] if i < 0]
        assert all(str(i) in a.result["qsnap"] for i in neg)
    # answering and finishing works with the unsaved questions too
    for q in room["questions"]:
        c.post(f"/api/rounds/{att}/answer", headers=ch, json={"qid": q["id"], "choice": 0})
    out = j(c.post(f"/api/rounds/{att}/submit", headers=ch))["data"]
    assert out["done"]
    assert added["id"]


def test_practice_skill_names_match_loosely(app):
    from services.mcq import match_skills
    with app.app_context():
        assert "Python" in match_skills(["python"]) and "Python" in match_skills(["Python programming"])
        assert match_skills(["Underwater basket weaving"]) == []


def test_ai_written_practice_questions_wait_for_review(app, monkeypatch):
    from services import ai
    from services.mcq import save_generated
    from models import Question
    with app.app_context():
        items = [{"skill": "Rust", "level": 3, "text": "Which keyword makes a Rust binding mutable?", "options": ["mut", "var", "let", "const"], "answer": 0},
                 {"skill": "Rust", "level": 3, "text": "Filler question", "options": ["a", "b"], "answer": 0, "fallback": True}]
        out = save_generated(items, None, ["Rust"], review=True)
        saved = [q for q in out if (q.id or 0) > 0]
        assert len(saved) == 1 and saved[0].status == "pending"
        assert [q for q in out if (q.id or 0) < 0][0].status == "filler"
        assert not Question.query.filter_by(text="Filler question").first()


# ---------------------------------------------------------------- SA-001: templates

def test_deleting_a_template_archives_it_and_archived_list_shows_it_SA001(c):
    h = sa(c)
    t = j(c.post("/api/platform/templates", headers=h, json={"name": "Temp to delete", "rounds": [{"type": "mcq", "name": "Screen"}]}))["data"]
    assert j(c.delete(f"/api/platform/templates/{t['id']}", headers=h))["data"]["archived"] is True
    assert t["id"] not in [x["id"] for x in j(c.get("/api/platform/templates", headers=h))["data"]]
    arch = j(c.get("/api/platform/templates?archived=true", headers=h))["data"]
    assert t["id"] in [x["id"] for x in arch] and all(x["archived"] for x in arch)
    j(c.patch(f"/api/platform/templates/{t['id']}", headers=h, json={"archived": False}))
    assert t["id"] in [x["id"] for x in j(c.get("/api/platform/templates", headers=h))["data"]]
    j(c.delete(f"/api/platform/templates/{t['id']}", headers=h))
    assert j(c.delete(f"/api/platform/templates/{t['id']}?permanent=1", headers=h))["data"]["deleted"] is True
    assert c.delete(f"/api/platform/templates/{t['id']}", headers=h).status_code == 404


# ---------------------------------------------------------------- SA-002/003/004: users

def test_users_can_be_deleted_archived_and_restored_SA002_SA003(c):
    h = sa(c)
    vikram = uid(c, "vikram@acme.test")
    rows = j(c.get("/api/platform/users?size=100", headers=h))["items"]
    assert any(r["id"] == vikram for r in rows) and all("company" in r for r in rows)
    me = next(r for r in rows if r["is_me"])
    assert c.post("/api/platform/users/archive", headers=h, json={"ids": [me["id"]]}).status_code == 400
    assert c.post("/api/platform/users/archive", headers=login(c, "admin@acme.test"), json={"ids": [vikram]}).status_code == 403
    j(c.post("/api/platform/users/archive", headers=h, json={"ids": [vikram]}))
    assert vikram not in [r["id"] for r in j(c.get("/api/platform/users?size=100", headers=h))["items"]]
    arch = j(c.get("/api/platform/users?archived=true", headers=h))["items"]
    assert [r["id"] for r in arch] == [vikram] and arch[0]["archived_at"]
    r = c.post("/api/auth/login", json={"email": "vikram@acme.test", "password": PW}, headers={"X-Forwarded-For": "10.8.9.1"})
    assert r.status_code == 403
    j(c.post("/api/platform/users/restore", headers=h, json={"ids": [vikram]}))
    r = c.post("/api/auth/login", json={"email": "vikram@acme.test", "password": PW}, headers={"X-Forwarded-For": "10.8.9.2"})
    assert r.status_code == 200
    # filters behind the overview cards
    staff = j(c.get("/api/platform/users?kind=staff&size=100", headers=h))["items"]
    assert staff and all(x["kind"] == "staff" and not x["is_superadmin"] for x in staff)
    assert all(x["is_superadmin"] for x in j(c.get("/api/platform/users?kind=superadmin", headers=h))["items"])


def test_superadmin_name_has_no_platform_word_and_can_be_changed_SA004(c):
    h = sa(c)
    me = j(c.get("/api/auth/me", headers=h))["data"]["user"]
    assert me["name"] == "Superadmin"
    assert c.patch("/api/platform/me", headers=h, json={"name": "x"}).status_code == 400
    assert j(c.patch("/api/platform/me", headers=h, json={"name": "Asha Admin"}))["data"]["name"] == "Asha Admin"
    j(c.patch("/api/platform/me", headers=h, json={"name": "Superadmin"}))


# ---------------------------------------------------------------- SA-005/006: audit log

def test_audit_log_is_readable_SA005(c):
    h = sa(c)
    rows = j(c.get("/api/platform/audit?size=100", headers=h))["items"]
    inv = next(r for r in rows if r["action"] == "round.invite")
    assert inv["action_label"] == "Invited to a round"
    assert inv["target_label"].startswith("Application: ")
    labels = {x["label"]: x["value"] for x in inv["detail_items"]}
    assert "Round" in labels and labels["Type"] in ("MCQ test", "AI interview", "Live interview with Isha", "Live interview")
    assert "company" in inv
    acts = j(c.get("/api/platform/audit/actions", headers=h))["data"]
    assert {"value": "round", "label": "Rounds"} in acts


def test_audit_search_finds_names_numbers_and_words_SA006(c):
    h = sa(c)
    total = j(c.get("/api/platform/audit?size=5", headers=h))["total"]
    by_name = j(c.get("/api/platform/audit?q=Score%20Cand", headers=h))
    assert 0 < by_name["total"] < total
    by_word = j(c.get("/api/platform/audit?q=invited", headers=h))["items"]
    assert by_word and all(r["action"] == "round.invite" for r in by_word)
    one = by_word[0]
    by_num = j(c.get(f"/api/platform/audit?q={one['target_id']}", headers=h))["items"]
    assert any(r["id"] == one["id"] for r in by_num)
    by_co = j(c.get("/api/platform/audit?q=Acme", headers=h))
    assert by_co["total"] > 0
    by_detail = j(c.get("/api/platform/audit?q=f2f_isha", headers=h))
    assert by_detail["total"] > 0
    assert j(c.get("/api/platform/audit?action=round", headers=h))["items"][0]["action"].startswith("round.")
    assert j(c.get("/api/platform/audit?q=zzzz-nothing", headers=h))["total"] == 0


# ---------------------------------------------------------------- SA-008: overview cards open lists

def test_overview_cards_have_lists_behind_them_SA008(c):
    h = sa(c)
    o = j(c.get("/api/platform/overview", headers=h))["data"]
    assert j(c.get("/api/platform/companies?status=active", headers=h))["total"] == o["companies"]["active"]
    assert j(c.get("/api/platform/jobs?status=live", headers=h))["total"] == o["jobs_live"]
    assert j(c.get("/api/platform/rounds?type=mcq", headers=h))["total"] == o["assessments"]
    assert j(c.get("/api/platform/rounds?type=f2f_isha", headers=h))["total"] == o["isha_sessions"]
    assert j(c.get("/api/platform/reports", headers=h))["total"] == o["reports"]
    assert j(c.get("/api/platform/users?kind=candidate&size=5", headers=h))["total"] == o["candidates"]
    for path in ("/api/platform/jobs", "/api/platform/rounds", "/api/platform/reports"):
        assert c.get(path, headers=login(c, "admin@acme.test")).status_code == 403


def test_practice_instructions_say_it_is_private(c):
    ch = login(c, "meera@demo.test")
    att = j(c.post("/api/me/practice", headers=ch, json={"role": "Backend Developer", "type": "mcq", "skills": ["SQL"], "questions": 4}))["data"]["attempt_id"]
    ins = j(c.get(f"/api/syscheck/requirements?attempt={att}&role=candidate", headers=ch))["data"]["instructions"]
    text = " ".join(" ".join(s["items"]) for s in ins["sections"])
    assert "private to you" in text and "hiring team reviews your round" not in text



# ---------------------------------------------------------------- technical retake (V02.00.08, decided 12 Nov)

def _credits(app, company="Acme Technologies"):
    from models import Company
    with app.app_context():
        return Company.query.filter_by(name=company).first().credits_used


def test_retake_limit_is_set_by_the_superadmin_default_5(c):
    h = sa(c)
    row = next(r for r in j(c.get("/api/platform/settings", headers=h))["data"] if r["key"] == "policy.retake_max")
    assert row["value"] == 5 and row["editable"]
    admin = login(c, "admin@acme.test")
    crow = next(r for r in j(c.get("/api/company/settings?scope=company", headers=admin))["data"] if r["key"] == "policy.retake_max")
    assert crow["editable"] is False
    r = c.put("/api/company/settings", headers=admin, json={"scope": "company", "key": "policy.retake_max", "value": 9})
    assert r.status_code in (400, 403)
    assert c.put("/api/platform/settings", headers=h, json={"key": "policy.retake_max", "value": 50}).status_code == 400


def test_technical_retake_voids_the_round_charges_and_sends_a_new_invite(c, app):
    att, ch, p, room = live_round(c, "retake.cand@mail.test", "Retake Cand")
    j(c.post(f"/api/isha/{att}/start", headers=p))
    j(c.post(f"/api/call/{att}/path", headers=p, json={"state": "failed"}))
    info = j(c.get(f"/api/attempts/{att}/retake", headers=p))["data"]
    assert info["allowed"] and info["limit"] == 5 and info["left"] == 5 and info["credits"] == 3
    assert info["evidence"]["connection"]["failures"] == 1 and "minutes" in info["evidence"]
    assert c.post(f"/api/attempts/{att}/retake", headers=p, json={}).status_code == 400            # a reason is needed
    assert c.post(f"/api/attempts/{att}/retake", headers=p, json={"reason": "other"}).status_code == 400  # "other" needs details
    before = _credits(app)
    out = j(c.post(f"/api/attempts/{att}/retake", headers=p, json={"reason": "video", "note": "Video never connected"}))["data"]
    assert _credits(app) == before + 3, "charged like a re-interview"
    new = out["attempt_id"]
    assert new != att and out["used"] == 1 and out["limit"] == 5
    # the old round is voided: closed for the candidate, its report marked, the room told it ended
    old = j(c.get(f"/api/rounds/{att}", headers=ch))["data"]
    assert old["status"] == "voided" and old["retake_attempt_id"] == new
    assert c.post(f"/api/rounds/{att}/consent", headers=ch, json={}).status_code == 409
    sig = j(c.get(f"/api/call/{att}/signal?after=0", headers=ch))["data"]
    assert sig["ended"] and any(s["kind"] == "bye" and s["payload"].get("retake") for s in sig["signals"])
    assert c.post(f"/api/isha/{att}/start", headers=p).status_code == 409
    # the candidate's application shows the new round, not the voided one
    apps = j(c.get("/api/me/applications", headers=ch))["data"]
    step = next(s for s in apps[0]["steps"] if s["attempt_id"] in (att, new))
    assert step["attempt_id"] == new and step["status"] in ("invited", "scheduled")
    # the hiring team's view: voided with its reason, and the retake marked
    aid = j(c.get(f"/api/rounds/{new}", headers=ch))["data"]
    rows = j(c.get(f"/api/applications/{_app_id(c, 'retake.cand@mail.test')}", headers=login(c, "rahul@acme.test")))["data"]["attempts"]
    v = next(x for x in rows if x["id"] == att)
    assert v["status"] == "voided" and v["voided"]["kind"] == "technical" and v["voided"]["reason_text"] == "The video didn't connect"
    assert next(x for x in rows if x["id"] == new)["retake_of"] == att
    assert aid["id"] == new


def _app_id(c, email):
    h = login(c, "rahul@acme.test")
    job = python_job(c)
    return j(c.get(f"/api/jobs/{job['id']}/applications?q={email}&stage=applied,shortlisted,in_round,awaiting_review,decision,on_hold,removed", headers=h))["items"][0]["id"]


def test_retake_rules(c, app):
    _, aid, ch = new_candidate(c, "retake.rules@mail.test", "Retake Rules")
    att = invite(c, aid, "mcq")
    p = login(c, "priya@acme.test")
    r = c.post(f"/api/attempts/{att}/retake", headers=p, json={"reason": "internet"})
    assert r.status_code == 400 and "Reschedule" in r.get_json()["error"]  # not started yet
    system_check(c, att, ch)
    j(c.post(f"/api/rounds/{att}/consent", headers=ch, json={}))
    j(c.post(f"/api/rounds/{att}/start", headers=ch))
    # the superadmin lowers the limit to 1: the second retake is refused
    h = sa(c)
    j(c.put("/api/platform/settings", headers=h, json={"key": "policy.retake_max", "value": 1}))
    new = j(c.post(f"/api/attempts/{att}/retake", headers=p, json={"reason": "candidate_device"}))["data"]["attempt_id"]
    system_check(c, new, ch)
    j(c.post(f"/api/rounds/{new}/consent", headers=ch, json={}))
    j(c.post(f"/api/rounds/{new}/start", headers=ch))
    r = c.post(f"/api/attempts/{new}/retake", headers=p, json={"reason": "candidate_device"})
    assert r.status_code == 403 and "most Code2Hire allows (1)" in r.get_json()["error"]
    assert j(c.get(f"/api/attempts/{new}/retake", headers=p))["data"]["left"] == 0
    j(c.put("/api/platform/settings", headers=h, json={"key": "policy.retake_max", "reset": True}))
    assert j(c.get(f"/api/attempts/{new}/retake", headers=p))["data"]["limit"] == 5
    # someone outside the company can't
    assert c.post(f"/api/attempts/{new}/retake", headers=ch, json={"reason": "video"}).status_code in (401, 403)
    # voided rounds are left out of the comparison
    from models import RoundAttempt
    from extensions import db
    with app.app_context():
        assert db.session.get(RoundAttempt, att).status == "voided"


# ---------------------------------------------------------------- remove from job and re-add (A1/A2)

def test_remove_from_job_cancels_invites_and_refunds(c, app):
    job, aid, ch = new_candidate(c, "remove.cand@mail.test", "Remove Cand")
    h = login(c, "rahul@acme.test")
    att = invite(c, aid, "ai_interview")
    before = _credits(app)
    j(c.post(f"/api/applications/{aid}/remove", headers=h, json={"note": "Duplicate profile"}))
    assert _credits(app) == before - 5, "the unused AI interview's credits come back"
    assert j(c.get(f"/api/rounds/{att}", headers=ch))["data"]["status"] == "cancelled"
    listed = [x["id"] for x in j(c.get(f"/api/jobs/{job['id']}/applications?size=100", headers=h))["items"]]
    assert aid not in listed
    removed = [x["id"] for x in j(c.get(f"/api/jobs/{job['id']}/applications?stage=removed", headers=h))["items"]]
    assert aid in removed
    assert c.post(f"/api/applications/{aid}/remove", headers=h).status_code == 409
    # adding the same email again offers Restore / Start fresh
    r = j(c.post("/api/candidates", headers=h, json={"name": "Remove Cand", "email": "remove.cand@mail.test", "job_id": job["id"]}))["data"]["results"][0]
    assert r["status"] == "removed" and r["application_id"] == aid
    a = j(c.post(f"/api/applications/{aid}/restore", headers=h, json={"mode": "continue"}))["data"]
    assert a["stage"] == "in_round"
    # the candidate sees the job as closed while removed
    j(c.post(f"/api/applications/{aid}/remove", headers=h))
    st = next(x for x in j(c.get("/api/me/applications", headers=ch))["data"] if x["id"] == aid)
    assert st["stage"] == "Closed"


def test_restore_fresh_starts_from_round_one_and_keeps_history(c):
    job, aid, ch = new_candidate(c, "fresh.cand@mail.test", "Fresh Cand")
    h = login(c, "rahul@acme.test")
    att = invite(c, aid, "mcq")
    system_check(c, att, ch)
    j(c.post(f"/api/rounds/{att}/consent", headers=ch, json={}))
    j(c.post(f"/api/rounds/{att}/start", headers=ch))
    r = c.post(f"/api/applications/{aid}/remove", headers=h)
    assert r.status_code == 409 and "taking a round" in r.get_json()["error"]
    j(c.post(f"/api/rounds/{att}/submit", headers=ch))
    j(c.post(f"/api/applications/{aid}/remove", headers=h))
    a = j(c.post(f"/api/applications/{aid}/restore", headers=h, json={"mode": "fresh"}))["data"]
    assert a["stage"] == "applied" and a["current_round"] == -1 and not a["verdict"]
    rows = j(c.get(f"/api/applications/{aid}", headers=h))["data"]["attempts"]
    assert rows and all(x["status"] == "voided" and x["voided"]["kind"] == "fresh_start" for x in rows)
    assert c.post(f"/api/applications/{aid}/restore", headers=h, json={"mode": "fresh"}).status_code == 409
    # round 1 can be sent again
    assert invite(c, aid, "mcq")


# ---------------------------------------------------------------- talent pool (A3)

def test_remove_from_talent_pool_and_bring_back(c):
    h = login(c, "rahul@acme.test")
    _, aid, ch = new_candidate(c, "pool.cand@mail.test", "Pool Cand")
    uid_ = j(c.get("/api/talent-pool?q=pool.cand", headers=h))["items"][0]["id"]
    j(c.post("/api/talent-pool/remove", headers=h, json={"user_ids": [uid_]}))
    assert not j(c.get("/api/talent-pool?q=pool.cand", headers=h))["items"]
    assert [x["id"] for x in j(c.get("/api/talent-pool?removed=true", headers=h))["items"]] == [uid_]
    assert not j(c.get("/api/candidates/search?q=Pool%20Cand", headers=h))["data"]["items"]
    j(c.post("/api/talent-pool/restore", headers=h, json={"user_ids": [uid_]}))
    assert j(c.get("/api/talent-pool?q=pool.cand", headers=h))["items"]
    # removing again, then adding them by email brings them back
    j(c.post("/api/talent-pool/remove", headers=h, json={"user_ids": [uid_]}))
    j(c.post("/api/candidates", headers=h, json={"name": "Pool Cand", "email": "pool.cand@mail.test"}))
    assert j(c.get("/api/talent-pool?q=pool.cand", headers=h))["items"]


# ---------------------------------------------------------------- company team members (A4)

def test_company_admin_removes_and_restores_a_team_member(c):
    admin = login(c, "admin@acme.test")
    team = j(c.get("/api/company/users?size=100", headers=admin))["items"]
    me = uid(c, "admin@acme.test")
    assert c.post(f"/api/company/users/{me}/remove", headers=admin).status_code == 400
    anita = next(x for x in team if x["email"] == "anita@acme.test")
    j(c.post(f"/api/company/users/{anita['id']}/remove", headers=admin))
    assert anita["id"] not in [x["id"] for x in j(c.get("/api/company/users?size=100", headers=admin))["items"]]
    assert [x["id"] for x in j(c.get("/api/company/users?removed=true", headers=admin))["items"]] == [anita["id"]]
    assert c.post("/api/auth/login", json={"email": "anita@acme.test", "password": PW}, headers={"X-Forwarded-For": "10.8.7.1"}).status_code == 403
    r = c.post("/api/company/users", headers=admin, json={"name": "Anita", "email": "anita@acme.test"})
    assert r.status_code == 409 and r.get_json()["restore_user_id"] == anita["id"]
    j(c.post(f"/api/company/users/{anita['id']}/restore", headers=admin))
    assert c.post("/api/auth/login", json={"email": "anita@acme.test", "password": PW}, headers={"X-Forwarded-For": "10.8.7.2"}).status_code == 200


def test_last_company_admin_cannot_be_removed(c, app):
    from models import RoleAssignment, User
    from extensions import db
    admin = login(c, "admin@acme.test")
    with app.app_context():
        admins = [u.id for u in User.query.join(RoleAssignment, RoleAssignment.user_id == User.id)
                  .filter(RoleAssignment.role == "company_admin", User.email != "admin@acme.test").all()]
    for a in admins:
        j(c.post(f"/api/company/users/{a}/remove", headers=admin))
    # ask another admin-capable account? there is none left: the remaining admin is the caller, who can't remove themselves
    assert c.post(f"/api/company/users/{uid(c, 'admin@acme.test')}/remove", headers=admin).status_code == 400
    for a in admins:
        j(c.post(f"/api/company/users/{a}/restore", headers=admin))


# ---------------------------------------------------------------- superadmin erase (A5)

def test_superadmin_can_erase_only_archived_users(c, app):
    h = sa(c)
    _, aid, ch = new_candidate(c, "erase.me@mail.test", "Erase Me")
    u = j(c.get("/api/auth/me", headers=ch))["data"]["user"]["id"]
    assert c.post("/api/platform/users/erase", headers=h, json={"ids": [u], "confirm": "DELETE"}).status_code == 400
    j(c.post("/api/platform/users/archive", headers=h, json={"ids": [u]}))
    assert c.post("/api/platform/users/erase", headers=h, json={"ids": [u]}).status_code == 400  # must confirm
    j(c.post("/api/platform/users/erase", headers=h, json={"ids": [u], "confirm": "DELETE"}))
    from models import User
    from extensions import db
    with app.app_context():
        x = db.session.get(User, u)
        assert x.name == "Deleted user" and x.email.startswith("deleted-") and not x.active
    # a deleted (archived) person's email can't be added by a company until the superadmin restores them
    _, aid2, ch2 = new_candidate(c, "arch.me@mail.test", "Arch Me")
    u2 = j(c.get("/api/auth/me", headers=ch2))["data"]["user"]["id"]
    j(c.post("/api/platform/users/archive", headers=h, json={"ids": [u2]}))
    r = j(c.post("/api/candidates", headers=login(c, "rahul@acme.test"), json={"name": "Arch Me", "email": "arch.me@mail.test"}))["data"]["results"][0]
    assert r["status"] == "invalid" and "restore" in r["error"]


# ---------------------------------------------------------------- visual reports (V02.00.08, 12 Nov)

def test_report_pdfs_have_charts_for_every_audience(c):
    """Every audience's PDF builds with the new charts: gauge, key figures, competency bars, radar and per-question chart."""
    import io
    import pypdf
    att, ch, p, room = live_round(c, "visual.cand@mail.test", "Visual Cand")
    j(c.post(f"/api/isha/{att}/start", headers=p))
    for a in room["brief"]["areas"][:3]:
        j(c.post(f"/api/isha/{att}/ask", headers=p, json={"q": a["q"], "area": a["area"]}))
        j(c.post(f"/api/isha/{att}/sentence", headers=p, json={"text": "I designed it, measured the result and cut latency by 40 percent."}))
    d = j(c.post(f"/api/isha/{att}/end", headers=p))["data"]["draft"]
    j(c.post(f"/api/isha/{att}/scorecard", headers=p, json={"competencies": [{**x, "score": x.get("score") or 3} for x in d["competencies"]], "recommendation": "proceed"}))
    rahul = login(c, "rahul@acme.test")
    rid = j(c.get(f"/api/reports/by-attempt/{att}", headers=rahul))["data"]["id"]
    for aud in ("internal", "hiring_manager", "client", "candidate"):
        r = c.get(f"/api/reports/{rid}/pdf?audience={aud}", headers=rahul)
        assert r.status_code == 200 and r.data[:4] == b"%PDF", aud
        text = " ".join(pg.extract_text() for pg in pypdf.PdfReader(io.BytesIO(r.data)).pages)
        if aud != "candidate":
            assert "Scores by competency" in text and "OVERALL" in text and "Visual Cand" in text, aud
        else:
            assert "What went well" in text and "Next steps" in text


def test_report_chart_helpers():
    from services import report_charts as RC
    assert RC.band(80) == "good" and RC.band(50) == "warn" and RC.band(10) == "bad" and RC.band(None) == "none"
    assert RC.level_of(4.2) == "Strong" and RC.level_of(3) == "Meets" and RC.level_of(2.9) == "Weak"
    qs = [{"skill": "SQL", "correct": True, "chosen": 1}, {"skill": "SQL", "correct": False, "chosen": 0}, {"skill": "Go", "chosen": None}]
    assert RC.answer_map(qs).width > 0 and RC.skill_stack(qs).height > 0
    assert RC.radar([{"name": "A", "score": 3}, {"name": "B", "score": 4}]) is None
    assert RC.radar([{"name": n, "score": 3} for n in "ABC"]) is not None
    d, cov = RC.question_columns([{"good_answer": ["x", "y"], "covered": [True, False]}, {"good_answer": ["z"], "covered": [False]}])
    assert d is not None and cov is True
    d, cov = RC.question_columns([{"score": 3.5}, {"score": 2}])
    assert d is not None and cov is False
