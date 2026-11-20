"""Regression tests for V02.01.01: Isha reviews the whole interview transcript when it ends, so answers are filed under
the right questions even when nobody marked a question as asked. Run: pytest -q"""
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
    os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "v020101.db")
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
        r = c.post("/api/auth/login", json={"email": email, "password": pw}, headers={"X-Forwarded-For": "10.32.0." + str(len(_tokens) + 1)})
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


def test_version_is_v02_01_02(c):
    assert j(c.get("/api/health"))["version"] == "V02.01.02"


def _started(c, email, name):
    att, ch, job = live_round(c, email, name)
    h = login(c, IV)
    room = d(c.get(f"/api/isha/{att}", headers=h))
    d(c.post(f"/api/isha/{att}/start", headers=h))
    return att, h, [a for a in room["brief"]["areas"] if a["area"] != "Wrap-up"]


def _words(a, n=8):
    from services.isha_review import _content
    return " ".join(dict.fromkeys(_content(a["q"] + " " + " ".join(a.get("good") or []))))


def test_nothing_marked_answers_are_filed_by_their_words(c, app):
    """The reported bug: the interviewer never pressed anything and Isha didn't hear them. Everything went under one
    question. The end-of-interview review files each answer under the question it answers."""
    att, h, areas = _started(c, "rv1@demo.test", "Rv One")
    picks = [a for a in areas if a["type"] not in ("intro",)][:3]
    for a in picks:
        d(c.post(f"/api/isha/{att}/sentence", headers=h, json={"text": "Well, " + _words(a)}))
    live = d(c.get(f"/api/isha/{att}", headers=h))["state"]["areas_log"]
    assert len(live) == 1  # during the interview it all sat under one (assumed) question
    out = d(c.post(f"/api/isha/{att}/end", headers=h))
    rv = out["review"]
    assert rv["source"] == "keywords" and rv["turns"] >= 3
    filed = [e["area"] for e in out["state"]["areas_log"] if e["type"] == "main"]
    assert set(a["area"] for a in picks) <= set(filed), (filed, [a["area"] for a in picks])
    assert all(e.get("reviewed") for e in out["state"]["areas_log"])
    assert rv["asked"] >= 3 and rv["of"] >= rv["asked"]


def _turns(app, att, rows):
    from extensions import db
    from models import Turn
    with app.app_context():
        seq = (db.session.query(db.func.max(Turn.seq)).filter_by(attempt_id=att).scalar() or 0)
        for i, (who, text) in enumerate(rows):
            db.session.add(Turn(attempt_id=att, seq=seq + i + 1, speaker=who, text=text, at_seconds=10 * (i + 1)))
        db.session.commit()


def test_interviewer_words_split_the_interview_into_questions(c, app):
    """Isha heard the interviewer only partly (no auto-move), but the transcript has their words: the review uses them
    to start each question, in any order, and files follow-ups and extra questions."""
    att, h, areas = _started(c, "rv2@demo.test", "Rv Two")
    a1, a2 = [a for a in areas if a["type"] not in ("intro",)][1:3]
    _turns(app, att, [
        ("interviewer", a2["q"]),                       # asked out of order
        ("candidate", "I would start by looking at what changed and measuring it first."),
        ("interviewer", "Why would you measure it before changing anything?"),   # a follow-up
        ("candidate", "Because otherwise I can't tell whether my fix helped at all."),
        ("interviewer", a1["q"]),
        ("candidate", "I explained it to a junior once using a simple example from our payments code."),
        ("interviewer", "Have you ever worked at a startup before joining a large company?"),   # not in the plan
        ("candidate", "Yes, two years at a small logistics startup."),
        ("interviewer", "Do you have any questions about the team or the role?"),                 # the Wrap-up
        ("candidate", "Yes, how big is the team?"),
    ])
    out = d(c.post(f"/api/isha/{att}/end?ai=0", headers=h))
    log_ = out["state"]["areas_log"]
    mains = [e["area"] for e in log_ if e["type"] == "main"]
    assert mains[:2] == [a2["area"], a1["area"]], mains
    fu = next(e for e in log_ if e["type"] == "Follow-up")
    assert fu["area"] == a2["area"] and fu["followup_of"] is not None and "measure" in fu["q"]
    assert any(e["type"] == "own" and "startup" in e["q"] for e in log_)   # the question that wasn't in the plan
    assert "Wrap-up" in mains
    assert a2["area"] not in out["review"]["not_asked"]


