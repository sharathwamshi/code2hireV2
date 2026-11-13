"""Ask Disha (V02.00.09, N1): the candidate's own assistant.

Disha answers from a snapshot of the candidate's OWN data, built here as the candidate: their profile, their
applications and where each one stands, their upcoming rounds (when, what kind, how to join), their practice and
skill-check results, their badges and jobs that match them, plus how-to help for Code2Hire itself.

What never goes into the snapshot, so Disha can't reveal it: other candidates, the hiring team's notes, scores or
recommendations from hiring rounds that the company hasn't shared, and the questions of rounds still to come.

When Claude is available it writes the answer from the snapshot only; without it, a keyword reader answers the
common questions from the same snapshot.
"""
import json
import re
from datetime import datetime

from extensions import db
from models import Application, CandidateProfile, Company, Credential, Job, Report, RoundAttempt, User
from services import ai
from services.pipeline import ROUND_TYPES, join_window, round_name, skill_match

STAGE = {"applied": "Applied", "shortlisted": "Shortlisted", "in_round": "In progress", "awaiting_review": "Being reviewed",
         "decision": "Being reviewed", "on_hold": "Being reviewed", "offer": "Offer", "hired": "Hired",
         "rejected": "Not selected", "withdrawn": "Withdrawn", "removed": "Closed"}
ROUND_STATUS = {"invited": "invited, not started", "scheduled": "scheduled", "in_progress": "in progress", "paused": "paused by the recruiter",
                "completed": "done", "reviewed": "done", "not_finished": "not finished", "expired": "missed",
                "voided": "replaced by a new session", "cancelled": "cancelled"}
EXAMPLES = ["When is my next interview?", "What's the status of my applications?", "How do I join a video interview?",
            "How did my last practice go?", "Which jobs match my skills?", "What should I improve?"]
HELP = {
    "join": "Open your Code2Hire home page and press Join on the interview card. Use Chrome or Edge on a laptop, allow the "
            "camera and microphone when the browser asks, and run the 1-minute system check first. If the video doesn't "
            "connect, press Try again; captions and chat still work.",
    "system_check": "The system check tests your camera, microphone, speakers and connection in about a minute. You'll find "
                    "it on every interview card (\"Test my setup\").",
    "rejoin": "If you drop out of a live interview, go back to your home page and press Rejoin while the interview is open.",
    "retake": "If an interview went wrong for a technical reason, tell the hiring team. They can give you a new session; "
              "you'll see the new invite on your home page.",
    "practice": "Practice interviews and quizzes are private to you. Employers never see them. Start one from Practice.",
    "badge": "Pass a short skill check (70% or more) and that skill shows as verified to employers, with a badge.",
    "password": "To change your password, open your profile menu and choose Change password.",
    "privacy": "Your data and download options are under Privacy in your profile menu.",
}


def _iso(d):
    return d.isoformat() + "Z" if d else None


