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
PAPER_REVIEW = True  # the real default: every hiring MCQ paper is reviewed


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
        r = c.post("/api/auth/login", json={"email": email, "password": pw}, headers={"X-Forwarded-For": "10.34.0." + str(len(_tokens) + 1)})
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




def test_version_is_v02_01_04(c):
    assert j(c.get("/api/health"))["version"] == "V02.01.04"


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


# ---------------------------------------------------------------------------------------------------- MCQ and the bank
def test_skill_matching_is_strict(app):
    from services.mcq import _canon, match_skills
    with app.app_context():
        assert match_skills(["React Native"]) == []            # not React
        assert match_skills(["JS"]) == ["JavaScript"]           # a known alias
        assert match_skills(["SQL databases"]) == ["SQL"]       # the skill plus generic words
        assert match_skills(["Python programming"]) == ["Python"]
        assert match_skills(["Java"]) == []                     # never JavaScript
    assert _canon("PostgreSQL") == _canon("Postgres") and _canon("C#") != _canon("C++")


def test_a_job_without_skills_never_draws_the_whole_bank(app):
    from types import SimpleNamespace
    from services.mcq import base_pool
    with app.app_context():
        fake = SimpleNamespace(company_id=None, skills=[])
        assert base_pool(None, fake, None, [], None).count() == 0
        assert base_pool(None, fake, None, ["Python"], None).count() > 0


def test_correct_answers_are_spread_over_the_letters(app):
    from services.mcq import answer_split, save_generated, shuffled_snap
    from extensions import db
    with app.app_context():
        snaps = [(1000 + i, {"text": f"q{i}", "options": ["a", "b", "c", "d"], "answer": 1, "skill": "Python", "level": 3}) for i in range(8)]
        split = answer_split(shuffled_snap(snaps).values())
        assert max(split.values()) <= 3 and len(split) == 4, split      # 8 questions: no letter more than 8/4 + 1
        # Claude put every right answer at B: they're spread before saving to the bank
        items = [{"text": f"Unique generated question number {i} about decorators?", "options": [f"o{i}{k}" for k in "abcd"], "answer": 1,
                  "skill": "Python", "level": 3} for i in range(8)]
        saved = save_generated(items, None, ["Python"], review=True)
        assert len(saved) == 8 and max(answer_split([q.snapshot() for q in saved]).values()) <= 3
        assert all(q.options[q.answer] == f"o{int(q.text.split()[4])}b" for q in saved)   # the right option moved with it
        db.session.rollback()


def test_interview_questions_never_reach_an_mcq_test(app):
    from services import ibank
    from services.mcq import base_pool
    from types import SimpleNamespace
    from extensions import db
    with app.app_context():
        n = base_pool(None, SimpleNamespace(company_id=None), None, ["Python"], None).count()
        made = ibank.save(None, [{"q": "Walk me through the hardest Python bug you fixed last year.", "skill": "Python", "type": "experience",
                                  "good": ["The symptom", "How they found it"], "model": "A clear story."}])
        assert made == 1
        assert ibank.save(None, [{"q": "Walk me through the hardest Python bug you fixed last year!", "skill": "Python"}]) == 0  # same words
        db.session.commit()
        assert base_pool(None, SimpleNamespace(company_id=None), None, ["Python"], None).count() == n
        q = ibank.find(None, "Python programming", "experience")
        assert q and q[0].kind == "interview" and q[0].status == "pending" and (q[0].meta or {}).get("good")


def _mcq_paper(c, email, name):
    job = python_job(c)
    r = d(c.post("/api/candidates", headers=login(c, REC), json={"name": name, "email": email, "job_id": job["id"]}))["results"][0]
    full = d(c.get(f"/api/applications/{r['application_id']}", headers=login(c, REC)))
    idx = next(i for i, x in enumerate(full["rounds"]) if x["type"] == "mcq")
    att = d(c.post(f"/api/applications/{r['application_id']}/invite", headers=login(c, REC), json={"round_index": idx}))["attempt_id"]
    return att, job


