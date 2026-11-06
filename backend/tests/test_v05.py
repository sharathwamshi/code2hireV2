"""Regression tests for V02.00.05: the system check, candidate instructions, phones blocked, Ask Hira, choosing an
existing candidate, and the F2F bug report (F2F-001 to 008). Each test names what it covers. Run: pytest -q"""
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
    os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "v05.db")
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["AZURE_SPEECH_KEY"] = ""

from tests.syscheck_helper import system_check  # noqa: E402
import seed  # noqa: E402
from app import create_app  # noqa: E402

PW = seed.PW
IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
ANDROID_TAB = "Mozilla/5.0 (Linux; Android 13; SM-X700) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


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
        r = c.post("/api/auth/login", json={"email": email, "password": pw}, headers={"X-Forwarded-For": "10.5.0." + str(len(_tokens) + 1)})
        assert r.status_code == 200, r.get_json()
        _tokens[email] = {"Authorization": "Bearer " + r.get_json()["data"]["token"]}
    return _tokens[email]


def j(r, code=200):
    assert r.status_code == code, (r.status_code, r.get_json())
    return r.get_json()


def uid(c, email):
    return j(c.get("/api/auth/me", headers=login(c, email)))["data"]["user"]["id"]


def jobs(c, h):
    return {x["title"]: x for x in j(c.get("/api/jobs?size=100", headers=h))["items"]}


def new_candidate(c, email, name, title="Senior Python Developer"):
    h = login(c, "rahul@acme.test")
    job = jobs(c, h)[title]
    r = j(c.post("/api/candidates", headers=h, json={"name": name, "email": email, "job_id": job["id"]}))["data"]["results"][0]
    op = j(c.post(f"/api/auth/invite/{r['link'].split('/')[-1]}/open"))["data"]
    return job, r["application_id"], {"Authorization": "Bearer " + op["token"]}


def invite(c, aid, kind, **extra):
    h = login(c, "rahul@acme.test")
    full = j(c.get(f"/api/applications/{aid}", headers=h))["data"]
    idx = next(i for i, r in enumerate(full["rounds"]) if r["type"] == kind)
    body = {"round_index": idx, **extra}
    if kind.startswith("f2f"):
        body["interviewer_id"] = uid(c, "priya@acme.test")
    return j(c.post(f"/api/applications/{aid}/invite", headers=h, json=body))["data"]["attempt_id"]


def steps_of(c, att, h, role="candidate", mode="full"):
    return j(c.get(f"/api/syscheck/requirements?attempt={att}&role={role}&mode={mode}", headers=h))["data"]


def all_pass(req):
    return {s["key"]: {"status": "pass", "detail": "ok"} for s in req["steps"]}


# ---------------------------------------------------------------- R1: system check

def test_steps_follow_the_round_R1(c):
    job, aid, ch = new_candidate(c, "steps.cand@mail.test", "Steps Cand")
    ai = invite(c, aid, "ai_interview")
    keys = [s["key"] for s in steps_of(c, ai, ch)["steps"]]
    assert keys == ["device", "browser", "permissions", "camera", "face", "mic", "speaker", "recording", "fullscreen", "internet", "room"]
    req = steps_of(c, ai, ch)
    assert [s["key"] for s in req["steps"] if not s["blocking"]] == ["internet"]   # only the internet test only warns
    assert req["instructions"]["sections"] and req["enforced"] is True
    # rejoining re-checks the devices only
    assert [s["key"] for s in steps_of(c, ai, ch, mode="recheck")["steps"]] == ["permissions", "camera", "mic", "speaker"]
    # the interviewer's shorter check: no face, no room checklist, no fullscreen
    _, aid2, _ = new_candidate(c, "steps.live@mail.test", "Steps Live")
    live = invite(c, aid2, "f2f_isha")
    iv = [s["key"] for s in steps_of(c, live, login(c, "priya@acme.test"), role="interviewer")["steps"]]
    assert iv == ["device", "browser", "permissions", "camera", "mic", "speaker", "recording", "internet"]
    assert "guide" in steps_of(c, live, login(c, "priya@acme.test"), role="interviewer")
    # someone else can't run a check for this candidate's round
    other = login(c, "meera@demo.test")
    assert c.get(f"/api/syscheck/requirements?attempt={ai}", headers=other).status_code == 403


