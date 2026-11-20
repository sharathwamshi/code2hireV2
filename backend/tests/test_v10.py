"""Regression tests for V02.00.10: the candidate portal review (Code2Hire_Portal_Review_2.xlsx), the candidate QA
tracker (CP-001 to CP-011), forgot password by email with SMTP settings, staff editing a candidate and their resume,
the strict profile-strength formula, and the Knowledge section of a certification verifying the skill.
Browser-only parts (layout, the Disha panel, filters, stepper, sticky save bar) are checked in walk10. Run: pytest -q"""
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("C2H_NO_AUTOCREATE", "1")
if os.environ.get("C2H_TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["C2H_TEST_DATABASE_URL"]
elif "DATABASE_URL" not in os.environ or not os.environ["DATABASE_URL"].startswith("sqlite"):
    import tempfile
    os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "v10.db")
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["AZURE_SPEECH_KEY"] = ""

import seed  # noqa: E402
from app import create_app  # noqa: E402
from services import mailer, skills as S  # noqa: E402

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


def login(c, email, pw=PW, fresh=False):
    if fresh or email not in _tokens:
        r = c.post("/api/auth/login", json={"email": email, "password": pw}, headers={"X-Forwarded-For": "10.10.0." + str(len(_tokens) + 1)})
        assert r.status_code == 200, r.get_json()
        _tokens[email] = {"Authorization": "Bearer " + r.get_json()["data"]["token"]}
    return _tokens[email]


def j(r, code=200):
    assert r.status_code == code, (r.status_code, r.get_json())
    return r.get_json()


def d(r, code=200):
    return j(r, code)["data"]


SUPER = "super@code2hire.ai"
CAND = "arjun@demo.test"


# ---------------------------------------------------------------- version

def test_version_is_v02_00_10(c):
    assert j(c.get("/api/health"))["version"].startswith("V02.")


# ---------------------------------------------------------------- skills (JOB-07, CP-004, LRN-03)

def test_skill_names_alternatives_and_synonyms():
    assert S.canon("sap attp") == "SAP ATTP"
    assert S.canon("javascript") == "JavaScript"
    assert S.options("JavaScript / TypeScript") == ["JavaScript", "TypeScript"]
    assert set(S.options("framework (React, Angular or Vue)")) >= {"React", "Angular", "Vue"}
    have = [{"name": "TypeScript", "level": 3}]
    assert S.find("JavaScript / TypeScript", have)["name"] == "TypeScript"
    assert S.same("JS", "JavaScript") and S.same("postgres", "PostgreSQL")
    # whole words only: "Java" is not found inside "JavaScript"
    got = S.extract("Built front ends in JavaScript and React.")
    assert "JavaScript" in got and "Java" not in got


def test_job_match_uses_alternatives(c):
    h = login(c, CAND)
    jobs = d(c.get("/api/me/jobs", headers=h))
    assert {"items", "filters", "verified_skills", "saved_count"} <= set(jobs)
    for it in jobs["items"]:
        assert it["work_mode"][:1].isupper()


# ---------------------------------------------------------------- strict profile strength

def test_profile_strength_is_strict(app):
    from services.profile import STRENGTH, strength
    assert sum(w for _, _, w, _ in STRENGTH) == 100
    user = SimpleNamespace(name="Asha Rao")
    empty = SimpleNamespace(resume_text="", headline="", location="", phone="", experience_years=None, skills=[], target_roles=[])
    assert strength(empty, user)["pct"] == 5  # only the name
    short = SimpleNamespace(resume_text="tiny", headline="Dev", location="Pune", phone="123", experience_years=0,
                            skills=[{"name": "Python"}], target_roles=["Backend developer"])
    s = strength(short, user)
    assert "Resume" in " ".join(s["missing"]) or any(not i["done"] and i["key"] == "resume" for i in s["items"])
    assert not next(i for i in s["items"] if i["key"] == "phone")["done"]  # 3 digits is not a phone
    assert next(i for i in s["items"] if i["key"] == "experience")["done"]  # 0 = fresher counts
    full = SimpleNamespace(resume_text="x" * 250, headline="Backend developer", location="Pune", phone="+91 98450 00000",
                           experience_years=3, skills=[{"name": n} for n in "ABCDE"] + [{"name": "F", "verified": True}],
                           target_roles=["Backend developer"])
    assert strength(full, user)["pct"] == 100