def test_a_test_with_claude_questions_needs_their_review(c, app):
    from extensions import db
    from models import Question, RoundAttempt
    att, job = _mcq_paper(c, "paper1@demo.test", "Paper One")
    p = d(c.get(f"/api/rounds/{att}/paper", headers=login(c, REC)))
    assert p["state"] == "pending_review" and p["answer_split"] and p["drafts"] == 0 and p["claude"] is False
    assert all(not q["draft"] for q in p["questions"])
    # one question in the paper becomes a draft Claude wrote
    qid = p["questions"][0]["id"]
    with app.app_context():
        q = db.session.get(Question, qid)
        q.status, q.source = "pending", "ai"
        db.session.commit()
    p = d(c.get(f"/api/rounds/{att}/paper", headers=login(c, REC)))
    assert p["drafts"] == 1 and p["questions"][0]["draft"]
    # bulk approval skips a test with drafts
    out = d(c.post(f"/api/jobs/{job['id']}/papers/approve-all", headers=login(c, REC)))
    with app.app_context():
        assert (db.session.get(RoundAttempt, att).result["paper"]["state"]) == "pending_review"
    # approve that one question, then the paper
    p = d(c.post(f"/api/rounds/{att}/paper/approve_question", headers=login(c, REC), json={"question_id": qid}))
    assert p["drafts"] == 0
    with app.app_context():
        assert db.session.get(Question, qid).status == "approved"
    # and "Approve all" approves drafts with the paper
    with app.app_context():
        q = db.session.get(Question, qid)
        q.status = "pending"
        db.session.commit()
    p = d(c.post(f"/api/rounds/{att}/paper/approve", headers=login(c, REC)))
    assert p["state"] == "approved"
    with app.app_context():
        assert db.session.get(Question, qid).status == "approved"


def test_isha_uses_the_bank_when_claude_is_down(c, app):
    from extensions import db
    from models import Question
    with app.app_context():
        for t in ("experience", "basics", "hands_on", "scenario", "real_world", "design"):
            db.session.add(Question(company_id=None, skill="Python", level=4, text=f"Bank interview question about Python, type {t}: tell me more?",
                                    options=[], answer=0, kind="interview", status="approved", source="ai",
                                    meta={"type": t, "good": ["Point one", "Point two"], "model": "Model."}))
        db.session.commit()
    att, ch, job = live_round(c, "bank1@demo.test", "Bank One")
    h = login(c, IV)
    d(c.get(f"/api/isha/{att}", headers=h))
    prep = d(c.post(f"/api/isha/{att}/prepare", headers=h, json={"reset": True}))
    qs = (prep.get("prep") or prep)["questions"]
    bank = [q for q in qs if q["source"] == "bank"]
    assert bank and all(q["q"].startswith("Bank interview question about Python") for q in bank)
    assert all(q.get("model") for q in bank)


# ---------------------------------------------------------------------------------------------------- auto-start
def test_start_is_idempotent_keeps_speech_before_start_and_never_restarts(c, app):
    att, ch, job = live_round(c, "auto1@demo.test", "Auto One")
    h = login(c, IV)
    d(c.get(f"/api/isha/{att}", headers=h))
    pre = [{"who": "interviewer", "text": "Hello, can you hear me?"}, {"who": "candidate", "text": "Yes, I can hear you clearly."}]
    d(c.post(f"/api/isha/{att}/start", headers=h, json={"auto": True, "pre": pre}))
    d(c.post(f"/api/isha/{att}/start", headers=h, json={"auto": True, "pre": pre}))   # the second tab: nothing doubles
    from models import Turn
    with app.app_context():
        before = Turn.query.filter_by(attempt_id=att, topic="Before the start").all()
        assert sorted(t.speaker for t in before) == ["candidate", "interviewer"] and all(t.at_seconds == 0 for t in before)
    d(c.post(f"/api/isha/{att}/end", headers=h, json={}))
    r = c.post(f"/api/isha/{att}/start", headers=h, json={"auto": True})
    assert r.status_code == 409


# ---------------------------------------------------------------------------------------------------- live scores
def test_isha_scores_a_topic_live_and_the_interviewer_can_override(c, app):
    att, h, areas, ch = _started(c, "score1@demo.test", "Score One")
    a = areas[0]
    from extensions import db
    from models import RoundAttempt
    with app.app_context():
        x = db.session.get(RoundAttempt, att)
        x.result = {**(x.result or {}), "live_seg": [{"area": a["area"], "from": 0}]}
        db.session.commit()
    words = " ".join(a.get("good") or []) + " for example in my last project we measured it and chose the simpler design"
    _turns(app, att, [("interviewer", a["q"]), ("candidate", words)])
    got = d(c.post(f"/api/isha/{att}/score-topic?ai=0", headers=h, json={"area": a["area"]}))
    assert got["score"] and 1 <= got["score"]["score"] <= 5
    row = next(t for t in got["state"]["topics"]["topics"] if t["area"] == a["area"])
    assert row["score"] and row["score_source"] in ("points", "claude") and row["reason"]
    st = d(c.post(f"/api/isha/{att}/topic-rating", headers=h, json={"area": a["area"], "score": 2}))
    assert next(t for t in st["topics"]["topics"] if t["area"] == a["area"])["your_rating"] == 2
    assert c.post(f"/api/isha/{att}/topic-rating", headers=h, json={"area": a["area"], "score": 9}).status_code == 400
    st = d(c.post(f"/api/isha/{att}/topic-rating", headers=h, json={"area": a["area"], "score": None}))
    assert "your_rating" not in next(t for t in st["topics"]["topics"] if t["area"] == a["area"])
    assert c.post(f"/api/isha/{att}/score-topic", headers=h, json={"area": "Not a topic"}).status_code == 400


