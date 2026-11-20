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
    os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "v12.db")
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["AZURE_SPEECH_KEY"] = ""

from tests.syscheck_helper import system_check  # noqa: E402
import seed  # noqa: E402
from app import create_app  # noqa: E402

PW = seed.PW
PAPER_REVIEW = True  # the real default, which V02.00.12 locks on


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
        r = c.post("/api/auth/login", json={"email": email, "password": pw}, headers={"X-Forwarded-For": "10.30.0." + str(len(_tokens) + 1)})
        assert r.status_code == 200, r.get_json()
        _tokens[email] = {"Authorization": "Bearer " + r.get_json()["data"]["token"]}
    return _tokens[email]


def j(r, code=200):
    assert r.status_code == code, (r.status_code, r.get_json())
    return r.get_json()


def d(r, code=200):
    return j(r, code)["data"]


REC = "rahul@acme.test"
IV = "anita@acme.test"  # interviewer only


def python_job(c):
    return next(x for x in j(c.get("/api/jobs?size=100", headers=login(c, REC)))["items"] if x["title"] == "Senior Python Developer")


def new_candidate(c, email, name):
    job = python_job(c)
    r = d(c.post("/api/candidates", headers=login(c, REC), json={"name": name, "email": email, "job_id": job["id"]}))["results"][0]
    op = d(c.post(f"/api/auth/invite/{r['link'].split('/')[-1]}/open"))
    return job, r["application_id"], {"Authorization": "Bearer " + op["token"]}


def invite(c, aid, kind="mcq"):
    full = d(c.get(f"/api/applications/{aid}", headers=login(c, REC)))
    idx = next(i for i, r in enumerate(full["rounds"]) if r["type"] == kind)
    return d(c.post(f"/api/applications/{aid}/invite", headers=login(c, REC), json={"round_index": idx}))["attempt_id"]


def items(x):
    x = x.get("data", x) if isinstance(x, dict) else x
    return x["items"] if isinstance(x, dict) and "items" in x else x


def test_version_is_v02_00_12(c):
    assert j(c.get("/api/health"))["version"].startswith("V02.")


# ---------------------------------------------------------------- A5: reading Claude's JSON

def test_parser_reads_code_fences_inside_strings_and_salvages_truncation():
    from services.ai import _parse
    reply = 'Here you go:\n```json\n[{"text": "What does this print?", "code": "```py\\nprint(1)\\n```", "answer": 2}]\n```'
    assert _parse(reply)[0]["answer"] == 2
    cut = '[{"text": "one", "answer": 0}, {"text": "two", "answer": 3}, {"text": "thr'
    out = _parse(cut)
    assert [q["text"] for q in out] == ["one", "two"]
    assert _parse('{"areas": [{"area": "A"}], "gaps": ["x", "y')["areas"] == [{"area": "A"}]


# ---------------------------------------------------------------- A2: answers no longer all B

def test_shuffle_spreads_answers_and_keeps_the_right_option():
    from services.mcq import shuffle_entry
    q = {"text": "t", "options": ["w1", "right", "w2", "w3"], "answer": 1}
    rng = random.Random(7)
    pos = Counter()
    for _ in range(400):
        s = shuffle_entry(q, rng)
        assert s["options"][s["answer"]] == "right" and sorted(s["options"]) == sorted(q["options"])
        assert [q["options"][i] for i in s["option_order"]] == s["options"]
        pos[s["answer"]] += 1
    assert all(60 < pos[k] < 140 for k in range(4)), pos
    fixed = {"options": ["a", "b", "c", "All of the above"], "answer": 3}
    for _ in range(20):
        assert shuffle_entry(fixed, rng)["options"][3] == "All of the above"


def test_seed_bank_is_balanced(app):
    from models import Question
    with app.app_context():
        qs = Question.query.filter(Question.status == "approved").all()
        pos = Counter(q.answer for q in qs)
        assert len(qs) >= 20 and max(pos.values()) <= len(qs) * 0.4, pos


def test_fallback_questions_are_not_all_b(app):
    from services.ai import generate_mcq
    with app.app_context():
        qs = generate_mcq(["Python", "SQL"], n=8)
    assert len({q["answer"] for q in qs}) >= 3
    assert all(q["options"][q["answer"]] for q in qs)


def test_hiring_paper_is_shuffled_and_grades_on_the_shuffled_order(c):
    _, aid, ch = new_candidate(c, "shuf1@demo.test", "Shuf One")
    att = invite(c, aid)
    paper = d(c.get(f"/api/rounds/{att}/paper", headers=login(c, REC)))
    assert paper["questions"] and all(q["id"] > 0 for q in paper["questions"])  # no built-in fillers in a hiring paper
    d(c.post(f"/api/rounds/{att}/paper/approve", headers=login(c, REC)))
    system_check(c, att, ch)
    j(c.post(f"/api/rounds/{att}/consent", headers=ch, json={}))
    shown = d(c.post(f"/api/rounds/{att}/start", headers=ch))["questions"]
    right = {q["id"]: q["answer"] for q in paper["questions"]}
    for q in shown:  # the candidate sees the same order the reviewer approved
        p = next(x for x in paper["questions"] if x["id"] == q["id"])
        assert q["options"] == p["options"] and "answer" not in q
        j(c.post(f"/api/rounds/{att}/answer", headers=ch, json={"qid": q["id"], "choice": right[q["id"]]}))
    d(c.post(f"/api/rounds/{att}/submit", headers=ch, json={"reason": "submitted"}))
    from extensions import db
    from models import RoundAttempt
    with c.application.app_context():
        assert db.session.get(RoundAttempt, att).score == 100


