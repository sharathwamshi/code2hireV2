"""Regression tests for the beta bug list (BETACODE2-1 to 48). Each test names the tickets it covers.
Run: pytest -q  (from backend/)."""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("C2H_NO_AUTOCREATE", "1")
if os.environ.get("C2H_TEST_DATABASE_URL"):  # e.g. a throwaway MariaDB/MySQL database: the suite resets it
    os.environ["DATABASE_URL"] = os.environ["C2H_TEST_DATABASE_URL"]
elif "DATABASE_URL" not in os.environ or not os.environ["DATABASE_URL"].startswith("sqlite"):
    import tempfile
    os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "fixes.db")
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["AZURE_SPEECH_KEY"] = ""

from tests.syscheck_helper import system_check  # noqa: E402
import seed  # noqa: E402
from app import create_app  # noqa: E402

PW = seed.PW


@pytest.fixture(scope="module")
def app():
    seed.run(reset=True)
    return create_app({"TESTING": True})


@pytest.fixture(scope="module")
def c(app):
    return app.test_client()


def login(c, email, pw=PW, ip="10.0.0.1"):
    r = c.post("/api/auth/login", json={"email": email, "password": pw}, headers={"X-Forwarded-For": ip})
    assert r.status_code == 200, r.get_json()
    return {"Authorization": "Bearer " + r.get_json()["data"]["token"]}


def j(r, code=200):
    assert r.status_code == code, (r.status_code, r.get_json())
    return r.get_json()


def python_job(c, h):
    return next(x for x in j(c.get("/api/jobs?status=live&size=100", headers=h))["items"] if x["title"] == "Senior Python Developer")


# ---------------------------------------------------------------- security and sign-in

def test_login_lockout_after_5_failures_BETACODE2_2(c):
    ip = {"X-Forwarded-For": "10.9.9.9"}
    for _ in range(5):
        r = c.post("/api/auth/login", json={"email": "vikram@acme.test", "password": "wrong-pass-1"}, headers=ip)
        assert r.status_code in (401, 429)
    # locked now, even with the right password, and the message doesn't reveal whether the account exists
    r = c.post("/api/auth/login", json={"email": "vikram@acme.test", "password": PW}, headers=ip)
    assert r.status_code == 429 and "wait" in r.get_json()["error"]
    r2 = c.post("/api/auth/login", json={"email": "nobody-here@acme.test", "password": "x"}, headers={"X-Forwarded-For": "10.9.9.10"})
    assert r2.status_code == 401
    # another account from another address is unaffected
    login(c, "anita@acme.test", ip="10.9.9.11")
    # failures are audited
    from models import AuditLog
    with c.application.app_context():
        assert AuditLog.query.filter_by(action="auth.login_failed").count() >= 5


def test_login_needs_both_fields(c):
    r = c.post("/api/auth/login", json={"email": "", "password": ""}, headers={"X-Forwarded-For": "10.1.1.1"})
    assert r.status_code == 400 and set(r.get_json()["fields"]) == {"email", "password"}


@pytest.mark.parametrize("bad", ["test@123", "sonu@123", "harish@1234", "sakshi@com", "cypress,playright", "a b@c.com", "x@y.c", "@x.com", "plain"])
def test_signup_rejects_invalid_email_BETACODE2_1(c, bad):
    r = c.post("/api/auth/signup", json={"email": bad, "password": "Abcdef12", "name": "Test User"}, headers={"X-Forwarded-For": f"10.2.{len(bad)}.1"})
    assert r.status_code == 400 and r.get_json()["fields"]["email"].startswith("Enter a valid email")


def test_signup_password_rules(c):
    h = {"X-Forwarded-For": "10.3.3.3"}
    for pw, msg in (("short1", "8 characters"), ("onlyletters", "number"), ("12345678", "letters"), ("Password123", "harder")):
        r = c.post("/api/auth/signup", json={"email": "pwtest@mail.test", "password": pw, "name": "Pw Test"}, headers=h)
        assert r.status_code == 400 and msg in r.get_json()["fields"]["password"], (pw, r.get_json())
    r = c.post("/api/auth/signup", json={"email": "pwtest@mail.test", "password": "pwtest2026x", "name": "Pw Test"}, headers=h)
    assert r.status_code == 400  # contains the email name
    j(c.post("/api/auth/signup", json={"email": "pwtest@mail.test", "password": "Green7Valley", "name": "Pw Test"}, headers=h))