def test_ratings_carry_over_undo_and_review_again(c, app):
    att, h, areas = _started(c, "rv3@demo.test", "Rv Three")
    a = [x for x in areas if x["type"] not in ("intro",)][0]
    st = d(c.post(f"/api/isha/{att}/ask", headers=h, json={"area": a["area"]}))
    d(c.post(f"/api/isha/{att}/sentence", headers=h, json={"text": "Well, " + _words(a)}))
    d(c.post(f"/api/isha/{att}/rate", headers=h, json={"index": st["current"]["index"], "score": 5}))
    # before the end there's nothing to re-file
    assert c.post(f"/api/isha/{att}/review", headers=h, json={}).status_code in (200, 409)
    out = d(c.post(f"/api/isha/{att}/end", headers=h))
    e = next(x for x in out["state"]["areas_log"] if x["area"] == a["area"] and x["type"] == "main")
    assert e["rating"] == 5                          # the interviewer's own rating survives the review
    assert out["state"]["can_undo_review"]
    u = d(c.post(f"/api/isha/{att}/review", headers=h, json={"undo": True}))
    assert u["review"]["undone"] and not any(x.get("reviewed") for x in u["state"]["areas_log"])
    assert c.post(f"/api/isha/{att}/review", headers=h, json={"undo": True}).status_code == 409
    again = d(c.post(f"/api/isha/{att}/review", headers=h, json={"ai": False}))
    # "Mark as asked" is only a hint: the review files everything from the transcript
    assert again["review"]["kept"] == 0 and again["review"]["refiled"] >= 1
    assert any(x.get("reviewed") and x["area"] == a["area"] for x in again["state"]["areas_log"])
    # submitted: the report has the reviewed questions; no more re-filing
    d(c.post(f"/api/isha/{att}/scorecard", headers=h, json={**skip_unanswered(c, att, h), "competencies": [{"name": "Python", "score": 4}], "recommendation": "hold"}))
    assert c.post(f"/api/isha/{att}/review", headers=h, json={}).status_code == 409


def test_marking_is_only_a_hint(c, app):
    """V02.01.01 decision: "Mark as asked" clicks are hints. A wrong or missing click never decides where an answer goes;
    the review files each answer by what it says."""
    att, h, areas = _started(c, "rv6@demo.test", "Rv Six")
    q1, q2, q3 = [a for a in areas if a["type"] not in ("intro",)][:3]
    d(c.post(f"/api/isha/{att}/ask", headers=h, json={"area": q1["area"]}))
    d(c.post(f"/api/isha/{att}/sentence", headers=h, json={"text": "Well, " + _words(q1)}))
    d(c.post(f"/api/isha/{att}/ask", headers=h, json={"area": q2["area"]}))
    # the interviewer forgot to mark Q3: its answer (about Q3's topic, not Q2's) still lands under Q3
    from services.isha_review import _content, _fit_text
    own = [w for w in dict.fromkeys(_content(_fit_text(q3))) if w not in set(_content(_fit_text(q2)))]
    ans = "So for this one I would talk about " + " ".join(own) + " in practice"
    d(c.post(f"/api/isha/{att}/sentence", headers=h, json={"text": ans}))
    out = d(c.post(f"/api/isha/{att}/end?ai=0", headers=h))
    log_ = out["state"]["areas_log"]
    assert out["review"]["kept"] == 0
    by = {e["area"]: e for e in log_ if e["type"] == "main"}
    assert q1["area"] in by and q3["area"] in by, list(by)
    assert ans in by[q3["area"]]["sentences"] and ans not in (by.get(q2["area"]) or {}).get("sentences", [])