def test_mcq_without_face_check_needs_no_camera_R1(c):
    h = login(c, "rahul@acme.test")
    job, aid, ch = new_candidate(c, "mcq.cand@mail.test", "Mcq Cand")
    full = j(c.get(f"/api/jobs/{job['id']}", headers=h))["data"]
    rounds = [{**r, "config": {**(r.get("config") or {}), "integrity.face_check": False}} if r["type"] == "mcq" else r for r in full["rounds"]]
    j(c.patch(f"/api/jobs/{job['id']}", headers=h, json={"rounds": rounds}))
    att = invite(c, aid, "mcq")
    keys = [s["key"] for s in steps_of(c, att, ch)["steps"]]
    assert "camera" not in keys and "mic" not in keys and "fullscreen" in keys and "room" in keys
    rounds = [{**r, "config": {k: v for k, v in (r.get("config") or {}).items() if k != "integrity.face_check"}} if r["type"] == "mcq" else r for r in full["rounds"]]
    j(c.patch(f"/api/jobs/{job['id']}", headers=h, json={"rounds": rounds}))


def test_consent_needs_a_passing_check_and_the_instructions_R1_R3(c):
    job, aid, ch = new_candidate(c, "consent.cand@mail.test", "Consent Cand")
    att = invite(c, aid, "ai_interview")
    r = c.post(f"/api/rounds/{att}/consent", headers=ch, json={})
    assert r.status_code == 409 and r.get_json()["fields"]["code"] == "system_check"
    req = steps_of(c, att, ch)
    # one blocking step failed: not passed
    bad = {**all_pass(req), "speaker": {"status": "fail", "detail": "Not heard"}}
    out = j(c.post("/api/syscheck", headers=ch, json={"attempt_id": att, "steps": bad, "instructions_read": True}))["data"]
    assert not out["passed"] and out["failed"] == ["speaker"]
    # a missing step counts as failed
    part = {k: v for k, v in all_pass(req).items() if k != "recording"}
    assert j(c.post("/api/syscheck", headers=ch, json={"attempt_id": att, "steps": part, "instructions_read": True}))["data"]["failed"] == ["recording"]
    # weak internet only warns
    weak = {**all_pass(req), "internet": {"status": "warn", "detail": "weak · 0.6 Mbps up"}}
    # ... but the instructions must be read
    out = j(c.post("/api/syscheck", headers=ch, json={"attempt_id": att, "steps": weak}))["data"]
    assert not out["passed"] and out["failed"] == ["instructions"]
    assert c.post(f"/api/rounds/{att}/consent", headers=ch, json={}).status_code == 409
    out = j(c.post("/api/syscheck", headers=ch, json={"attempt_id": att, "steps": weak, "instructions_read": True}))["data"]
    assert out["passed"]
    a = j(c.post(f"/api/rounds/{att}/consent", headers=ch, json={}))["data"]
    assert a["consented"] and a["instructions_read"] and a["check_passed"]
    j(c.post(f"/api/rounds/{att}/start", headers=ch))


def test_phones_and_tablets_are_blocked_R2(c):
    job, aid, ch = new_candidate(c, "phone.cand@mail.test", "Phone Cand")
    att = invite(c, aid, "ai_interview")
    for ua in (IPHONE, ANDROID_TAB):
        req = j(c.get(f"/api/syscheck/requirements?attempt={att}", headers={**ch, "User-Agent": ua}))["data"]
        assert req["mobile"] and "laptop or desktop" in req["mobile_message"]
        # even if the browser claims every step passed, the server sees the phone
        out = j(c.post("/api/syscheck", headers={**ch, "User-Agent": ua}, json={"attempt_id": att, "steps": all_pass(req), "instructions_read": True}))["data"]
        assert not out["passed"] and "device" in out["failed"] and out["steps"]["device"]["detail"] == "Phone or tablet"
    system_check(c, att, {**ch, "User-Agent": CHROME})
    r = c.post(f"/api/rounds/{att}/consent", headers={**ch, "User-Agent": IPHONE}, json={})
    assert r.status_code == 403 and r.get_json()["fields"]["code"] == "use_laptop"
    j(c.post(f"/api/rounds/{att}/consent", headers={**ch, "User-Agent": CHROME}, json={}))
    assert c.post(f"/api/rounds/{att}/start", headers={**ch, "User-Agent": IPHONE}).status_code == 403