def test_integration_test_uses_typed_key_BETACODE2_24_22(c):
    sa = login(c, "super@code2hire.ai")
    r = c.post("/api/platform/integrations/test", headers=sa, json={"which": "anthropic", "key": "sk-ant-fake-key-123"})
    body = r.get_json()
    assert r.status_code == 400 and "typed key …-123" in body["error"]
    assert "{" not in body["error"]  # a sentence, never raw JSON
    r = c.post("/api/platform/integrations/test", headers=sa, json={"which": "azure", "key": "fakeazurekey99", "region": "bad region!"})
    assert r.status_code == 400 and "region" in r.get_json()["error"]


# ---------------------------------------------------------------- add candidate and links

def test_add_candidate_validation_BETACODE2_44_43_36_46(c):
    h = login(c, "rahul@acme.test")
    r = j(c.post("/api/candidates", headers=h, json={"name": "Srusti Gowda", "email": "srustipatil41@l", "phone": "+918867BHBHSBHB"}))["data"]
    row = r["results"][0]
    assert r["added"] == 0 and row["status"] == "invalid"
    assert set(row["fields"]) >= {"email", "phone"}
    # a job selected doesn't skip the checks
    job = python_job(c, h)
    r = j(c.post("/api/candidates", headers=h, json={"job_id": job["id"], "candidates": [{"name": "X", "email": "nope"}]}))["data"]
    assert r["invalid"] == 1 and r["results"][0]["fields"]["name"] and r["results"][0]["fields"]["email"]
    # empty name is required
    r = j(c.post("/api/candidates", headers=h, json={"email": "noname@mail.test"}))["data"]
    assert r["results"][0]["fields"]["name"] == "This is required."


def test_add_candidate_preview_duplicates_and_phone_BETACODE2_47(c):
    h = login(c, "rahul@acme.test")
    rows = [{"name": "Asha Rao", "email": "asha.rao@mail.test", "phone": "98450 00001", "skills": ["Python", "python", "SQL"]},
            {"name": "Vikas Nair", "email": "vikas.nair@mail.test", "phone": ""},
            {"name": "Asha Again", "email": "ASHA.RAO@mail.test"},
            {"name": "Bad Mail", "email": "bad@mail"}]
    pre = j(c.post("/api/candidates", headers=h, json={"candidates": rows, "dry_run": True}))["data"]
    assert pre["dry_run"] and pre["ready"] == 2 and pre["invalid"] == 1 and pre["duplicates"] == 1
    assert "row 1" in pre["results"][2]["error"]
    # nothing was saved by the preview
    assert not j(c.get("/api/candidates?q=asha.rao", headers=h))["items"]
    res = j(c.post("/api/candidates", headers=h, json={"candidates": rows[:2]}))["data"]
    assert res["added"] == 2
    a = res["results"][0]
    assert a["phone"] == "+919845000001" and a["state"] == "not_sent" and a["link"].startswith("/welcome/")
    # adding the same email again (no job) is a duplicate, not a second account
    again = j(c.post("/api/candidates", headers=h, json={"name": "Asha Rao", "email": "asha.rao@mail.test"}))["data"]
    assert again["added"] == 0 and again["duplicates"] == 1
    # same phone as someone in the pool
    ph = j(c.post("/api/candidates", headers=h, json={"name": "Other Person", "email": "other.p@mail.test", "phone": "+91 98450 00001"}))["data"]
    assert ph["results"][0]["status"] == "duplicate" and "phone" in ph["results"][0]["fields"]
    # check-while-typing
    chk = j(c.get("/api/candidates/check?email=asha.rao@mail.test", headers=h))["data"]["existing"]
    assert chk["kind"] == "in_company" and chk["name"] == "Asha Rao"
    assert j(c.get("/api/candidates/check?email=free.person@mail.test", headers=h))["data"]["existing"] is None
    # "Sent" only after sharing
    j(c.post(f"/api/candidates/{a['user_id']}/link/shared", headers=h, json={"via": "copy"}))
    row = j(c.get("/api/candidates?q=asha.rao", headers=h))["items"][0]
    assert row["state"] == "sent" and row["link_shared_via"] == "copy"


