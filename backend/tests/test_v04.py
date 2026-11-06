"""Regression tests for V02.00.04: interview bugs BUG-001 to 007 and interview videos (NEW-001).
Each test names what it covers. Run: pytest -q  (from backend/)."""
import io
import os
import sys
import time
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("C2H_NO_AUTOCREATE", "1")
if os.environ.get("C2H_TEST_DATABASE_URL"):  # e.g. a throwaway MariaDB/MySQL database: the suite resets it
    os.environ["DATABASE_URL"] = os.environ["C2H_TEST_DATABASE_URL"]
elif "DATABASE_URL" not in os.environ or not os.environ["DATABASE_URL"].startswith("sqlite"):
    import tempfile
    os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "v04.db")
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["AZURE_SPEECH_KEY"] = ""

from tests.syscheck_helper import system_check  # noqa: E402
import seed  # noqa: E402
from app import create_app  # noqa: E402
from tests.test_e2e import make_video  # noqa: E402

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
        r = c.post("/api/auth/login", json={"email": email, "password": pw}, headers={"X-Forwarded-For": "10.4.0." + str(len(_tokens) + 1)})
        assert r.status_code == 200, r.get_json()
        _tokens[email] = {"Authorization": "Bearer " + r.get_json()["data"]["token"]}
    return _tokens[email]


def j(r, code=200):
    assert r.status_code == code, (r.status_code, r.get_json())
    return r.get_json()


def uid(c, email):
    return j(c.get("/api/auth/me", headers=login(c, email)))["data"]["user"]["id"]


def python_job(c, h):
    return next(x for x in j(c.get("/api/jobs?status=live&size=100", headers=h))["items"] if x["title"] == "Senior Python Developer")


def new_candidate(c, h, email, name, job=None):
    job = job or python_job(c, h)
    r = j(c.post("/api/candidates", headers=h, json={"name": name, "email": email, "job_id": job["id"]}))["data"]["results"][0]
    op = j(c.post(f"/api/auth/invite/{r['link'].split('/')[-1]}/open"))["data"]
    return job, r["application_id"], {"Authorization": "Bearer " + op["token"]}


def live_round(c, email, name, cfg=None):
    """A candidate invited to the job's live round with Priya as interviewer. Returns (attempt_id, candidate headers, job)."""
    h = login(c, "rahul@acme.test")
    job, aid, ch = new_candidate(c, h, email, name)
    f2f = next(i for i, r in enumerate(job["rounds"]) if r["type"] in ("f2f_isha", "f2f_human"))
    if cfg:
        full = j(c.get(f"/api/jobs/{job['id']}", headers=h))["data"]
        rounds = [{**r, "config": {**(r.get("config") or {}), **cfg}} if i == f2f else r for i, r in enumerate(full["rounds"])]
        j(c.patch(f"/api/jobs/{job['id']}", headers=h, json={"rounds": rounds}))
    att = j(c.post(f"/api/applications/{aid}/invite", headers=h, json={"round_index": f2f, "interviewer_id": uid(c, "priya@acme.test")}))["data"]["attempt_id"]
    return att, ch, job


def chunk(c, h, att, seg, seq, data, seconds):
    return c.post(f"/api/recordings/{att}/chunk", headers=h, content_type="multipart/form-data",
                  data={"segment": seg, "seq": str(seq), "mime": "video/webm", "seconds": str(seconds), "file": (io.BytesIO(data), "c.webm")})


# ---------------------------------------------------------------- BUG-006, BUG-007: settings limits

@pytest.mark.parametrize("bad", [0, 1, -1, 7, 99999, "abc", 2.5, True, None])
def test_options_shown_limit_every_level_BUG_007(c, bad):
    sa, admin = login(c, "super@code2hire.ai"), login(c, "admin@acme.test")
    r = c.put("/api/platform/settings", headers=sa, json={"key": "isha.options", "value": bad})
    assert r.status_code == 400 and "isha.options" in r.get_json()["fields"], r.get_json()
    r = c.put("/api/company/settings", headers=admin, json={"scope": "company", "key": "isha.options", "value": bad})
    assert r.status_code == 400
    job = python_job(c, login(c, "rahul@acme.test"))
    r = c.put("/api/company/settings", headers=admin, json={"scope": "job", "id": job["id"], "key": "isha.options", "value": bad})
    assert r.status_code == 400


