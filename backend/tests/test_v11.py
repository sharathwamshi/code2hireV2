"""Regression tests for V02.00.11: the candidate AI voice / MCQ interview bug report (CAN-001 to CAN-022) and the
decisions on it. Browser-only parts (the fixed room layout, the screen cover, the chat colour, the conversation panel)
are checked in walk11. Run: pytest -q"""
import io
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
    os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "v11.db")
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["AZURE_SPEECH_KEY"] = ""

from tests.syscheck_helper import system_check  # noqa: E402
import seed  # noqa: E402
from app import create_app  # noqa: E402

PW = seed.PW
PAPER_REVIEW = True  # this suite runs with the real default: MCQ papers are checked before the candidate starts


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
        r = c.post("/api/auth/login", json={"email": email, "password": pw}, headers={"X-Forwarded-For": "10.20.0." + str(len(_tokens) + 1)})
        assert r.status_code == 200, r.get_json()
        _tokens[email] = {"Authorization": "Bearer " + r.get_json()["data"]["token"]}
    return _tokens[email]


def j(r, code=200):
    assert r.status_code == code, (r.status_code, r.get_json())
    return r.get_json()


def d(r, code=200):
    return j(r, code)["data"]


REC = "rahul@acme.test"
CAND = "arjun@demo.test"


def python_job(c):
    return next(x for x in j(c.get("/api/jobs?size=100", headers=login(c, REC)))["items"] if x["title"] == "Senior Python Developer")


def new_candidate(c, email, name, resume=None):
    job = python_job(c)
    body = {"name": name, "email": email, "job_id": job["id"]}
    if resume:
        body["resume_text"] = resume
    r = d(c.post("/api/candidates", headers=login(c, REC), json=body))["results"][0]
    op = d(c.post(f"/api/auth/invite/{r['link'].split('/')[-1]}/open"))
    return job, r["application_id"], {"Authorization": "Bearer " + op["token"]}


def invite(c, aid, kind="mcq"):
    full = d(c.get(f"/api/applications/{aid}", headers=login(c, REC)))
    idx = next(i for i, r in enumerate(full["rounds"]) if r["type"] == kind)
    return d(c.post(f"/api/applications/{aid}/invite", headers=login(c, REC), json={"round_index": idx}))["attempt_id"]


def ready_to_start(c, att, ch):
    system_check(c, att, ch)
    j(c.post(f"/api/rounds/{att}/consent", headers=ch, json={}))


def test_version_is_v02_00_11(c):
    assert j(c.get("/api/health"))["version"].startswith("V02.")


# ---------------------------------------------------------------- CAN-015 / CAN-016: MCQ papers checked before the test

def test_paper_drawn_at_invite_and_needs_review(c):
    _, aid, ch = new_candidate(c, "paper1@demo.test", "Paper One")
    att = invite(c, aid)
    me = d(c.get("/api/me", headers=ch))
    inv = next(i for i in me["invites"] if i["attempt_id"] == att)
    assert inv["paper_pending"] is True
    assert d(c.get(f"/api/rounds/{att}", headers=ch))["paper_pending"] is True
    ready_to_start(c, att, ch)
    r = c.post(f"/api/rounds/{att}/start", headers=ch)
    assert r.status_code == 409 and r.get_json()["fields"]["code"] == "paper_review"
    # the hiring team sees the questions WITH answers; the candidate can't open the paper
    p = d(c.get(f"/api/rounds/{att}/paper", headers=login(c, REC)))
    assert p["state"] == "pending_review" and p["questions"] and "answer" in p["questions"][0]
    assert c.get(f"/api/rounds/{att}/paper", headers=ch).status_code in (401, 403)
    first = p["questions"][0]["id"]
    sw = d(c.post(f"/api/rounds/{att}/paper/swap", headers=login(c, REC), json={"question_id": first}))
    assert first not in [q["id"] for q in sw["questions"]] and len(sw["questions"]) == len(p["questions"])
    ok = d(c.post(f"/api/rounds/{att}/paper/approve", headers=login(c, REC)))
    assert ok["state"] == "approved"
    notes = j(c.get("/api/inbox/notifications", headers=ch))
    notes = notes.get("data", notes)
    items = notes["items"] if isinstance(notes, dict) else notes
    assert any("test is ready" in (n.get("title") or "").lower() for n in items)
    started = d(c.post(f"/api/rounds/{att}/start", headers=ch))
    shown = [q["id"] for q in started.get("questions") or d(c.get(f"/api/rounds/{att}", headers=ch))["questions"]]
    assert shown == [q["id"] for q in ok["questions"]]  # exactly the approved paper
    # locked once started
    assert c.post(f"/api/rounds/{att}/paper/redraw", headers=login(c, REC)).status_code == 409


