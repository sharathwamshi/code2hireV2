"""Regression tests for V02.00.06: the 6 Nov screenshots (B1 to B4, C1 to C4) and the report showing expected answers
next to the candidate's answers (R6). Each test names what it covers. Run: pytest -q"""
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
    os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "v06.db")
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
        r = c.post("/api/auth/login", json={"email": email, "password": pw}, headers={"X-Forwarded-For": "10.6.0." + str(len(_tokens) + 1)})
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


# ---------------------------------------------------------------- B1, C1, C2: the interviewer started first

def test_interviewer_starts_first_candidate_still_gets_the_full_flow_B1_C2(c):
    job, aid, ch = new_candidate(c, "b1.cand@mail.test", "Bone Cand")
    att = invite(c, aid, "f2f_isha")
    p = login(c, "priya@acme.test")
    assert status(c, att)["text"] == "Hasn't opened the round yet"
    j(c.post(f"/api/isha/{att}/start", headers=p))                  # the screenshot: started before the candidate arrived
    a = j(c.get(f"/api/rounds/{att}", headers=ch))["data"]
    assert a["status"] == "in_progress" and a["had_full_check"] is False
    # the page asks for a re-check (old behaviour); the server gives the full check and the instructions instead
    req = j(c.get(f"/api/syscheck/requirements?attempt={att}&mode=recheck", headers=ch))["data"]
    assert req["upgraded"] is True and req["mode"] == "full" and req["instructions"]["read_at"] is None
    assert "room" in [s["key"] for s in req["steps"]]
    # a re-check result can't stand in for the full check either
    steps = {s["key"]: {"status": "pass"} for s in j(c.get(f"/api/syscheck/requirements?attempt={att}&mode=recheck", headers=ch))["data"]["steps"]}
    out = j(c.post("/api/syscheck", headers=ch, json={"attempt_id": att, "mode": "recheck", "steps": {"camera": {"status": "pass"}}}))["data"]
    assert not out["passed"] and "instructions" in out["failed"]
    # C2: the interviewer sees each stage
    j(c.post("/api/syscheck/progress", headers=ch, json={"attempt_id": att, "stage": "instructions"}))
    assert status(c, att)["text"] == "Reading the instructions"
    j(c.post("/api/syscheck/progress", headers=ch, json={"attempt_id": att, "stage": "check", "step": "mic", "index": 6, "total": 10}))
    assert status(c, att)["text"] == "Doing the system check: step 6 of 10 (Microphone)"
    system_check(c, att, ch)
    st = status(c, att)
    assert st["text"] == "System check passed, joining the call" and st["kind"] == "good" and st["check_passed"]
    j(c.post(f"/api/rounds/{att}/consent", headers=ch, json={}))
    assert status(c, att)["text"] == "Joined the call"
    a = j(c.get(f"/api/rounds/{att}", headers=ch))["data"]
    assert a["had_full_check"] is True and a["consented"]
    # only now is a rejoin a device re-check
    assert j(c.get(f"/api/syscheck/requirements?attempt={att}&mode=recheck", headers=ch))["data"]["mode"] == "recheck"
    assert steps  # (the full step list was offered above)


def test_progress_and_status_are_private_C2(c):
    job, aid, ch = new_candidate(c, "c2.cand@mail.test", "Ctwo Cand")
    att = invite(c, aid, "f2f_isha")
    other = login(c, "meera@demo.test")
    assert c.post("/api/syscheck/progress", headers=other, json={"attempt_id": att, "stage": "check"}).status_code == 403
    assert c.get(f"/api/isha/{att}/candidate-status", headers=other).status_code in (403, 404)
    j(c.post("/api/syscheck/progress", headers=ch, json={"attempt_id": att, "stage": "nonsense", "step": "x" * 99}))
    assert status(c, att)["text"] == "Opened the round"


def test_stuck_screen_and_general_help_C4(c, app):
    from models import Notification
    job, aid, ch = new_candidate(c, "c4.cand@mail.test", "Cfour Cand")
    att = invite(c, aid, "f2f_isha")
    j(c.post("/api/syscheck/progress", headers=ch, json={"attempt_id": att, "stage": "stuck", "note": "Please read the instructions"}))
    st = status(c, att)
    assert st["kind"] == "bad" and "Please read the instructions" in st["text"]
    r = j(c.post("/api/syscheck/help", headers=ch, json={"attempt_id": att, "step": "other", "note": "The page shows only an error"}))["data"]
    assert r["sent"]
    with app.app_context():
        n = Notification.query.filter(Notification.title == "Cfour Cand needs help joining their round").first()
        assert n and "stuck" in n.body and "only an error" in n.body
    assert status(c, att)["text"] == "Asked for help: Something else"
    rows = j(c.get(f"/api/applications/{aid}", headers=login(c, "rahul@acme.test")))["data"]["attempts"]
    assert rows[-1]["setup"]["text"] == "Asked for help with: Something else"


