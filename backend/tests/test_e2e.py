"""End-to-end flow across every role on a throwaway SQLite database. Run: pytest -q  (from backend/)."""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["C2H_NO_AUTOCREATE"] = "1"
_db = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["DATABASE_URL"] = "sqlite:///" + _db
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["AZURE_SPEECH_KEY"] = ""

import seed  # noqa: E402
from app import create_app  # noqa: E402

PW = seed.PW


@pytest.fixture(scope="module")
def client():
    seed.run(reset=True)
    app = create_app({"TESTING": True})
    return app.test_client()


def login(c, email, pw=PW):
    r = c.post("/api/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.json
    return {"Authorization": "Bearer " + r.json["data"]["token"]}


def j(r, code=200):
    assert r.status_code == code, (r.status_code, r.get_json())
    return r.get_json()


def test_full_flow(client):
    c = client
    sa = login(c, "super@code2hire.ai")
    admin = login(c, "admin@acme.test")
    priya = login(c, "priya@acme.test")
    rahul = login(c, "rahul@acme.test")
    anita = login(c, "anita@acme.test")
    vikram = login(c, "vikram@acme.test")

    # Superadmin
    ov = j(c.get("/api/platform/overview", headers=sa))
    assert ov["data"]
    new = j(c.post("/api/platform/companies", headers=sa, json={"name": "Beta Corp", "admin_email": "boss@beta.test", "plan": "trial"}))
    assert new["data"]["temporary_password"]
    assert c.get("/api/platform/overview", headers=admin).status_code == 403
    j(c.get("/api/platform/companies?q=beta&sort=name&dir=asc&page=1&size=10", headers=sa))

    # Company admin: stacked roles, settings with locks
    me = j(c.get("/api/auth/me", headers=rahul))["data"]
    assert {r["role"] for r in me["roles"]} == {"recruiter", "interviewer"}
    users = j(c.get("/api/company/users?q=a&sort=name", headers=admin))
    assert users["total"] >= 4
    j(c.put("/api/company/settings", headers=admin, json={"scope": "company", "key": "voice.name", "value": "en-IN-PrabhatNeural", "locked": False}))
    j(c.put("/api/company/settings", headers=admin, json={"scope": "company", "key": "integrity.warnings_allowed", "value": 2, "locked": True}))
    teams = j(c.get("/api/company/teams", headers=admin))["data"]
    eng = next(t for t in teams if t["name"] == "Engineering")
    r = c.put("/api/company/settings", headers=priya, json={"scope": "team", "id": eng["id"], "key": "integrity.warnings_allowed", "value": 5})
    assert r.status_code == 403  # locked at company level
    rows = j(c.get(f"/api/company/settings?scope=team&id={eng['id']}", headers=admin))["data"]
    v = next(x for x in rows if x["key"] == "voice.name")
    assert v["value"] == "en-IN-PrabhatNeural" and v["source"] == "company"
    assert c.post("/api/company/policies", headers=rahul, json={"name": "x", "event": "job.publish", "action": "notify"}).status_code == 403

    # Recruiter: Hira drafts a job, publish public -> approval -> manager approves
    d = j(c.post("/api/jobs/draft", headers=rahul, json={"text": "Senior Node.js engineer with AWS, Docker and SQL"}))["data"]
    assert d["skills"]
    job = j(c.post("/api/jobs", headers=rahul, json={**d, "team_id": eng["id"], "visibility": "public"}))["data"]
    # Rahul is a recruiter; recruiters lack jobs.publish, so a public publish is refused
    assert c.post(f"/api/jobs/{job['id']}/publish", headers=rahul).status_code == 403
    jobs = j(c.get("/api/jobs?status=live&sort=title&dir=asc", headers=rahul))
    py = next(x for x in jobs["items"] if x["title"] == "Senior Python Developer")

    # Manager publishes a public job -> policy creates an approval; admin approves
    job2 = j(c.post("/api/jobs", headers=priya, json={"title": "Platform Engineer", "skills": [{"name": "Python", "level": 3, "must": True}],
                                                       "visibility": "public", "team_id": eng["id"]}))["data"]
    p2 = j(c.post(f"/api/jobs/{job2['id']}/publish", headers=priya))["data"]
    assert p2["approval"] and p2["status"] == "pending_approval"
    appr = j(c.get("/api/company/approvals", headers=admin))["data"]
    aid = next(a["id"] for a in appr if a["ref_id"] == job2["id"])
    assert c.post(f"/api/company/approvals/{aid}/decide", headers=priya, json={"approve": True}).status_code == 403  # own request
    j(c.post(f"/api/company/approvals/{aid}/decide", headers=admin, json={"approve": True}))
    assert j(c.get(f"/api/jobs/{job2['id']}", headers=priya))["data"]["status"] == "live"

    # Candidate signs up and applies
    cand = j(c.post("/api/auth/signup", json={"email": "new@demo.test", "password": "longpassword", "name": "Nikhil",
                                               "resume_text": "Python and Django developer, 5 years, SQL, AWS, Docker"}))["data"]
    ch = {"Authorization": "Bearer " + cand["token"]}
    board = j(c.get("/api/me/jobs?q=python", headers=ch))["data"]
    assert board["items"] and board["items"][0]["match"] is not None
    j(c.post(f"/api/me/jobs/{py['id']}/apply", headers=ch))

    # Hira shortlists, Ask Hira filter, invite to MCQ
    j(c.post(f"/api/jobs/{py['id']}/shortlist", headers=rahul, json={"threshold": 40}))
    chips = j(c.post(f"/api/jobs/{py['id']}/ask", headers=rahul, json={"text": "shortlisted above 50"}))["data"]["chips"]
    assert chips
    apps = j(c.get(f"/api/jobs/{py['id']}/applications?sort=match&q=Nikhil", headers=rahul))
    app_id = apps["items"][0]["id"]
    j(c.post(f"/api/applications/{app_id}/invite", headers=rahul, json={"round_index": 0}))

    # Candidate: MCQ with integrity events
    inv = j(c.get("/api/me", headers=ch))["data"]["invites"][0]
    att = inv["attempt_id"]
    assert c.post(f"/api/rounds/{att}/start", headers=ch).status_code == 400  # consent first
    j(c.post(f"/api/rounds/{att}/consent", headers=ch, json={"checks": {"camera": True}}))
    room = j(c.post(f"/api/rounds/{att}/start", headers=ch))["data"]
    assert room["questions"] and "answer" not in room["questions"][0]
    for q in room["questions"]:
        j(c.post(f"/api/rounds/{att}/answer", headers=ch, json={"qid": q["id"], "choice": 1}))
    e1 = j(c.post(f"/api/rounds/{att}/integrity", headers=ch, json={"type": "window_blur"}))["data"]
    assert not e1["counted"]
    e2 = j(c.post(f"/api/rounds/{att}/integrity", headers=ch, json={"type": "tab_switch"}))["data"]
    assert e2["warnings"] == 1 and not e2["paused"]
    e3 = j(c.post(f"/api/rounds/{att}/integrity", headers=ch, json={"type": "multi_face"}))["data"]
    assert e3["paused"]
    assert c.post(f"/api/rounds/{att}/submit", headers=ch).status_code == 409
    j(c.post(f"/api/rounds/{att}/resume", headers=rahul, json={"note": "Checked with candidate"}))
    res = j(c.post(f"/api/rounds/{att}/submit", headers=ch))["data"]
    assert res["done"]
    rep = j(c.get(f"/api/reports/by-attempt/{att}", headers=rahul))["data"]
    assert rep["sections"]["integrity"]["warnings"] == 2

    # Review + verdict proceed -> AI interview
    j(c.post(f"/api/reports/{rep['id']}/review", headers=rahul, json={"note": "Good basics", "verdict": "proceed"}))
    j(c.post(f"/api/applications/{app_id}/verdict", headers=rahul, json={"verdict": "proceed"}))
    att2 = [i for i in j(c.get("/api/me", headers=ch))["data"]["invites"] if i["type"] == "ai_interview"][0]["attempt_id"]
    voices = j(c.get(f"/api/speech/voices?attempt={att2}", headers=ch))["data"]
    assert voices["voices"]
    j(c.post(f"/api/rounds/{att2}/consent", headers=ch, json={"voice": voices["voices"][0]["name"]}))
    room = j(c.post(f"/api/rounds/{att2}/start", headers=ch))["data"]
    assert room["current"]["q"]
    tts = j(c.post("/api/speech/tts", headers=ch, json={"text": room["current"]["q"], "voice": voices["voices"][0]["name"]}))
    assert tts["data"]["fallback"]
    done = False
    for _ in range(20):
        r = j(c.post(f"/api/rounds/{att2}/turn", headers=ch,
                     json={"answer": "In my last role I designed a Django service because the old one could not scale; "
                                     "we measured a 40 percent drop in latency after moving the hot path to a cache and "
                                     "I wrote the tests and the migration plan myself."}))["data"]
        if r["done"]:
            done = True
            break
    assert done
    rep2 = j(c.get(f"/api/reports/by-attempt/{att2}", headers=rahul))["data"]
    assert rep2["sections"]["competencies"] and rep2["recommendation"]
    client_view = j(c.get(f"/api/reports/{rep2['id']}?audience=client", headers=rahul))["data"]
    assert "integrity" not in client_view["sections"]
    assert c.post(f"/api/reports/{rep2['id']}/share", headers=rahul, json={"audience": "client"}).status_code == 409  # review first
    j(c.post(f"/api/reports/{rep2['id']}/review", headers=rahul,
             json={"edits": [{"name": rep2["sections"]["competencies"][0]["name"], "score": 4, "reason": "Strong example"}]}))
    sh = j(c.post(f"/api/reports/{rep2['id']}/share", headers=rahul, json={"audience": "client", "days": 3}))["data"]
    j(c.get(f"/api/public/shared/{sh['token']}"))
    j(c.post(f"/api/reports/{rep2['id']}/share", headers=rahul, json={"audience": "candidate"}))
    fb = j(c.get("/api/me/feedback", headers=ch))["data"]
    assert fb and "overall" not in fb[0]

    # F2F with Isha: Priya interviews
    me_priya = j(c.get("/api/auth/me", headers=priya))["data"]["user"]
    j(c.post(f"/api/applications/{app_id}/invite", headers=rahul, json={"round_index": 2, "interviewer_id": me_priya["id"]}))
    iv = j(c.get("/api/interviews?status=invited,scheduled", headers=priya))["items"]
    att3 = iv[0]["id"]
    roomi = j(c.get(f"/api/isha/{att3}", headers=priya))["data"]
    assert roomi["brief"]["areas"]
    j(c.post(f"/api/isha/{att3}/start", headers=priya))
    area = roomi["brief"]["areas"][0]
    j(c.post(f"/api/isha/{att3}/ask", headers=priya, json={"area": area["area"], "q": area["q"]}))
    for s in ["I led the migration of our payments service to AWS Lambda.",
              "We chose Lambda because traffic was spiky, and we measured a 30 percent cost drop.",
              "Honestly I think the monitoring part was set up by another team."]:
        out = j(c.post(f"/api/isha/{att3}/sentence", headers=priya, json={"text": s}))["data"]
        assert out["analysis"]["tags"] and out["options"]
    assert any(o["type"] == "Clarify" for o in out["options"])
    draft = j(c.post(f"/api/isha/{att3}/end", headers=priya))["data"]["draft"]
    comps = [{**x, "score": x.get("score") or 3} for x in draft["competencies"]]
    j(c.post(f"/api/isha/{att3}/scorecard", headers=priya, json={"competencies": comps, "recommendation": "proceed"}))

    # Separation of duties: Priya interviewed, so she can't give a final verdict
    r = c.post(f"/api/applications/{app_id}/verdict", headers=priya, json={"verdict": "reject"})
    assert r.status_code == 403
    # Vikram (hiring manager on this job via assignment) makes an offer over band -> 2 approvals
    r = j(c.post(f"/api/applications/{app_id}/verdict", headers=vikram, json={"verdict": "offer", "salary": 4000000}))
    appr = [a for a in j(c.get("/api/company/approvals", headers=admin))["data"] if a["kind"] == "offer.create"][0]
    assert appr["approvals_needed"] == 2
    j(c.post(f"/api/company/approvals/{appr['id']}/decide", headers=admin, json={"approve": True}))
    j(c.post(f"/api/company/approvals/{appr['id']}/decide", headers=priya, json={"approve": True}))
    assert j(c.get(f"/api/applications/{app_id}", headers=rahul))["data"]["stage"] == "offer"

    # Grants with expiry and cover
    anita_id = next(u["id"] for u in users["items"] if u["email"] == "anita@acme.test")
    j(c.post("/api/company/grants", headers=admin, json={"user_id": anita_id, "permission": "analytics.view",
                                                          "expires_at": "2099-01-01T00:00:00"}))
    j(c.get("/api/analytics/overview", headers=anita))
    gr = j(c.post("/api/company/grants", headers=admin, json={"user_id": anita_id, "permission": "export"}))["data"]
    assert gr["status"] == "pending"  # sensitive grant policy

    # Analytics, report builder, export, inbox
    ov = j(c.get("/api/analytics/overview", headers=priya))["data"]
    assert ov["funnel"][0]["count"] >= 1
    j(c.get("/api/analytics/interviewers", headers=priya))
    j(c.get("/api/analytics/questions", headers=priya))
    rb = j(c.post("/api/analytics/ask", headers=priya, json={"text": "average interview score by interviewer"}))["data"]
    assert rb["spec"]["source"] == "interviews"
    exp = c.get("/api/export/applications", headers=admin)
    assert exp.status_code == 200 and b"candidate" in exp.data
    assert c.get("/api/export/applications", headers=rahul).status_code == 403
    today = j(c.get("/api/inbox/today", headers=admin))["data"]
    assert "cards" in today
    j(c.get("/api/company/audit?q=report", headers=admin))
    j(c.get("/api/company/access-review", headers=admin))

    # Candidate growth: practice, skill check badge, learning, certification exam
    pr = j(c.post("/api/me/practice", headers=ch, json={"type": "ai_interview", "skills": ["Python"], "questions": 2}))["data"]
    j(c.post(f"/api/rounds/{pr['attempt_id']}/consent", headers=ch, json={}))
    j(c.post(f"/api/rounds/{pr['attempt_id']}/start", headers=ch))
    for _ in range(6):
        if j(c.post(f"/api/rounds/{pr['attempt_id']}/turn", headers=ch, json={"answer": "A long and specific answer " * 10}))["data"]["done"]:
            break
    sc = j(c.post("/api/me/skill-check", headers=ch, json={"skill": "Python", "level": 3}))["data"]
    j(c.post(f"/api/rounds/{sc['attempt_id']}/consent", headers=ch, json={}))
    room = j(c.post(f"/api/rounds/{sc['attempt_id']}/start", headers=ch))["data"]
    from extensions import db
    from models import Question
    with c.application.app_context():
        for q in room["questions"]:
            ans = db.session.get(Question, q["id"]).answer
            c.post(f"/api/rounds/{sc['attempt_id']}/answer", headers=ch, json={"qid": q["id"], "choice": ans})
    out = j(c.post(f"/api/rounds/{sc['attempt_id']}/submit", headers=ch))["data"]
    assert out["outcome"] == "badge"
    badges = j(c.get("/api/me/badges", headers=ch))["data"]
    v = j(c.get(f"/api/public/verify/{badges[0]['code']}"))["data"]
    assert v["state"] == "valid"
    lp = j(c.post("/api/me/learning", headers=ch, json={"skill": "AWS"}))["data"]
    j(c.patch(f"/api/me/learning/{lp['id']}/topics/0", headers=ch, json={"done": True}))
    cat = j(c.get("/api/certs-catalog", headers=ch))["data"]
    cert = cat[0]
    ex = j(c.post(f"/api/certs/{cert['id']}/start", headers=ch))["data"]
    a1 = ex["attempt_id"]
    j(c.post(f"/api/rounds/{a1}/consent", headers=ch, json={}))
    room = j(c.post(f"/api/rounds/{a1}/start", headers=ch))["data"]
    with c.application.app_context():
        for q in room["questions"]:
            c.post(f"/api/rounds/{a1}/answer", headers=ch, json={"qid": q["id"], "choice": db.session.get(Question, q["id"]).answer})
    out = j(c.post(f"/api/rounds/{a1}/submit", headers=ch))["data"]
    assert out["outcome"].startswith("next_section:")
    a2 = int(out["outcome"].split(":")[1])
    j(c.post(f"/api/rounds/{a2}/consent", headers=ch, json={}))
    j(c.post(f"/api/rounds/{a2}/start", headers=ch))
    for _ in range(8):
        r = j(c.post(f"/api/rounds/{a2}/turn", headers=ch, json={"answer": "I built it because we measured the trade-off carefully " * 6}))["data"]
        if r["done"]:
            break
    mine = j(c.get("/api/me/certifications", headers=ch))["data"]
    assert mine[0]["status"] in ("completed", "review")

    # Company certification config validation
    bad = j(c.post("/api/certs", headers=admin, json={"name": "SQL L2", "skills": ["SQL"], "sections": [{"type": "mcq", "weight": 50}]}))["data"]
    assert c.post(f"/api/certs/{bad['id']}/publish", headers=admin).status_code == 400

    # Privacy
    j(c.get("/api/me/export", headers=ch))
    assert c.get("/api/health").status_code == 200


def test_video_call(client):
    import io
    c = client
    rahul = login(c, "rahul@acme.test")
    priya = login(c, "priya@acme.test")
    arjun = login(c, "arjun@demo.test")
    meera = login(c, "meera@demo.test")
    pid = j(c.get("/api/auth/me", headers=priya))["data"]["user"]["id"]
    aid = j(c.get("/api/jobs/1/applications?q=Arjun", headers=rahul))["items"][0]["id"]
    att = j(c.post(f"/api/applications/{aid}/invite", headers=rahul, json={"round_index": 2, "interviewer_id": pid}))["data"]["attempt_id"]

    iv = j(c.get(f"/api/call/{att}", headers=priya))["data"]
    assert iv["role"] == "interviewer" and iv["ice_servers"] and iv["enabled"]
    cd = j(c.get(f"/api/call/{att}", headers=arjun))["data"]
    assert cd["role"] == "candidate" and cd["can_join"]
    assert c.get(f"/api/call/{att}", headers=meera).status_code == 403

    # signalling: join -> offer -> answer -> ice, each side only sees the other's messages
    j(c.post(f"/api/call/{att}/signal", headers=arjun, json={"kind": "join"}))
    got = j(c.get(f"/api/call/{att}/signal?after={iv['cursor']}", headers=priya))["data"]
    assert [s["kind"] for s in got["signals"]] == ["join"] and got["peer_online"]
    j(c.post(f"/api/call/{att}/signal", headers=priya, json={"kind": "offer", "payload": {"type": "offer", "sdp": "v=0"}}))
    g2 = j(c.get(f"/api/call/{att}/signal?after={cd['cursor']}", headers=arjun))["data"]
    assert [s["kind"] for s in g2["signals"]] == ["offer"]
    j(c.post(f"/api/call/{att}/signal", headers=arjun, json={"kind": "answer", "payload": {"type": "answer", "sdp": "v=0"}}))
    j(c.post(f"/api/call/{att}/signal", headers=arjun, json={"kind": "ice", "payload": {"candidate": "x"}}))
    g3 = j(c.get(f"/api/call/{att}/signal?after={got['cursor']}", headers=priya))["data"]
    assert [s["kind"] for s in g3["signals"]] == ["answer", "ice"]

    # captions only from the candidate; chat; focus notice becomes a non-counted integrity event
    assert c.post(f"/api/call/{att}/signal", headers=priya, json={"kind": "caption", "payload": {"text": "x"}}).status_code == 403
    j(c.post(f"/api/call/{att}/signal", headers=arjun, json={"kind": "caption", "payload": {"text": "I designed the cache layer."}}))
    j(c.post(f"/api/call/{att}/signal", headers=priya, json={"kind": "chat", "payload": {"text": "Can you hear me?"}}))
    j(c.post(f"/api/call/{att}/signal", headers=arjun, json={"kind": "focus", "payload": {"visible": False}}))
    assert len(j(c.get(f"/api/call/{att}/chat", headers=arjun))["data"]) == 1
    assert c.post(f"/api/call/{att}/signal", headers=arjun, json={"kind": "hack"}).status_code == 400

    # Isha uses the caption as a sentence; then recording upload, report shows it, replay works
    j(c.post(f"/api/isha/{att}/start", headers=priya))
    j(c.post(f"/api/isha/{att}/ask", headers=priya, json={"area": "Python", "q": "Tell me about caching"}))
    out = j(c.post(f"/api/isha/{att}/sentence", headers=priya, json={"text": "I designed the cache layer because reads were slow."}))["data"]
    assert out["analysis"]["tags"]
    r = c.post(f"/api/call/{att}/recording", headers=priya, data={"file": (io.BytesIO(b"\x1aE\xdf\xa3" + b"0" * 4000), "a.webm"), "seconds": "95"},
               content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    assert c.post(f"/api/call/{att}/recording", headers=arjun, data={"file": (io.BytesIO(b"x"), "a.webm")}, content_type="multipart/form-data").status_code == 403
    draft = j(c.post(f"/api/isha/{att}/end", headers=priya))["data"]["draft"]
    j(c.post(f"/api/isha/{att}/scorecard", headers=priya, json={"competencies": [{**x, "score": x.get("score") or 4} for x in draft["competencies"]], "recommendation": "proceed"}))
    rep = j(c.get(f"/api/reports/by-attempt/{att}", headers=rahul))["data"]
    assert rep["recording"][0]["seconds"] == 95
    assert c.get(f"/api/call/{att}/recording/0", headers=rahul).status_code == 200
    assert c.get(f"/api/call/{att}/recording/0", headers=arjun).status_code == 403
    assert c.post(f"/api/call/{att}/signal", headers=arjun, json={"kind": "chat", "payload": {"text": "late"}}).status_code == 409
