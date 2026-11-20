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


_local = __import__("threading").local()


class offline:
    """`with ai.offline():` uses the built-in fallbacks only (V02.00.09), e.g. when a background report took too long."""
    def __enter__(self):
        _local.off = True

    def __exit__(self, *a):
        _local.off = False


def _client():
    if getattr(_local, "off", False):
        return None
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
    """A5 (V02.00.12): read the JSON in Claude's reply.
    The old reader took the text between the first pair of ``` fences, so a question whose code snippet had its own
    fences was cut in half ("Unterminated string"). Now: start at the first { or [ and decode exactly one JSON value,
    whatever comes before or after it. If the reply was cut off (it hit the length limit), keep every complete item
    that came through and close the brackets, instead of throwing all of it away."""
    text = (text or "").strip()
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if not starts:
        return json.loads(text)
    start = min(starts)
    try:
        return json.JSONDecoder().raw_decode(text, start)[0]
    except json.JSONDecodeError as first:
        out = _salvage(text[start:])
        if out is None:
            raise first
        log.warning("AI reply was incomplete; kept the complete items")
        return out


def _salvage(t):
    """Longest prefix of t that ends after a complete object or array, with the open brackets closed."""
    stack, safe, in_str, esc = [], [], False, False
    for i, ch in enumerate(t):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if not stack:
                break
            stack.pop()
            if stack:
                safe.append((i, "".join("}" if c == "{" else "]" for c in reversed(stack))))
    for i, closers in reversed(safe):
        try:
            return json.loads(t[:i + 1] + closers)
        except json.JSONDecodeError:
            continue
    return None


# V02.00.08: every AI call records whether it worked, so a saved key that fails (wrong model, quota, network) shows up
# on the platform overview, in /api/health and in Isha's room instead of silently falling back to templates.
_status = {"ok_at": None, "error": None, "error_at": None, "fallbacks": 0, "model": None}


def status():
    """{"configured", "working", "error", "error_at", "ok_at", "fallbacks", "model"} for the health check and the overview."""
    import time
    st = dict(_status)
    try:
        saved = platform_secret("ai_status", None)
        latest = lambda d: max(d.get("ok_at") or 0, d.get("error_at") or 0)  # noqa: E731
        if isinstance(saved, dict) and latest(saved) > latest(st):  # another worker saw something newer
            st.update({k: saved.get(k) for k in ("ok_at", "error", "error_at", "model")})
    except Exception:
        pass
    st["configured"] = configured()
    st["working"] = bool(st["configured"] and (st["ok_at"] and (not st["error_at"] or st["ok_at"] > st["error_at"])))
    st["recent_error"] = bool(st["error_at"] and time.time() - st["error_at"] < 3600 and not st["working"])
    return st


def _record(ok_, model=None, error=None):
    """Keeps the in-process state and saves a change of state (working <-> failing) for the other workers."""
    import time
    was_ok = _status["ok_at"] and (not _status["error_at"] or _status["ok_at"] > _status["error_at"])
    now = time.time()
    if ok_:
        _status.update(ok_at=now, model=model)
    else:
        _status.update(error=error, error_at=now, model=model)
        _status["fallbacks"] += 1
    changed = bool(was_ok) != bool(ok_) or (not ok_ and (now - (_status.get("_saved") or 0) > 300)) or (ok_ and not _status.get("_saved"))
    if changed:
        try:
            from extensions import db
            from services.settings import set_secret
            set_secret("ai_status", {k: _status[k] for k in ("ok_at", "error", "error_at", "model")})
            db.session.commit()
            _status["_saved"] = now
        except Exception:
            try:
                from extensions import db
                db.session.rollback()
            except Exception:
                pass


def _describe(e, model):
    name = type(e).__name__
    return {"AuthenticationError": "Anthropic rejected the API key",
            "PermissionDeniedError": "the API key isn't allowed to use the API",
            "NotFoundError": f"the model {model} isn't available to this key",
            "RateLimitError": "rate limit or credit limit reached",
            "APIConnectionError": "the server can't reach Anthropic",
            "APITimeoutError": "Anthropic took too long to answer",
            "JSONDecodeError": "Claude's answer wasn't valid JSON"}.get(name, f"{name}: {str(e)[:120]}")


def ask_json(task, prompt, fallback, company_id=None, max_tokens=2000, system_extra="", timeout=None):
    """Call Anthropic and parse JSON. Falls back on any failure, and records the failure (see status()).
    timeout (seconds, V02.00.09): for calls a person is waiting on live; one try, then the fallback."""
    client = _client()
    if client is None:
        _status["fallbacks"] += 1
        return fallback() if callable(fallback) else fallback
    banned, _, _ = resolve("ai.banned_topics", company_id=company_id)
    system = SYSTEM_BASE + f" Task: {task}. Banned topics: {', '.join(banned or [])}. " + system_extra
    model = _model(company_id)
    default = current_app.config.get("ANTHROPIC_MODEL")
    last = None
    for attempt in range(3):
        try:
            kw = {"timeout": timeout} if timeout else {}
            msg = client.messages.create(model=model, max_tokens=max_tokens, system=system,
                                         messages=[{"role": "user", "content": prompt}], **kw)
            text = "".join(getattr(b, "text", "") for b in msg.content)
            if getattr(msg, "stop_reason", None) == "max_tokens":  # A5: say why a reply was cut off
                log.warning("AI task %s hit its length limit (%s tokens, %s characters)", task, max_tokens, len(text))
            out = _parse(text)
            _record(True, model)
            return out
        except Exception as e:  # network, quota, malformed JSON
            last = e
            log.warning("AI task %s failed (attempt %s, model %s): %s", task, attempt + 1, model, e)
            # a model saved in an older version may no longer exist: use the platform default instead of giving up
            if type(e).__name__ in ("NotFoundError", "BadRequestError") and default and model != default:
                model = default
                continue
            if type(e).__name__ in ("AuthenticationError", "PermissionDeniedError"):
                break
            if attempt >= 1 or timeout:
                break
    _record(False, model, _describe(last, model) if last else "unknown error")
    return fallback() if callable(fallback) else fallback


# ---------------------------------------------------------------- helpers for fallbacks