def test_same_paper_for_everyone(c):
    job = python_job(c)
    h = login(c, REC)
    full = d(c.get(f"/api/jobs/{job['id']}", headers=h))
    idx = next(i for i, r in enumerate(full["rounds"]) if r["type"] == "mcq")
    sample = d(c.get(f"/api/jobs/{job['id']}/rounds/{idx}/sample?questions=5", headers=h))
    assert sample["questions"] and "answer" in sample["questions"][0]
    ids = [q["id"] for q in sample["questions"]]
    rounds = full["rounds"]
    rounds[idx] = {**rounds[idx], "config": {**(rounds[idx].get("config") or {}), "mcq.paper": "same", "mcq.fixed_ids": ids, "mcq.questions": len(ids)}}
    d(c.patch(f"/api/jobs/{job['id']}", headers=h, json={"rounds": rounds}))
    again = d(c.get(f"/api/jobs/{job['id']}/rounds/{idx}/sample", headers=h))
    assert again["fixed"] and [q["id"] for q in again["questions"]] == ids
    papers = []
    for n in ("Two", "Three"):
        _, aid, ch = new_candidate(c, f"same{n.lower()}@demo.test", f"Same {n}")
        att = invite(c, aid)
        p = d(c.get(f"/api/rounds/{att}/paper", headers=h))
        assert p["state"] == "approved"  # checked once in round setup
        papers.append([q["id"] for q in p["questions"]])
    assert papers[0] == papers[1] == ids
    rounds[idx]["config"].update({"mcq.paper": "random", "mcq.fixed_ids": []})
    d(c.patch(f"/api/jobs/{job['id']}", headers=h, json={"rounds": rounds}))


def test_setting_bad_question_ids_refused(c):
    from services.settings import check_value
    assert check_value("mcq.fixed_ids", ["x"])[1]
    assert check_value("mcq.fixed_ids", [3, 3, 4])[0] == [3, 4]
    assert check_value("mcq.paper", "sometimes")[1]


# ---------------------------------------------------------------- CAN-004: delete practice for good

def test_delete_practice_permanently(c, app):
    from models import Report, RoundAttempt, Turn
    ch = login(c, CAND)
    att = d(c.post("/api/me/practice", headers=ch, json={"type": "ai_interview", "role": "Backend Developer", "questions": 2}))["attempt_id"]
    with app.app_context():
        from extensions import db
        db.session.add(Turn(attempt_id=att, seq=0, speaker="ai", text="Tell me about Flask"))
        db.session.commit()
    assert c.delete(f"/api/me/practice/{att}", headers=login(c, "meera@demo.test")).status_code == 404  # not hers
    d(c.delete(f"/api/me/practice/{att}", headers=ch))
    with app.app_context():
        assert RoundAttempt.query.get(att) is None and not Turn.query.filter_by(attempt_id=att).count()
        assert not Report.query.filter_by(attempt_id=att).count()
    assert all(p["id"] != att for p in d(c.get("/api/me/practice", headers=ch)))
    chk = d(c.post("/api/me/skill-check", headers=ch, json={"skill": "Python", "level": 2}))["attempt_id"]
    assert c.delete(f"/api/me/practice/{chk}", headers=ch).status_code == 400  # skill checks back badges


# ---------------------------------------------------------------- CAN-021: practice rehearsal, jobless rounds end