def test_number_settings_have_ranges_and_good_values_save_BUG_006(c):
    admin = login(c, "admin@acme.test")
    rows = j(c.get("/api/company/settings", headers=admin))["data"]
    ints = [r for r in rows if r["type"] == "int"]
    assert ints and all("min" in r and "max" in r and r["unit"] for r in ints)  # every number setting has limits
    for key, bad in (("mcq.questions", -5), ("interview.minutes", 0), ("integrity.warnings_allowed", -1), ("invite.link_days", 400)):
        assert c.put("/api/company/settings", headers=admin, json={"scope": "company", "key": key, "value": bad}).status_code == 400
    rows = j(c.put("/api/company/settings", headers=admin, json={"scope": "company", "key": "isha.options", "value": 5}))["data"]
    assert next(r for r in rows if r["key"] == "isha.options")["value"] == 5
    j(c.put("/api/company/settings", headers=admin, json={"scope": "company", "key": "isha.options", "reset": True}))


def test_choice_text_and_cross_checks_BUG_006(c):
    admin = login(c, "admin@acme.test")
    put = lambda k, v: c.put("/api/company/settings", headers=admin, json={"scope": "company", "key": k, "value": v})  # noqa: E731
    assert put("report.scale", 7).status_code == 400            # choices only
    assert put("interview.difficulty", "extreme").status_code == 400
    assert put("brand.color", "red").status_code == 400
    assert put("call.turn_url", "x" * 400).status_code == 400   # text length
    assert put("integrity.instant_pause", ["anything"]).status_code == 400
    r = put("pass.reject", 90)                                     # auto-reject above auto-advance (70)
    assert r.status_code == 400 and "auto-advance" in r.get_json()["error"]
    r = put("mcq.minutes", 2)                                      # 10 questions in 2 minutes
    assert r.status_code == 400 and "minutes" in r.get_json()["error"]


def test_round_config_is_checked_and_old_bad_values_are_clamped_BUG_006_007(c):
    h = login(c, "rahul@acme.test")
    job = j(c.get(f"/api/jobs/{python_job(c, h)['id']}", headers=h))["data"]
    f2f = next(i for i, r in enumerate(job["rounds"]) if r["type"].startswith("f2f"))
    bad = [{**r, "config": {"isha.options": 50000}} if i == f2f else r for i, r in enumerate(job["rounds"])]
    r = c.patch(f"/api/jobs/{job['id']}", headers=h, json={"rounds": bad})
    assert r.status_code == 400 and "Round" in r.get_json()["error"]
    # a value saved before the limits existed is read back inside them
    from extensions import db
    from models import Setting
    from services.settings import resolve
    with c.application.app_context():
        db.session.add(Setting(scope_type="company", scope_id=job["company_id"], key="isha.options", value=-5))
        db.session.commit()
        assert resolve("isha.options", company_id=job["company_id"])[0] == 2
        Setting.query.filter_by(scope_type="company", key="isha.options").delete()
        db.session.commit()
    meta = job["rounds_resolved"][f2f]["meta"]["isha.options"]
    assert meta["min"] == 2 and meta["max"] == 6


# ---------------------------------------------------------------- BUG-001: F2F question count and own questions

def test_f2f_plan_has_the_configured_count_and_own_questions_first_BUG_001(c):
    own = ["Why do you want to join us?", "Tell me about your last project, briefly."]
    att, ch, job = live_round(c, "count.cand@mail.test", "Kiran Das", {"f2f.questions": 20, "f2f.own_questions": own})
    room = j(c.get(f"/api/isha/{att}", headers=login(c, "priya@acme.test")))["data"]
    areas = room["brief"]["areas"]
    assert len(areas) == 20                                         # not 7
    assert [a["q"] for a in areas[:2]] == own and areas[-1]["area"] == "Wrap-up"
    assert len({a["area"] for a in areas}) == 20 and len({a["q"] for a in areas}) == 20
    # more own questions than the count is refused when saving the round
    h = login(c, "rahul@acme.test")
    full = j(c.get(f"/api/jobs/{job['id']}", headers=h))["data"]
    f2f = next(i for i, r in enumerate(full["rounds"]) if r["type"].startswith("f2f"))
    too_many = [{**r, "config": {"f2f.questions": 2, "f2f.own_questions": ["a question one", "a question two", "a question three"]}} if i == f2f else r
                for i, r in enumerate(full["rounds"])]
    assert c.patch(f"/api/jobs/{job['id']}", headers=h, json={"rounds": too_many}).status_code == 400
    j(c.patch(f"/api/jobs/{job['id']}", headers=h, json={"rounds": [{**r, "config": {}} if i == f2f else r for i, r in enumerate(full["rounds"])]}))


