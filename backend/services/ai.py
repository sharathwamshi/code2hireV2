"""Every AI task in Code2Hire runs through Anthropic here.

Each function has a deterministic fallback so the platform still works end to end
when no API key is configured (useful for local demos and tests).
"""
import json
import logging
import random
import re

from flask import current_app

from services.settings import platform_secret, resolve

log = logging.getLogger("code2hire.ai")

SYSTEM_BASE = (
    "You are part of Code2Hire, an AI hiring platform with three agents: Hira (recruiter agent), "
    "Isha (live interview copilot) and Disha (candidate agent). Be fair, specific and evidence-based. "
    "Never ask about or use age, religion, caste, gender, marital status, pregnancy, disability or salary history. "
    "A human always makes the final hiring decision. Reply with valid JSON only, no prose around it."
)


def _client():
    key = platform_secret("anthropic_api_key", current_app.config.get("ANTHROPIC_API_KEY", ""))
    if not key:
        return None
    import anthropic
    return anthropic.Anthropic(api_key=key)


def configured():
    return bool(platform_secret("anthropic_api_key", current_app.config.get("ANTHROPIC_API_KEY", "")))


def _model(company_id=None):
    m, _, _ = resolve("ai.model", company_id=company_id)
    return m or current_app.config.get("ANTHROPIC_MODEL")


def _parse(text):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=0)
    return json.loads(text[start:])


def ask_json(task, prompt, fallback, company_id=None, max_tokens=2000, system_extra=""):
    """Call Anthropic and parse JSON. Falls back on any failure."""
    client = _client()
    if client is None:
        return fallback() if callable(fallback) else fallback
    banned, _, _ = resolve("ai.banned_topics", company_id=company_id)
    system = SYSTEM_BASE + f" Task: {task}. Banned topics: {', '.join(banned or [])}. " + system_extra
    for attempt in range(2):
        try:
            msg = client.messages.create(model=_model(company_id), max_tokens=max_tokens, system=system,
                                         messages=[{"role": "user", "content": prompt}])
            text = "".join(getattr(b, "text", "") for b in msg.content)
            return _parse(text)
        except Exception as e:  # network, quota, malformed JSON
            log.warning("AI task %s failed (attempt %s): %s", task, attempt + 1, e)
    return fallback() if callable(fallback) else fallback


# ---------------------------------------------------------------- helpers for fallbacks

KNOWN_SKILLS = ["Java", "Spring Boot", "SQL", "Python", "Django", "Flask", "React", "JavaScript", "TypeScript",
                "Node.js", "Kubernetes", "Docker", "AWS", "Azure", "Kafka", "Microservices", "System design",
                "Data analysis", "Excel", "Power BI", "Tableau", "Statistics", "Machine learning", "Communication",
                "Sales", "Negotiation", "CRM", "Customer success", "Go", "C#", ".NET", "Angular", "DevOps", "Linux",
                "Testing", "Selenium", "Product management", "Figma", "PostgreSQL", "MySQL", "MongoDB", "Redis"]


def extract_skills(text):
    t = (text or "").lower()
    return [s for s in KNOWN_SKILLS if s.lower() in t]


EMAIL_IN_TEXT = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}")
PHONE_IN_TEXT = re.compile(r"(?:\+\d{1,3}[\s-]?)?(?:\(?\d{2,5}\)?[\s-]?)?\d{3,5}[\s-]?\d{4,5}")