def test_practice_integrity_is_a_rehearsal(c):
    ch = login(c, CAND)
    att = d(c.post("/api/me/practice", headers=ch, json={"type": "mcq", "role": "Backend Developer", "skills": ["Python"], "questions": 3}))["attempt_id"]
    j(c.post(f"/api/rounds/{att}/consent", headers=ch, json={}))   # V02.01.04: no filler questions, so a skill the bank has
    d(c.post(f"/api/rounds/{att}/start", headers=ch))
    for _ in range(4):
        r = d(c.post(f"/api/rounds/{att}/integrity", headers=ch, json={"type": "tab_switch"}))
    assert r["rehearsal"] and not r["counted"] and r["status"] == "in_progress" and r["message"].startswith("Practice")
    back = d(c.post(f"/api/rounds/{att}/integrity", headers=ch, json={"type": "returned", "seconds": 12}))
    assert not back["counted"]


def test_skill_check_past_the_limit_ends_instead_of_pausing(c):
    ch = login(c, "meera@demo.test")
    att = d(c.post("/api/me/skill-check", headers=ch, json={"skill": "Python", "level": 2}))["attempt_id"]
    ready_to_start(c, att, ch)
    d(c.post(f"/api/rounds/{att}/start", headers=ch))
    last = None
    for _ in range(6):
        last = d(c.post(f"/api/rounds/{att}/integrity", headers=ch, json={"type": "tab_switch"}))
        if last.get("ended"):
            break
    assert last.get("ended") and d(c.get(f"/api/rounds/{att}", headers=ch))["status"] not in ("paused", "in_progress")


# ---------------------------------------------------------------- CAN-022: paused screen, remind the team

def test_paused_candidate_can_remind_the_team(c):
    _, aid, ch = new_candidate(c, "pause1@demo.test", "Pause One")
    att = invite(c, aid)
    d(c.post(f"/api/rounds/{att}/paper/approve", headers=login(c, REC)))
    ready_to_start(c, att, ch)
    d(c.post(f"/api/rounds/{att}/start", headers=ch))
    assert c.post(f"/api/rounds/{att}/nudge", headers=ch).status_code == 400  # not paused yet
    d(c.post(f"/api/rounds/{att}/integrity", headers=ch, json={"type": "devtools"}))  # an instant-pause event
    assert d(c.get(f"/api/rounds/{att}", headers=ch))["status"] == "paused"
    assert d(c.get(f"/api/rounds/{att}", headers=ch))["has_team"] is True
    d(c.post(f"/api/rounds/{att}/nudge", headers=ch))
    assert c.post(f"/api/rounds/{att}/nudge", headers=ch).status_code == 429


# ---------------------------------------------------------------- CAN-017: the candidate sees the conversation

def test_candidate_sees_conversation_during_round(c, app):
    from models import Turn
    ch = login(c, "sana@demo.test")
    # a hiring AI interview, started
    _, aid, ch = new_candidate(c, "talk1@demo.test", "Talk One")
    att = invite(c, aid, "ai_interview") if any(r["type"] == "ai_interview" for r in d(c.get(f"/api/applications/{aid}", headers=login(c, REC)))["rounds"]) else None
    if not att:
        pytest.skip("the seeded job has no AI interview round")
    with app.app_context():
        from extensions import db
        from models import RoundAttempt
        a = db.session.get(RoundAttempt, att)
        a.status = "in_progress"
        db.session.add(Turn(attempt_id=att, seq=0, speaker="ai", text="What is a decorator?", analysis={"secret": 1}))
        db.session.add(Turn(attempt_id=att, seq=1, speaker="candidate", text="A function wrapping a function", analysis={"secret": 2}))
        db.session.commit()
    rows = d(c.get(f"/api/rounds/{att}/transcript", headers=ch))
    assert [r["speaker"] for r in rows] == ["ai", "candidate"] and all("analysis" not in r for r in rows)


# ---------------------------------------------------------------- CAN-005: certification progress never jumps