# ---------------------------------------------------------------- A1: approvals reachable; review locked on

def test_review_setting_is_locked_on(c):
    from services.settings import DEFAULTS, check_value
    assert DEFAULTS["mcq.review_before_start"][0] is True and DEFAULTS["mcq.review_before_start"][3] == "locked"
    assert check_value("mcq.review_before_start", False) == (True, None)
    c.put("/api/company/settings", headers=login(c, "admin@acme.test"), json={"scope": "company", "key": "mcq.review_before_start", "value": False})
    _, aid, ch = new_candidate(c, "lock1@demo.test", "Lock One")
    att = invite(c, aid)
    assert d(c.get(f"/api/rounds/{att}", headers=ch))["paper_pending"] is True  # still reviewed


def test_papers_waiting_approve_all_and_interviewer_can_review(c):
    job, aid1, ch1 = new_candidate(c, "wait1@demo.test", "Wait One")
    _, aid2, _ = new_candidate(c, "wait2@demo.test", "Wait Two")
    a1, a2 = invite(c, aid1), invite(c, aid2)
    w = d(c.get("/api/papers/waiting", headers=login(c, REC)))
    assert {a1, a2} <= {x["attempt_id"] for x in w}
    # an interviewer may review papers too (A1)
    iv = d(c.get("/api/papers/waiting", headers=login(c, IV)))
    assert {a1, a2} <= {x["attempt_id"] for x in iv}
    # Today shows a "paper" card
    today = d(c.get("/api/inbox/today", headers=login(c, REC)))
    cards = today.get("cards", today) if isinstance(today, dict) else today
    assert any(x.get("kind") == "paper" for x in cards)
    out = d(c.post(f"/api/jobs/{job['id']}/papers/approve-all", headers=login(c, REC)))
    assert out["approved"] >= 2
    assert not {a1, a2} & {x["attempt_id"] for x in d(c.get("/api/papers/waiting", headers=login(c, REC)))}
    assert c.post(f"/api/jobs/{job['id']}/papers/approve-all", headers=ch1).status_code in (401, 403)


def test_fill_asks_hira_for_more_and_never_pads_with_fillers(c):
    _, aid, _ = new_candidate(c, "fill1@demo.test", "Fill One")
    att = invite(c, aid)
    r = c.post(f"/api/rounds/{att}/paper/fill", headers=login(c, REC))
    assert r.status_code in (200, 400, 409)
    p = d(c.get(f"/api/rounds/{att}/paper", headers=login(c, REC)))
    assert all(q["id"] > 0 for q in p["questions"])


# ---------------------------------------------------------------- B4 / B5: the job's people are told

def test_invite_records_who_sent_it_and_pause_reaches_the_job_team(c, app):
    _, aid, ch = new_candidate(c, "team1@demo.test", "Team One")
    att = invite(c, aid)
    from extensions import db
    from models import Notification, RoundAttempt, User
    with app.app_context():
        rahul = User.query.filter_by(email=REC).first()
        assert db.session.get(RoundAttempt, att).result.get("invited_by") == rahul.id
    d(c.post(f"/api/rounds/{att}/paper/approve", headers=login(c, REC)))
    system_check(c, att, ch)
    j(c.post(f"/api/rounds/{att}/consent", headers=ch, json={}))
    d(c.post(f"/api/rounds/{att}/start", headers=ch))
    d(c.post(f"/api/rounds/{att}/integrity", headers=ch, json={"type": "devtools"}))
    with app.app_context():
        n = Notification.query.filter_by(user_id=rahul.id, title="Assessment paused").order_by(Notification.id.desc()).first()
        assert n is not None and n.link == f"/app/reports/{att}"  # B4: the report page has Resume, not the interviews list


# ---------------------------------------------------------------- D1: candidate feedback written once

def test_candidate_feedback_is_saved_not_regenerated(app):
    from extensions import db
    from models import Report
    with app.app_context():
        r = Report.query.first()
        assert r is not None
        from services.pipeline import make_report
        from models import RoundAttempt
        att = db.session.get(RoundAttempt, r.attempt_id)
        r.candidate_feedback = {"strengths": ["kept"]}
        db.session.commit()
        make_report(att, dict(r.sections or {}), r.overall, r.recommendation)
        assert r.candidate_feedback == {"strengths": ["kept"]}  # same sections: kept
        make_report(att, {**(r.sections or {}), "strengths": ["changed"]}, r.overall, r.recommendation)
        assert r.candidate_feedback == {}  # changed sections: written again on the next view
        db.session.rollback()