def test_practice_runs_the_check_but_does_not_require_it_R1(c):
    ch = login(c, "arjun@demo.test")
    pr = j(c.post("/api/me/practice", headers=ch, json={"type": "ai_interview", "skills": ["Python"], "questions": 2}))["data"]
    req = steps_of(c, pr["attempt_id"], ch)
    assert req["enforced"] is False and req["steps"]
    j(c.post(f"/api/rounds/{pr['attempt_id']}/consent", headers=ch, json={}))


def test_help_request_tells_the_hiring_team_R1(c, app):
    from models import Notification
    job, aid, ch = new_candidate(c, "help.cand@mail.test", "Help Cand")
    att = invite(c, aid, "ai_interview")
    assert c.post("/api/syscheck/help", headers=ch, json={"attempt_id": att, "step": "nonsense"}).status_code == 400
    r = j(c.post("/api/syscheck/help", headers=ch, json={"attempt_id": att, "step": "mic", "note": "My laptop has no microphone"}))["data"]
    assert r["sent"] and "invite stays valid" in r["message"]
    with app.app_context():
        n = Notification.query.filter(Notification.title == "Help Cand needs help with the system check").all()
        assert n and "Microphone" in n[0].body and "no microphone" in n[0].body and n[0].link == f"/app/applications/{aid}"
    rahul = login(c, "rahul@acme.test")
    rows = j(c.get(f"/api/jobs/{job['id']}/applications?size=100", headers=rahul))["items"]
    assert next(x for x in rows if x["id"] == aid)["last_round"]["setup"] == "needs_help"   # the pipeline shows it
    detail = j(c.get(f"/api/applications/{aid}", headers=rahul))["data"]
    assert detail["attempts"][-1]["setup"]["state"] == "needs_help"
    # Ask Hira lists it under "what needs my attention"
    out = j(c.post("/api/assistant/ask", headers=rahul, json={"q": "What needs my attention today?"}))["data"]
    assert any("needs help with the system check" in it["label"] for it in out["items"])
    # passing afterwards turns it into "tested"
    system_check(c, att, ch)
    rows = j(c.get(f"/api/jobs/{job['id']}/applications?size=100", headers=rahul))["items"]
    assert next(x for x in rows if x["id"] == aid)["last_round"]["setup"] == "tested"


def test_test_upload_and_speed_test_R1(c):
    ch = login(c, "arjun@demo.test")
    webm = b"\x1a\x45\xdf\xa3" + b"\x00" * 4000
    r = j(c.post("/api/syscheck/upload-test", headers=ch, content_type="multipart/form-data", data={"file": (io.BytesIO(webm), "t.webm")}))["data"]
    assert r["format"] == "webm" and r["bytes"] == len(webm)
    mp4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 4000
    assert j(c.post("/api/syscheck/upload-test", headers=ch, content_type="multipart/form-data", data={"file": (io.BytesIO(mp4), "t.mp4")}))["data"]["format"] == "mp4"
    assert c.post("/api/syscheck/upload-test", headers=ch, content_type="multipart/form-data", data={"file": (io.BytesIO(b"x" * 500), "t.bin")}).status_code == 400
    assert c.post("/api/syscheck/upload-test", headers=ch, content_type="multipart/form-data", data={"file": (io.BytesIO(b""), "t.webm")}).status_code == 400
    assert len(c.get("/api/syscheck/ping?bytes=1000", headers=ch).data) == 1000
    assert len(c.get("/api/syscheck/ping?bytes=999999999", headers=ch).data) == 2 * 1024 * 1024   # capped
    assert j(c.post("/api/syscheck/ping", headers=ch, data=b"y" * 5000, content_type="application/octet-stream"))["data"]["bytes"] == 5000
    assert c.get("/api/syscheck/ping").status_code == 401