def resume_fields(text, company_id=None):
    """Name, email, phone, city, headline, years and skills from resume text. Falls back to simple pattern matching."""
    def fb():
        lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
        email = (EMAIL_IN_TEXT.search(text or "") or [None])[0]
        phone = None
        for m in PHONE_IN_TEXT.finditer(text or ""):
            if 10 <= len(re.sub(r"\D", "", m.group(0))) <= 15:
                phone = m.group(0).strip()
                break
        name = ""
        for l in lines[:6]:
            if not EMAIL_IN_TEXT.search(l) and not re.search(r"\d", l) and 2 <= len(l.split()) <= 5 and len(l) <= 60:
                name = l.title() if l.isupper() else l
                break
        yrs = re.search(r"(\d{1,2})\+?\s*(?:years|yrs)", text or "", re.I)
        return {"name": name, "email": email, "phone": phone, "location": "", "headline": "",
                "experience_years": int(yrs.group(1)) if yrs else None, "skills": extract_skills(text)}
    out = ask_json("read a resume", f"""Read this resume and return the candidate's details exactly as written.
Resume:
\"\"\"{(text or '')[:8000]}\"\"\"
Return JSON: {{"name": str, "email": str|null, "phone": str|null (with country code if shown), "location": str (city),
"headline": str (current role in under 8 words), "experience_years": int|null, "skills": [str] (up to 15, most relevant first)}}.
Use null or "" when something isn't in the resume. Never guess an email or phone.""", fb, company_id, max_tokens=700)
    if not isinstance(out, dict):
        out = fb()
    # never trust a model-invented contact: it must appear in the text
    for k in ("email", "phone"):
        v = out.get(k)
        if v and re.sub(r"\W", "", str(v)).lower() not in re.sub(r"\W", "", text or "").lower():
            out[k] = fb().get(k)
    out["skills"] = [str(s)[:60] for s in (out.get("skills") or []) if s][:15]
    return out


def _words(text):
    return set(re.findall(r"[a-z0-9+#.]+", (text or "").lower()))


# ---------------------------------------------------------------- Hira: jobs and screening

def draft_job(text, company_id=None):
    def fb():
        skills = extract_skills(text) or ["Communication", "Problem solving"]
        title = (text.strip().split("\n")[0][:80] or "New role").title()
        return {
            "title": title,
            "summary": f"{title}: a role focused on {', '.join(skills[:3])}.",
            "description": text if len(text) > 60 else f"We are hiring a {title}. You will work with {', '.join(skills[:4])} "
                           "to deliver reliable, well-tested work as part of a collaborative team.",
            "skills": [{"name": s, "level": 3 if i < 3 else 2, "must": i < 3} for i, s in enumerate(skills[:7])],
            "level": "Senior" if "senior" in text.lower() else ("Junior" if "junior" in text.lower() else "Mid"),
            "rounds": [{"type": "mcq", "name": "Skill screen"}, {"type": "ai_interview", "name": "AI interview with Hira"},
                       {"type": "f2f_isha", "name": "F2F with Isha"}, {"type": "f2f_human", "name": "Hiring manager"}],
            "questions": [f"Walk me through a recent project where you used {s}. What was hard about it?" for s in skills[:3]],
        }
    return ask_json("draft a job from a description", f"""Turn this job input into a hiring plan.
Input:
\"\"\"{text[:6000]}\"\"\"
Return JSON: {{"title": str, "summary": str (1 sentence), "description": str (120-200 words, plain, inclusive),
"skills": [{{"name": str, "level": 1-5, "must": bool}}] (4-8 items), "level": "Junior|Mid|Senior|Lead",
"rounds": [{{"type": "mcq|ai_interview|f2f_isha|f2f_human", "name": str}}] (2-4 rounds),
"questions": [str] (3 strong first interview questions)}}""", fb, company_id)