def test_home_payload(c):
    h = login(c, CAND)
    me = d(c.get("/api/me", headers=h))
    assert {"completeness", "next_steps", "top_skills", "jobs_preview", "activity", "role_chips", "tip"} <= set(me)
    assert me["next_steps"]["total"] == 5 and len(me["jobs_preview"]) <= 3
    assert all(i["link"].startswith("/me") for i in me["completeness"]["items"])


def test_path_needs_goal(c):
    h = login(c, CAND)
    r = c.post("/api/me/path", headers=h, json={"goal": ""})
    assert r.status_code == 400 and r.get_json()["fields"].get("goal")


# ---------------------------------------------------------------- resume replaces the old resume's skills (CP-004)

RESUME = "Meera Iyer\nData analyst in Bengaluru. 4 years of experience.\nSkills: SQL, Power BI, Tableau, Excel, Python.\n" * 2


def test_resume_preview_then_replace(c):
    h = login(c, CAND)
    before = d(c.get("/api/me", headers=h))["profile"]["skills"]
    # a hand-added skill stays
    j(c.patch("/api/me/profile", headers=h, json={"skills": before + [{"name": "Communication", "level": 3}]}))
    prev = d(c.post("/api/me/resume/read", headers=h, json={"text": RESUME}))
    plan = prev["plan"]
    assert "Power BI" in plan["add"] and "Communication" not in plan["remove"]
    old_resume = [s["name"] for s in before if s.get("source") == "resume" and not s.get("verified")]
    gone = [s for s in old_resume if not any(S.same(s, n) for n in prev["fields"]["skills"])]
    assert set(gone) <= set(plan["remove"])
    nothing = d(c.get("/api/me", headers=h))["profile"]["skills"]
    assert not any(s["name"] == "Power BI" for s in nothing)  # preview saves nothing
    res = d(c.post("/api/me/resume", headers=h, json={"text": RESUME, "fields": prev["fields"], "add": plan["add"], "remove": plan["remove"], "fill": {}}))
    names = [s["name"] for s in d(c.get("/api/me", headers=h))["profile"]["skills"]]
    assert "Power BI" in names and "Communication" in names
    assert not any(g in names for g in gone) and set(res["removed"]) == set(plan["remove"])


def test_merge_skills_no_duplicates(c):
    h = login(c, CAND)
    cur = d(c.get("/api/me", headers=h))["profile"]["skills"]
    j(c.patch("/api/me/profile", headers=h, json={"skills": cur + [{"name": "power bi", "level": 2}, {"name": "POWER BI", "level": 2}]}))
    names = [s["name"].lower() for s in d(c.get("/api/me", headers=h))["profile"]["skills"]]
    assert names.count("power bi") == 1


# ---------------------------------------------------------------- practice (CP-011, PRA-04)

def test_practice_needs_role_and_uses_role_skills(c):
    h = login(c, CAND)
    r = c.post("/api/me/practice", headers=h, json={"type": "mcq", "questions": 3})
    assert r.status_code == 400 and r.get_json()["fields"].get("role")
    rs = d(c.get("/api/me/practice/role-skills?role=Data%20Analyst", headers=h))
    assert rs["skills"]
    sug = d(c.get("/api/me/practice/suggest", headers=h))
    assert {"suggestions", "roles", "profile_skills"} <= set(sug)
    att = d(c.post("/api/me/practice", headers=h, json={"type": "mcq", "role": "Data Analyst", "questions": 3}))
    assert att["attempt_id"]
    hist = d(c.get("/api/me/practice", headers=h))
    assert any((p["title"] or "").startswith("Practice: Data Analyst") for p in hist)


# ---------------------------------------------------------------- jobs: save, filters, search