def test_setup_test_without_a_round_and_home_page_R1(c):
    ch = login(c, "meera@demo.test")
    req = j(c.get("/api/syscheck/requirements", headers=ch))["data"]
    assert req["mode"] == "test" and "instructions" not in req and len(req["steps"]) == 11
    j(c.post("/api/syscheck", headers=ch, json={"steps": all_pass(req)}))
    home = j(c.get("/api/me", headers=ch))["data"]
    assert home["setup_tested"] is True
    assert home["invites"] and home["invites"][0]["instructions"]          # short instructions next to each round


def test_report_shows_the_check_R1(c):
    job, aid, ch = new_candidate(c, "report.cand@mail.test", "Report Cand")
    att = invite(c, aid, "ai_interview")
    req = steps_of(c, att, ch)
    steps = {**all_pass(req), "internet": {"status": "warn", "detail": "weak · 0.8 Mbps up"}}
    j(c.post("/api/syscheck", headers=ch, json={"attempt_id": att, "steps": steps, "instructions_read": True,
                                                 "device": {"camera": "FaceTime HD", "mic": "MacBook mic", "browser": "Google Chrome 130"}}))
    j(c.post(f"/api/rounds/{att}/consent", headers=ch, json={}))
    j(c.post(f"/api/rounds/{att}/start", headers=ch))
    for _ in range(8):
        if j(c.post(f"/api/rounds/{att}/turn", headers=ch, json={"answer": "A detailed answer about Django and SQL " * 8}))["data"]["done"]:
            break
    else:
        j(c.post(f"/api/rounds/{att}/finish", headers=ch, json={"reason": "ended_early"}))
    rahul = login(c, "rahul@acme.test")
    v = j(c.get(f"/api/reports/by-attempt/{att}", headers=rahul))["data"]
    setup = v.get("setup") or (v.get("report") or {}).get("setup")
    assert setup and setup["state"] == "tested" and "Internet weak" in setup["text"] and "Microphone OK" in setup["text"]
    assert setup["device"]["browser"] == "Google Chrome 130"


# ---------------------------------------------------------------- R3: instructions

def test_instructions_follow_the_round_and_company_text_R3(c):
    admin = login(c, "admin@acme.test")
    assert c.put("/api/company/settings", headers=admin, json={"scope": "company", "key": "instructions.extra", "value": "x" * 2001}).status_code == 400
    j(c.put("/api/company/settings", headers=admin, json={"scope": "company", "key": "instructions.extra", "value": "Business casual, please. A notepad is allowed."}))
    job, aid, ch = new_candidate(c, "ins.cand@mail.test", "Ins Cand")
    att = invite(c, aid, "mcq")
    ins = steps_of(c, att, ch)["instructions"]
    text = " ".join(" ".join(s["items"]) for s in ins["sections"])
    assert "10 questions in 20 minutes" in text and "laptop or desktop" in text and "Copying and pasting" in text
    assert ins["extra"].startswith("Business casual")
    pdf = c.get(f"/api/syscheck/instructions/{att}/pdf", headers=ch)
    assert pdf.status_code == 200 and pdf.data[:4] == b"%PDF"
    assert c.get(f"/api/syscheck/instructions/{att}/pdf", headers=login(c, "meera@demo.test")).status_code == 403
    att2 = invite(c, aid, "f2f_isha")
    ins2 = steps_of(c, att2, ch)["instructions"]
    t2 = " ".join(" ".join(s["items"]) for s in ins2["sections"])
    assert "live video call" in t2 and "interviewer steps out" in t2 and "recorded" in t2
    j(c.put("/api/company/settings", headers=admin, json={"scope": "company", "key": "instructions.extra", "reset": True}))


# ---------------------------------------------------------------- R4: Ask Hira

def ask(c, h, q, page=None):
    return j(c.post("/api/assistant/ask", headers=h, json={"q": q, "page": page or {}}))["data"]