def generate_mcq(skills, level=3, n=5, company_id=None):
    def fb():
        out = []
        for i in range(n):
            s = skills[i % len(skills)] if skills else "General"
            out.append({"skill": s, "level": level,
                        "text": f"Which statement about {s} is most accurate for a level {level} practitioner?",
                        "options": [f"{s} is best learned only from documentation",
                                    f"Applying {s} well means understanding its trade-offs in context",
                                    f"{s} has no common failure modes",
                                    f"{s} should never be tested"],
                        "answer": 1, "explanation": "Understanding trade-offs is the practical skill being tested."})
        return out
    data = ask_json("write multiple-choice questions", f"""Write {n} multiple-choice questions to screen candidates.
Skills: {', '.join(skills)}. Difficulty level {level} of 5. Practical, unambiguous, one correct answer, 4 options each.
Include a short code snippet in "code" only when it helps (else empty string).
Return JSON list: [{{"skill": str, "level": int, "text": str, "code": str, "options": [str,str,str,str], "answer": 0-3, "explanation": str}}]""",
                    fb, company_id, max_tokens=3000)
    return data if isinstance(data, list) else fb()


def score_resume(job, resume_text, company_id=None):
    skills = job.skills or []

    def fb():
        words = _words(resume_text)
        hit, missing = [], []
        for s in skills:
            name = s["name"] if isinstance(s, dict) else s
            (hit if all(w in words for w in _words(name)) else missing).append(name)
        must = [s["name"] for s in skills if isinstance(s, dict) and s.get("must")]
        must_hit = [m for m in must if m in hit]
        score = int(round(100 * (len(hit) + len(must_hit)) / max(1, len(skills) + len(must)))) if skills else 50
        reasons = [f"{len(must_hit)} of {len(must)} must-haves"] if must else []
        if missing:
            reasons.append("No " + ", ".join(missing[:2]))
        return {"score": score, "reasons": reasons or ["Profile reviewed"], "matched": hit, "missing": missing}
    return ask_json("score a resume against a job", f"""Score this candidate against the job. Be fair; judge skills and evidence only.
Job: {job.title}. Must-haves and skills: {json.dumps(skills)}
Resume:
\"\"\"{(resume_text or '')[:6000]}\"\"\"
Return JSON: {{"score": 0-100, "reasons": [short plain reasons, max 3, e.g. "5 of 7 must-haves", "No Kubernetes"],
"matched": [skill names], "missing": [skill names]}}""", fb, company_id)


# ---------------------------------------------------------------- Hira: AI interview

def interview_plan(job, resume_text, n=5, difficulty="medium", company_id=None):
    skills = [s["name"] if isinstance(s, dict) else s for s in (job.skills or [])] or ["the role"]

    def fb():
        base = (job.plan or {}).get("questions") or []
        qs = list(base)
        templates = ["Tell me about a project where you used {s}. What decisions did you make and why?",
                     "What is a common mistake people make with {s}, and how do you avoid it?",
                     "Describe a time {s} work went wrong in production. How did you find and fix it?",
                     "How would you explain {s} trade-offs to a non-technical teammate?"]
        i = 0
        while len(qs) < n:
            qs.append(templates[i % len(templates)].format(s=skills[i % len(skills)]))
            i += 1
        return {"questions": [{"q": q, "topic": skills[k % len(skills)]} for k, q in enumerate(qs[:n])]}
    data = ask_json("plan an AI interview", f"""Plan a structured spoken interview for {job.title} ({job.level}).
Skills to cover: {json.dumps(job.skills)}. Difficulty: {difficulty}.
Candidate resume (to tailor questions and test claims):
\"\"\"{(resume_text or '')[:4000]}\"\"\"
Return JSON: {{"questions": [{{"q": str (one question, speakable, under 35 words), "topic": skill name}}]}} with exactly {n} questions.""",
                    fb, company_id)
    if not isinstance(data, dict) or not data.get("questions"):
        return fb()
    return data


def followup(question, answer, topic, company_id=None):
    """Decide whether to ask one follow-up based on the answer."""
    def fb():
        words = len((answer or "").split())
        if words < 25:
            return {"ask": True, "q": f"Could you give a specific example of that from your own work with {topic}?"}
        return {"ask": False, "q": ""}
    return ask_json("decide on an interview follow-up", f"""Interview question: {question}
Candidate answer: {answer}
Should the interviewer ask ONE follow-up to test depth or clarify a vague claim? Return JSON:
{{"ask": bool, "q": str (one short spoken question, or empty)}}""", fb, company_id, max_tokens=300)