def snapshot(user):
    """Everything Disha may use, from the candidate's own records. Nothing about anyone else."""
    p = CandidateProfile.query.filter_by(user_id=user.id).first()
    apps, upcoming = [], []
    for a in Application.query.filter_by(candidate_id=user.id).order_by(Application.created_at.desc()).all():
        j = db.session.get(Job, a.job_id)
        if not j:
            continue
        c = db.session.get(Company, j.company_id)
        company = None if j.client_hidden else (c.name if c else None)
        rounds = []
        for att in (RoundAttempt.query.filter_by(application_id=a.id).order_by(RoundAttempt.round_index, RoundAttempt.id).all()):
            if att.status == "voided" and ((att.result or {}).get("voided") or {}).get("retake_attempt_id"):
                continue
            item = {"round": round_name(att, j), "kind": ROUND_TYPES.get(att.round_type, att.round_type),
                    "status": ROUND_STATUS.get(att.status, att.status)}
            if att.status in ("invited", "scheduled", "in_progress", "paused"):
                can_join, opens = join_window(att)
                iv = db.session.get(User, att.interviewer_id) if att.interviewer_id else None
                item.update({"scheduled_at": _iso(att.scheduled_at), "deadline": _iso(att.deadline_at), "can_join_now": can_join,
                             "opens_at": _iso(opens), "interviewer": iv.name if iv else None,
                             "minutes": (att.config or {}).get("interview.minutes") or (att.config or {}).get("mcq.minutes"),
                             "setup_tested": bool(((att.result or {}).get("syscheck") or {}).get("passed")),
                             "link": f"/room/{att.id}"})
                upcoming.append({**item, "job": j.title, "company": company})
            r = Report.query.filter_by(attempt_id=att.id).first()
            if r and r.shared_with_candidate:  # only feedback the company chose to share
                fb = r.candidate_feedback or {}
                item["shared_feedback"] = {k: fb.get(k) for k in ("summary", "strengths", "improve", "next_steps") if fb.get(k)}
            rounds.append(item)
        apps.append({"job": j.title, "company": company, "status": STAGE.get(a.stage, a.stage), "applied": _iso(a.created_at),
                     "rounds": rounds, "link": "/me/applications"})
    practice = []
    for att in RoundAttempt.query.filter_by(practice_user_id=user.id).order_by(RoundAttempt.created_at.desc()).limit(6).all():
        r = Report.query.filter_by(attempt_id=att.id).first()
        s = (r.sections or {}) if r else {}
        practice.append({"title": (att.config or {}).get("title") or "Practice", "kind": ROUND_TYPES.get(att.round_type, att.round_type),
                         "skill_check": bool((att.config or {}).get("skill_check")), "status": ROUND_STATUS.get(att.status, att.status),
                         "score": (f"{att.score}%" if att.round_type == "mcq" else f"{att.score} / 5") if att.score is not None else None,
                         "date": _iso(att.created_at), "strengths": (s.get("strengths") or [])[:4], "gaps": (s.get("gaps") or [])[:4]})
    badges = [{"skill": b.skill, "level": b.level, "title": b.title} for b in
              Credential.query.filter_by(user_id=user.id, revoked=False).order_by(Credential.created_at.desc()).limit(10).all()]
    matches = []
    if p:
        for j in Job.query.filter_by(status="live", visibility="public").limit(200).all():
            pct, got, missing = skill_match(j, p.skills or [])
            c = db.session.get(Company, j.company_id)
            matches.append({"job": j.title, "company": None if j.client_hidden else (c.name if c else None), "match": pct,
                            "missing": missing[:3], "link": f"/me/jobs/{j.id}"})
        matches.sort(key=lambda m: -(m["match"] or 0))
    return {"today": datetime.utcnow().strftime("%a %d %b %Y, %H:%M UTC"), "name": user.name,
            "profile": {"headline": p.headline if p else None, "skills": [{"name": s.get("name"), "verified": bool(s.get("verified"))} for s in (p.skills or [])][:15] if p else [],
                        "experience_years": p.experience_years if p else None, "has_resume": bool(p and p.resume_text),
                        "goal": (p.target_roles or [None])[0] if p else None},
            "applications": apps, "upcoming": upcoming, "practice": practice, "badges": badges, "job_matches": matches[:5]}


def _fmt_when(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.rstrip("Z")).strftime("%a %d %b, %H:%M UTC")
    except ValueError:
        return s