def test_add_candidate_with_job_puts_pool_member_on_job(c):
    h = login(c, "rahul@acme.test")
    job = python_job(c, h)
    r = j(c.post("/api/candidates", headers=h, json={"name": "Vikas Nair", "email": "vikas.nair@mail.test", "job_id": job["id"]}))["data"]
    assert r["added"] == 1 and r["results"][0]["application_id"]
    r2 = j(c.post("/api/candidates", headers=h, json={"name": "Vikas Nair", "email": "vikas.nair@mail.test", "job_id": job["id"]}))["data"]
    assert r2["duplicates"] == 1  # already on this job


def test_parse_list_file_and_template(c):
    import io
    h = login(c, "rahul@acme.test")
    t = c.get("/api/candidates/template.csv", headers=h)
    assert t.status_code == 200 and b"Name,Email,Phone" in t.data
    csv = "Name,Email,Mobile,Key skills\nRavi Kumar,ravi@mail.test,9845000002,Go; Docker\n".encode()
    r = j(c.post("/api/candidates/parse-file", headers=h, data={"file": (io.BytesIO(csv), "list.csv")}, content_type="multipart/form-data"))["data"]
    assert r["rows"][0] == {"name": "Ravi Kumar", "email": "ravi@mail.test", "phone": "9845000002", "skills": ["Go", "Docker"]}
    bad = c.post("/api/candidates/parse-file", headers=h, data={"file": (io.BytesIO(b"x"), "list.xls")}, content_type="multipart/form-data")
    assert bad.status_code == 400 and "XLSX" in bad.get_json()["error"]


def test_parse_resume_fills_fields(c):
    import io
    h = login(c, "rahul@acme.test")
    text = b"MEERA PILLAI\nmeera.pillai@mail.test | +91 98450 11111\nBengaluru\n6 years building Python and Django services with SQL and AWS."
    r = j(c.post("/api/candidates/parse-resume", headers=h, data={"file": (io.BytesIO(text), "cv.txt")}, content_type="multipart/form-data"))["data"]
    assert r["email"] == "meera.pillai@mail.test" and r["phone"] == "+919845011111" and r["name"] == "Meera Pillai"
    assert "Python" in r["skills"] and r["experience_years"] == 6


def test_pool_to_job_only_takes_pool_members(c):
    h = login(c, "rahul@acme.test")
    job = python_job(c, h)
    from models import User
    with c.application.app_context():
        staff_id = User.query.filter_by(email="priya@acme.test").first().id
    r = j(c.post("/api/talent-pool/add-to-job", headers=h, json={"job_id": job["id"], "user_ids": [staff_id, 999999]}))["data"]
    assert r["added"] == 0


# ---------------------------------------------------------------- jobs

def test_job_rules_BETACODE2_18_28(c):
    h = login(c, "priya@acme.test")
    for bad, field in (({"title": "Neg", "hires_target": -5}, "hires_target"), ({"title": "Band", "salary_min": 5000000, "salary_max": 1000000}, "salary_min"),
                       ({"title": ""}, "title"), ({"title": "Old", "deadline": "2020-01-01"}, "deadline"), ({"title": "Half", "hires_target": 2.5}, "hires_target")):
        r = c.post("/api/jobs", headers=h, json=bad)
        assert r.status_code == 400 and field in r.get_json()["fields"], (bad, r.get_json())
    job = j(c.post("/api/jobs", headers=h, json={"title": "QA Engineer", "hires_target": 2, "salary_min": 600000, "salary_max": 900000}))["data"]
    r = c.patch(f"/api/jobs/{job['id']}", headers=h, json={"salary_min": 1000000})
    assert r.status_code == 400 and "salary_min" in r.get_json()["fields"]  # checked against the saved maximum
    assert c.patch(f"/api/jobs/{job['id']}", headers=h, json={"hires_target": 0}).status_code == 400
    assert c.patch(f"/api/jobs/{job['id']}", headers=h, json={"rounds": []}).status_code == 400