def interview_report(job, resume_text, qa, rubric, company_id=None, round_name="AI interview"):
    """qa: [{q, a, topic, at}] -> full report sections."""
    comps = rubric or [{"name": s["name"] if isinstance(s, dict) else s, "weight": 1} for s in (job.skills or [])][:5]
    if not comps:
        comps = [{"name": "Role knowledge", "weight": 1}, {"name": "Communication", "weight": 1}]

    def fb():
        rows, qscores = [], []
        for item in qa:
            n = len((item.get("a") or "").split())
            sc = 1.5 if n < 5 else (2.5 if n < 20 else (3.5 if n < 60 else 4.2))
            qscores.append({"q": item["q"], "a": item.get("a", ""), "score": sc, "time": item.get("at", ""),
                            "good_answer": ["A specific example", "The reasoning behind decisions", "What was learned"],
                            "covered": [n >= 20, n >= 40, n >= 60], "topic": item.get("topic")})
        avg = round(sum(q["score"] for q in qscores) / max(1, len(qscores)), 1) if qscores else 0
        for c in comps:
            related = [q for q in qscores if (q.get("topic") or "").lower() in c["name"].lower() or c["name"].lower() in (q.get("topic") or "").lower()]
            sc = round(sum(q["score"] for q in related) / len(related), 1) if related else avg
            quote = related[0]["a"][:220] if related else (qscores[0]["a"][:220] if qscores else "")
            rows.append({"name": c["name"], "score": sc, "weight": c.get("weight", 1),
                         "level": "Strong" if sc >= 4 else ("Meets" if sc >= 3 else "Weak"),
                         "evidence": quote, "time": related[0]["time"] if related else ""})
        rec = "proceed" if avg >= 3.6 else ("hold" if avg >= 2.8 else "reject")
        return {"overall": avg, "recommendation": rec, "confidence": "medium",
                "summary": f"Answered {len(qa)} questions with an average of {avg} out of 5. "
                           + ("Answers were specific and well reasoned." if avg >= 3.6 else "Several answers lacked specific examples."),
                "competencies": rows, "questions": qscores,
                "resume_vs_reality": [{"claim": s, "status": "confirmed" if any(s.lower() in (q.get('a') or '').lower() for q in qa) else "not_tested"}
                                      for s in extract_skills(resume_text)[:4]],
                "strengths": [r["name"] for r in rows if r["score"] >= 4][:3] or ["Completed every question"],
                "gaps": [r["name"] for r in rows if r["score"] < 3][:3],
                "coverage": {"planned": [c["name"] for c in comps], "tested": [r["name"] for r in rows if r["evidence"]]},
                "handoff": [f"Probe {r['name']} with a concrete scenario" for r in rows if r["score"] < 3.5][:3]}
    transcript = "\n".join(f"Q{i+1} [{x.get('topic','')}] ({x.get('at','')}): {x['q']}\nA: {x.get('a','')}" for i, x in enumerate(qa))
    length, _, _ = resolve("ai.summary_length", company_id=company_id)
    return ask_json("write an evidence-linked interview report", f"""Write the {round_name} report for {job.title}.
Rubric competencies (name, weight): {json.dumps(comps)}
Resume:
\"\"\"{(resume_text or '')[:3000]}\"\"\"
Transcript:
{transcript[:12000]}
Score 1-5 per competency and per question. Every score MUST cite an exact quote from the candidate's answer.
Summary length: {length}.
Return JSON: {{"overall": float, "recommendation": "proceed|hold|reject", "confidence": "low|medium|high",
"summary": str (max 3 sentences), "competencies": [{{"name","score","weight","level":"Strong|Meets|Weak","evidence": exact quote,"time": str}}],
"questions": [{{"q","a","score","time","good_answer":[3 short points],"covered":[bool,bool,bool],"topic"}}],
"resume_vs_reality": [{{"claim": str, "status": "confirmed|partly|contradicted|not_tested"}}],
"strengths": [str], "gaps": [str], "coverage": {{"planned":[str],"tested":[str]}}, "handoff": [what the next round should probe]}}""",
                    fb, company_id, max_tokens=4000)