def _rules(q, snap):
    """Answers without Claude, from the same snapshot."""
    t = q.lower()
    items = []
    if re.search(r"\b(join|camera|microphone|mic|video|connect|browser|audio)\b", t):
        return HELP["join"] + " " + HELP["system_check"], [{"label": "Open my home page", "link": "/me"}], "help"
    if re.search(r"\b(rejoin|dropped|disconnect)", t):
        return HELP["rejoin"], [{"label": "Open my home page", "link": "/me"}], "help"
    if re.search(r"\b(retake|went wrong|technical|again)\b", t):
        return HELP["retake"], [], "help"
    if re.search(r"\b(password)\b", t):
        return HELP["password"], [], "help"
    if re.search(r"\b(privacy|delete my|my data)\b", t):
        return HELP["privacy"], [], "help"
    if re.search(r"\b(badge|verified|skill check)\b", t):
        if snap["badges"]:
            return f"You have {len(snap['badges'])} badge{'s' if len(snap['badges']) != 1 else ''}: " + ", ".join(b["title"] or b["skill"] for b in snap["badges"]) + ". " + HELP["badge"], [{"label": "Skill checks", "link": "/me/skills"}], "badges"
        return "You don't have a badge yet. " + HELP["badge"], [{"label": "Take a skill check", "link": "/me/skills"}], "badges"
    if re.search(r"\b(practice|practise|mock|improve|better|feedback|weak)", t):
        if not snap["practice"]:
            return "You haven't practised yet. " + HELP["practice"], [{"label": "Start practising", "link": "/me/practice"}], "practice"
        last = snap["practice"][0]
        gaps = sorted({g for pr in snap["practice"] for g in pr.get("gaps") or []})
        text = f"Your last practice was \"{last['title']}\" ({last['kind']})" + (f": {last['score']}." if last["score"] else f", {last['status']}.")
        if gaps:
            text += " Areas to work on from your practice: " + ", ".join(gaps[:5]) + "."
        return text, [{"label": "Practice", "link": "/me/practice"}, {"label": "Learning paths", "link": "/me/learning"}], "practice"
    if re.search(r"\b(job|jobs|match|role|openings?)\b", t) and not re.search(r"\b(status|applied|application)", t):
        if not snap["job_matches"]:
            return "I couldn't find open jobs to match yet. Add your skills to your profile so I can match you.", [{"label": "Profile", "link": "/me/profile"}], "jobs"
        items = [{"label": f"{m['job']}" + (f" · {m['company']}" if m["company"] else ""), "sub": f"{m['match']}% match", "link": m["link"]} for m in snap["job_matches"]]
        return "These open jobs match your skills best:", items, "jobs"
    if re.search(r"\b(next|upcoming|when|interview|schedule|today|tomorrow|round)\b", t) and snap["upcoming"]:
        for u in snap["upcoming"][:5]:
            when = _fmt_when(u.get("scheduled_at"))
            sub = ", ".join(x for x in [u["kind"], f"at {when}" if when else ("take it when you're ready" if not u.get("deadline") else f"before {_fmt_when(u['deadline'])}"),
                                        f"with {u['interviewer']}" if u.get("interviewer") else None] if x)
            items.append({"label": f"{u['round']} · {u['job']}", "sub": sub, "link": u["link"]})
        return f"You have {len(snap['upcoming'])} round{'s' if len(snap['upcoming']) != 1 else ''} waiting:", items, "upcoming"
    if snap["applications"]:
        items = [{"label": f"{a['job']}" + (f" · {a['company']}" if a["company"] else ""), "sub": a["status"], "link": a["link"]} for a in snap["applications"][:8]]
        lead = "Here's where your applications stand:" if not re.search(r"\b(next|upcoming|interview)\b", t) else "You have no rounds waiting right now. Your applications:"
        return lead, items, "applications"
    return ("I can help with your applications, interviews, practice, badges and matching jobs. You haven't applied to a job yet; "
            "take a look at the jobs that match you."), [{"label": "Find jobs", "link": "/me/jobs"}], "help"


def answer(user, q, history=()):
    snap = snapshot(user)
    text, items, intent = _rules(q, snap)
    engine = "rules"
    if ai.configured():
        def fb():
            return None
        prev = [{"role": m.role, "text": m.text[:400]} for m in history][-6:]
        out = ai.ask_json("answer a candidate's question as Disha", f"""You are Disha, the friendly career assistant inside Code2Hire, talking to {snap['name']}, a job seeker.
Answer ONLY from the data below (it is this candidate's own record) and the how-to notes. If the data doesn't answer it, say so
plainly and suggest where in Code2Hire to look. Never invent dates, scores, companies, interview questions or outcomes. Never
guess how the hiring team will decide. Be warm, short (at most 5 sentences) and practical. Times are in UTC; say so.
How-to notes: {json.dumps(HELP)}
Earlier in this chat: {json.dumps(prev)}
Candidate data: {json.dumps(snap)[:9000]}
Question: {q}
Return JSON: {{"answer": str, "links": [{{"label": short, "link": a path that appears in the data or one of /me, /me/applications, /me/jobs, /me/practice, /me/skills, /me/learning, /me/profile, /me/feedback}}] (0-4)}}""",
                          fb, max_tokens=700, timeout=20)
        if isinstance(out, dict) and str(out.get("answer") or "").strip():
            text = str(out["answer"]).strip()[:2000]
            allowed = {"/me", "/me/applications", "/me/jobs", "/me/practice", "/me/skills", "/me/learning", "/me/profile", "/me/feedback"}
            allowed |= {u["link"] for u in snap["upcoming"]} | {m["link"] for m in snap["job_matches"]}
            links = [{"label": str(x.get("label") or "Open")[:60], "link": x["link"]} for x in out.get("links") or []
                     if isinstance(x, dict) and x.get("link") in allowed][:4]
            items = links or items
            engine = "claude"
    return {"text": text, "items": items, "intent": intent, "engine": engine}