def test_ask_hira_answers_from_live_data_R4(c):
    rahul = login(c, "rahul@acme.test")
    out = ask(c, rahul, "Which jobs are open?")
    assert out["intent"] == "open_jobs" and {"Senior Python Developer", "React Frontend Engineer"} <= {i["label"] for i in out["items"]}
    assert all(i["link"].startswith("/app/jobs/") for i in out["items"])
    py = jobs(c, rahul)["Senior Python Developer"]
    st = ask(c, rahul, "What's the status of this job?", {"job_id": py["id"]})
    assert st["intent"] == "job_status" and "Senior Python Developer is live" in st["text"] and st["job_id"] == py["id"]
    st2 = ask(c, rahul, "status of the react frontend job")
    assert st2["job_id"] == jobs(c, rahul)["React Frontend Engineer"]["id"]
    nojobs = ask(c, rahul, "Which jobs have no candidates?")
    assert nojobs["intent"] == "jobs_no_candidates"
    assert ask(c, rahul, "Who is waiting for review?")["intent"] == "pending_reviews"
    assert ask(c, rahul, "who scored above 70%?")["intent"] == "score_above"
    assert ask(c, rahul, "who is in the final round?")["intent"] == "final_round"
    sh = ask(c, rahul, "show candidates who are shortlisted")
    assert sh["intent"] == "stage"
    who = ask(c, rahul, "Show Arjun's results")
    assert who["intent"] == "candidate" and any(i["label"] == "Arjun Mehta" for i in who["items"])
    dunno = ask(c, rahul, "What's the weather like?")
    assert dunno["intent"] == "help" and "don't know" in dunno["text"] and dunno["items"][0]["ask"]
    hist = j(c.get("/api/assistant/history", headers=rahul))["data"]
    assert len(hist["messages"]) >= 2 and hist["messages"][-1]["role"] == "hira" and hist["examples"]
    j(c.delete("/api/assistant/history", headers=rahul))
    assert j(c.get("/api/assistant/history", headers=rahul))["data"]["messages"] == []
    assert c.post("/api/assistant/ask", headers=rahul, json={"q": ""}).status_code == 400
    assert c.post("/api/assistant/ask", headers=login(c, "arjun@demo.test"), json={"q": "Which jobs are open?"}).status_code == 403


def test_ask_hira_suggests_candidates_for_a_job_R4(c, app):
    from extensions import db
    from models import CandidateProfile, User
    with app.app_context():  # a Disha candidate whose profile is open to everyone, with matching skills
        u = User.query.filter_by(email="karan@demo.test").first()
        p = CandidateProfile.query.filter_by(user_id=u.id).first()
        p.visibility = "everyone"
        db.session.commit()
    rahul = login(c, "rahul@acme.test")
    fe = jobs(c, rahul)["React Frontend Engineer"]
    out = ask(c, rahul, "Which candidates should I add to this job?", {"job_id": fe["id"]})
    assert out["intent"] == "suggest"
    names = [i["label"] for i in out["items"]]
    assert "Meera Iyer" not in names                          # already on the job
    assert all("match" in i["sub"] for i in out["items"]) and all(i["pick"]["user_id"] for i in out["items"])


def test_ask_hira_never_shows_another_company_R4(c, app):
    from extensions import db
    from models import Company, RoleAssignment, User
    from services.perms import hash_password
    with app.app_context():
        co = Company(name="Other Co", domain="other.test", plan="employer", status="active")
        db.session.add(co)
        db.session.flush()
        u = User(email="boss@other.test", name="Other Boss", kind="staff", company_id=co.id, password_hash=hash_password(PW))
        db.session.add(u)
        db.session.flush()
        db.session.add(RoleAssignment(user_id=u.id, company_id=co.id, role="company_admin", scope_type="company", scope_id=co.id))
        db.session.commit()
    other = login(c, "boss@other.test")
    out = ask(c, other, "Which jobs are open?")
    assert out["items"] == [] and "no open jobs" in out["text"]
    who = ask(c, other, "Show Arjun's results")
    assert who["items"] == []
    s = j(c.get("/api/candidates/search?q=arjun", headers=other))["data"]["items"]
    assert all(x["source"] == "disha" for x in s)            # Acme's candidates aren't Other Co's