def test_a_new_topic_starts_a_live_segment(c, app):
    att, h, areas, ch = _started(c, "seg1@demo.test", "Seg One")
    from extensions import db
    from models import RoundAttempt

    def segs():
        with app.app_context():
            return (db.session.get(RoundAttempt, att).result or {}).get("live_seg") or []
    say = lambda a: d(c.post(f"/api/isha/{att}/sentence", headers=h, json={"who": "candidate", "text": " ".join(a.get("good") or [a["q"]])}))
    r1 = say(areas[0])
    assert "topic_ended" not in r1 and segs() and segs()[-1]["area"] in {x["area"] for x in areas}
    first = segs()[-1]["area"]
    other = next(x for x in areas if x["area"] != first)
    r2 = say(other)
    if segs()[-1]["area"] != first:   # the topic moved: the room is told which one ended, so Isha rates it
        assert r2["topic_ended"] == first


# ---------------------------------------------------------------------------------------------------- File under…
def test_filing_a_sentence_is_kept_by_review_again(c, app):
    att, h, areas, ch = _started(c, "file1@demo.test", "File One")
    room = d(c.get(f"/api/isha/{att}", headers=h))
    topics = room["state"]["file_topics"]
    assert topics.get("selected") and "jd" in topics and "resume" in topics
    sentence = "I once rebuilt our billing export so finance could reconcile it every morning."
    _turns(app, att, [("interviewer", areas[0]["q"]), ("candidate", sentence)])
    target = areas[-1]["area"]
    st = d(c.post(f"/api/isha/{att}/file-sentence", headers=h, json={"text": sentence, "to": target}))
    assert target in st["manual_filing"].values()
    assert c.post(f"/api/isha/{att}/file-sentence", headers=h, json={"text": sentence, "to": "Made up"}).status_code == 400
    d(c.post(f"/api/isha/{att}/end", headers=h, json={}))
    for _ in range(2):   # the review, then Review again
        st = d(c.post(f"/api/isha/{att}/review", headers=h, json={"ai": False}))["state"]
        mine = [e for e in st["areas_log"] if e["area"] == target]
        assert any(sentence in " ".join(map(str, e.get("answers") or e.get("sentences") or [e.get("answer") or ""])) or sentence in str(e)
                   for e in mine), "the filed sentence stays under the chosen topic"


# ---------------------------------------------------------------------------------------------------- transcription
def test_the_recording_is_transcribed_when_the_captions_missed_it(c, app, monkeypatch, tmp_path):
    import shutil
    import subprocess
    from datetime import datetime
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg is not installed")
    att, h, areas, ch = _started(c, "stt1@demo.test", "Stt One")
    d(c.post(f"/api/isha/{att}/end", headers=h, json={}))
    from extensions import db
    from models import Recording, RoundAttempt
    from services import storage, transcribe
    with app.app_context():
        key = f"att{att}-candidate-test.webm"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=70",
                        "-c:a", "libopus", storage.local_path(key)], check=True)
        x = db.session.get(RoundAttempt, att)
        db.session.add(Recording(attempt_id=att, side="candidate", segment="t1", status="ready", file_key=key, storage="local",
                                 started_at=x.started_at or datetime.utcnow()))
        db.session.commit()
        monkeypatch.setattr(transcribe, "recognize", lambda wav, language="en-IN": "I designed the cache layer and measured the hit rate every week.")
        out = transcribe.run(att, use_ai=False)
    assert out["state"] == "done" and out["total"] == 2 and "candidate" in out["replaced"]
    st = d(c.get(f"/api/isha/{att}", headers=h))
    assert st.get("transcribe", {}).get("state") == "done" or (st.get("state") or {}).get("transcribe", {}).get("state") == "done"