def test_cert_section_counts_when_finished(app):
    from routes.certs import cert_breakdown
    with app.test_request_context():
        from extensions import db
        from models import CertAttempt, Certification, RoundAttempt, User
        u = User.query.filter_by(email=CAND).first()
        c = Certification.query.first()
        ca = CertAttempt(cert_id=c.id, user_id=u.id, status="in_progress", section_scores={})
        db.session.add(ca)
        db.session.flush()
        db.session.add(RoundAttempt(cert_attempt_id=ca.id, round_index=0, round_type=c.sections[0]["type"], status="completed", config={}))
        db.session.flush()
        b = cert_breakdown(ca, c)
        assert b["progress"]["done"] == 1 and b["scoring"] and b["breakdown"][0]["scoring"]
        ca.section_scores = {"0": {"pct": 80}}
        b = cert_breakdown(ca, c)
        assert b["progress"]["done"] == 1 and not b["scoring"]
        db.session.rollback()


# ---------------------------------------------------------------- CAN-018: edit, delete, archive, rescore

def test_edit_job_history_and_rescore(c, app):
    h = login(c, REC)
    job = python_job(c)
    before = d(c.get(f"/api/jobs/{job['id']}/candidates?size=100", headers=h)) if False else None
    full = d(c.get(f"/api/jobs/{job['id']}", headers=h))
    skills = full["skills"] + [{"name": "Rust", "level": 3, "must": False}]
    r = d(c.patch(f"/api/jobs/{job['id']}", headers=h, json={"skills": skills, "location": "Pune"}))
    assert r["rescored"] >= 1
    hist = d(c.get(f"/api/jobs/{job['id']}/history", headers=h))
    assert {"skills", "location"} <= {x["field"] for x in hist[0]["changes"]} and hist[0]["rescored"] == r["rescored"]
    with app.app_context():
        from models import Application, User
        u = User.query.filter_by(email=CAND).first()
        a = Application.query.filter_by(job_id=job["id"], candidate_id=u.id).first()
        assert "Rust" in (a.match_reasons or {}).get("missing", []) and (a.match_reasons or {}).get("previous")
        old = a.match_score
    # the candidate updates their own skills from the job page: the match follows
    ch = login(c, CAND)
    added = d(c.post("/api/me/skills/add", headers=ch, json={"name": "rust", "level": 3}))
    assert added["added"] and added["rescored"] >= 1
    again = d(c.post("/api/me/skills/add", headers=ch, json={"name": "Rust"}))
    assert again["added"] is False
    with app.app_context():
        from models import Application, User
        u = User.query.filter_by(email=CAND).first()
        a = Application.query.filter_by(job_id=job["id"], candidate_id=u.id).first()
        assert "Rust" not in a.match_reasons.get("missing", []) and a.match_score >= old


def test_delete_and_archive_jobs(c):
    h = login(c, REC)
    with_apps = python_job(c)
    r = c.delete(f"/api/jobs/{with_apps['id']}", headers=h)
    assert r.status_code == 409 and r.get_json()["fields"]["code"] == "has_applications"
    draft = d(c.post("/api/jobs", headers=h, json={"title": "Mistake job", "team_id": d(c.get(f"/api/jobs/{with_apps['id']}", headers=h)).get("team_id"), "rounds": [{"type": "mcq", "name": "Screen", "config": {}}], "hires_target": 1}))
    d(c.delete(f"/api/jobs/{draft['id']}", headers=h))
    assert c.get(f"/api/jobs/{draft['id']}", headers=h).status_code in (403, 404)
    d(c.post(f"/api/jobs/{with_apps['id']}/archive", headers=h, json={"on": True}))
    assert all(x["id"] != with_apps["id"] for x in j(c.get("/api/jobs?size=100", headers=h))["items"])
    assert any(x["id"] == with_apps["id"] for x in j(c.get("/api/jobs?size=100&status=archived", headers=h))["items"])
    back = d(c.post(f"/api/jobs/{with_apps['id']}/archive", headers=h, json={"on": False}))
    assert back["status"] == "closed"
    d(c.post(f"/api/jobs/{with_apps['id']}/publish", headers=login(c, "admin@acme.test")))


# ---------------------------------------------------------------- CAN-002 / CAN-014: resume files