def test_ask_hira_respects_the_role_R4(c):
    vikram = login(c, "vikram@acme.test")                   # hiring manager on one job only
    names = {i["label"] for i in ask(c, vikram, "Which jobs are open?")["items"]}
    assert "React Frontend Engineer" not in names


# ---------------------------------------------------------------- R5: choosing an existing candidate

def test_search_shows_pool_and_open_disha_profiles_R5(c, app):
    from extensions import db
    from models import CandidateProfile, User
    rahul = login(c, "rahul@acme.test")
    py = jobs(c, rahul)["Senior Python Developer"]
    items = j(c.get(f"/api/candidates/search?q=arj&job_id={py['id']}", headers=rahul))["data"]["items"]
    arjun = next(x for x in items if x["name"] == "Arjun Mehta")
    assert arjun["source"] == "company" and arjun["email"] == "arjun@demo.test" and arjun["in_this_job"]["stage"]
    assert arjun["jobs"] and arjun["jobs"][0]["title"] == "Senior Python Developer"
    by_mail = j(c.get("/api/candidates/search?q=arjun@demo", headers=rahul))["data"]["items"]
    assert by_mail and by_mail[0]["user_id"] == arjun["user_id"]
    # a Disha candidate who keeps their profile to companies they applied to doesn't appear
    with app.app_context():
        u = User(email="hidden.disha@mail.test", name="Hidden Dishaperson", kind="candidate", password_hash="x")
        v = User(email="open.disha@mail.test", name="Open Dishaperson", kind="candidate", password_hash="x")
        db.session.add_all([u, v])
        db.session.flush()
        db.session.add_all([CandidateProfile(user_id=u.id, visibility="applied", skills=[{"name": "Python", "level": 3}]),
                            CandidateProfile(user_id=v.id, visibility="everyone", headline="Python dev", skills=[{"name": "Python", "level": 4}])])
        db.session.commit()
    items = j(c.get("/api/candidates/search?q=dishaperson", headers=rahul))["data"]["items"]
    assert [x["name"] for x in items] == ["Open Dishaperson"]
    assert items[0]["email"] is None and items[0]["source"] == "disha" and items[0]["skills"] == ["Python"]  # no email until added
    assert j(c.get("/api/candidates/search?q=a", headers=rahul))["data"]["items"] == []    # needs 2 letters
    assert c.get("/api/candidates/search?q=arjun", headers=login(c, "arjun@demo.test")).status_code == 403


def test_pick_an_existing_candidate_R5(c, app):
    from models import Application, CandidateProfile, Notification, User
    rahul = login(c, "rahul@acme.test")
    js = jobs(c, rahul)
    py, fe = js["Senior Python Developer"], js["React Frontend Engineer"]
    open_id = next(x for x in j(c.get("/api/candidates/search?q=open dishaperson", headers=rahul))["data"]["items"])["user_id"]
    # a Disha candidate needs a job
    r = j(c.post("/api/candidates", headers=rahul, json={"candidates": [{"user_id": open_id}]}))["data"]["results"][0]
    assert r["status"] == "invalid" and "Pick a job" in r["error"]
    r = j(c.post("/api/candidates", headers=rahul, json={"candidates": [{"user_id": open_id}], "job_id": py["id"]}))["data"]["results"][0]
    assert r["status"] == "added" and r["application_id"] and r["email"] == "open.disha@mail.test"
    with app.app_context():
        a = Application.query.get(r["application_id"])
        p = CandidateProfile.query.filter_by(user_id=open_id).first()
        assert a.source == "picked" and p.source_company_id is None       # their profile isn't claimed
        assert Notification.query.filter_by(user_id=open_id, title="You've been added to Senior Python Developer").first().body.count("withdraw")
    # now on the job: the dropdown greys them out, and adding again says why
    items = j(c.get(f"/api/candidates/search?q=open dishaperson&job_id={py['id']}", headers=rahul))["data"]["items"]
    assert items[0]["in_this_job"]["stage"] == "applied" and items[0]["source"] == "company" and items[0]["email"]
    r = j(c.post("/api/candidates", headers=rahul, json={"candidates": [{"user_id": open_id}], "job_id": py["id"]}))["data"]["results"][0]
    assert r["status"] == "duplicate" and r["reason"] == "in_job"
    # a pool candidate picked for another job keeps one account
    arjun = uid(c, "arjun@demo.test")
    r = j(c.post("/api/candidates", headers=rahul, json={"candidates": [{"user_id": arjun}], "job_id": fe["id"]}))["data"]["results"][0]
    assert r["status"] == "added"
    with app.app_context():
        assert User.query.filter_by(email="arjun@demo.test").count() == 1
    # a hidden profile can't be picked by guessing its id
    with app.app_context():
        hid = User.query.filter_by(email="hidden.disha@mail.test").first().id
    r = j(c.post("/api/candidates", headers=rahul, json={"candidates": [{"user_id": hid}], "job_id": py["id"]}))["data"]["results"][0]
    assert r["status"] == "invalid" and "isn't open" in r["error"]