# ---------------------------------------------------------------- E3: no Isha name for candidates

def test_candidate_never_sees_isha():
    from services.audit import candidate_json, candidate_text
    assert candidate_text("F2F with Isha") == "Live interview"
    assert candidate_text("Isha Sharma will interview you") == "Isha Sharma will interview you"  # a person's name stays
    assert "Isha" not in str(candidate_json({"rounds": [{"name": "Tech round (with Isha)"}, "Isha's panel"]}))


def test_candidate_api_responses_have_no_isha(c):
    _, aid, ch = new_candidate(c, "isha1@demo.test", "Isha Free")
    job = python_job(c)
    body = c.get(f"/api/me/jobs/{job['id']}", headers=ch).get_data(as_text=True)
    assert "with Isha" not in body and "Isha copilot" not in body
    body = c.get("/api/me/applications", headers=ch).get_data(as_text=True)
    assert "with Isha" not in body


# ---------------------------------------------------------------- C4: MCQ rounds are recorded

def test_hiring_mcq_is_recorded_and_needs_camera(c):
    _, aid, ch = new_candidate(c, "rec1@demo.test", "Rec One")
    att = invite(c, aid)
    a = d(c.get(f"/api/rounds/{att}", headers=ch))
    assert a["record"] is True


# ---------------------------------------------------------------- F6, F11, A4, D3

def test_single_name_counts_in_profile_strength():
    from types import SimpleNamespace
    from services.profile import _checks
    assert _checks(None, SimpleNamespace(name="Suriya", email="s@x.test"))["name"] is True
    assert _checks(None, SimpleNamespace(name="s", email="s@x.test"))["name"] is False
    assert _checks(None, SimpleNamespace(name="arun", email="arun@x.test"))["name"] is False  # the email's start isn't a name


def test_applied_job_stays_readable_after_it_closes(c, app):
    job, aid, ch = new_candidate(c, "closed1@demo.test", "Closed One")
    from extensions import db
    from models import Job
    with app.app_context():
        jb = db.session.get(Job, job["id"])
        old = jb.status
        jb.status = "closed"
        db.session.commit()
    try:
        out = d(c.get(f"/api/me/jobs/{job['id']}", headers=ch))
        assert out["closed"] is True and "no longer" in out["closed_note"]
    finally:
        with app.app_context():
            jb = db.session.get(Job, job["id"])
            jb.status = old
            db.session.commit()


def test_ai_interview_minutes_must_fit_the_questions():
    from services.settings import cross_errors
    assert "interview.minutes" in cross_errors({"interview.questions": 8, "interview.minutes": 10})
    assert not cross_errors({"interview.questions": 5, "interview.minutes": 30})


def test_analytics_tabs_honour_the_date_range(c):
    h = login(c, "admin@acme.test")
    ov = d(c.get("/api/analytics/overview?days=30", headers=h))
    assert ov["days"] in (29, 30) and "since" in ov
    assert isinstance(d(c.get("/api/analytics/interviewers?days=1", headers=h)), list)
    assert isinstance(d(c.get("/api/analytics/questions?days=1", headers=h)), list)
    assert c.get("/api/analytics/overview?days=abc", headers=h).status_code == 200


# ---------------------------------------------------------------- migration 010: data fixes

def test_data_fix_rebalances_freezes_and_is_safe_to_rerun(app):
    from extensions import db
    from models import Question, QuestionVersion, RoundAttempt
    from services.data_v12 import NOTE, run
    with app.app_context():
        # make the bank look like before: every answer at B
        for q in Question.query.all():
            if len(q.options or []) == 4 and not any(w in " ".join(q.options).lower() for w in ("above", "of these")):
                right = q.options[q.answer]
                rest = [o for i, o in enumerate(q.options) if i != q.answer]
                q.options, q.answer = [rest[0], right, rest[1], rest[2]], 1
        old = RoundAttempt.query.filter_by(round_type="mcq").first()
        if old is not None:
            res = dict(old.result or {})
            ids = res.get("question_ids") or [Question.query.first().id]
            res.update({"question_ids": ids, "qsnap": {}})
            old.result = res
        db.session.commit()
        before = {q.id: (q.options[q.answer], q.version or 1) for q in Question.query.all()}
        with db.engine.begin() as conn:
            out = run(conn)
        db.session.commit()  # ends this session's snapshot (MySQL/MariaDB REPEATABLE READ) so it sees the fix
        assert out["questions_reordered"] > 10
        qs = Question.query.all()
        pos = Counter(q.answer for q in qs if len(q.options or []) == 4)
        assert max(pos.values()) <= sum(pos.values()) * 0.35, pos
        for q in qs:  # the right option is still right; the version went up and was saved
            assert q.options[q.answer] == before[q.id][0]
        assert QuestionVersion.query.filter_by(note=NOTE).count() == out["questions_reordered"]
        if old is not None:
            assert db.session.get(RoundAttempt, old.id).result["qsnap"]
        with db.engine.begin() as conn:
            again = run(conn)
        assert again["questions_reordered"] == 0 and again["attempts_frozen"] == 0