# ---------------------------------------------------------------- Isha: live copilot

def isha_brief(job, resume_text, prior, company_id=None):
    skills = [s["name"] if isinstance(s, dict) else s for s in (job.skills or [])]
    gaps = []
    for r in prior:
        gaps += (r.get("handoff") or []) + (r.get("gaps") or [])

    def fb():
        areas = []
        for s in skills[:5]:
            areas.append({"area": s, "why": "JD must-have" if s in gaps else "From the JD",
                          "q": f"Walk me through how you have used {s} in a real project. What would you do differently?",
                          "simple": f"Tell me about a time you used {s} at work.",
                          "good": ["A specific situation", "Their own decisions and why", "A measurable result"]})
        areas.append({"area": "Wrap-up", "why": "Always", "q": "What questions do you have for us about the team or the role?",
                      "simple": "Is there anything you'd like to ask us?", "good": ["Thoughtful questions about the work"]})
        return {"areas": areas, "gaps": gaps[:4]}
    return ask_json("prepare a live interview plan for a non-expert interviewer", f"""Prepare Isha's brief for a live interview for {job.title}.
The interviewer may not be a domain expert. Skills: {json.dumps(job.skills)}
Gaps and handoffs from earlier rounds: {json.dumps(gaps[:8])}
Resume:
\"\"\"{(resume_text or '')[:3000]}\"\"\"
Return JSON: {{"areas": [{{"area": str, "why": short reason, "q": the question, "simple": the same question in plain words,
"good": [3 points a good answer covers]}}] (5-7 areas, last is Wrap-up), "gaps": [str]}}""", fb, company_id, max_tokens=2500)