def test_check_says_in_job_and_possible_duplicates_R5(c):
    rahul = login(c, "rahul@acme.test")
    py = jobs(c, rahul)["Senior Python Developer"]
    r = j(c.get(f"/api/candidates/check?email=arjun@demo.test&job_id={py['id']}", headers=rahul))["data"]
    assert r["existing"]["kind"] == "in_company" and r["existing"]["in_job"]["job"] == "Senior Python Developer"
    r = j(c.get("/api/candidates/check?name=arjun mehta&email=arjun.m@other.test", headers=rahul))["data"]
    assert r["similar"] and r["similar"][0]["email"] == "arjun@demo.test"     # same name, different email
    r = j(c.get("/api/candidates/check?name=Arjun Mehta&email=arjun@demo.test", headers=rahul))["data"]
    assert r["similar"] == []


def test_bulk_preview_marks_new_existing_and_in_job_R5(c):
    rahul = login(c, "rahul@acme.test")
    py = jobs(c, rahul)["Senior Python Developer"]
    rows = [{"name": "Brand New", "email": "brand.new@mail.test"}, {"name": "Meera Iyer", "email": "meera@demo.test"},
            {"name": "Arjun Mehta", "email": "arjun@demo.test"}]
    out = j(c.post("/api/candidates", headers=rahul, json={"candidates": rows, "job_id": py["id"], "dry_run": True}))["data"]
    st = out["results"]
    assert st[0]["status"] == "ok" and st[0]["kind"] == "new"
    assert st[1]["status"] == "ok" and st[1]["kind"] == "in_pool"            # Meera applied to another Acme job
    assert st[2]["status"] == "duplicate" and st[2]["reason"] == "in_job"


# ---------------------------------------------------------------- F2F bug report

def live(c, email, name):
    job, aid, ch = new_candidate(c, email, name)
    att = invite(c, aid, "f2f_isha")
    p = login(c, "priya@acme.test")
    system_check(c, att, ch)
    j(c.post(f"/api/rounds/{att}/consent", headers=ch, json={}))
    return att, ch, p


def test_interviewer_check_is_saved_F2F_001_003(c):
    att, ch, p = live(c, "iv.check@mail.test", "Iv Check")
    out = system_check(c, att, p, role="interviewer")
    assert out["passed"]
    rahul = login(c, "rahul@acme.test")
    v = j(c.get(f"/api/reports/by-attempt/{att}", headers=rahul))["data"]
    # before the report exists the attempt view still works; the check is kept on the attempt
    assert c.get(f"/api/syscheck/requirements?attempt={att}&role=interviewer", headers=p).get_json()["data"]["passed_recently"] is True
    assert v is not None
    # the candidate can't run the interviewer's check
    assert c.get(f"/api/syscheck/requirements?attempt={att}&role=interviewer", headers=ch).status_code == 403