def test_earlier_round_still_running_is_warned_not_blocked_C3(c):
    job, aid, ch = new_candidate(c, "c3.cand@mail.test", "Cthree Cand")
    mcq = invite(c, aid, "mcq")
    system_check(c, mcq, ch)
    j(c.post(f"/api/rounds/{mcq}/consent", headers=ch, json={}))
    j(c.post(f"/api/rounds/{mcq}/start", headers=ch))                  # the MCQ is running
    live = invite(c, aid, "f2f_isha")
    a = j(c.get(f"/api/rounds/{live}", headers=ch))["data"]
    assert a["earlier_open"]["attempt_id"] == mcq and a["earlier_open"]["status"] == "in_progress"
    assert status(c, live)["earlier_open"]["name"] == a["earlier_open"]["name"]
    system_check(c, live, ch)
    j(c.post(f"/api/rounds/{live}/consent", headers=ch, json={}))       # warned, not blocked


# ---------------------------------------------------------------- R6: expected answers and candidate answers

def test_expected_points_fit_the_question_R6():
    from services.ai import expected_points
    assert "cause" in expected_points("How did you debug the failing payment job?", "Python")[0]
    assert "trade-offs" in expected_points("Design a URL shortener that scales", "System design")[1]
    assert "Python example" in expected_points("Walk me through a Python project you built", "Python")[0]
    assert "each" in expected_points("What's the difference between a list and a tuple?", "Python")[0]
    assert len(expected_points("Hello?", None)) == 3


def test_f2f_report_has_expected_points_coverage_and_both_voices_R6(c):
    job, aid, ch = new_candidate(c, "r6.f2f@mail.test", "Rsix Live")
    att = invite(c, aid, "f2f_isha")
    p = login(c, "priya@acme.test")
    system_check(c, att, ch)
    j(c.post(f"/api/rounds/{att}/consent", headers=ch, json={}))
    room = j(c.get(f"/api/isha/{att}", headers=p))["data"]
    area = room["brief"]["areas"][0]
    j(c.post(f"/api/isha/{att}/start", headers=p))
    j(c.post(f"/api/isha/{att}/ask", headers=p, json={"q": area["q"], "area": area["area"]}))
    j(c.post(f"/api/isha/{att}/sentence", headers=p, json={"text": "I built an order service in Django with PostgreSQL."}))
    j(c.post(f"/api/isha/{att}/said", headers=p, json={"text": "Nice, go on."}))
    # the interviewer's own question gets expected points too
    st = j(c.post(f"/api/isha/{att}/ask", headers=p, json={"q": "How did you debug the slow checkout page?", "area": "General", "type": "own"}))["data"]
    assert "cause" in st["areas_log"][-1]["good"][0]
    j(c.post(f"/api/isha/{att}/sentence", headers=p, json={"text": "I profiled the queries and added an index."}))
    draft = j(c.post(f"/api/isha/{att}/end", headers=p))["data"]["draft"]
    j(c.post(f"/api/isha/{att}/scorecard", headers=p, json={"competencies": [{**x, "score": 4} for x in draft["competencies"]], "recommendation": "proceed"}))
    rahul = login(c, "rahul@acme.test")
    v = j(c.get(f"/api/reports/by-attempt/{att}", headers=rahul))["data"]
    q1, q2 = v["sections"]["questions"][0], v["sections"]["questions"][1]
    assert q1["q"] == area["q"] and q1["good_answer"] == area["good"] and len(q1["covered"]) == len(q1["good_answer"])
    assert q1["a"] == "I built an order service in Django with PostgreSQL." and q1["interviewer_said"] == ["Nice, go on."]
    assert "cause" in q2["good_answer"][0] and q2["a"] == "I profiled the queries and added an index."
    # PDF: expected points and answers, for the hiring team
    pdf = c.get(f"/api/reports/{v['id']}/pdf?audience=internal", headers=rahul)
    text = pdf_text(pdf.data)
    assert "A good answer covers" in text and "Candidate's answer" in text and "order service in Django" in text
    # the client version hides the answers and the interviewer's remarks (default "replay" hidden)
    cl = j(c.get(f"/api/reports/{v['id']}?audience=client", headers=rahul))["data"]["sections"]["questions"][0]
    assert "a" not in cl and "interviewer_said" not in cl and cl["good_answer"]
    # candidates see questions only when the company turns it on
    cand = j(c.get(f"/api/reports/{v['id']}?audience=candidate", headers=rahul))["data"]["sections"]
    assert "questions" not in cand
    admin = login(c, "admin@acme.test")
    j(c.put("/api/company/settings", headers=admin, json={"scope": "company", "key": "report.candidate_sections",
                                                          "value": ["strengths", "gaps", "learning_path", "questions"]}))
    cand = j(c.get(f"/api/reports/{v['id']}?audience=candidate", headers=rahul))["data"]["sections"]
    cq = cand["questions"][0]
    assert cq["a"] and cq["good_answer"] and "score" not in cq and "tags" not in cq and "interviewer_said" not in cq
    j(c.put("/api/company/settings", headers=admin, json={"scope": "company", "key": "report.candidate_sections", "reset": True}))