def test_duplicate_copy_naming_BETACODE2_35(c):
    h = login(c, "priya@acme.test")
    base = j(c.post("/api/jobs", headers=h, json={"title": "Manual Testing"}))["data"]
    c1 = j(c.post(f"/api/jobs/{base['id']}/duplicate", headers=h))["data"]
    c2 = j(c.post(f"/api/jobs/{c1['id']}/duplicate", headers=h))["data"]
    c3 = j(c.post(f"/api/jobs/{c2['id']}/duplicate", headers=h))["data"]
    assert [c1["title"], c2["title"], c3["title"]] == ["Manual Testing (copy)", "Manual Testing (copy 2)", "Manual Testing (copy 3)"]


# ---------------------------------------------------------------- scheduling, rounds, timer

def _candidate_on_python_job(c, h, email, name):
    job = python_job(c, h)
    r = j(c.post("/api/candidates", headers=h, json={"name": name, "email": email, "job_id": job["id"]}))["data"]["results"][0]
    return job, r["application_id"], r["user_id"], r["link"].split("/")[-1]


def test_timezone_and_join_window_BETACODE2_6_8(c):
    h = login(c, "rahul@acme.test")
    job, aid, uid, token = _candidate_on_python_job(c, h, "tz.cand@mail.test", "Sneha Rao")
    priya_id = j(c.get("/api/auth/me", headers=login(c, "priya@acme.test")))["data"]["user"]["id"]
    f2f = next(i for i, r in enumerate(job["rounds"]) if r["type"] in ("f2f_isha", "f2f_human"))
    # 12:36 pm IST, sent the way the web app sends it (with the timezone)
    when_ist = (datetime.now(timezone(timedelta(hours=5, minutes=30))) + timedelta(hours=3)).replace(second=0, microsecond=0)
    j(c.post(f"/api/applications/{aid}/invite", headers=h, json={"round_index": f2f, "interviewer_id": priya_id, "scheduled_at": when_ist.isoformat()}))
    op = j(c.post(f"/api/auth/invite/{token}/open"))["data"]
    ch = {"Authorization": "Bearer " + op["token"]}
    inv = next(i for i in j(c.get("/api/me", headers=ch))["data"]["invites"] if i["type"].startswith("f2f"))
    got = datetime.fromisoformat(inv["scheduled_at"].replace("Z", "+00:00"))
    assert got == when_ist  # same instant: no 5 h 30 m shift
    assert inv["can_join"] is False and inv["opens_at"]
    opens = datetime.fromisoformat(inv["opens_at"].replace("Z", "+00:00"))
    assert opens == when_ist - timedelta(minutes=15)
    info = j(c.get(f"/api/call/{inv['attempt_id']}", headers=ch))["data"]
    assert info["can_join"] is False and info["opens_at"] == inv["opens_at"]
    # the interviewer's inbox gets the same instant, as ISO, formatted in the browser
    today = j(c.get("/api/inbox/today", headers=login(c, "priya@acme.test")))["data"]["cards"]
    card = next(x for x in today if x["kind"] == "interview" and "Sneha Rao" in x["title"])
    assert datetime.fromisoformat(card["at"].replace("Z", "+00:00")) == when_ist
    # a time in the past is refused
    r = c.post(f"/api/applications/{aid}/invite", headers=h, json={"round_index": f2f, "interviewer_id": priya_id,
                                                                      "scheduled_at": "2020-01-01T10:00:00+05:30"})
    assert r.status_code in (400, 409)