def test_plan_reorder_skip_and_add_during_interview_BUG_001(c):
    att, ch, job = live_round(c, "plan.cand@mail.test", "Plan Cand")
    p = login(c, "priya@acme.test")
    areas = j(c.get(f"/api/isha/{att}", headers=p))["data"]["brief"]["areas"]
    assert len(areas) == 7                                          # the default
    names = [a["area"] for a in areas]
    out = j(c.post(f"/api/isha/{att}/plan", headers=p, json={"order": [names[1], names[0]] + names[2:]}))["data"]
    assert [a["area"] for a in out["brief"]["areas"]][:2] == [names[1], names[0]]
    out = j(c.post(f"/api/isha/{att}/plan", headers=p, json={"skip": names[2]}))["data"]
    assert out["state"]["coverage"]["skipped"] == 1
    out = j(c.post(f"/api/isha/{att}/plan", headers=p, json={"add": "How do you review a teammate's code?"}))["data"]
    assert any(a.get("own") and "review" in a["q"] for a in out["brief"]["areas"])
    assert out["brief"]["areas"][-1]["area"] == "Wrap-up"


def test_ai_interview_plan_has_exactly_the_main_questions(c):
    from services.ai import interview_plan
    from models import Job
    with c.application.app_context():
        for n in (1, 5, 12):
            plan = interview_plan(Job(title="Dev", level="Mid", skills=[{"name": "Python"}], plan={}), "", n)
            assert len(plan["questions"]) == n and len({q["q"] for q in plan["questions"]}) == n


# ---------------------------------------------------------------- BUG-002: leaving vs ending

def test_leave_call_does_not_end_the_interview_BUG_002(c):
    att, ch, job = live_round(c, "leave.cand@mail.test", "Leave Cand")
    p = login(c, "priya@acme.test")
    j(c.post(f"/api/isha/{att}/start", headers=p))
    cur = j(c.get(f"/api/call/{att}", headers=ch))["data"]["cursor"]
    j(c.post(f"/api/call/{att}/signal", headers=p, json={"kind": "bye", "payload": {}}))   # Leave call
    got = j(c.get(f"/api/call/{att}/signal?after={cur}", headers=ch))["data"]
    assert got["signals"][-1]["kind"] == "bye" and not got["signals"][-1]["payload"].get("ended")
    assert not got["ended"] and got["status"] == "in_progress"
    assert j(c.get(f"/api/call/{att}", headers=ch))["data"]["can_join"]                    # the candidate can stay / rejoin
    # the candidate can't end it for both
    j(c.post(f"/api/call/{att}/signal", headers=ch, json={"kind": "bye", "payload": {"ended": True}}))
    pg = j(c.get(f"/api/call/{att}/signal?after=0", headers=p))["data"]
    assert all(not s["payload"].get("ended") for s in pg["signals"] if s["kind"] == "bye")
    # End interview: the candidate's room is told, and joining is closed
    j(c.post(f"/api/isha/{att}/end", headers=p))
    got = j(c.get(f"/api/call/{att}/signal?after={cur}", headers=ch))["data"]
    assert got["ended"] and any(s["kind"] == "bye" and s["payload"].get("ended") for s in got["signals"])
    info = j(c.get(f"/api/call/{att}", headers=ch))["data"]
    assert info["ended"] and not info["can_join"]
    assert c.post(f"/api/call/{att}/signal", headers=ch, json={"kind": "chat", "payload": {"text": "hi"}}).status_code == 409