def test_corrected_captions_reach_the_transcript(c, app):
    att, h, areas = _started(c, "rv4@demo.test", "Rv Four")
    d(c.post(f"/api/isha/{att}/sentence", headers=h, json={"text": "I built it in jango with pytest."}))
    st = d(c.get(f"/api/isha/{att}", headers=h))["state"]
    d(c.post(f"/api/isha/{att}/edit-sentence", headers=h, json={"index": 0, "sentence": 0, "text": "I built it in Django with pytest."}))
    from services.isha_review import transcript
    from extensions import db
    from models import RoundAttempt
    with app.app_context():
        t = transcript(db.session.get(RoundAttempt, att))
        assert any("Django" in x["text"] for x in t) and not any("in jango" in x["text"] for x in t)
    d(c.post(f"/api/isha/{att}/edit-sentence", headers=h, json={"index": 0, "sentence": 0, "text": ""}))
    with app.app_context():
        assert not any(x["who"] == "candidate" for x in transcript(db.session.get(RoundAttempt, att)))
    assert st


def test_ending_with_no_transcript_is_fine(c):
    att, h, areas = _started(c, "rv5@demo.test", "Rv Five")
    out = d(c.post(f"/api/isha/{att}/end", headers=h))
    assert out["review"]["source"] == "none" and out["review"]["turns"] == 0
    assert out["draft"] is not None


def test_keyword_coverage_and_score():
    from services.isha_review import coverage, score_from
    cov = coverage(["Reads the query plan first", "Checks indexes on the table", "Has a rollback plan"],
                   "First I would read the query plan, then check the indexes.")
    assert cov[0] == "full" and cov[1] in ("full", "partial") and cov[2] in ("none", "partial")
    assert score_from(cov, "x y z") >= 2 and score_from([], "") is None


# ---------------------------------------------------------------------------------------------------- V14 part 2
def _ended(c, app, email, name):
    """A live round with a short transcript, ended (keyword review)."""
    att, h, areas = _started(c, email, name)
    q1, q2 = [a for a in areas if a["type"] not in ("intro",)][:2]
    _turns(app, att, [("interviewer", q1["q"]), ("candidate", "Well, " + _words(q1)),
                      ("candidate", "Nice weather today, by the way, it is sunny here in the city."),
                      ("interviewer", q2["q"]), ("candidate", "Well, " + _words(q2))])
    out = d(c.post(f"/api/isha/{att}/end?ai=0", headers=h))
    return att, h, q1, q2, out


def test_live_state_shows_topic_coverage(c, app):
    att, h, areas = _started(c, "rv7@demo.test", "Rv Seven")
    q1 = [a for a in areas if a["type"] not in ("intro",)][0]
    _turns(app, att, [("interviewer", q1["q"]), ("candidate", "Well, " + _words(q1))])
    st = d(c.get(f"/api/isha/{att}", headers=h))["state"]
    tp = {t["area"]: t for t in st["topics"]["topics"]}
    assert tp[q1["area"]]["state"] in ("touched", "well")
    assert any(t["state"] == "none" for t in tp.values())
    assert st["topics"]["turns"] >= 2


def test_missing_ratings_are_listed_and_skip_is_not_counted(c, app):
    att, h, q1, q2, out = _ended(c, app, "rv8@demo.test", "Rv Eight")
    comps = [x["name"] for x in out["draft"]["competencies"]][:2] if out.get("draft") and out["draft"].get("competencies") else ["Python", "SQL"]
    if len(comps) < 2:
        comps = comps + ["Communication"]
    r = c.post(f"/api/isha/{att}/scorecard", headers=h, json={**skip_unanswered(c, att, h), "competencies": [{"name": comps[0], "score": None}, {"name": comps[1], "score": 4}],
                                                               "recommendation": "hold"})
    body_ = r.get_json()
    assert r.status_code == 400 and body_["error"].startswith(f"Rating not received for: {comps[0]}") and body_["fields"]["missing"] == [comps[0]]
    rep = d(c.post(f"/api/isha/{att}/scorecard", headers=h, json={**skip_unanswered(c, att, h),
        "competencies": [{"name": comps[0], "score": None, "skipped": True, "show_on_report": True}, {"name": comps[1], "score": 4}], "recommendation": "hold"}))
    s = d(c.get(f"/api/reports/{rep['report_id']}", headers=login(c, REC)))["sections"]
    sk = next(x for x in s["competencies"] if x["name"] == comps[0])
    assert sk["level"] == "Skipped" and sk.get("score") in (None, "")
    assert float(rep["overall"]) == 4   # only the rated one counts