def test_ai_interview_report_has_question_specific_points_R6(c):
    job, aid, ch = new_candidate(c, "r6.ai@mail.test", "Rsix Ai")
    att = invite(c, aid, "ai_interview")
    system_check(c, att, ch)
    j(c.post(f"/api/rounds/{att}/consent", headers=ch, json={}))
    j(c.post(f"/api/rounds/{att}/start", headers=ch))
    for _ in range(10):
        if j(c.post(f"/api/rounds/{att}/turn", headers=ch, json={"answer": "I built a Django API and tested it with pytest " * 6}))["data"]["done"]:
            break
    else:
        j(c.post(f"/api/rounds/{att}/finish", headers=ch, json={"reason": "ended_early"}))
    v = j(c.get(f"/api/reports/by-attempt/{att}", headers=login(c, "rahul@acme.test")))["data"]
    qs = v["sections"]["questions"]
    assert qs and all(q["good_answer"] and len(q["covered"]) == len(q["good_answer"]) and q["a"] for q in qs)
    assert any(q["good_answer"] != ["A specific example", "The reasoning behind decisions", "What was learned"] for q in qs)


def test_mcq_pdf_shows_correct_answer_and_choice_R6(c):
    job, aid, ch = new_candidate(c, "r6.mcq@mail.test", "Rsix Mcq")
    att = invite(c, aid, "mcq")
    system_check(c, att, ch)
    j(c.post(f"/api/rounds/{att}/consent", headers=ch, json={}))
    a = j(c.post(f"/api/rounds/{att}/start", headers=ch))["data"]
    first = a["questions"][0]["id"]
    j(c.post(f"/api/rounds/{att}/answer", headers=ch, json={"qid": first, "choice": 0}))
    j(c.post(f"/api/rounds/{att}/submit", headers=ch, json={}))
    rahul = login(c, "rahul@acme.test")
    v = j(c.get(f"/api/reports/by-attempt/{att}", headers=rahul))["data"]
    q = v["sections"]["questions"][0]
    assert "options" in q and isinstance(q["answer"], int)
    text = pdf_text(c.get(f"/api/reports/{v['id']}/pdf?audience=internal", headers=rahul).data)
    assert "Correct answer" in text and "Candidate chose" in text and "Skipped" in text


def test_old_reports_get_expected_points_when_read_R6(c, app):
    from extensions import db
    from models import Report
    job, aid, ch = new_candidate(c, "r6.old@mail.test", "Rsix Old")
    att = invite(c, aid, "f2f_isha")
    with app.app_context():
        r = Report(attempt_id=att, status="awaiting_review", overall=3.5, recommendation="hold",
                   sections={"kind": "f2f_isha", "questions": [{"q": "How did you debug a memory leak?", "a": "I used tracemalloc.", "score": 3, "topic": "Python"}]})
        db.session.add(r)
        db.session.commit()
        rid = r.id
    q = j(c.get(f"/api/reports/{rid}", headers=login(c, "rahul@acme.test")))["data"]["sections"]["questions"][0]
    assert "cause" in q["good_answer"][0] and q["covered"] == [False, False, False] and q["a"] == "I used tracemalloc."
    with app.app_context():
        assert "good_answer" not in Report.query.get(rid).sections["questions"][0]     # stored report unchanged


def test_version_V02_00_06(c):
    assert c.get("/api/health").get_json()["version"] == "V02.00.06"