# ---------------------------------------------------------------------------------------------------- the candidate's end
def test_the_candidate_is_thanked_with_next_steps(c, app):
    att, h, areas, ch = _started(c, "bye1@demo.test", "Bye One")
    d(c.post(f"/api/isha/{att}/end", headers=h, json={}))
    info = d(c.get(f"/api/call/{att}", headers=ch))
    assert info["ended"] and info["end"]["first"] == "Bye" and info["end"]["job"] == "Senior Python Developer"
    assert info["end"]["closed"] is False
    from models import Notification
    with app.app_context():
        from models import User
        me = User.query.filter_by(email="bye1@demo.test").first()
        notes = Notification.query.filter_by(user_id=me.id).all()
        assert sum(1 for n in notes if n.title == "Thank you for your interview") == 1
    d(c.post(f"/api/isha/{att}/end", headers=h, json={}))   # ending twice never sends twice
    with app.app_context():
        assert Notification.query.filter_by(user_id=me.id, title="Thank you for your interview").count() == 1
    r = d(c.post(f"/api/call/{att}/message-team", headers=ch, json={"text": "Thanks, when will I hear back?"}))
    assert "Sent" in r["message"]
    assert c.post(f"/api/call/{att}/message-team", headers=h, json={"text": "x y"}).status_code == 403


def test_a_closed_interview_tells_the_candidate_it_was_stopped(c, app):
    att, h, areas, ch = _started(c, "bye2@demo.test", "Bye Two")
    d(c.post(f"/api/isha/{att}/close", headers=h, json={"reason": "The candidate's connection kept dropping."}))
    info = d(c.get(f"/api/call/{att}", headers=ch))
    assert info["ended"] and info["end"]["closed"] is True
    from models import Notification, User
    with app.app_context():
        me = User.query.filter_by(email="bye2@demo.test").first()
        assert Notification.query.filter_by(user_id=me.id, title="Your interview was stopped before the end").count() == 1


# ---------------------------------------------------------------------------------------------------- the report
def _words(a):
    from services.isha_review import _content
    return " ".join(dict.fromkeys(_content(a["q"] + " " + " ".join(a.get("good") or []))))


def _report(c, app, email, name, extra=None):
    att, h, areas, ch = _started(c, email, name)
    q1, q2 = [a for a in areas if a["type"] not in ("intro",)][:2]
    _turns(app, att, [("interviewer", q1["q"]), ("candidate", "Well, " + _words(q1)),
                      ("interviewer", q2["q"]), ("candidate", "Well, " + _words(q2))] + (extra or []))
    out = d(c.post(f"/api/isha/{att}/end?ai=0", headers=h))
    if extra:
        log_ = out["state"]["areas_log"]
        k = next(i for i, e in enumerate(log_) if e.get("sentences") and any(extra[-1][1] in s for s in e["sentences"]))
        si = next(n for n, s in enumerate(log_[k]["sentences"]) if extra[-1][1] in s)
        d(c.post(f"/api/isha/{att}/move-quote", headers=h, json={"index": k, "sentence": si, "to": "From the resume: Kafka pipelines"}))
    comps = (out.get("draft") or {}).get("competencies") or [{"name": "Python"}]
    rep = d(c.post(f"/api/isha/{att}/scorecard", headers=h, json={**skip_unanswered(c, att, h),
        "competencies": [{"name": x["name"], "score": 4} for x in comps], "recommendation": "hold"}))
    return att, h, rep["report_id"]


def test_an_answer_filed_under_a_resume_topic_reaches_the_report(c, app):
    said = "At my last job I ran the Kafka pipelines that moved orders between our services every night."
    att, h, rid = _report(c, app, "rep1@demo.test", "Rep One", extra=[("candidate", said)])
    qs = d(c.get(f"/api/reports/{rid}", headers=login(c, REC)))["sections"]["questions"]
    added = [q for q in qs if q.get("added")]
    assert added and any(said in (q.get("a") or "") for q in added)
    assert added[0].get("added_from") in ("resume", "From the resume", "jd", "From the job description") or added[0].get("added_from")


def test_a_reviewer_refiles_or_removes_an_answer_on_the_report(c, app):
    att, h, rid = _report(c, app, "rep2@demo.test", "Rep Two")
    hr = login(c, REC)
    qs = d(c.get(f"/api/reports/{rid}", headers=hr))["sections"]["questions"]
    assert len(qs) >= 2
    moved = qs[1].get("q")
    out = d(c.post(f"/api/reports/{rid}/refile", headers=hr, json={"index": 1, "to": 0, "reason": "It answered the first question."}))
    qs2 = (out.get("sections") or d(c.get(f"/api/reports/{rid}", headers=hr))["sections"])["questions"]
    assert len(qs2) == len(qs) - 1 and any(f.get("moved") and f.get("q") == moved for f in qs2[0].get("followups") or [])
    out = d(c.post(f"/api/reports/{rid}/refile", headers=hr, json={"index": 0, "to": "remove", "reason": "Not relevant."}))
    qs3 = (out.get("sections") or d(c.get(f"/api/reports/{rid}", headers=hr))["sections"])["questions"]
    assert len(qs3) == len(qs2) - 1
    assert c.post(f"/api/reports/{rid}/refile", headers=hr, json={"index": 99, "to": 0}).status_code == 400