def test_move_quote_between_topics(c, app):
    att, h, q1, q2, out = _ended(c, app, "rv9@demo.test", "Rv Nine")
    log_ = out["state"]["areas_log"]
    k = next(i for i, e in enumerate(log_) if e["area"] == q1["area"] and e["type"] == "main")
    sent = log_[k]["sentences"][0]
    st = d(c.post(f"/api/isha/{att}/move-quote", headers=h, json={"index": k, "sentence": 0, "to": q2["area"]}))
    log2 = st["state"]["areas_log"] if "state" in st else st["areas_log"]
    tgt = next(e for e in log2 if e["area"] == q2["area"] and e["type"] == "main")
    assert sent in tgt["sentences"]
    assert c.post(f"/api/isha/{att}/move-quote", headers=h, json={"index": 999, "sentence": 0, "to": q2["area"]}).status_code == 400


def test_summaries_go_to_the_report_and_are_shared_only_when_chosen(c, app):
    att, h, q1, q2, out = _ended(c, app, "rv10@demo.test", "Rv Ten")
    d(c.post(f"/api/isha/{att}/chat", headers=h, json={"message": "Give me a harder SQL question"}))
    rep = d(c.post(f"/api/isha/{att}/scorecard", headers=h, json={**skip_unanswered(c, att, h), "competencies": [{"name": "Python", "score": 4}], "recommendation": "proceed"}))
    rid = rep["report_id"]
    s = d(c.get(f"/api/reports/{rid}", headers=login(c, REC)))["sections"]
    assert s["isha_summary"]["text"] and any(q.get("summary") for q in s["questions"])
    assert not any("harder SQL" in str(v) for v in s.values())   # the Ask Isha chat never reaches the report
    assert not any(q.get("smalltalk") for q in s["questions"])
    cand = d(c.get(f"/api/reports/{rid}?audience=candidate", headers=login(c, REC)))["sections"]
    assert "shared_summary" not in cand and "shared_parts" not in cand   # off by default
    d(c.post(f"/api/reports/{rid}/share-summaries", headers=login(c, REC), json={"overall": True, "overall_text": "Clear on the basics."}))
    cand = d(c.get(f"/api/reports/{rid}?audience=candidate", headers=login(c, REC)))["sections"]
    assert cand["shared_summary"] == "Clear on the basics." and "shared_parts" not in cand
    d(c.post(f"/api/reports/{rid}/share-summaries", headers=login(c, REC), json={"overall": False, "topics": True}))
    cand = d(c.get(f"/api/reports/{rid}?audience=candidate", headers=login(c, REC)))["sections"]
    assert "shared_summary" not in cand and cand["shared_parts"]


def _ai_round(c, email, name):
    job = python_job(c)
    r = d(c.post("/api/candidates", headers=login(c, REC), json={"name": name, "email": email, "job_id": job["id"]}))["results"][0]
    op = d(c.post(f"/api/auth/invite/{r['link'].split('/')[-1]}/open"))
    ch = {"Authorization": "Bearer " + op["token"]}
    full = d(c.get(f"/api/jobs/{job['id']}", headers=login(c, REC)))
    ai = next(i for i, x in enumerate(full["rounds"]) if x["type"] == "ai_interview")
    att = d(c.post(f"/api/applications/{r['application_id']}/invite", headers=login(c, REC), json={"round_index": ai}))["attempt_id"]
    system_check(c, att, ch)
    j(c.post(f"/api/rounds/{att}/consent", headers=ch, json={}))
    j(c.post(f"/api/rounds/{att}/start", headers=ch))
    return att, ch