def test_no_duplicate_rounds_BETACODE2_7(c):
    h = login(c, "rahul@acme.test")
    job, aid, uid, _ = _candidate_on_python_job(c, h, "dup.round@mail.test", "Dup Round")
    from models import Company, RoundAttempt
    with c.application.app_context():
        before = Company.query.filter_by(name="Acme Technologies").first().credits_used
    for _ in range(3):
        j(c.post(f"/api/jobs/{job['id']}/bulk", headers=h, json={"ids": [aid], "action": "invite", "round_index": 0}))
    with c.application.app_context():
        atts = RoundAttempt.query.filter_by(application_id=aid, round_index=0).all()
        after = Company.query.filter_by(name="Acme Technologies").first().credits_used
    assert len(atts) == 1  # one live attempt, not three
    from services.pipeline import CREDIT_COST
    assert after - before == CREDIT_COST.get("mcq", 0)  # charged once


def test_timer_uses_server_clock_and_closes_overdue_BETACODE2_14(c):
    h = login(c, "rahul@acme.test")
    job, aid, uid, token = _candidate_on_python_job(c, h, "timer.cand@mail.test", "Timer Cand")
    j(c.post(f"/api/applications/{aid}/invite", headers=h, json={"round_index": 0}))
    op = j(c.post(f"/api/auth/invite/{token}/open"))["data"]
    ch = {"Authorization": "Bearer " + op["token"]}
    att = next(i for i in j(c.get("/api/me", headers=ch))["data"]["invites"] if i["type"] == "mcq")["attempt_id"]
    system_check(c, att, ch)
    j(c.post(f"/api/rounds/{att}/consent", headers=ch, json={"checks": {"camera": True}}))
    room = j(c.post(f"/api/rounds/{att}/start", headers=ch))["data"]
    mins = room["config"]["mcq.minutes"]
    assert mins * 60 - 5 <= room["seconds_left"] <= mins * 60
    # pretend the laptop slept past the limit: the server closes the round on the next request
    from extensions import db
    from models import RoundAttempt
    with c.application.app_context():
        a = db.session.get(RoundAttempt, att)
        a.started_at = datetime.utcnow() - timedelta(minutes=mins, seconds=200)
        db.session.commit()
    st = j(c.get(f"/api/rounds/{att}/status", headers=ch))["data"]
    assert st["status"] == "completed"
    assert c.post(f"/api/rounds/{att}/answer", headers=ch, json={"qid": room["questions"][0]["id"], "choice": 0}).status_code in (403, 409)


def test_warning_count_and_snapshot_BETACODE2_4_3_48(c):
    h = login(c, "rahul@acme.test")
    job, aid, uid, token = _candidate_on_python_job(c, h, "face.cand@mail.test", "Face Cand")
    j(c.post(f"/api/applications/{aid}/invite", headers=h, json={"round_index": 0}))
    ch = {"Authorization": "Bearer " + j(c.post(f"/api/auth/invite/{token}/open"))["data"]["token"]}
    att = next(i for i in j(c.get("/api/me", headers=ch))["data"]["invites"] if i["type"] == "mcq")["attempt_id"]
    system_check(c, att, ch)
    j(c.post(f"/api/rounds/{att}/consent", headers=ch, json={}))
    j(c.post(f"/api/rounds/{att}/start", headers=ch))
    snap = "data:image/jpeg;base64," + "A" * 400
    e = j(c.post(f"/api/rounds/{att}/integrity", headers=ch, json={"type": "multi_face", "note": "2 people on camera", "snapshot": snap}))["data"]
    assert e["counted"] and e["warnings"] == 1 and (e["message"].startswith("Warning 1 of") or e["paused"])  # instant pause by default
    assert j(c.get(f"/api/rounds/{att}/status", headers=ch))["data"]["warnings"] == 1  # one number everywhere
    n = j(c.post(f"/api/rounds/{att}/integrity", headers=ch, json={"type": "face_check_unavailable"}))["data"]
    assert not n["counted"] and n["warnings"] == 1
    from extensions import db
    from models import RoundAttempt
    with c.application.app_context():
        shots = db.session.get(RoundAttempt, att).result.get("snapshots")
    assert shots and shots[0]["event"] == "multi_face"