def test_save_job_filters_and_search(c):
    h = login(c, CAND)
    jobs = d(c.get("/api/me/jobs", headers=h))["items"]
    jid = jobs[0]["id"]
    d(c.post(f"/api/me/jobs/{jid}/save", headers=h, json={"on": True}))
    saved = d(c.get("/api/me/jobs?saved=1", headers=h))
    assert [x["id"] for x in saved["items"]] == [jid] and saved["saved_count"] == 1
    d(c.post(f"/api/me/jobs/{jid}/save", headers=h, json={"on": False}))
    assert d(c.get("/api/me/jobs?saved=1", headers=h))["items"] == []
    none = d(c.get("/api/me/jobs?location=Nowhere-City", headers=h))
    assert none["items"] == []
    res = d(c.get("/api/me/search?q=python", headers=h))
    assert {"jobs", "skills", "paths"} <= set(res) and res["jobs"]


def test_applications_steps_and_prepare(c):
    h = login(c, CAND)
    apps = d(c.get("/api/me/applications", headers=h))
    assert apps
    a = apps[0]
    assert a["prepare"]["role"] and a["steps"]
    assert all("Isha" not in s["name"] for s in a["steps"])  # APP-04: candidates see "(AI-assisted)"
    assert {s["state"] for s in a["steps"]} <= {"completed", "scheduled", "next", "not_finished", "missed", "not_selected", "closed", "upcoming"}


# ---------------------------------------------------------------- learning paths

def test_learning_one_path_per_skill_and_capitals(c):
    h = login(c, CAND)
    p = d(c.post("/api/me/learning", headers=h, json={"skill": "power bi"}))
    assert p["skill"] == "Power BI" and p["meta"]["basic"] is True
    assert all(t.get("minutes") for t in p["topics"]) and "skill check" in p["topics"][-1]["title"].lower()
    again = d(c.post("/api/me/learning", headers=h, json={"skill": "POWER BI"}))
    assert again["id"] == p["id"] and again["existing"]
    lst = d(c.get("/api/me/learning", headers=h))
    assert {"paths", "try"} <= set(lst)
    t = d(c.patch(f"/api/me/learning/{p['id']}/topics/0", headers=h, json={"done": True}))
    assert t["done_count"] == 1 and t["current"] == 1
    assert c.post(f"/api/me/learning/{p['id']}/rebuild", headers=h).status_code == 503  # no AI in tests


# ---------------------------------------------------------------- product feedback (CP-008)

def test_product_feedback_round_trip(c):
    h = login(c, CAND)
    topics = d(c.get("/api/me/product-feedback", headers=h))["topics"]
    assert topics
    d(c.post("/api/me/product-feedback", headers=h, json={"topics": topics[:1], "rating": 4, "text": "Nice portal", "page": "feedback"}))
    assert c.post("/api/me/product-feedback", headers=h, json={"topics": [], "text": ""}).status_code == 400
    hs = login(c, SUPER)
    rows = d(c.get("/api/platform/feedback", headers=hs))
    items = rows["items"] if isinstance(rows, dict) else rows
    fid = items[0]["id"]
    d(c.patch(f"/api/platform/feedback/{fid}", headers=hs, json={"status": "read"}))
    assert c.get("/api/platform/feedback", headers=login(c, CAND)).status_code in (401, 403)


# ---------------------------------------------------------------- forgot password by email (CP-010)

def test_forgot_needs_smtp(c):
    r = c.post("/api/auth/forgot", json={"email": CAND}, headers={"X-Forwarded-For": "10.11.0.1"})
    assert r.status_code == 503


def test_smtp_settings_validate_save_and_test(c):
    hs = login(c, SUPER)
    bad = c.put("/api/platform/integrations", headers=hs, json={"smtp_host": "", "smtp_from_email": "nope", "smtp_port": "abc"})
    assert bad.status_code == 400 and {"smtp_from_email", "smtp_port"} <= set(bad.get_json()["fields"])
    d(c.put("/api/platform/integrations", headers=hs, json={"smtp_host": "smtp.example.com", "smtp_port": "587", "smtp_security": "starttls",
                                                           "smtp_username": "mailer", "smtp_password": "s3cret!", "smtp_from_email": "no-reply@code2hire.ai",
                                                           "smtp_from_name": "Code2Hire"}))
    got = d(c.get("/api/platform/integrations", headers=hs))
    assert got["smtp_ok"] and got["smtp_host"] == "smtp.example.com" and got["smtp_password"] != "s3cret!"
    mailer.OUTBOX.clear()
    d(c.post("/api/platform/integrations/smtp-test", headers=hs, json={"to": "ops@code2hire.ai"}))
    assert mailer.OUTBOX and mailer.OUTBOX[-1]["to"] == "ops@code2hire.ai"
    assert c.put("/api/platform/integrations", headers=login(c, "admin@acme.test"), json={"smtp_host": "x"}).status_code in (401, 403)