def _media(path, seconds=4, kind="video"):
    import subprocess
    if kind == "video":
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size=160x120:rate=10:duration={seconds}",
               "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=mono", "-t", str(seconds), "-c:v", "libvpx", "-c:a", "libopus", path]
    else:
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "libmp3lame", path]
    subprocess.run(cmd, check=True)


@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"), reason="needs ffmpeg")
def test_hira_voice_is_merged_into_the_ai_interview_video(c, app):
    from datetime import datetime, timedelta
    from extensions import db
    from models import Recording, RoundAttempt
    from routes.recordings import finish_now
    from services import hira_audio, storage
    att, ch = _ai_round(c, "hira1@demo.test", "Hira One")
    rd = d(c.get(f"/api/rounds/{att}", headers=ch))
    assert "hira_merge" in (rd.get("attempt") or rd)
    # Azure isn't set up in tests: the browser speaks it itself, but the server still keeps the line and its time
    r = j(c.post("/api/speech/tts", headers=ch, json={"text": "Tell me about yourself.", "attempt_id": att}))
    assert r["data"]["fallback"]
    # someone else's attempt id is ignored
    assert j(c.post("/api/speech/tts", headers=login(c, IV), json={"text": "Not mine.", "attempt_id": att}))["data"]["fallback"]
    with app.app_context():
        a = db.session.get(RoundAttempt, att)
        clips = a.result["hira_audio"]
        assert [x["text"] for x in clips] == ["Tell me about yourself."] and clips[0]["key"] is None
        # a second line with real audio (as Azure would return it), two seconds into the recording
        mp3 = storage.local_path("t-sine.mp3")
        _media(mp3, 2, "audio")
        hira_audio.save(a, "Why Python?", open(mp3, "rb").read())
        start = datetime.utcnow() - timedelta(seconds=2)
        res = dict(a.result)
        res["hira_audio"] = [{**x, "at": (start + timedelta(seconds=0.5 + 2 * i)).isoformat()} for i, x in enumerate(res["hira_audio"])]
        a.result = res
        raw = f"att{att}-t1-raw.webm"
        _media(storage.local_path(raw), 5)
        rec = Recording(attempt_id=att, side="candidate", segment="t1", mime="video/webm", started_at=start,
                        last_at=start + timedelta(seconds=5), seconds=5, status="processing", raw_key=raw)
        db.session.add(rec)
        db.session.commit()
        finish_now(rec.id)
        rec = db.session.get(Recording, rec.id)
        assert rec.status == "ready" and rec.file_key.endswith("-hira.webm"), (rec.status, rec.note, rec.file_key)
        assert rec.note.startswith("Hira's voice included for 1 of 2"), rec.note   # the browser-voice line: no Azure, no espeak here
        import subprocess
        vol = subprocess.run(["ffmpeg", "-i", storage.local_path(rec.file_key), "-af", "volumedetect", "-f", "null", "-"],
                             capture_output=True, text=True).stderr
        assert "max_volume: -inf" not in vol   # the sine (Hira) is in the audio track
        rid = rec.id
    v = d(c.get(f"/api/recordings/{att}", headers=login(c, REC)))
    assert v["captions"] is True and v["hira_voice"] is False
    cap = c.get(f"/api/recordings/{att}/{rid}/captions.vtt", headers=login(c, REC))
    assert cap.status_code == 200 and cap.data.decode().startswith("WEBVTT") and "Hira: Why Python?" in cap.data.decode()


def test_ask_isha_finds_questions_from_the_bank_offline(c, app):
    """Ask Isha answers like any assistant, scoped to hiring. Offline it still finds questions in the question bank,
    with what a good answer covers and a model answer."""
    att, h, areas = _started(c, "rv11@demo.test", "Rv Eleven")
    out = d(c.post(f"/api/isha/{att}/chat", headers=h, json={"message": "get me 3 simple sql questions"}))["reply"]
    assert out["source"] == "offline"
    qs = out["questions"]
    assert len(qs) == 3 and all(q["source"] in ("bank", "plan") for q in qs)
    bank = [q for q in qs if q["source"] == "bank"]
    assert bank and all(q["model"] and q["good"] for q in bank) and all(q["level"] == "Easy" for q in bank)
    assert "SQL" in out["text"]
    t = d(c.post(f"/api/isha/{att}/chat", headers=h, json={"message": "how much time is left and what is still to ask?"}))["reply"]
    assert "Still to ask" in t["text"] and "minutes" in t["text"]