def test_pause_time_is_not_counted(c):
    h = login(c, "rahul@acme.test")
    job, aid, uid, token = _candidate_on_python_job(c, h, "pause.cand@mail.test", "Pause Cand")
    j(c.post(f"/api/applications/{aid}/invite", headers=h, json={"round_index": 0}))
    ch = {"Authorization": "Bearer " + j(c.post(f"/api/auth/invite/{token}/open"))["data"]["token"]}
    att = next(i for i in j(c.get("/api/me", headers=ch))["data"]["invites"] if i["type"] == "mcq")["attempt_id"]
    system_check(c, att, ch)
    j(c.post(f"/api/rounds/{att}/consent", headers=ch, json={}))
    j(c.post(f"/api/rounds/{att}/start", headers=ch))
    for t in ("tab_switch", "tab_switch", "tab_switch"):
        c.post(f"/api/rounds/{att}/integrity", headers=ch, json={"type": t})
        import time as _t
        _t.sleep(0.01)
    from extensions import db
    from models import RoundAttempt
    with c.application.app_context():
        a = db.session.get(RoundAttempt, att)
        if a.status == "paused":
            res = dict(a.result)
            res["paused_at"] = (datetime.utcnow() - timedelta(hours=2)).isoformat()  # waited 2 h for the recruiter
            a.result = res
            db.session.commit()
            paused = True
        else:
            paused = False
    if paused:
        j(c.post(f"/api/rounds/{att}/resume", headers=h, json={"note": "ok"}))
        st = j(c.get(f"/api/rounds/{att}/status", headers=ch))["data"]
        assert st["status"] == "in_progress" and st["seconds_left"] > 60


# ---------------------------------------------------------------- reports, disputes, admin

def test_report_scale_and_formats_BETACODE2_12_29(c):
    admin = login(c, "admin@acme.test")
    j(c.put("/api/company/settings", headers=admin, json={"scope": "company", "key": "report.scale", "value": 10, "locked": False}))
    rows = j(c.get("/api/reports?size=5", headers=admin))["items"]
    if rows:
        assert rows[0]["scale"] == 10 and isinstance(rows[0]["warnings"], int)
        rep = j(c.get(f"/api/reports/{rows[0]['id']}", headers=admin))["data"]
        assert rep["scale"] == 10 and (rep["overall"] is None or rep["overall"] <= 5)  # stored out of 5, shown out of 10
    j(c.put("/api/company/settings", headers=admin, json={"scope": "company", "key": "report.scale", "value": 5, "locked": False}))


def test_pending_report_is_private_to_the_company(c):
    sa = login(c, "super@code2hire.ai")
    j(c.post("/api/platform/companies", headers=sa, json={"name": "Gamma Labs", "admin_email": "boss@gamma.test", "admin_name": "Gita Rao", "admin_password": "Gamma2026pass"}))
    other = login(c, "boss@gamma.test", "Gamma2026pass")
    from models import RoundAttempt
    with c.application.app_context():
        att = RoundAttempt.query.filter(RoundAttempt.application_id.isnot(None)).first()
    r = c.get(f"/api/reports/by-attempt/{att.id}", headers=other)
    assert r.status_code in (403, 404)


def test_onboard_company_required_fields_BETACODE2_32(c):
    sa = login(c, "super@code2hire.ai")
    r = c.post("/api/platform/companies", headers=sa, json={"name": "", "admin_email": "x@", "domain": "https://acme.com/"})
    f = r.get_json()["fields"]
    assert r.status_code == 400 and {"name", "admin_email", "admin_name", "domain"} <= set(f)
    r = c.post("/api/platform/companies", headers=sa, json={"name": "Gamma Labs", "admin_email": "new.boss@gamma.test", "admin_name": "New Boss"})
    assert r.status_code == 400 and "already exists" in r.get_json()["fields"]["name"]