def test_sniff_by_content():
    from services.files import sniff
    assert sniff(b"%PDF-1.4 ...") == "pdf"
    assert sniff(b"PK\x03\x04....") == "docx"
    assert sniff(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1....") == "doc"
    assert sniff("Asha Rao, Python developer".encode()) == "txt"
    assert sniff(b"\x89PNG\r\n\x1a\n\x00\x00") is None


RESUME = b"Arjun Mehta\nBackend developer in Bengaluru, 5 years.\nSkills: Python, Django, FastAPI, PostgreSQL, Docker.\n"


def test_resume_file_kept_versioned_and_downloadable(c):
    ch = login(c, CAND)
    # a phone file manager may give a name with no extension: the content decides
    prev = d(c.post("/api/me/resume/read", headers=ch, data={"file": (io.BytesIO(RESUME), "msf:1234")}, content_type="multipart/form-data"))
    assert prev["upload_id"]
    saved = d(c.post("/api/me/resume", headers=ch, json={"text": prev["text"], "fields": prev["fields"], "upload_id": prev["upload_id"],
                                                         "add": prev["plan"]["add"], "remove": [], "fill": {}}))
    assert saved["file"]["filename"].endswith(".txt")
    me = d(c.get("/api/me", headers=ch))
    assert me["resume_file"]["id"] == saved["file"]["id"]
    got = c.get("/api/me/resume/file", headers=ch)
    assert got.status_code == 200 and got.data == RESUME
    # a second upload becomes current; the first is kept as an older version
    prev2 = d(c.post("/api/me/resume/read", headers=ch, data={"file": (io.BytesIO(RESUME + b"Kafka\n"), "cv.txt")}, content_type="multipart/form-data"))
    d(c.post("/api/me/resume", headers=ch, json={"text": prev2["text"], "fields": prev2["fields"], "upload_id": prev2["upload_id"], "add": [], "remove": [], "fill": {}}))
    me = d(c.get("/api/me", headers=ch))
    assert me["resume_file"]["filename"] == "cv.txt" and any(h["status"] == "old" for h in me["resume_history"])
    bad = c.post("/api/me/resume/read", headers=ch, data={"file": (io.BytesIO(b"\x89PNG\r\n\x1a\n\x00\x00\x00"), "photo.png")}, content_type="multipart/form-data")
    assert bad.status_code == 400


def test_staff_download_and_upload(c):
    h = login(c, REC)
    uid = d(c.get("/api/auth/me", headers=login(c, CAND)))["user"]["id"]
    got = c.get(f"/api/candidates/{uid}/resume/file", headers=h)
    assert got.status_code == 200 and b"Kafka" in got.data
    prev = d(c.post(f"/api/candidates/{uid}/resume/read", headers=h, data={"file": (io.BytesIO(RESUME), "arjun-cv.txt")}, content_type="multipart/form-data"))
    d(c.post(f"/api/candidates/{uid}/resume", headers=h, json={"text": prev["text"], "fields": prev["fields"], "upload_id": prev["upload_id"], "add": [], "remove": [], "fill": {}}))
    view = d(c.get(f"/api/candidates/{uid}/profile", headers=h))
    assert view["resume_file"]["filename"] == "arjun-cv.txt" and view["resume_file"]["by"]
    assert c.get(f"/api/candidates/{uid}/resume/file", headers=login(c, "meera@demo.test")).status_code in (401, 403, 404)


def test_ai_round_shows_resume_before_start(c):
    _, aid, ch = new_candidate(c, "res1@demo.test", "Res One", resume="Res One, data analyst. SQL, Excel, Power BI. 3 years in Pune.")
    if not any(r["type"] == "ai_interview" for r in d(c.get(f"/api/applications/{aid}", headers=login(c, REC)))["rounds"]):
        pytest.skip("the seeded job has no AI interview round")
    att = invite(c, aid, "ai_interview")
    r = d(c.get(f"/api/rounds/{att}", headers=ch))
    assert r["resume"] and r["resume"]["has_text"] and r["resume"]["file"] is None