# ---------------------------------------------------------------------------------------------------- V02.01.02
def test_unanswered_selected_questions_need_a_decision_and_show_only_when_ticked(c, app):
    """A selected question with no answer needs its answer picked, or Skip. A skipped question, a skipped competency
    and an extra question are on the report only when "Show on report" is ticked. Follow-ups fold into their question."""
    att, h, areas = _started(c, "rv12@demo.test", "Rv Twelve")
    q1, q2, q3 = [a for a in areas if a["type"] not in ("intro",)][:3]
    _turns(app, att, [("interviewer", q1["q"]), ("candidate", "Well, " + _words(q1)),
                      ("interviewer", "And what was your own part in that?"), ("candidate", "I designed the retry logic and wrote the worker myself."),
                      ("interviewer", "Unrelated: which city do you live in these days, and would you relocate?"),
                      ("candidate", "I live in Pune and I would relocate for the right team and role here."),
                      ("interviewer", q2["q"]), ("candidate", "Well, " + _words(q2))])
    d(c.post(f"/api/isha/{att}/end?ai=0", headers=h))
    st = d(c.get(f"/api/isha/{att}", headers=h))["state"]
    un = [u["area"] for u in st["unanswered"]]
    assert q3["area"] in un and q1["area"] not in un and q2["area"] not in un and "Wrap-up" not in un
    assert st["extras"], st["extras"]
    rows = [{"name": "Python", "score": 4}, {"name": "SQL", "score": None, "skipped": True}]
    # nothing decided: a clear message listing them
    r = c.post(f"/api/isha/{att}/scorecard", headers=h, json={"competencies": rows, "recommendation": "hold"})
    body_ = r.get_json()
    assert r.status_code == 400 and "Decision needed for:" in body_["error"] and q3["area"] in body_["fields"]["undecided"]
    # pick the answer for one from the transcript: it's then answered
    m = st["review"]["map"]
    src = next(x for x in m if x.get("quotes"))
    d(c.post(f"/api/isha/{att}/move-quote", headers=h, json={"index": src["index"], "sentence": 0, "to": q3["area"]}))
    un2 = [u["area"] for u in d(c.get(f"/api/isha/{att}", headers=h))["state"]["unanswered"]]
    assert q3["area"] not in un2
    dec = [{"area": a, "skip": True, "reason": "Ran out of time", "show_on_report": a == un2[0]} for a in un2]
    rep = d(c.post(f"/api/isha/{att}/scorecard", headers=h, json={"competencies": rows, "recommendation": "hold", "question_decisions": dec}))
    s = d(c.get(f"/api/reports/{rep['report_id']}", headers=login(c, REC)))["sections"]
    topics = [q["topic"] for q in s["questions"]]
    plan_order = [a["area"] for a in areas]
    # selected questions only, in plan order; the one skipped and ticked shows as skipped; the others don't show
    shown_skip = [q for q in s["questions"] if q.get("skipped")]
    assert [q["topic"] for q in shown_skip] == [un2[0]] and shown_skip[0]["skip_reason"] == "Ran out of time"
    assert not any(q["topic"] in un2[1:] for q in s["questions"])
    assert topics == sorted(topics, key=plan_order.index)
    # the extra question isn't there (not ticked); the follow-up sits inside its question, not as its own row
    assert not any(q.get("extra") for q in s["questions"])
    first = next(q for q in s["questions"] if q["topic"] == q1["area"])
    assert first["followups"] and "retry logic" in first["followups"][0]["a"]
    assert not any(q.get("followup") for q in s["questions"])
    # the skipped competency wasn't ticked: not on the report
    assert [x["name"] for x in s["competencies"]] == ["Python"]
    # summaries only for answered questions
    assert not any(q.get("summary") for q in shown_skip)