def isha_analyze(question, area, good_points, sentences, new_sentence, resume_text, remaining_areas, n_options=4, company_id=None):
    """Called after every candidate sentence. Returns tags, live score, rubric coverage and ranked next-question options."""
    def fb():
        s = new_sentence.lower()
        tags = []
        if any(w in s for w in ["i led", "i owned", "i built", "i designed", "i set up", "my team"]):
            tags.append({"type": "claim", "label": "Personal claim to verify"})
        if any(w in s for w in ["because", "so that", "trade-off", "instead of", "measured", "percent", "%"]):
            tags.append({"type": "good", "label": "Explains reasoning or gives evidence"})
        if any(w in s for w in ["i think", "maybe", "trial and error", "not sure", "kind of", "basically", "somehow"]):
            tags.append({"type": "vague", "label": "Vague or unsure"})
        if any(w in s for w in ["another team", "someone else", "wasn't me", "i didn't"]):
            tags.append({"type": "flag", "label": "May contradict the resume"})
        if not tags:
            tags.append({"type": "good" if len(s.split()) > 12 else "vague",
                         "label": "Relevant detail" if len(s.split()) > 12 else "Short answer"})
        allw = " ".join(sentences + [new_sentence]).lower()
        cov = []
        for gp in good_points:
            kw = [w for w in _words(gp) if len(w) > 4]
            hits = sum(1 for w in kw if w in allw)
            cov.append("full" if kw and hits >= max(1, len(kw) // 2) else ("partial" if hits else "none"))
        good = sum(1 for t in tags if t["type"] == "good")
        bad = sum(1 for t in tags if t["type"] in ("vague", "flag"))
        n = len(sentences) + 1
        score = max(1.0, min(5.0, 2.4 + 0.35 * n + 0.3 * good - 0.4 * bad + 0.3 * cov.count("full")))
        opts = []
        if any(t["type"] == "flag" for t in tags):
            opts.append({"type": "Clarify", "q": "Earlier you mentioned that differently. What exactly was your own part in it?", "why": "Possible contradiction", "w": 5})
        if any(t["type"] == "vague" for t in tags):
            opts.append({"type": "Probe", "q": "Can you give me a concrete example, with numbers if possible?", "why": "Answer was vague", "w": 4})
        if any(t["type"] == "good" for t in tags):
            opts.append({"type": "Go deeper", "q": f"What trade-offs did you consider there, and what would you change now?", "why": "Strong answer: test depth", "w": 3})
        for ra in remaining_areas[:2]:
            opts.append({"type": "Move on", "q": ra.get("q"), "why": f"{ra.get('area')} not covered yet", "w": 2, "area": ra.get("area")})
        opts.sort(key=lambda o: -o["w"])
        return {"tags": tags, "score": round(score, 1), "coverage": cov, "options": opts[:n_options]}
    data = ask_json("analyse one sentence of a live interview answer and suggest next questions", f"""You are Isha, a live copilot for a possibly non-expert interviewer.
Current question ({area}): {question}
A good answer covers: {json.dumps(good_points)}
Candidate's answer so far: {json.dumps(sentences)}
NEW sentence just spoken: "{new_sentence}"
Resume excerpt: \"\"\"{(resume_text or '')[:1500]}\"\"\"
Areas not yet covered: {json.dumps([{'area': a.get('area'), 'q': a.get('q')} for a in remaining_areas])}
Return JSON: {{"tags": [{{"type": "good|claim|vague|flag", "label": short plain reason}}] (tags for the NEW sentence only),
"score": 1-5 running score for the whole answer so far,
"coverage": ["full|partial|none" for each good-answer point, same order],
"options": [{{"type": "Go deeper|Clarify|Probe|Challenge|Move on|Wrap up", "q": a speakable question, "why": short reason, "w": 1-5 priority, "area": optional}}] (max {n_options}, best first)}}""",
                    fb, company_id, max_tokens=900)
    if not isinstance(data, dict) or "tags" not in data:
        return fb()
    return data


def isha_scorecard(areas_log, company_id=None):
    """areas_log: [{area, q, sentences:[...], score}] -> draft competency scores with quotes."""
    def fb():
        rows = []
        for a in areas_log:
            if a.get("area") == "Wrap-up" or not a.get("sentences"):
                continue
            best = max(a["sentences"], key=len)
            rows.append({"name": a["area"], "score": int(round(a.get("score") or 3)), "quote": best})
        return {"competencies": rows}
    return ask_json("draft an interview scorecard", f"""Draft the interviewer's scorecard from this live interview.
Per area: question asked, candidate sentences and the live score.
{json.dumps(areas_log)[:10000]}
Return JSON: {{"competencies": [{{"name": area, "score": 1-5 integer, "quote": the single strongest exact quote}}]}}""",
                    fb, company_id, max_tokens=1500)


# ---------------------------------------------------------------- Disha: candidates

def candidate_feedback(report_sections, company_id=None):
    def fb():
        return {"strengths": report_sections.get("strengths", [])[:3],
                "gaps": report_sections.get("gaps", [])[:3],
                "next_steps": [f"Practise {g} with a mock interview" for g in report_sections.get("gaps", [])[:2]] or ["Keep practising with mock interviews"]}
    return ask_json("write kind, specific candidate feedback", f"""Turn this internal report into feedback for the candidate.
Be kind, specific and useful; no scores, no internal notes, no comparison with others.
{json.dumps({k: report_sections.get(k) for k in ('summary', 'strengths', 'gaps', 'competencies')})[:6000]}
Return JSON: {{"strengths": [3 short points], "gaps": [up to 3 short points], "next_steps": [2-3 concrete actions]}}""",
                    fb, company_id, max_tokens=800)


def learning_path(goal, skill, current_level=1, company_id=None):
    def fb():
        topics = [f"{skill} fundamentals", f"Core patterns in {skill}", f"{skill} in real projects",
                  f"Common mistakes with {skill}", f"Explaining {skill} in interviews", f"{skill} skill check"]
        return {"title": f"{skill} for {goal}", "topics": [
            {"title": t, "summary": f"Learn {t.lower()} with short examples and a practice question.",
             "practice": [f"Explain {t.lower()} in two sentences.", f"Give one example of {t.lower()} from your work."], "done": False}
            for t in topics]}
    return ask_json("design a learning path", f"""Design a short learning path for someone aiming to become a {goal}.
Skill: {skill}, current level {current_level} of 5. 5-7 topics in order, each with a 1-2 sentence summary and 2 practice prompts.
Return JSON: {{"title": str, "topics": [{{"title": str, "summary": str, "practice": [str, str], "done": false}}]}}""",
                    fb, None, max_tokens=1500)


def disha_path(goal, skills, company_id=None):
    def fb():
        return {"steps": [
            {"t": "Find your level", "d": "Take short skill checks to see where you stand, L1 to L5."},
            {"t": "Close the gaps", "d": f"Follow a learning path and practise mock interviews for {goal}."},
            {"t": "Prove it and apply", "d": "Earn verified badges and apply to jobs that match them."}]}
    return ask_json("give a candidate a 3-step path", f"""A candidate wants to become: {goal}. Their skills: {json.dumps(skills)}.
Return JSON: {{"steps": [{{"t": short title, "d": one sentence}}] (exactly 3)}}""", fb, company_id, max_tokens=500)


# ---------------------------------------------------------------- Ask Hira

def nl_filter(text, fields, company_id=None):
    def fb():
        t = text.lower()
        chips = []
        m = re.search(r"(above|over|>=?|more than)\s*(\d+)", t)
        if m:
            chips.append({"field": "match_score", "op": "gte", "value": int(m.group(2)), "label": f"Match ≥ {m.group(2)}%"})
        for stage in ["applied", "shortlisted", "in_round", "awaiting_review", "offer", "rejected", "hired", "on_hold"]:
            if stage.replace("_", " ") in t:
                chips.append({"field": "stage", "op": "eq", "value": stage, "label": f"Stage is {stage.replace('_', ' ')}"})
        if "strong" in t and not m:
            chips.append({"field": "match_score", "op": "gte", "value": 70, "label": "Match ≥ 70%"})
        for s in extract_skills(text):
            chips.append({"field": "q", "op": "contains", "value": s, "label": f"Mentions {s}"})
        return {"chips": chips}
    return ask_json("turn a plain-language filter into structured filters", f"""Convert this request into table filters.
Available fields: {json.dumps(fields)}
Request: "{text}"
Return JSON: {{"chips": [{{"field": str, "op": "eq|gte|lte|contains", "value": any, "label": short human label}}]}}""",
                    fb, company_id, max_tokens=400)


def nl_report(text, sources, company_id=None):
    def fb():
        t = text.lower()
        source = "applications"
        group = "stage"
        if "interviewer" in t:
            source, group = "interviews", "interviewer"
        elif "job" in t:
            group = "job"
        elif "month" in t or "week" in t:
            group = "month"
        measure = "avg_score" if "score" in t else ("time_to_decision" if "time" in t else "count")
        return {"name": text[:60], "source": source, "measure": measure, "group_by": group, "chart": "bar", "filters": []}
    return ask_json("turn a plain-language report request into a report spec", f"""Build a report spec.
Sources and their group_by options and measures: {json.dumps(sources)}
Request: "{text}"
Return JSON: {{"name": str, "source": str, "measure": str, "group_by": str, "chart": "bar|line|table|funnel", "filters": []}}""",
                    fb, company_id, max_tokens=400)