def test_both_away_30_minutes_closes_as_not_finished_BUG_002(c):
    att, ch, job = live_round(c, "away.cand@mail.test", "Away Cand")
    p = login(c, "priya@acme.test")
    j(c.post(f"/api/isha/{att}/start", headers=p))
    from extensions import db
    from models import Notification, RoundAttempt
    from services import housekeeping
    from routes import call as call_routes
    with c.application.app_context():
        a = db.session.get(RoundAttempt, att)
        old = time.time() - 31 * 60
        a.result = {**(a.result or {}), "call": {"candidate_seen": old, "interviewer_seen": old}}
        db.session.commit()
        call_routes._seen.clear()
        assert housekeeping.close_abandoned_calls() >= 1
        a = db.session.get(RoundAttempt, att)
        assert a.status == "not_finished" and a.result["closed"]["reason"] == "both_left"
        assert Notification.query.filter(Notification.title == "Interview closed as not finished").count() >= 1
    # the interviewer can still submit the scorecard
    draft = j(c.post(f"/api/isha/{att}/end", headers=p))["data"]["draft"]
    j(c.post(f"/api/isha/{att}/scorecard", headers=p, json={"competencies": [{**x, "score": 3} for x in draft["competencies"]], "recommendation": "hold"}))


# ---------------------------------------------------------------- BUG-003: live integrity

def test_live_tab_switch_is_counted_never_paused_and_reaches_the_interviewer_BUG_003(c):
    att, ch, job = live_round(c, "tab.cand@mail.test", "Tab Cand")
    p = login(c, "priya@acme.test")
    system_check(c, att, ch)
    j(c.post(f"/api/rounds/{att}/consent", headers=ch, json={}))
    j(c.post(f"/api/isha/{att}/start", headers=p))
    cur = j(c.get(f"/api/call/{att}", headers=p))["data"]["cursor"]
    for _ in range(5):
        r = j(c.post(f"/api/rounds/{att}/integrity", headers=ch, json={"type": "tab_switch"}))["data"]
        assert r["counted"] and not r["paused"]
    assert r["warnings"] == 5 and r["status"] == "in_progress" and "interviewer" in r["message"]
    for et in ("copy_paste", "fullscreen_exit", "multi_face"):
        assert j(c.post(f"/api/rounds/{att}/integrity", headers=ch, json={"type": et}))["data"]["counted"]
    sig = j(c.get(f"/api/call/{att}/signal?after={cur}", headers=p))["data"]["signals"]
    live = [s for s in sig if s["kind"] == "integrity"]
    assert len(live) == 8 and live[0]["payload"]["label"] == "Switched tab or app"
    room = j(c.get(f"/api/isha/{att}", headers=p))["data"]
    assert len(room["integrity"]) == 8                              # the panel after a reload
    # the focus notice no longer adds an uncounted duplicate
    j(c.post(f"/api/call/{att}/signal", headers=ch, json={"kind": "focus", "payload": {"visible": False}}))
    assert len(j(c.get(f"/api/isha/{att}", headers=p))["data"]["integrity"]) == 8


# ---------------------------------------------------------------- NEW-001: interview videos