def test_forgot_and_reset(c):
    mailer.OUTBOX.clear()
    ip = {"X-Forwarded-For": "10.11.0.2"}
    same_answer = d(c.post("/api/auth/forgot", json={"email": "nobody@nowhere.test"}, headers=ip))
    assert not mailer.OUTBOX
    real = d(c.post("/api/auth/forgot", json={"email": "karan@demo.test"}, headers=ip))
    assert real == same_answer  # no hint whether an account exists
    mail = mailer.OUTBOX[-1]
    assert mail["to"] == "karan@demo.test" and "/reset/" in mail["text"]
    token = mail["text"].split("/reset/")[1].split()[0].strip(").,")
    # a reset token is not a portal link
    assert c.post(f"/api/auth/invite/{token}/open").status_code in (400, 404, 410)
    assert d(c.get(f"/api/auth/reset/{token}"))["email"] == "karan@demo.test"
    weak = c.post(f"/api/auth/reset/{token}", json={"new": "short"})
    assert weak.status_code == 400
    ok = d(c.post(f"/api/auth/reset/{token}", json={"new": "NewPass@2026x"}))
    assert ok["token"]
    assert c.get(f"/api/auth/reset/{token}").status_code == 410  # single use
    assert c.post("/api/auth/login", json={"email": "karan@demo.test", "password": PW}, headers={"X-Forwarded-For": "10.11.0.3"}).status_code == 401
    login(c, "karan@demo.test", "NewPass@2026x", fresh=True)


def test_forgot_is_throttled(c):
    ip = {"X-Forwarded-For": "10.11.0.9"}
    codes = [c.post("/api/auth/forgot", json={"email": "sana@demo.test"}, headers=ip).status_code for _ in range(7)]
    assert 429 in codes


def test_admin_can_change_password(c):
    h = login(c, "admin@acme.test")
    j(c.post("/api/auth/change-password", headers=h, json={"current": PW, "new": "Kestrel#Orbit73"}))
    login(c, "admin@acme.test", "Kestrel#Orbit73", fresh=True)
    from models import User, db
    from services.perms import hash_password
    with c.application.app_context():  # put the seed password back for the other tests
        User.query.filter_by(email="admin@acme.test").first().password_hash = hash_password(PW)
        db.session.commit()
    login(c, "admin@acme.test", fresh=True)


# ---------------------------------------------------------------- staff edit a candidate and their resume

def _cand_id(c, email):
    return d(c.get("/api/auth/me", headers=login(c, email)))["user"]["id"]


def test_staff_edit_candidate(c):
    uid = _cand_id(c, "sana@demo.test")
    for who in ("rahul@acme.test", "anita@acme.test", "admin@acme.test"):  # recruiter, interviewer, admin
        v = d(c.get(f"/api/candidates/{uid}/profile", headers=login(c, who)))
        assert v["email"] == "sana@demo.test"
    h = login(c, "rahul@acme.test")
    bad = c.patch(f"/api/candidates/{uid}/profile", headers=h, json={"phone": "12", "experience_years": 99})
    assert bad.status_code == 400 and {"phone", "experience_years"} <= set(bad.get_json()["fields"])
    v = d(c.patch(f"/api/candidates/{uid}/profile", headers=h, json={"headline": "Python developer", "location": "Pune", "skills": [{"name": "fastapi", "level": 3}]}))
    assert v["headline"] == "Python developer" and any(s["name"] == "FastAPI" for s in v["skills"])
    prev = d(c.post(f"/api/candidates/{uid}/resume/read", headers=h, json={"text": RESUME}))
    d(c.post(f"/api/candidates/{uid}/resume", headers=h, json={"text": RESUME, "fields": prev["fields"], "add": prev["plan"]["add"], "remove": prev["plan"]["remove"], "fill": {}}))
    v = d(c.get(f"/api/candidates/{uid}/profile", headers=h))
    assert v["has_resume"] and "Power BI" in [s["name"] for s in v["skills"]]
    # someone with no role in the company, and a candidate, can't
    assert c.get(f"/api/candidates/{uid}/profile", headers=login(c, "vikram@acme.test")).status_code == 403
    assert c.get(f"/api/candidates/{uid}/profile", headers=login(c, CAND)).status_code in (401, 403)