def test_partial_captions_and_device_lost_signals_F2F_007(c):
    att, ch, p = live(c, "cap.cand@mail.test", "Cap Cand")
    cur = j(c.get(f"/api/call/{att}", headers=p))["data"]["cursor"]
    j(c.post(f"/api/call/{att}/signal", headers=ch, json={"kind": "partial", "payload": {"text": "I built the payments " + "x" * 900}}))
    j(c.post(f"/api/call/{att}/signal", headers=ch, json={"kind": "device", "payload": {"captions": "azure", "evil": 1}}))
    j(c.post(f"/api/call/{att}/signal", headers=ch, json={"kind": "devlost", "payload": {"cam": True, "mic": 0, "x": "y"}}))
    assert c.post(f"/api/call/{att}/signal", headers=p, json={"kind": "partial", "payload": {"text": "hi"}}).status_code == 403
    sig = j(c.get(f"/api/call/{att}/signal?after={cur}", headers=p))["data"]["signals"]
    part = next(s for s in sig if s["kind"] == "partial")
    assert part["payload"]["text"].startswith("I built the payments") and len(part["payload"]["text"]) == 500
    assert next(s for s in sig if s["kind"] == "device")["payload"] == {"captions": "azure"}
    assert next(s for s in sig if s["kind"] == "devlost")["payload"] == {"cam": True, "mic": False}


def test_isha_hears_the_interviewer_ask_a_plan_question_F2F_005_006(c):
    att, ch, p = live(c, "said.cand@mail.test", "Said Cand")
    room = j(c.get(f"/api/isha/{att}", headers=p))["data"]
    areas = room["brief"]["areas"]
    assert room["state"]["remaining"][0]["area"] == areas[0]["area"]       # the Next question card: first in the plan
    j(c.post(f"/api/isha/{att}/start", headers=p))
    target = areas[2]
    # filler talk is kept in the transcript but doesn't move the plan
    st = j(c.post(f"/api/isha/{att}/said", headers=p, json={"text": "Great, thanks for joining today."}))["data"]
    assert st["moved"] is None
    # reading a plan question out loud, with filler words, moves Isha to it
    st = j(c.post(f"/api/isha/{att}/said", headers=p, json={"text": "Okay so, " + target["q"].lower()}))["data"]
    assert st["moved"]["area"] == target["area"] and st["state"]["current"]["area"] == target["area"]
    assert st["state"]["areas_log"][-1]["auto"] is True
    assert target["area"] not in [a["area"] for a in st["state"]["remaining"]]
    # wrong guess: undo
    back = j(c.post(f"/api/isha/{att}/undo-move", headers=p))["data"]
    assert target["area"] in [a["area"] for a in back["remaining"]]
    assert c.post(f"/api/isha/{att}/undo-move", headers=p).status_code == 400
    # the candidate's answer goes to the question that was asked
    j(c.post(f"/api/isha/{att}/ask", headers=p, json={"q": areas[0]["q"], "area": areas[0]["area"]}))
    j(c.post(f"/api/isha/{att}/sentence", headers=p, json={"text": "I designed the API with Django REST framework."}))
    st = j(c.post(f"/api/isha/{att}/said", headers=p, json={"text": "Interesting, tell me more."}))["data"]
    entry = st["state"]["areas_log"][-1]
    assert entry["area"] == areas[0]["area"] and entry["sentences"] and entry["said"][0]["t"] == "Interesting, tell me more."
    assert entry["said"][0]["after"] == 1
    # the candidate can't post as the interviewer
    assert c.post(f"/api/isha/{att}/said", headers=ch, json={"text": "x"}).status_code in (403, 409)


def test_match_question_needs_most_of_the_words_F2F_005():
    from routes.isha import match_question
    areas = [{"area": "Python", "q": "Walk me through a Python service you built and how you tested it."},
             {"area": "SQL", "q": "How would you find slow queries in a MySQL database?"}]
    assert match_question("walk me through a python service you built, and how did you test it", areas)["area"] == "Python"
    assert match_question("so how would you find the slow queries in mysql", areas)["area"] == "SQL"
    assert match_question("python is nice", areas) is None
    assert match_question("tell me about yourself", areas) is None
    assert match_question("walk me through a python service you built and how you tested it", areas, current_area="Python") is None


def test_version_V02_00_05(c):
    assert c.get("/api/health").get_json()["version"] == "V02.00.05"