def test_video_chunks_retries_gaps_and_access_NEW_001(c):
    att, ch, job = live_round(c, "video.cand@mail.test", "Video Cand")
    p, rahul = login(c, "priya@acme.test"), login(c, "rahul@acme.test")
    assert j(c.get(f"/api/call/{att}", headers=ch))["data"]["record"] is True   # always recorded
    assert chunk(c, p, att, "a1", 0, b"x" * 100, 10).status_code == 409         # not running yet
    j(c.post(f"/api/isha/{att}/start", headers=p))
    data = make_video(4)
    parts = [data[: len(data) // 3], data[len(data) // 3: 2 * len(data) // 3], data[2 * len(data) // 3:]]
    j(chunk(c, p, att, "a1", 0, parts[0], 1.3))
    again = j(chunk(c, p, att, "a1", 0, parts[0], 1.3))["data"]               # a retried chunk isn't stored twice
    assert again.get("duplicate")
    r = chunk(c, p, att, "a1", 2, parts[2], 4)                                 # a missing chunk is asked for
    assert r.status_code == 409 and r.get_json()["fields"]["expected"] == 1
    j(chunk(c, p, att, "a1", 1, parts[1], 2.6))
    j(chunk(c, p, att, "a1", 2, parts[2], 4))
    # the candidate's backup copy, recorded as its own side
    j(chunk(c, ch, att, "b1", 0, data, 4))
    assert chunk(c, ch, att, "a1", 3, b"x", 5).status_code == 403              # can't write into the interviewer's piece
    j(c.post(f"/api/recordings/{att}/finish", headers=p, json={"segment": "a1"}))
    j(c.post(f"/api/recordings/{att}/finish", headers=ch, json={"segment": "b1"}))
    v = j(c.get(f"/api/recordings/{att}", headers=rahul))["data"]
    assert v["status"] == "ready" and {x["side"] for x in v["pieces"]} == {"interviewer", "candidate"}
    main = next(x for x in v["pieces"] if x["side"] == "interviewer")
    vid = c.get(f"/api/recordings/{att}/{main['id']}/video", headers=rahul)
    assert vid.status_code == 200 and vid.data[:4] == b"\x1aE\xdf\xa3"          # a real webm
    if __import__("shutil").which("ffprobe"):
        assert 3 <= (main["seconds"] or 0) <= 5                                # remuxed: duration known, seekable
    # who can watch: the hiring team; never the candidate; never another company
    assert c.get(f"/api/recordings/{att}", headers=ch).status_code == 403
    assert c.get(f"/api/recordings/{att}/{main['id']}/video", headers=ch).status_code == 403
    sa = login(c, "super@code2hire.ai")
    j(c.post("/api/platform/companies", headers=sa, json={"name": "Delta Works", "admin_email": "boss@delta.test", "admin_name": "Dev Shah", "admin_password": "Delta2026pass"}))
    assert c.get(f"/api/recordings/{att}", headers=login(c, "boss@delta.test", "Delta2026pass")).status_code == 403
    # downloading needs its own permission (company admin has it, the recruiter doesn't)
    assert c.get(f"/api/recordings/{att}/{main['id']}/video?download=1", headers=rahul).status_code == 403
    assert c.get(f"/api/recordings/{att}/{main['id']}/video?download=1", headers=login(c, "admin@acme.test")).status_code == 200
    # every viewing is logged
    from models import AuditLog
    with c.application.app_context():
        assert AuditLog.query.filter(AuditLog.action.in_(("recording.view", "recording.download"))).count() >= 2


def test_video_timeline_fills_gaps_from_the_backup_NEW_001(c):
    from extensions import db
    from models import Recording, RoundAttempt
    from routes.recordings import _timeline
    with c.application.app_context():
        att = RoundAttempt(round_type="f2f_isha", status="completed", started_at=datetime(2026, 11, 5, 10, 0, 0), config={}, result={})
        t0 = att.started_at
        recs = [Recording(id=1, side="interviewer", segment="m1", started_at=t0, seconds=600, status="ready"),
                Recording(id=2, side="interviewer", segment="m2", started_at=t0 + timedelta(seconds=900), seconds=300, status="ready"),
                Recording(id=3, side="candidate", segment="b1", started_at=t0 + timedelta(seconds=650), seconds=200, status="ready")]
        parts, gaps = _timeline(att, recs)
        assert [(p["id"], p["from"], p["to"]) for p in parts] == [(1, 0, 600), (3, 650, 850), (2, 900, 1200)]
        assert gaps == [{"from": 600, "to": 650}, {"from": 850, "to": 900}]
        db.session.rollback()


def test_ai_interview_is_recorded_by_the_candidate_and_decline_blocks_start_NEW_001(c):
    h = login(c, "rahul@acme.test")
    job, aid, ch = new_candidate(c, h, "ai.video@mail.test", "Ai Video")
    ai_idx = next(i for i, r in enumerate(job["rounds"]) if r["type"] == "ai_interview")
    att = j(c.post(f"/api/applications/{aid}/invite", headers=h, json={"round_index": ai_idx}))["data"]["attempt_id"]
    a = j(c.get(f"/api/rounds/{att}", headers=ch))["data"]
    assert a["record"] is True
    system_check(c, att, ch)
    j(c.post(f"/api/rounds/{att}/consent", headers=ch, json={}))
    j(c.post(f"/api/rounds/{att}/start", headers=ch))
    j(chunk(c, ch, att, "c1", 0, make_video(2), 2))
    j(c.post(f"/api/recordings/{att}/finish", headers=ch, json={"segment": "c1"}))
    v = j(c.get(f"/api/recordings/{att}", headers=h))["data"]
    assert v["status"] == "ready" and v["parts"][0]["side"] == "candidate"
    assert any(m["kind"] == "question" for m in v["markers"])                  # Hira's questions on the timeline
    # another candidate says no to recording: the interview can't start and the team is told
    job, aid2, ch2 = new_candidate(c, h, "no.video@mail.test", "No Video")
    att2 = j(c.post(f"/api/applications/{aid2}/invite", headers=h, json={"round_index": ai_idx}))["data"]["attempt_id"]
    j(c.post(f"/api/recordings/{att2}/declined", headers=ch2))
    system_check(c, att2, ch2)
    j(c.post(f"/api/rounds/{att2}/consent", headers=ch2, json={}))
    assert c.post(f"/api/rounds/{att2}/start", headers=ch2).status_code == 409
    from models import Notification
    with c.application.app_context():
        assert Notification.query.filter_by(title="Candidate declined recording").count() >= 1
    v2 = j(c.get(f"/api/recordings/{att2}", headers=h))["data"]
    assert v2["status"] == "none" and "declined" in v2["reason"]


def test_idle_pieces_are_finished_and_old_videos_deleted_NEW_001(c):
    att, ch, job = live_round(c, "idle.cand@mail.test", "Idle Cand")
    p = login(c, "priya@acme.test")
    j(c.post(f"/api/isha/{att}/start", headers=p))
    j(chunk(c, p, att, "z1", 0, make_video(2), 2))                             # then the browser crashed: no finish call
    from extensions import db
    from models import Recording
    from routes.recordings import finish_idle, purge_expired
    from services import storage
    with c.application.app_context():
        rec = Recording.query.filter_by(attempt_id=att, segment="z1").first()
        rec.last_at = datetime.utcnow() - timedelta(minutes=5)
        db.session.commit()
        assert finish_idle() >= 1
        rec = Recording.query.filter_by(attempt_id=att, segment="z1").first()
        assert rec.status == "ready" and rec.file_key
        path = storage.local_path(rec.file_key)
        assert os.path.exists(path)
        rec.created_at = datetime.utcnow() - timedelta(days=181)               # older than the 180-day default
        db.session.commit()
        assert purge_expired() >= 1
        rec = Recording.query.filter_by(attempt_id=att, segment="z1").first()
        assert rec.status == "deleted" and not os.path.exists(path)
    v = j(c.get(f"/api/recordings/{att}", headers=login(c, "rahul@acme.test")))["data"]
    assert v["status"] == "none" and "retention" in v["reason"]


def test_retention_setting_limits(c):
    admin = login(c, "admin@acme.test")
    assert c.put("/api/company/settings", headers=admin, json={"scope": "company", "key": "recording.retention_days", "value": 10}).status_code == 400
    j(c.put("/api/company/settings", headers=admin, json={"scope": "company", "key": "recording.retention_days", "value": 90}))


# ---------------------------------------------------------------- BUG-004: MCQ picking

def _mcq_bank_company(c, n_questions):
    """A fresh company with exactly n distinct SQL questions (and a few copies of them) in its bank."""
    from extensions import db
    from models import Application, Company, Job, Question, User
    from services.perms import hash_password
    with c.application.app_context():
        co = Company(name=f"Bank Co {n_questions}-{time.time()}", domain="bank.test", plan="employer", status="active", credits_total=999)
        db.session.add(co)
        db.session.flush()
        job = Job(company_id=co.id, title="SQL Analyst", status="live", skills=[{"name": "ZetaSQL", "level": 3}],
                  rounds=[{"type": "mcq", "name": "Screen", "config": {}}], rubric=[], plan={})
        db.session.add(job)
        for i in range(n_questions):
            db.session.add(Question(company_id=co.id, skill="ZetaSQL", level=3, text=f"ZetaSQL question number {i}?",
                                    options=["a", "b", "c", "d"], answer=0, status="approved"))
        for i in range(3):  # copies: same text, different case and spacing
            db.session.add(Question(company_id=co.id, skill="ZetaSQL", level=3, text=f"zetasql  QUESTION number {i} ?",
                                    options=["a", "b", "c", "d"], answer=0, status="approved"))
        cand = User(email=f"mcq{n_questions}.{int(time.time() * 1000)}@mail.test", name="Mcq Cand", kind="candidate", password_hash=hash_password(PW))
        db.session.add(cand)
        db.session.flush()
        app_ = Application(job_id=job.id, candidate_id=cand.id, stage="applied")
        db.session.add(app_)
        db.session.commit()
        return co.id, job.id, app_.id, cand.id, cand.email


def _mcq_attempt(c, app_id, n):
    from extensions import db
    from models import RoundAttempt
    with c.application.app_context():
        att = RoundAttempt(application_id=app_id, round_index=0, round_type="mcq", status="invited",
                           config={"mcq.questions": n, "mcq.minutes": 30, "mcq.randomise": True, "mcq.ai_review": True}, result={})
        db.session.add(att)
        db.session.commit()
        return att.id


def test_mcq_never_repeats_in_a_test_and_retakes_get_new_questions_BUG_004(c):
    co, job, app_id, cand, email = _mcq_bank_company(c, 25)
    ch = login(c, email)
    for _ in range(40):  # many tests from one bank
        att = _mcq_attempt(c, app_id, 10)
        system_check(c, att, ch)
        j(c.post(f"/api/rounds/{att}/consent", headers=ch, json={}))
        qs = j(c.post(f"/api/rounds/{att}/start", headers=ch))["data"]["questions"]
        texts = [" ".join(q["text"].lower().replace("?", " ").split()) for q in qs]
        assert len(qs) == 10 and len(set(texts)) == 10
        from extensions import db
        from models import RoundAttempt
        with c.application.app_context():
            a = db.session.get(RoundAttempt, att)
            a.status = "completed"
            db.session.commit()
    # retake: the questions from the previous attempts come last, so with 25 distinct, two tests in a row don't overlap
    co, job, app_id, cand, email = _mcq_bank_company(c, 25)
    ch = login(c, email)
    seen = []
    for _ in range(2):
        att = _mcq_attempt(c, app_id, 10)
        system_check(c, att, ch)
        j(c.post(f"/api/rounds/{att}/consent", headers=ch, json={}))
        seen.append({q["text"] for q in j(c.post(f"/api/rounds/{att}/start", headers=ch))["data"]["questions"]})
    assert not (seen[0] & seen[1])


def test_mcq_short_bank_gives_a_shorter_test_never_copies_BUG_004(c):
    co, job, app_id, cand, email = _mcq_bank_company(c, 3)
    ch = login(c, email)
    att = _mcq_attempt(c, app_id, 10)
    system_check(c, att, ch)
    j(c.post(f"/api/rounds/{att}/consent", headers=ch, json={}))
    qs = j(c.post(f"/api/rounds/{att}/start", headers=ch))["data"]["questions"]
    norm = lambda t: " ".join(__import__("re").sub(r"[^\w\s]", " ", t.lower()).split())  # noqa: E731
    assert len({norm(q["text"]) for q in qs}) == len(qs)                       # no copies, whatever the count
    from extensions import db
    from models import Question
    with c.application.app_context():
        texts = [norm(q.text) for q in Question.query.filter(Question.company_id == co, Question.status != "archived").all()]
        new = Question.query.filter_by(company_id=co, source="ai").all()
        assert all(q.status == "pending" for q in new)                         # AI questions wait for review
        # nothing AI wrote duplicates the bank
        assert len([t for t in texts if texts.count(t) > 1]) == 6                # only the 3 planted copies (x2)
        from models import RoundAttempt
        info = db.session.get(RoundAttempt, att).result["mcq_info"]
        assert info["got"] == len(qs) and info["short"] == (len(qs) < 10) and info["generated"] >= 1


def test_mcq_generate_skips_text_already_in_the_bank_BUG_004(c):
    from extensions import db
    from services.mcq import save_generated
    co, job, app_id, cand, email = _mcq_bank_company(c, 2)
    with c.application.app_context():
        out = save_generated([{"text": "ZetaSQL question number 0?", "options": ["a", "b"], "answer": 0},
                              {"text": "A brand new ZetaSQL question?", "options": ["a", "b", "c"], "answer": 1},
                              {"text": "a brand NEW zetasql question", "options": ["a", "b"], "answer": 0},
                              {"text": "Bad options?", "options": ["same", "same"], "answer": 0}], co, ["ZetaSQL"])
        assert [q.text for q in out] == ["A brand new ZetaSQL question?"] and out[0].status == "pending"
        db.session.rollback()


def test_mcq_coverage_preview_BUG_004(c):
    h = login(c, "rahul@acme.test")
    job = python_job(c, h)
    idx = next(i for i, r in enumerate(job["rounds"]) if r["type"] == "mcq")
    cov = j(c.get(f"/api/jobs/{job['id']}/rounds/{idx}/coverage?questions=10", headers=h))["data"]
    assert cov["available"] >= 1 and "available" in cov["message"] or "Only" in cov["message"]
    big = j(c.get(f"/api/jobs/{job['id']}/rounds/{idx}/coverage?questions=100", headers=h))["data"]
    assert big["short"]


# ---------------------------------------------------------------- BUG-005: PDFs

def test_report_and_feedback_and_certificate_pdfs_BUG_005(c):
    from extensions import db
    from models import Application, Credential, Report, RoundAttempt, User
    with c.application.app_context():
        cand = User.query.filter_by(email="arjun@demo.test").first()
        app_ = Application.query.filter_by(candidate_id=cand.id).first()
        att = RoundAttempt(application_id=app_.id, round_index=0, round_type="mcq", status="completed", score=80.0,
                           completed_at=datetime.utcnow(), config={}, result={})
        db.session.add(att)
        db.session.flush()
        r = Report(attempt_id=att.id, status="shared", overall=4.0, recommendation="proceed", shared_with_candidate=True,
                   sections={"kind": "mcq", "summary": "Strong SQL — ✓ joins", "strengths": ["SQL"], "gaps": ["Indexes"],
                             "questions": [{"q": "What is a JOIN?", "correct": True, "chosen": 1}]})
        db.session.add(r)
        cr = Credential(code="C2H-TEST-PDF1", user_id=cand.id, kind="certificate", title="SQL Professional", level=3, grade="A", issuer="Code2Hire")
        db.session.add(cr)
        db.session.commit()
        rid, att_id = r.id, att.id
    rahul, arjun = login(c, "rahul@acme.test"), login(c, "arjun@demo.test")
    for aud in ("internal", "client", "candidate"):
        res = c.get(f"/api/reports/{rid}/pdf?audience={aud}", headers=rahul)
        assert res.status_code == 200 and res.mimetype == "application/pdf" and res.data[:5] == b"%PDF-", aud
    fb = j(c.get("/api/me/feedback", headers=arjun))["data"]
    mine = next(x for x in fb if x["id"] == rid)
    assert mine["pdf"] and mine["result"]["score"] == 4.0 and "overall" not in mine
    res = c.get(f"/api/me/feedback/{rid}/pdf", headers=arjun)
    assert res.status_code == 200 and res.data[:5] == b"%PDF-"
    assert c.get(f"/api/me/feedback/{rid}/pdf", headers=login(c, "meera@demo.test")).status_code == 404   # only your own
    res = c.get("/api/me/credentials/C2H-TEST-PDF1/pdf", headers=arjun)
    assert res.status_code == 200 and res.data[:5] == b"%PDF-"
    assert c.get("/api/me/credentials/C2H-TEST-PDF1/pdf", headers=login(c, "meera@demo.test")).status_code == 404
    # the company can switch candidate downloads off
    admin = login(c, "admin@acme.test")
    j(c.put("/api/company/settings", headers=admin, json={"scope": "company", "key": "report.candidate_pdf", "value": False}))
    assert c.get(f"/api/me/feedback/{rid}/pdf", headers=arjun).status_code == 403
    j(c.put("/api/company/settings", headers=admin, json={"scope": "company", "key": "report.candidate_pdf", "reset": True}))


# ---------------------------------------------------------------- version

def test_version_in_health(c):
    assert c.get("/api/health").get_json()["version"].startswith("V02.00.")