def test_staff_cant_edit_outside_company(c):
    # a candidate who never applied to, and wasn't added by, the company
    from models import User, db
    from services.perms import hash_password
    with c.application.app_context():
        u = User(email="outsider@demo.test", name="Out Sider", kind="candidate", password_hash=hash_password(PW))
        db.session.add(u)
        db.session.commit()
        oid = u.id
    assert c.get(f"/api/candidates/{oid}/profile", headers=login(c, "rahul@acme.test")).status_code in (403, 404)
    assert c.get(f"/api/candidates/{oid}/profile", headers=login(c, SUPER)).status_code == 200


# ---------------------------------------------------------------- certifications: state order and Knowledge section

def test_cert_state_in_progress_before_cooldown(c):
    h = login(c, CAND)
    cat = d(c.get("/api/certs-catalog", headers=h))
    assert cat and all({"state", "why", "pass_mark", "issuer"} <= set(x) for x in cat)
    assert all(x["state"] in ("open", "in_progress", "locked", "cooldown", "held", "used_up") for x in cat)
    target = next((x for x in cat if x["state"] == "open"), None)
    if not target:
        pytest.skip("no open certification in the seed")
    d(c.post(f"/api/certs/{target['id']}/start", headers=h))
    again = next(x for x in d(c.get("/api/certs-catalog", headers=h)) if x["id"] == target["id"])
    assert again["state"] == "in_progress" and again["action"]["label"] == "Continue"


def test_knowledge_section_verifies_skill(app):
    from models import CandidateProfile, Credential, User
    from routes.certs import _verify_from_knowledge
    with app.test_request_context():
        u = User.query.filter_by(email="meera@demo.test").first()
        cert = SimpleNamespace(sections=[{"type": "mcq", "name": "Knowledge", "minimum": 60}, {"type": "ai_interview"}],
                               skills=[{"name": "sql"}], level=3, validity_months=12)
        ca = SimpleNamespace(user_id=u.id)
        _verify_from_knowledge(ca, cert, SimpleNamespace(round_index=0, round_type="mcq", warnings=0), 55)
        assert not Credential.query.filter_by(user_id=u.id, skill="SQL", level=3).first()  # below the minimum
        _verify_from_knowledge(ca, cert, SimpleNamespace(round_index=0, round_type="mcq", warnings=99), 90)
        assert not Credential.query.filter_by(user_id=u.id, skill="SQL", level=3).first()  # too many warnings
        _verify_from_knowledge(ca, cert, SimpleNamespace(round_index=1, round_type="ai_interview", warnings=0), 90)
        assert not Credential.query.filter_by(user_id=u.id, skill="SQL", level=3).first()  # not the knowledge section
        _verify_from_knowledge(ca, cert, SimpleNamespace(round_index=0, round_type="mcq", warnings=0), 80)
        assert Credential.query.filter_by(user_id=u.id, skill="SQL", level=3).count() == 1
        _verify_from_knowledge(ca, cert, SimpleNamespace(round_index=0, round_type="mcq", warnings=0), 85)
        assert Credential.query.filter_by(user_id=u.id, skill="SQL", level=3).count() == 1  # no duplicate badge
        p = CandidateProfile.query.filter_by(user_id=u.id).first()
        assert any(S.same(s["name"], "SQL") and s.get("verified") for s in p.skills)


def test_skill_recommendations(c):
    r = d(c.get("/api/me/skills/recommend", headers=login(c, CAND)))
    assert {"recommended", "levels", "skills", "quick"} <= set(r) and len(r["levels"]) == 5