def test_templates_crud_BETACODE2_26(c):
    sa = login(c, "super@code2hire.ai")
    assert c.post("/api/platform/templates", headers=sa, json={"name": "Test Typos", "rounds": []}).status_code == 400
    t = j(c.post("/api/platform/templates", headers=sa, json={"name": "Test Typos", "rounds": [{"type": "mcq"}]}))["data"]
    t = j(c.patch(f"/api/platform/templates/{t['id']}", headers=sa, json={"name": "Test Typo Fixed", "description": "x"}))["data"]
    assert t["name"] == "Test Typo Fixed" and t["updated_at"]
    d = j(c.post(f"/api/platform/templates/{t['id']}/duplicate", headers=sa))["data"]
    assert d["name"] == "Test Typo Fixed (copy)"
    j(c.patch(f"/api/platform/templates/{d['id']}", headers=sa, json={"archived": True}))
    rahul = login(c, "rahul@acme.test")
    names = [x["name"] for x in j(c.get("/api/templates", headers=rahul))["data"]]
    assert "Test Typo Fixed" in names and "Test Typo Fixed (copy)" not in names  # archived ones are hidden from companies
    j(c.delete(f"/api/platform/templates/{t['id']}", headers=sa))
    assert "Test Typo Fixed" not in [x["name"] for x in j(c.get("/api/templates", headers=rahul))["data"]]


def test_disputes_end_to_end_BETACODE2_31(c):
    """A candidate raises a dispute; the platform team sees it with a Review route and resolves it."""
    sa = login(c, "super@code2hire.ai")
    from extensions import db
    from models import Application, Report, RoundAttempt, User
    with c.application.app_context():
        # a finished, shared round for a seeded demo candidate
        cand = User.query.filter_by(email="meera@demo.test").first()
        app_ = Application.query.filter_by(candidate_id=cand.id).first()
        att = RoundAttempt(application_id=app_.id, round_index=0, round_type="mcq", status="completed", score=60.0,
                           completed_at=datetime.utcnow(), config={}, result={})
        db.session.add(att)
        db.session.flush()
        r = Report(attempt_id=att.id, status="shared", overall=3.0, recommendation="hold", sections={"kind": "mcq", "strengths": ["SQL"], "gaps": []},
                   candidate_feedback={"strengths": ["SQL"], "gaps": ["Python"], "next_steps": ["Practice"]}, shared_with_candidate=True)
        db.session.add(r)
        db.session.commit()
        rid, email = r.id, cand.email
    # the seeded candidate signs in with the demo password
    ch = login(c, email)
    assert c.post(f"/api/me/feedback/{rid}/dispute", headers=ch, json={"note": "bad"}).status_code == 400  # too short
    j(c.post(f"/api/me/feedback/{rid}/dispute", headers=ch, json={"note": "My microphone stopped during question 3."}))
    assert c.post(f"/api/me/feedback/{rid}/dispute", headers=ch, json={"note": "Again, the microphone stopped."}).status_code == 409
    ov = j(c.get("/api/platform/overview", headers=sa))["data"]
    assert ov["disputes"] >= 1
    items = j(c.get("/api/platform/disputes?status=open", headers=sa))["data"]["items"]
    row = next(x for x in items if x["id"] == rid)
    assert row["note"].startswith("My microphone") and row["status"] == "open"
    detail = j(c.get(f"/api/platform/disputes/{rid}", headers=sa))["data"]
    assert detail["dispute_status"] == "open" and "sections" in detail
    bad = c.post(f"/api/platform/disputes/{rid}/resolve", headers=sa, json={"action": "dismissed", "note": "ok"})
    assert bad.status_code == 400
    j(c.post(f"/api/platform/disputes/{rid}/resolve", headers=sa, json={"action": "dismissed", "note": "We checked the recording; the audio was clear."}))
    assert c.post(f"/api/platform/disputes/{rid}/resolve", headers=sa, json={"action": "changed", "note": "Second try at resolving."}).status_code == 409
    fb = j(c.get("/api/me/feedback", headers=ch))["data"]
    mine = next(x for x in fb if x["id"] == rid)
    assert mine["dispute_status"] == "dismissed" and "recording" in mine["dispute_resolution"]
    notes = j(c.get("/api/inbox/notifications", headers=ch))["data"]
    assert any("looked into your concern" in n["title"] for n in notes)