KNOWN_SKILLS = ["Java", "Spring Boot", "SQL", "Python", "Django", "Flask", "React", "JavaScript", "TypeScript",
                "Node.js", "Kubernetes", "Docker", "AWS", "Azure", "Kafka", "Microservices", "System design",
                "Data analysis", "Excel", "Power BI", "Tableau", "Statistics", "Machine learning", "Communication",
                "Sales", "Negotiation", "CRM", "Customer success", "Go", "C#", ".NET", "Angular", "DevOps", "Linux",
                "Testing", "Selenium", "Product management", "Figma", "PostgreSQL", "MySQL", "MongoDB", "Redis"]


def extract_skills(text):
    """V02.00.10: whole words only ("JavaScript" no longer also counts as "Java"), with synonyms and capitals fixed."""
    from services.skills import extract
    return extract(text)


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


def generate_mcq(skills, level=3, n=5, company_id=None, avoid=None):
    """n new questions. `avoid` lists question texts already in the bank, so the AI doesn't write them again.
    Without AI the fallback rotates through different question shapes, so it doesn't write one question n times."""
    shapes = MCQ_SHAPES

    def fb():
        out = []
        for i in range(n):
            s = skills[i % len(skills)] if skills else "General"
            text, opts, ans = shapes[(i // max(1, len(skills or [1]))) % len(shapes)]
            opts = list(opts)
            k = (i + 2) % len(opts)  # A2 (V02.00.12): the right option doesn't sit at B every time
            opts.insert(k, opts.pop(ans))
            out.append({"skill": s, "level": level, "text": text.format(s=s, l=level), "options": [o.format(s=s) for o in opts],
                        "answer": k, "explanation": "The correct option is the practical, evidence-based approach.",
                        "fallback": True})  # CD-005 (V02.00.08): filler, never saved to a question bank
        return out
    avoid_txt = ""
    if avoid:
        avoid_txt = "\nDo NOT repeat or rephrase any of these existing questions:\n" + "\n".join("- " + str(a)[:160] for a in avoid[:60])
    data = ask_json("write multiple-choice questions", f"""Write {n} multiple-choice questions to screen candidates.
Skills: {', '.join(skills)}. Difficulty level {level} of 5. Practical, unambiguous, one correct answer, 4 options each.
Every question must be different from the others in topic and wording.
Mix question styles: concept, read-the-code / output, debugging, scenario or design choice, best practice. Don't start every question the same way.
Spread the correct answer across positions 0-3 roughly evenly; never put most answers in the same position.
Wrong options must be plausible to someone who half-knows the topic (no joke options), and similar in length to the right one.
Include a short code snippet in "code" only when it helps (else empty string).{avoid_txt}
Return JSON list: [{{"skill": str, "level": int, "text": str, "code": str, "options": [str,str,str,str], "answer": 0-3, "explanation": str}}]""",
                    fb, company_id, max_tokens=3000)
    return data if isinstance(data, list) else fb()


MCQ_SHAPES = [
        ("Which statement about {s} is most accurate for a level {l} practitioner?",
         ["{s} is best learned only from documentation", "Applying {s} well means understanding its trade-offs in context",
          "{s} has no common failure modes", "{s} should never be tested"], 1),
        ("A teammate's {s} work passes review but fails in production. What should you check first?",
         ["Rewrite it from scratch", "The difference between the test setup and production", "Blame the reviewer", "Nothing, production is always wrong"], 1),
        ("What is the main benefit of writing automated tests for {s} code?",
         ["They make the code run faster", "They catch regressions when the code changes", "They replace code review", "They are required by law"], 1),
        ("You must learn a new part of {s} quickly for a project. What works best?",
         ["Read everything before trying anything", "Build a small working example, then read deeper where it breaks", "Wait for formal training", "Copy code without reading it"], 1),
        ("When is it right to choose a simpler {s} solution over a more powerful one?",
         ["Never", "When it meets the need and is easier to maintain", "Only for prototypes", "When the powerful one is newer"], 1),
        ("How should a {s} decision with real trade-offs be recorded for the team?",
         ["It shouldn't be recorded", "A short note of the options, the choice and why", "Only in a private chat", "In the code comments of one file"], 1),
    ]


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
        """Different questions only: the job's drafted ones, then skill templates, then general ones."""
        qs, seen = [], set()

        def add(q, topic):
            if q and q.strip().lower() not in seen and len(qs) < n:
                seen.add(q.strip().lower())
                qs.append({"q": q, "topic": topic})
        for k, q in enumerate((job.plan or {}).get("questions") or []):
            add(q, skills[k % len(skills)])
        templates = ["Tell me about a project where you used {s}. What decisions did you make and why?",
                     "What is a common mistake people make with {s}, and how do you avoid it?",
                     "Describe a time {s} work went wrong in production. How did you find and fix it?",
                     "How would you explain {s} trade-offs to a non-technical teammate?"] + [t[0] for t in AREA_TEMPLATES]
        for t in templates:
            for s_ in skills:
                add(t.format(s=s_), s_)
        for area, q in GENERAL_QUESTIONS:
            add(q, area)
        return {"questions": qs}
    practice = not getattr(job, "company_id", None)
    rule = (f"This is a PRACTICE interview for the role {job.title}. Every question must be about this role and the skills "
            f"listed; never ask about other roles or technologies, even if the resume mentions them.\n") if practice else ""
    data = ask_json("plan an AI interview", f"""{rule}Plan a structured spoken interview for {job.title} ({job.level}).
Skills to cover: {json.dumps(job.skills)}. Difficulty: {difficulty}.
Candidate resume ({'context only: questions stay on the role and skills above' if practice else 'to tailor questions and test claims'}):
\"\"\"{(resume_text or '')[:4000]}\"\"\"
Return JSON: {{"questions": [{{"q": str (one question, speakable, under 35 words), "topic": skill name}}]}} with exactly {n} questions.""",
                    fb, company_id, max_tokens=3500)
    if not isinstance(data, dict) or not data.get("questions"):
        return fb()
    # exactly n main questions: trim extras, fill missing ones from the fallback (different wording, no repeats)
    qs = [q for q in data["questions"] if isinstance(q, dict) and q.get("q")]
    seen = {q["q"].strip().lower() for q in qs}
    for extra in fb()["questions"]:
        if len(qs) >= n:
            break
        if extra["q"].strip().lower() not in seen:
            qs.append(extra)
            seen.add(extra["q"].strip().lower())
    return {**data, "questions": qs[:n]}


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
{{"ask": bool, "q": str (one short spoken question, or empty)}}""", fb, company_id, max_tokens=300, timeout=8)


def expected_points(question, topic=None):
    """R6 (V02.00.06): what a good answer to this question covers, when nobody wrote it down. Built from the kind of
    question, so it fits the question instead of being the same three points every time."""
    q = (question or "").lower()
    t = topic if topic and topic not in ("Not in the plan", "General", "Small talk") else None
    if any(w in q for w in ("debug", "bug", "error", "broke", "incident", "outage", "fail")):
        return [f"How they found the cause (logs, reproducing it, narrowing it down)", "The fix and why it works",
                "How they stopped it happening again (a test, a check, monitoring)"]
    if any(w in q for w in ("design", "architect", "scale", "system", "structure", "organise", "organize")):
        return ["The main parts and how data moves between them", "The trade-offs they considered and why they chose this",
                "How it handles growth, bad input and failure"]
    if any(w in q for w in ("difference", "compare", " vs ", "versus", "when would you use")):
        return ["A correct explanation of each", "When to use which, with the reason", "A real example from their work"]
    if any(w in q for w in ("how would you", "how do you", "what would you do", "how will you")):
        return ["A clear, step-by-step approach", f"The {t} tools or features they would use" if t else "The tools or methods they would use", "Risks, and how they'd check it worked"]
    if any(w in q for w in ("walk me through", "tell me about", "project", "time when", "time you", "example")):
        return [f"A specific {t} example: what it was and their own role" if t else "A specific example: what it was and their own role", "What they did and why (their decisions)",
                "The result, ideally measurable, and what they'd do differently"]
    if any(w in q for w in ("questions do you have", "anything else", "why do you want", "why this")):
        return ["Genuine interest in the role and team", "Thoughtful questions or reasons", "Clear, honest communication"]
    if any(w in q for w in ("your part", "your own", "yours", "you personally", "your role")):
        return ["What they did themselves, not the team", "A decision they made and why", "The result of their part"]
    return [f"A direct, correct answer about {t}" if t else "A direct answer to the question", "A real example from their own work", "The reasoning behind their choices"]


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
                            "good_answer": item.get("good") or expected_points(item["q"], item.get("topic")),
                            "covered": [n >= 20, n >= 40, n >= 60], "topic": item.get("topic"), "kind": item.get("kind")})
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
    out = ask_json("write an evidence-linked interview report", f"""Write the {round_name} report for {job.title}.
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
    # R6: every question shows what was asked, what a good answer covers, and the candidate's own words, even when the
    # AI left something out: the answer always comes from the transcript, never from the AI's retelling.
    by_q = {x["q"]: x for x in qa}
    fixed = []
    for i, q in enumerate(out.get("questions") or []):
        src = by_q.get(q.get("q")) or (qa[i] if i < len(qa) else {})
        pts = q.get("good_answer") if isinstance(q.get("good_answer"), list) and q.get("good_answer") else (src.get("good") or expected_points(q.get("q"), q.get("topic") or src.get("topic")))
        cov = q.get("covered") if isinstance(q.get("covered"), list) else []
        fixed.append({**q, "a": src.get("a", q.get("a", "")), "time": q.get("time") or src.get("at", ""), "good_answer": pts,
                      "covered": [bool(x) for x in (cov + [False] * len(pts))[:len(pts)]], "kind": src.get("kind")})
    if not fixed and qa:
        fixed = fb()["questions"]
    out["questions"] = fixed
    return out


# ---------------------------------------------------------------- Isha: live copilot

AREA_TEMPLATES = [
    ("Walk me through a piece of work where you used {s}. What would you do differently?", "Tell me about a time you used {s} at work.",
     ["A specific situation", "Their own decisions and why", "A measurable result"]),
    ("What is the hardest {s} problem you have solved? How did you know it was solved?", "What was a hard {s} problem you fixed?",
     ["A concrete problem", "How they diagnosed it", "How they checked the fix"]),
    ("If you joined us and found the way the team handles {s} was slowing work down, what would you look at first?", "How would you improve how a team handles {s}?",
     ["Asks questions before changing things", "Measures first", "A sensible first step"]),
    ("Tell me about a {s} decision you disagreed with. What did you do?", "Have you ever disagreed about {s} at work? What happened?",
     ["Respectful disagreement", "Evidence they used", "How it ended"]),
    ("How do you keep your {s} skills current? Give a recent example.", "How do you keep learning {s}?",
     ["A recent, specific example", "Applied what they learned", "Sensible sources"]),
]
GENERAL_QUESTIONS = [
    ("Teamwork", "Tell me about a time you helped a teammate who was stuck. What did you do?"),
    ("Ownership", "Describe something you owned from start to finish. What was the result?"),
    ("Mistakes", "Tell me about a mistake you made at work and what you changed afterwards."),
    ("Priorities", "When you have three urgent tasks and time for one, how do you decide?"),
    ("Feedback", "What is the most useful feedback you have received, and what did you do with it?"),
    ("Communication", "How do you explain a complex problem to someone outside your field?"),
    ("Deadlines", "Tell me about a deadline you were at risk of missing. What did you do?"),
    ("Quality", "How do you check your own work before you hand it over?"),
    ("Learning", "What is something new you learned in the last six months, and how?"),
    ("Conflict", "Describe a disagreement with a colleague. How was it resolved?"),
    ("Ambiguity", "Tell me about a task with unclear requirements. How did you get clarity?"),
    ("Impact", "What work are you most proud of, and why does it matter?"),
    ("Pressure", "Tell me about a stressful week at work. How did you handle it?"),
    ("Improvement", "What process at your last job did you make better?"),
    ("Customers", "Describe a time you changed your work because of a user or customer."),
    ("Estimation", "How do you estimate how long a task will take? Give an example."),
    ("Mentoring", "Have you taught someone a skill? How did you go about it?"),
    ("Decisions", "Tell me about a decision you made with incomplete information."),
    ("Motivation", "What kind of work gives you the most energy?"),
    ("Role fit", "Why does this role interest you, and what would you want to learn here?"),
    ("Growth", "Where do you want your skills to be in two years?"),
    ("Collaboration", "How do you work with people in other teams or time zones?"),
    ("Risk", "Tell me about a time you spotted a risk early. What did you do?"),
    ("Documentation", "How do you make sure others can pick up your work?"),
    ("Change", "Describe a big change at work and how you adapted."),
]
WRAP_UP = {"area": "Wrap-up", "why": "Always", "q": "What questions do you have for us about the team or the role?",
           "simple": "Is there anything you'd like to ask us?", "good": ["Thoughtful questions about the work"]}


def fill_plan(areas, n, skills, gaps=(), own=(), extra=(), avoid=()):
    """BUG-001: the plan has exactly `n` questions. The recruiter's own questions come first, in their order; then the
    AI's (or the fallback's) areas; then more from the job's skills until the count is reached. Wrap-up stays last.
    Area names are unique, because the room tracks progress by area."""
    out, names = [], set()

    def add(a):
        name = (str(a.get("area") or "Question").strip() or "Question")[:80]
        base, k = name, 2
        while name.lower() in names:
            name, k = f"{base} ({k})", k + 1
        names.add(name.lower())
        out.append({**a, "area": name})
    for i, q in enumerate(own or []):
        add({"area": f"Your question {i + 1}", "why": "Added for this round", "q": q, "simple": q, "good": [], "own": True})
    wrap = None
    seen_q = {str(q).strip().lower() for q in (own or [])} | {str(q).strip().lower() for q in (avoid or [])}
    for a in list(areas or []) + list(extra or []):
        if not isinstance(a, dict) or not a.get("q"):
            continue
        if str(a.get("area", "")).lower() == "wrap-up":
            wrap = a
            continue
        if a["q"].strip().lower() in seen_q:
            continue
        if len(out) >= n - (1 if n >= 3 else 0):
            break
        seen_q.add(a["q"].strip().lower())
        add(a)
    room = n - (1 if n >= 3 else 0)  # keep a slot for Wrap-up when the plan has 3 or more questions
    skills = list(skills or []) or ["the role"]
    i = 0
    while len(out) < room and i < 200:
        s_ = skills[i % len(skills)]
        # F2F-003 (V02.00.08): each skill gets a different kind of question, so the plan doesn't read like one template
        q, simple, good = AREA_TEMPLATES[(i % len(skills) + i // len(skills)) % len(AREA_TEMPLATES)]
        q = q.format(s=s_)
        if q.lower() not in seen_q:
            seen_q.add(q.lower())
            add({"area": s_, "why": "JD must-have" if s_ in gaps else "From the JD", "q": q, "simple": simple.format(s=s_), "good": good})
        i += 1
        if i >= len(skills) * len(AREA_TEMPLATES):
            break
    for area, q in GENERAL_QUESTIONS:
        if len(out) >= room:
            break
        if q.lower() not in seen_q:
            seen_q.add(q.lower())
            add({"area": area, "why": "General", "q": q, "simple": q, "good": ["A specific example", "What they did themselves", "The result"]})
    out = out[:room] if len(out) > room else out
    if n >= 3:
        add(wrap or dict(WRAP_UP))
    return out[:n]


def _jd_points(description, limit=6):
    """Duties from the job description: bullet lines or sentences that describe work ("Design…", "Own…")."""
    out = []
    for line in re.split(r"\n+|•|(?<=[.;])\s+", description or ""):
        t = line.strip(" -*.;:\t")
        if 25 <= len(t) <= 160 and not t.lower().startswith(("we are", "about", "benefits", "salary", "location", "apply", "you will be", "requirements")):
            out.append(t[0].lower() + t[1:] if t[:1].isupper() and not t[:2].isupper() else t)
        if len(out) >= limit:
            break
    return out


def _resume_points(resume_text, limit=4):
    """Projects or achievements from the resume: lines with an action verb and something concrete."""
    verbs = ("built", "led", "designed", "developed", "migrated", "launched", "implemented", "reduced", "improved", "owned",
             "created", "automated", "scaled", "managed", "delivered")
    out = []
    for line in re.split(r"[\n•]+|(?<=\.)\s+", resume_text or ""):
        t = line.strip(" -*.;")
        # B1 (V02.00.12): education and certificates are not work to verify in a job interview
        if _EDU.search(t):
            continue
        if 30 <= len(t) <= 180 and any(v in t.lower() for v in verbs):
            out.append(t)
        if len(out) >= limit:
            break
    return out


_EDU = re.compile(r"\b(university|college|school|institute|b\.?\s?tech|m\.?\s?tech|b\.?e\b|bachelor|master|degree|diploma|"
                  r"cgpa|gpa|graduat|semester|coursework|certificat|class (?:x|xii|10|12))", re.I)


def plan_extras(job, resume_text, competencies=()):
    """Fallback plan questions written from this job's duties and this candidate's resume (V02.00.08, F2F-003), so
    the plan is specific even without Claude."""
    extra = []
    for i, p in enumerate(_resume_points(resume_text)):
        short = p if len(p) < 90 else p[:87].rsplit(" ", 1)[0] + "…"
        q = [f"Your resume says: \"{short}\". Walk me through what you did yourself and how you measured the result.",
             f"Tell me about this from your resume: \"{short}\". What was the hardest part, and what would you do differently?"][i % 2]
        extra.append({"area": f"Resume: {short[:40]}", "why": "From the resume: verify the claim", "q": q,
                      "simple": "Tell me about this project from your resume.", "good": ["Their own part, not the team's", "A concrete obstacle", "A measurable result"]})
    for i, d in enumerate(_jd_points(job.description if job else "")):
        q = [f"This role involves {d}. Tell me about a time you did something similar. What was your approach?",
             f"Imagine your first month here, and you need to {d}. How would you go about it?"][i % 2]
        extra.append({"area": f"Role: {d[:40]}", "why": "A duty from the job description", "q": q,
                      "simple": "Have you done work like this before? How?", "good": ["A relevant example", "A clear approach", "How they'd check it worked"]})
    # interleave resume and role questions
    res_q = [e for e in extra if e["area"].startswith("Resume")]
    role_q = [e for e in extra if e["area"].startswith("Role")]
    mixed = []
    for i in range(max(len(res_q), len(role_q))):
        mixed += ([res_q[i]] if i < len(res_q) else []) + ([role_q[i]] if i < len(role_q) else [])
    return mixed[:4]


def isha_brief(job, resume_text, prior, company_id=None, n=7, own=(), competencies=(), avoid=()):
    """The live interview plan. Specific to this job's duties and this candidate's resume, never repeating questions
    from earlier rounds (`avoid`), and each question linked to one of the job's competencies."""
    skills = [s["name"] if isinstance(s, dict) else s for s in (job.skills or [])]
    gaps = []
    for r in prior:
        gaps += (r.get("handoff") or []) + (r.get("gaps") or [])
    need = max(0, n - len(own or []))

    def fb():
        return {"areas": [], "gaps": gaps[:4]}
    data = {"areas": [], "gaps": gaps[:4]}
    if need > 1:
        data = ask_json("prepare a live interview plan for a non-expert interviewer", f"""Prepare Isha's brief for a live interview for {job.title} ({job.level or 'any level'}).
The interviewer may not be a domain expert. Skills: {json.dumps(job.skills)}
Competencies the scorecard uses: {json.dumps(list(competencies or []))}
Job description: \"\"\"{(job.description or '')[:2500]}\"\"\"
Gaps and handoffs from earlier rounds: {json.dumps(gaps[:8])}
Questions already asked in earlier rounds or by the interviewer, don't repeat or rephrase them: {json.dumps((list(own or []) + list(avoid or []))[:40])}
Resume:
\"\"\"{(resume_text or '')[:3000]}\"\"\"
Every question must test something THIS JOB needs: one of the skills above, a duty in the job description, or a gap
from earlier rounds. Use the resume to make a question personal (ask about their own work with a job skill), but never
ask about resume items unrelated to this job (education, hobbies, other fields). At least two in three questions must
name a job skill or duty. Fit the question to the job's field: for non-software jobs, don't ask about code.
Vary the kind of question (a past example, a scenario, a design or trade-off, a claim to verify, a failure). No two
questions may share an opening phrase. Avoid generic questions like "Tell me about yourself".
Return JSON: {{"areas": [{{"area": short topic, "competency": one of the competencies above (or null), "why": short reason,
"q": the question, "simple": the same question in plain words, "good": [3 points a good answer covers]}}]
(exactly {need} areas, all different, last is Wrap-up), "gaps": [str]}}""", fb, company_id, max_tokens=3500)
        if not isinstance(data, dict):
            data = fb()
    extra = [] if data.get("areas") else plan_extras(job, resume_text, competencies)
    areas = fill_plan(data.get("areas"), n, skills, gaps, own, extra=extra, avoid=avoid)
    from services.scorecard import link_plan
    return {"areas": link_plan(areas, list(competencies or [])), "gaps": (data.get("gaps") or gaps)[:4],
            "ai": bool(data.get("areas")) or need <= 1}


FOLLOW_UPS = {  # F2F-003 (V02.00.08): several wordings per kind, used in turn and never repeated in one interview
    "Clarify": ["Earlier you mentioned that differently. What exactly was your own part in it?",
                "Just to be clear, which parts of that did you do yourself, and which did others do?",
                "How does that fit with what you said a moment ago?"],
    "Probe": ["Can you give me a concrete example, with numbers if possible?", "What did that look like day to day? Walk me through one specific case.",
              "How did you know it worked? What did you measure?", "What exactly did you do first, and why?"],
    "Go deeper": ["What trade-offs did you consider there, and what would you change now?", "What went wrong along the way, and how did you handle it?",
                  "If you had half the time, what would you have cut, and why?", "How would that approach hold up at ten times the scale?"],
}


def _topic(sentence):
    """A word or phrase from the candidate's sentence to build a follow-up around: a known skill, or a capitalised name."""
    low = sentence.lower()
    for k in KNOWN_SKILLS:
        if re.search(r"(?<![a-z])" + re.escape(k.lower()) + r"(?![a-z])", low):
            return k
    m = re.findall(r"(?<!^)(?<![.!?] )\b([A-Z][A-Za-z0-9+#.]{2,}(?: [A-Z][A-Za-z0-9+#.]{2,})?)", sentence)
    m = [x for x in m if x not in ("I", "The", "We", "My", "And", "But", "So", "Then")]
    return m[0] if m else None


def _norm_q(q):
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", str(q or "").lower()).split())


def _prepared_options(prepared, good_points, cov, seen, limit=3):
    """V02.00.13: follow-ups written while preparing, one per point of a good answer. Offered for the points the answer
    hasn't covered yet, so follow-ups stay specific when Claude is down."""
    out = []
    for f in prepared or []:
        try:
            k = int(f.get("if_missing", 0))
        except (TypeError, ValueError):
            k = 0
        q = str(f.get("q") or "").strip()
        if not q or _norm_q(q) in seen or (k < len(cov) and cov[k] == "full"):
            continue
        point = good_points[k] if k < len(good_points or []) else None
        out.append({"type": "Probe", "q": q, "why": f"Not covered yet: {point}" if point else "Prepared follow-up", "w": 4.5,
                    "source": "prepared"})
        if len(out) >= limit:
            break
    return out


def isha_analyze(question, area, good_points, sentences, new_sentence, resume_text, remaining_areas, n_options=4, company_id=None, shown=(), prepared=(), asked=()):
    """Called after every candidate sentence. Returns tags, live score, rubric coverage and ranked next-question options.
    `shown`: questions already suggested or asked in this interview; they are never suggested again."""
    seen = {_norm_q(q) for q in shown or []}

    def fresh(kind):
        for q in FOLLOW_UPS[kind]:
            if _norm_q(q) not in seen:
                return q
        return None

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
        topic = _topic(new_sentence)
        if topic:  # built from the candidate's own words, so it never reads like a template
            for q in (f"You mentioned {topic}. What exactly was your part in it, and what was the result?",
                      f"Tell me more about {topic}. What problem were you solving, and why that choice?",
                      f"What would you do differently with {topic} if you started again?"):
                if _norm_q(q) not in seen:
                    opts.append({"type": "Go deeper", "q": q, "why": f"Picks up on {topic}", "w": 4})
                    break
        for kind, why, w, when in (("Clarify", "Possible contradiction", 5, "flag"), ("Probe", "Answer was vague", 4, "vague"),
                                   ("Go deeper", "Strong answer: test depth", 3, "good")):
            if any(t["type"] == when for t in tags):
                q = fresh(kind)
                if q:
                    opts.append({"type": kind, "q": q, "why": why, "w": w})
        for o in opts:
            o.setdefault("source", "builtin")
        asked_n = {_norm_q(q) for q in asked or []}
        opts = _prepared_options(prepared, good_points, cov, asked_n) + [o for o in opts if o["q"] not in {p.get("q") for p in prepared or []}]
        for ra in remaining_areas[:2]:
            opts.append({"type": "Move on", "q": ra.get("q"), "why": f"{ra.get('area')} not covered yet", "w": 2, "area": ra.get("area"), "source": "plan"})
        opts.sort(key=lambda o: -o["w"])
        return {"tags": tags, "score": round(score, 1), "coverage": cov, "options": opts[:n_options], "offline": True}
    data = ask_json("analyse one sentence of a live interview answer and suggest next questions", f"""You are Isha, a live copilot for a possibly non-expert interviewer.
Current question ({area}): {question}
A good answer covers: {json.dumps(good_points)}
Candidate's answer so far: {json.dumps(sentences)}
NEW sentence just spoken: "{new_sentence}"
Resume excerpt: \"\"\"{(resume_text or '')[:1500]}\"\"\"
Areas not yet covered: {json.dumps([{'area': a.get('area'), 'q': a.get('q')} for a in remaining_areas])}
Already suggested or asked, never suggest these again or a rewording of them: {json.dumps(list(shown or [])[-25:])}
Follow-ups must pick up on something specific the candidate just said, in their words. No generic follow-ups.
Return JSON: {{"tags": [{{"type": "good|claim|vague|flag", "label": short plain reason}}] (tags for the NEW sentence only),
"score": 1-5 running score for the whole answer so far,
"coverage": ["full|partial|none" for each good-answer point, same order],
"options": [{{"type": "Go deeper|Clarify|Probe|Challenge|Move on|Wrap up", "q": a speakable question, "why": short reason, "w": 1-5 priority, "area": optional}}] (max {n_options}, best first)}}""",
                    fb, company_id, max_tokens=900, timeout=10)
    if not isinstance(data, dict) or "tags" not in data:
        return fb()
    if data.get("offline"):  # the fallback answered (Claude isn't set up): its options are already labelled
        return data
    data["options"] = [dict(o, source="claude") for o in data.get("options") or [] if isinstance(o, dict) and o.get("q") and _norm_q(o["q"]) not in seen][:n_options]
    if len(data["options"]) < n_options:  # fewer than asked for: the prepared follow-ups fill the gap
        cov = data.get("coverage") if isinstance(data.get("coverage"), list) else []
        data["options"] += _prepared_options(prepared, good_points, cov, {_norm_q(q) for q in asked or []} | {_norm_q(o["q"]) for o in data["options"]},
                                             n_options - len(data["options"]))
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
    """V02.00.10 (LRN-03/04): topics carry minutes and specific prompts; the built-in outline is marked _basic so the
    screen can offer "Rebuild with Disha" when the AI was unavailable."""
    def fb():
        plan = [(f"What {skill} is and where it is used", f"The main ideas of {skill}, the words people use, and the problems it solves.", 10),
                (f"Core {skill} building blocks", f"The parts of {skill} you use every day, each with a small worked example.", 12),
                (f"{skill} in a real project", f"How {skill} fits into a real project: inputs, outputs and the usual steps.", 15),
                (f"Common {skill} mistakes and how to avoid them", f"The errors beginners make with {skill}, and the checks that catch them.", 10),
                (f"Talking about {skill} in interviews", f"How to explain your {skill} work clearly, with one example and its result.", 10),
                (f"Prove it with a {skill} skill check", f"A short proctored check. Score 70% to turn {skill} into a verified skill.", 12)]
        return {"_basic": True, "title": f"{skill} for {goal}", "topics": [
            {"title": t, "summary": sm, "minutes": m,
             "practice": [f"In two sentences, explain {t[0].lower() + t[1:]}.", f"Describe one example from a project or course where you used {skill}."],
             "done": False} for t, sm, m in plan]}
    out = ask_json("design a learning path", f"""Design a short learning path for someone aiming to become a {goal}.
Skill: {skill}, current level {current_level} of 5. 5-7 topics in order. Each topic: a specific title, a 1-2 sentence
summary of what is learned, the minutes it takes (5-20), and 2 practice prompts specific to that topic (prompts must
suit a new graduate too: say "from a project or course", never assume a job). The last topic is
"Prove it with a {skill} skill check". Write skill names and acronyms with correct capitals.
Return JSON: {{"title": str, "topics": [{{"title": str, "summary": str, "minutes": int, "practice": [str, str], "done": false}}]}}""",
                   fb, company_id, max_tokens=1600)
    return out if isinstance(out, dict) and out.get("topics") else fb()


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


_LEVEL_WORDS = ((1, ("simple", "easy", "basic", "beginner", "fresher", "entry", "junior")),
                (3, ("hard", "difficult", "advanced", "tough", "senior", "expert", "deep", "tricky")),
                (2, ("medium", "intermediate", "moderate", "mid")))
_ASK_FOR_QS = re.compile(r"(?i)\b(questions?|qs|ask (him|her|them)|give me|get me|suggest|more|another|follow[- ]?ups?)\b")
_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "a couple": 2, "a few": 3}


def _wanted(message, job):
    """What the interviewer asked for: a skill, a level (1-3) and how many."""
    low = message.lower()
    level = next((lv for lv, words in _LEVEL_WORDS if any(re.search(rf"\b{w}\b", low) for w in words)), None)
    m = re.search(r"\b(\d{1,2})\b", low)
    n = int(m.group(1)) if m else next((v for w, v in _NUM_WORDS.items() if re.search(rf"\b{w}\b", low)), None)
    skills = [str(x.get("name") if isinstance(x, dict) else x) for x in (job.skills or [])] if job else []
    skill = next((sk for sk in skills if sk and re.search(rf"(?<![a-z]){re.escape(sk.lower())}(?![a-z])", low)), None)
    if not skill:
        from models import Question
        from extensions import db
        known = [r[0] for r in db.session.query(Question.skill).distinct().limit(400).all() if r[0]]
        skill = next((sk for sk in sorted(known, key=len, reverse=True) if re.search(rf"(?<![a-z]){re.escape(sk.lower())}(?![a-z])", low)), None)
    return skill, level, max(1, min(n or 5, 10))


def bank_questions(skill, level=None, n=5, company_id=None):
    """V02.01.01: questions from the Question bank for Ask Isha, as spoken questions with the points of a good answer
    and a model answer. MCQs become open questions: the correct option and its explanation are the model answer."""
    from models import Question
    if not skill:
        return []
    q = Question.query.filter(Question.status == "approved", Question.skill.ilike(f"%{skill}%"),
                              (Question.company_id.is_(None)) | (Question.company_id == company_id))
    band = {1: (1, 2), 2: (3, 3), 3: (4, 5)}.get(level)  # bank levels are 1-5: easy 1-2, medium 3, hard 4-5
    if band:
        q = q.filter(Question.level >= band[0], Question.level <= band[1])
    rows = q.order_by(Question.level, Question.id).limit(60).all()
    if not rows and level:
        rows = Question.query.filter(Question.status == "approved", Question.skill.ilike(f"%{skill}%"),
                                     (Question.company_id.is_(None)) | (Question.company_id == company_id)).limit(60).all()
    random.Random(f"{skill}{level}{n}").shuffle(rows)
    out = []
    for r in rows[:n]:
        opts = r.options or []
        right = opts[r.answer] if isinstance(r.answer, int) and 0 <= r.answer < len(opts) else None
        good = [x for x in [right and f"Gets to: {right}", r.explanation and _key_sentences(r.explanation, 1)] if x]
        text = r.text.strip()
        if r.code:
            text += "\n" + r.code.strip()
        lv = r.level or 3
        out.append({"q": text[:600], "why": f"From the question bank · {r.skill} · level {lv}", "good": good[:3],
                    "model": " ".join(x for x in [right, r.explanation] if x)[:700] or None,
                    "level": "Easy" if lv <= 2 else "Medium" if lv == 3 else "Hard", "source": "bank"})
    return out


def isha_chat(message, job, resume_text, plan, areas_log, current, history=(), company_id=None, ctx=None):
    """Ask Isha, the interviewer's private in-app assistant during a live interview (V02.00.13; V02.01.01 makes it a
    full assistant for hiring work, so the interviewer never needs another AI tool). She can: suggest questions on any
    skill and level with the points of a good answer and a model answer (also from the Question bank, offline); check
    an answer; explain a concept; help with the plan and the time; and answer about the candidate's resume. Anything
    outside hiring she politely declines. Returns {"reply", "questions": [{"q", "why", "good", "model", "level",
    "source"}], "source": "claude" | "offline"}. The chat never reaches the report."""
    low = message.lower()
    ctx = ctx or {}
    asked = {a.get("area") for a in areas_log or []}
    remaining = [a for a in plan or [] if a.get("area") not in asked and not a.get("skipped") and a.get("area") != "Wrap-up"]
    skill, level, n = _wanted(message, job)
    wants_qs = bool(_ASK_FOR_QS.search(message)) and not re.search(r"(?i)\b(explain|what is|what are|meaning|define)\b", message)
    bank = bank_questions(skill, level, n, company_id) if (skill and wants_qs) else []

    def from_plan(sk):
        rows = []
        for a in plan or []:
            if sk and sk.lower() not in " ".join([a.get("competency") or "", a.get("section") or "", a.get("area") or ""]).lower():
                continue
            if a.get("q") and a.get("area") != "Wrap-up":
                rows.append({"q": a["q"], "why": f"From your plan · {a.get('area')}", "good": (a.get("good") or [])[:4],
                             "model": None, "level": a.get("type") or None, "source": "plan"})
        return rows

    def fb():
        qs, lines = [], []
        if wants_qs and skill:
            qs = bank + [x for x in from_plan(skill) if x["q"] not in {b["q"] for b in bank}]
            qs = qs[:n]
            lines.append(f"Here are {len(qs)} {skill} questions" + (f" at {['', 'an easy', 'a medium', 'a hard'][level]} level" if level else "")
                         + " from the question bank and your plan, with what a good answer covers." if qs
                         else f"I found no {skill} questions in the question bank.")
        if current:
            good = current.get("good") or []
            cov = current.get("coverage") or []
            missed = [g for i, g in enumerate(good) if i >= len(cov) or cov[i] != "full"]
            if any(w in low for w in ("cover", "answer", "point", "miss", "did they", "did she", "did he", "check")):
                lines.append(("Covered so far: " + "; ".join(g for i, g in enumerate(good) if i < len(cov) and cov[i] == "full") + ". ")
                             if any(c == "full" for c in cov) else "Nothing is fully covered yet. ")
                if missed:
                    lines.append("Still missing: " + "; ".join(missed) + ".")
            if not qs:
                area = next((a for a in plan or [] if a.get("area") == current.get("area")), {})
                for f in (area.get("followups") or [])[:3]:
                    qs.append({"q": f.get("q"), "why": "Prepared follow-up", "good": [], "model": None, "source": "plan"})
        if any(w in low for w in ("next", "remaining", "left", "skip", "time", "minutes")) and remaining:
            mins = ctx.get("minutes")
            used = round((ctx.get("elapsed") or 0) / 60)
            if mins:
                lines.append(f"{used} of {mins} minutes used.")
            lines.append("Still to ask: " + "; ".join(a.get("area") for a in remaining[:5]) + ".")
        if any(w in low for w in ("harder", "difficult", "deeper", "tough")) and not bank:
            qs.insert(0, {"q": "What would change in your answer at ten times the scale, with half the budget?", "why": "A harder version of any question",
                          "good": ["Names what breaks first", "Trades cost against reliability", "Measures before changing"], "model": None, "source": "built-in"})
        if not lines and not qs:
            lines.append("Claude isn't available right now. I can still find questions from the question bank (say a skill and a level, "
                         "like \"5 easy SQL questions\"), say what the current answer covered, and what's left in the plan.")
        elif not lines:
            lines.append("Claude isn't available right now. These are from your plan.")
        return {"reply": " ".join(lines).strip(), "questions": [q for q in qs if q.get("q")][:10], "source": "offline"}

    convo = [{"q": a.get("q"), "answer": " ".join(a.get("sentences") or [])[:700], "score": a.get("rating") or a.get("score")}
             for a in (areas_log or [])[-8:]]
    data = ask_json("answer the interviewer's question during a live interview", f"""You are Isha, the in-app AI assistant of Code2Hire, helping
the person running a live interview for {job.title}. You are their only AI tool, so answer fully, the way a strong
general assistant would, but only about hiring and this interview: technical questions on any skill (with a good-answer
checklist and a short model answer), checking whether an answer is correct, explaining a concept or term, follow-ups,
the candidate's resume and claims, the plan and the time left, fair and legal interviewing. Politely decline anything
unrelated to hiring or Code2Hire in one sentence. The candidate never sees this chat and it isn't added to the report.
Rules: questions must be speakable and specific; give the level; "good" lists 2-4 points a good answer covers; "model"
is a 2-4 sentence model answer. When asked for N questions, return N (max 10). Keep "reply" under 180 words; put the
questions in "questions", not in "reply". Never judge the candidate on age, gender, religion, family or anything not
about the job.
Job skills: {json.dumps(job.skills)}
Resume excerpt: \"\"\"{(resume_text or '')[:2000]}\"\"\"
Time: {json.dumps({'minutes_planned': ctx.get('minutes'), 'minutes_used': round((ctx.get('elapsed') or 0) / 60)})}
Plan still to ask: {json.dumps([{'area': a.get('area'), 'q': a.get('q')} for a in remaining][:10])}
Current question: {json.dumps({'q': (current or {}).get('q'), 'good': (current or {}).get('good'), 'coverage': (current or {}).get('coverage'), 'answer': (current or {}).get('sentences')})}
The interview so far: {json.dumps(convo)}
From the company's question bank (reuse when they fit): {json.dumps([{'q': b['q'], 'model': b['model']} for b in bank][:8])}
Earlier in this chat: {json.dumps([{'who': h.get('who'), 'text': h.get('text')} for h in history or []])}
The interviewer asks: "{message}"
Return JSON: {{"reply": your answer, "questions": [{{"q": question, "why": short reason, "level": "Easy|Medium|Hard", "good": [points], "model": model answer}}] (0-10)}}""",
                    fb, company_id, max_tokens=2200, timeout=30)
    if not isinstance(data, dict) or not str(data.get("reply") or "").strip():
        return fb()
    if data.get("source") == "offline" or data.get("offline"):
        return data
    qs = []
    for q in data.get("questions") or []:
        if isinstance(q, dict) and q.get("q"):
            qs.append({"q": str(q.get("q"))[:600], "why": str(q.get("why") or "")[:160], "level": str(q.get("level") or "")[:20] or None,
                       "good": [str(x)[:200] for x in (q.get("good") or []) if x][:5], "model": str(q.get("model") or "")[:900] or None,
                       "source": "claude"})
    return {"reply": str(data["reply"]).strip()[:2000], "questions": qs[:10], "source": "claude"}


def _key_sentences(text, n=2):
    """The longest, most specific sentences of an answer: the summary when Claude is unavailable."""
    sents = [x.strip() for x in re.split(r"(?<=[.!?])\s+", text or "") if len(x.split()) >= 5]
    best = sorted(sents, key=lambda x: (-sum(ch.isdigit() for ch in x), -len(x)))[:n]
    return " ".join(x for x in sents if x in best)[:400]


def answer_summaries(job, name, questions, competencies, company_id=None):
    """V02.01.01: a 2-3 line summary of each part of an interview (live topic or AI-interview question) and of the
    whole interview, for the report. questions: [{"q", "a", ...}]. Returns {"parts": [str|None per question],
    "overall": {"text", "strengths", "gaps", "claims", "source"}}. Without Claude: the answers' key sentences."""
    def fb():
        parts = [(_key_sentences(q.get("a") or "") or None) for q in questions]
        rated = [c for c in competencies or [] if isinstance(c.get("score"), (int, float))]
        strong = [c["name"] for c in rated if c["score"] >= 4]
        weak = [c["name"] for c in rated if c["score"] < 3]
        text = f"{name} answered {sum(1 for q in questions if (q.get('a') or '').strip())} of {len(questions)} questions."
        if strong:
            text += f" Strongest on {', '.join(strong)}."
        if weak:
            text += f" Weaker on {', '.join(weak)}."
        return {"parts": parts, "overall": {"text": text, "strengths": strong, "gaps": weak, "claims": [], "source": "key sentences"}}
    items = [{"n": i, "q": (q.get("q") or "")[:300], "a": (q.get("a") or "")[:1500]} for i, q in enumerate(questions)]
    if not any(x["a"].strip() for x in items):
        return fb()
    data = ask_json("summarise an interview for the hiring team", f"""Summarise this interview for {job.title if job else 'a role'} for the hiring team.
For each item, write a 2-3 line summary of what {name} actually said (facts, examples, numbers; no praise words, no
score). Leave it empty when there was no real answer. Then an overall summary of 3-4 lines, the main strengths, the
main gaps, and claims the team should check (from what the candidate said).
Items: {json.dumps(items)}
Ratings given by the interviewer: {json.dumps([{'name': c.get('name'), 'score': c.get('score'), 'skipped': c.get('skipped')} for c in competencies or []])}
Return JSON: {{"parts": [{{"n": item number, "summary": "..."}}], "overall": "...", "strengths": [..], "gaps": [..], "claims": [..]}}""",
                    lambda: None, company_id, max_tokens=2500, timeout=45)
    if not isinstance(data, dict) or not isinstance(data.get("parts"), list):
        return fb()
    by = {}
    for p in data["parts"]:
        if isinstance(p, dict) and isinstance(p.get("n"), int) and str(p.get("summary") or "").strip():
            by[p["n"]] = str(p["summary"]).strip()[:600]
    base = fb()
    return {"parts": [by.get(i) or base["parts"][i] for i in range(len(questions))],
            "overall": {"text": str(data.get("overall") or base["overall"]["text"])[:1200],
                        "strengths": [str(x)[:200] for x in data.get("strengths") or []][:6],
                        "gaps": [str(x)[:200] for x in data.get("gaps") or []][:6],
                        "claims": [str(x)[:200] for x in data.get("claims") or []][:6], "source": "claude"}}