def test_notifications_clear_BETACODE2_39(c):
    h = login(c, "rahul@acme.test")
    items = j(c.get("/api/inbox/notifications", headers=h))["data"]
    if items:
        j(c.delete(f"/api/inbox/notifications/{items[0]['id']}", headers=h))
    j(c.delete("/api/inbox/notifications", headers=h))
    assert j(c.get("/api/inbox/notifications", headers=h))["data"] == []
    # someone else's notification can't be cleared
    from models import Notification, User
    with c.application.app_context():
        other = Notification.query.join(User, User.id == Notification.user_id).filter(User.email != "rahul@acme.test").first()
    if other:
        j(c.delete(f"/api/inbox/notifications/{other.id}", headers=h))
        with c.application.app_context():
            from extensions import db
            assert db.session.get(Notification, other.id) is not None


def test_cert_breakdown_BETACODE2_34(c):
    from routes.certs import cert_breakdown

    class Cert:
        sections = [{"name": "Knowledge", "weight": 60}, {"name": "Spoken interview", "weight": 40}]

    class Att:
        section_scores = {"0": {"pct": 62.5}}
        status = "in_progress"
    b = cert_breakdown(Att, Cert)
    assert b["progress"] == {"done": 1, "total": 2} and not b["final"]
    assert b["breakdown"][0]["points"] == 37.5 and b["breakdown"][1]["pct"] is None


def test_public_hiring_plan_any_title_BETACODE2_9(c):
    r = j(c.post("/api/public/hiring-plan", json={"title": "Cloud Architect"}, headers={"X-Forwarded-For": "10.7.7.7"}))["data"]
    assert r["title"] and "Java" not in str(r) and r["rounds"]
    assert c.post("/api/public/hiring-plan", json={"title": "x"}, headers={"X-Forwarded-For": "10.7.7.7"}).status_code == 400


def test_verify_rate_limited(c):
    ip = {"X-Forwarded-For": "10.8.8.8"}
    codes = [c.get(f"/api/public/verify/C2H-PYT3-{100000 + i}", headers=ip).status_code for i in range(22)]
    assert codes[0] == 404 and codes[-1] == 429


def test_dispute_reinterview_from_company_side(c):
    from extensions import db
    from models import Application, Report, RoundAttempt, User
    with c.application.app_context():
        cand = User.query.filter_by(email="arjun@demo.test").first()
        app_ = Application.query.filter_by(candidate_id=cand.id).first()
        RoundAttempt.query.filter(RoundAttempt.application_id == app_.id, RoundAttempt.round_index == 0,
                                  RoundAttempt.status.in_(["invited", "scheduled", "in_progress", "paused"])).update({"status": "expired"})
        att = RoundAttempt(application_id=app_.id, round_index=0, round_type="mcq", status="completed", score=40.0,
                           completed_at=datetime.utcnow(), config={}, result={})
        db.session.add(att)
        db.session.flush()
        r = Report(attempt_id=att.id, status="shared", overall=2.0, recommendation="reject", sections={"kind": "mcq"},
                   candidate_feedback={"strengths": [], "gaps": ["SQL"], "next_steps": []}, shared_with_candidate=True)
        db.session.add(r)
        db.session.commit()
        rid, aid = r.id, app_.id
    ch = login(c, "arjun@demo.test")
    j(c.post(f"/api/me/feedback/{rid}/dispute", headers=ch, json={"note": "The page froze for five minutes in the middle."}))
    rahul = login(c, "rahul@acme.test")
    open_rows = j(c.get("/api/disputes?status=open", headers=rahul))["data"]["items"]
    assert any(x["id"] == rid for x in open_rows)
    j(c.post(f"/api/reports/{rid}/resolve-dispute", headers=rahul, json={"action": "reinterview", "note": "Sorry about that. Please take the round again."}))
    with c.application.app_context():
        live = RoundAttempt.query.filter(RoundAttempt.application_id == aid, RoundAttempt.round_index == 0,
                                         RoundAttempt.status.in_(["invited", "scheduled"])).count()
    assert live == 1
    assert any(i["type"] == "mcq" for i in j(c.get("/api/me", headers=ch))["data"]["invites"])
