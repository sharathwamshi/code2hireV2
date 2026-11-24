"""V02.00.13: preparing a live (F2F) interview with Isha.

The interviewer picks the questions before the interview. Isha proposes them in SECTIONS, one per skill or topic
found in the job description and the resume, and each section mixes question TYPES (basics, hands-on, scenario,
real situation, own experience, design). How much of each type depends on the candidate's LEVEL (fresher, mid,
senior, lead). An Introduction ("tell me about yourself") opens every interview.

Every question says where it came from: Claude, built-in (Claude was unavailable), or the interviewer. Every
question carries "prepared" follow-ups, one per point of a good answer, so follow-ups stay specific when Claude is
down during the interview.

The prepared set lives in att.brief["prep"]; the chosen questions become att.brief["areas"], the plan the live room
already understands.
"""
import json
import re
from datetime import datetime

# ---------------------------------------------------------------------------------------------------- types & levels
TYPES = {  # key: (label, one-line meaning, default minutes)
    "intro": ("Introduction", "Tell me about yourself: sets the scene and gives claims to follow up", 3),
    "basics": ("Basics", "Applied fundamentals: explain it and say when it's the wrong choice, never a textbook definition", 3),
    "hands_on": ("Hands-on", "What does this print, read this log, say the query you'd write", 5),
    "scenario": ("Scenario", "A situation with a constraint: what do you do first, and why", 6),
    "real_world": ("Real situation", "Production or on-call pressure: what you check, in order", 6),
    "experience": ("Own experience", "Their own project from the resume: what they did, what broke, what they'd change", 6),
    "design": ("Design / trade-off", "Architecture and trade-offs at scale, for experienced candidates", 7),
    "behaviour": ("Working style", "Ownership, communication and pressure, from one real example", 4),
}
TYPE_ORDER = ["intro", "basics", "hands_on", "scenario", "real_world", "experience", "design", "behaviour"]

# share of the technical questions (intro and working style are fixed slots), in percent
LEVELS = {
    "fresher": {"label": "Fresher", "years": "0-2 years",
                "mix": {"basics": 35, "hands_on": 30, "scenario": 10, "real_world": 10, "experience": 15, "design": 0},
                "note": "Checks the basics and hands-on skill; experience questions use projects and internships."},
    "mid": {"label": "Mid-level", "years": "3-6 years",
            "mix": {"basics": 15, "hands_on": 25, "scenario": 15, "real_world": 15, "experience": 30, "design": 0},
            "note": "Less theory, more real situations and their own work."},
    "senior": {"label": "Senior", "years": "7+ years",
               "mix": {"basics": 5, "hands_on": 10, "scenario": 10, "real_world": 15, "experience": 30, "design": 30},
               "note": "Basics only as quick checks; depth comes from design, trade-offs and their own decisions."},
    "lead": {"label": "Lead / manager", "years": "leads a team",
             "mix": {"basics": 0, "hands_on": 0, "scenario": 10, "real_world": 15, "experience": 35, "design": 40},
             "note": "Design, people and process decisions, judged from their own examples."},
}

SECTION_KINDS = {  # key: (label, what it's for)
    "intro": ("Introduction", "Opens the interview"),
    "core": ("Core", "In the job description and on the resume: go deep and check the claims"),
    "gap": ("Gap", "Needed for the job but not on the resume: find out if they know it, start basic"),
    "claim": ("Resume claim", "On the resume but not needed for the job: one quick check that it's true"),
    "domain": ("Domain", "The job's own duties and business"),
    "behaviour": ("Working style", "How they work with others and under pressure"),
    "own": ("Your questions", "Questions you added"),
}

PARENT = {  # related skills share one section (Django goes under Python)
    "django": "python", "flask": "python", "fastapi": "python", "pandas": "python", "numpy": "python",
    "postgres": "sql", "postgresql": "sql", "mysql": "sql", "mariadb": "sql", "sqlite": "sql", "oracle": "sql",
    "react": "javascript", "reactjs": "javascript", "node": "javascript", "nodejs": "javascript", "node.js": "javascript",
    "typescript": "javascript", "next.js": "javascript", "vue": "javascript", "angular": "javascript",
    "spring": "java", "spring boot": "java", "hibernate": "java",
    "ec2": "aws", "s3": "aws", "lambda": "aws",
}

MAX_TECH_SECTIONS = 5
MAX_CLAIMS = 2


def _key(name):
    return re.sub(r"[^a-z0-9.+# ]", "", str(name or "").lower()).strip()


def _name(s):
    return (s.get("name") if isinstance(s, dict) else s) or ""


def guess_level(job, profile):
    """fresher / mid / senior / lead from the resume's years first, then the job's level."""
    years = getattr(profile, "experience_years", None) if profile else None
    jl = str(getattr(job, "level", "") or "").lower()
    if any(w in jl for w in ("lead", "manager", "head", "principal", "architect", "director")):
        return "lead" if (years or 8) >= 7 else "senior"
    if years is not None:
        return "fresher" if years < 3 else ("mid" if years < 7 else "senior")
    if any(w in jl for w in ("intern", "junior", "entry", "fresher", "graduate", "trainee")):
        return "fresher"
    if "senior" in jl or "sr" in jl.split():
        return "senior"
    return "mid"


def build_sections(job, profile, prior=(), own=()):
    """The sections for this job and candidate, before any questions are written."""
    jd = [s for s in (job.skills or []) if _name(s)]
    cv = [s for s in ((profile.skills if profile else None) or []) if _name(s)]
    cv_by = {}
    for s in cv:
        k = _key(_name(s))
        cv_by.setdefault(PARENT.get(k, k), []).append(s)
    proven = set()
    for r in prior or []:  # earlier rounds that went well for a skill: fewer basics there
        for h in (r.get("handoff") or []):
            if isinstance(h, str) and "strong" in h.lower():
                proven.add(_key(h.split(":")[0]))
    weak = [g for r in prior or [] for g in (r.get("gaps") or []) if isinstance(g, str)]

    sections, seen = [{"key": "intro", "kind": "intro", "name": "Introduction", "skill": None, "must": False}], set()
    for s in sorted(jd, key=lambda x: not (isinstance(x, dict) and x.get("must"))):
        k = _key(_name(s))
        p = PARENT.get(k, k)
        if p in seen:
            continue
        seen.add(p)
        mine = cv_by.get(p) or []
        years = max([float(x.get("years") or 0) for x in mine if isinstance(x, dict)] or [0]) or None
        verified = any(isinstance(x, dict) and x.get("verified") for x in mine) or p in proven
        probe = [g for g in weak if p in _key(g)]
        sections.append({"key": f"s{len(sections)}", "kind": "core" if mine else "gap", "name": _name(s), "skill": _name(s),
                         "must": bool(isinstance(s, dict) and s.get("must")), "years": years, "verified": verified,
                         "probe": probe[:2], "related": [_name(x) for x in mine if _key(_name(x)) != p][:3]})
        if len([x for x in sections if x["kind"] in ("core", "gap")]) >= MAX_TECH_SECTIONS:
            break
    claims = 0
    for p, mine in cv_by.items():
        if p in seen or claims >= MAX_CLAIMS:
            continue
        seen.add(p)
        claims += 1
        sections.append({"key": f"s{len(sections)}", "kind": "claim", "name": _name(mine[0]), "skill": _name(mine[0]), "must": False,
                         "verified": any(isinstance(x, dict) and x.get("verified") for x in mine)})
    if (job.description or "").strip():
        sections.append({"key": f"s{len(sections)}", "kind": "domain", "name": f"The role: {job.title}", "skill": None, "must": False})
    sections.append({"key": f"s{len(sections)}", "kind": "behaviour", "name": "Working style", "skill": None, "must": False})
    if own:
        sections.append({"key": "own", "kind": "own", "name": "Your questions", "skill": None, "must": False})
    return sections


def types_for(section, level):
    """Which question types to propose in a section, best first."""
    mix = LEVELS[level]["mix"]
    kind = section["kind"]
    if kind == "intro":
        return ["intro"]
    if kind == "behaviour":
        return ["behaviour"]
    if kind == "claim":
        return ["experience"]
    if kind == "domain":
        return ["scenario", "real_world"]
    ranked = [t for t in sorted(mix, key=lambda t: -mix[t]) if mix[t] > 0]
    if kind == "gap":  # unknown on the resume: start basic, no own-experience question
        ranked = ["basics", "hands_on"] + [t for t in ranked if t not in ("basics", "hands_on", "experience")]
    if section.get("verified"):  # proven already: skip the basics
        ranked = [t for t in ranked if t != "basics"]
    return ranked[:4]


# ---------------------------------------------------------------------------------------------------- built-in questions
def _domain_word(job):
    d = f"{job.title} {job.description or ''}".lower()
    for k, w in (("payment", "payments"), ("bank", "banking"), ("fintech", "payments"), ("health", "patient records"),
                 ("hospital", "patient records"), ("ecommerce", "online orders"), ("e-commerce", "online orders"),
                 ("retail", "store orders"), ("logistic", "deliveries"), ("insurance", "insurance claims"),
                 ("education", "student records"), ("travel", "bookings"), ("telecom", "subscriber billing")):
        if k in d:
            return w
    return "customer orders"


def _builtin(section, qtype, job, profile, i, quoted=None):
    """A built-in question when Claude is unavailable, written from this job and resume (never a bare definition)."""
    from services.ai import _jd_points, _resume_points
    s = section.get("skill") or section.get("name")
    dom = _domain_word(job)
    rpts = _resume_points(profile.resume_text if profile else "", limit=6)
    duties = _jd_points(job.description or "", limit=6)
    # V02.01.01: quote a resume line about THIS skill, and a real piece of work (not the skills list or a job title
    # line full of commas), so Python, SQL and AWS don't all quote the same line
    def _work_line(r):
        return r.count(",") < 3 and not re.match(r"(?i)\s*(skills?|tech|tools|stack)\b", r)
    lines = rpts + [x.strip() for x in re.split(r"(?<=[.!?])\s+|\n", profile.resume_text if profile and profile.resume_text else "")
                    if re.match(r"(?i)\s*(built|moved|migrated|led|designed|created|wrote|ran|owned|launched|cut|reduced|improved|automated|scaled|rewrote)\b", x.strip())]
    quoted = quoted if quoted is not None else set()
    work = [r for r in dict.fromkeys(lines) if _work_line(r) and r not in quoted]
    rline = next((r for r in work if s and re.search(rf"(?i){re.escape(s.lower())}", r)), None) or (work[0] if work else None)
    if qtype == "experience" and rline:
        quoted.add(rline)   # each resume line is quoted once across the plan
    if section.get("kind") == "domain":
        s = None   # "The role: …" is a section name, not a skill: the scenario is written from the job's duties
    duty = duties[i % len(duties)] if duties else f"work with {dom}"
    duty = re.sub(r"(?i)^\s*(you'll|you will|you would|you)\s+", "", duty).rstrip(".").strip()
    duty = duty[:1].lower() + duty[1:] if duty else duty
    n_rows = ["2 million", "40 million", "800,000", "15 million"][i % 4]
    duty_s = " ".join(duty.split()[:9]).rstrip(",.;:") if duty else duty
    Dom = dom[:1].upper() + dom[1:]
    # V02.01.05: one short sentence each, easy to say aloud; the twists are the follow-ups
    T = {
        "intro": ("Tell me about your current role and the work you're proudest of from the last two years.",
                  "Tell me about yourself and your best recent work.",
                  ["Current role and scope", "A recent project close to this job", "What they did themselves", "Why this role"],
                  ["Which of those projects is closest to this role?",
                   "What was your own part in it?",
                   "How did you measure the result?",
                   "What made you look for a new role now?"]),
        "basics": (f"How would you explain {s} to a new teammate?",
                   f"What is {s} for?",
                   [f"A correct, plain explanation of {s}", "A concrete example of using it", "A case where it's the wrong choice, and why"],
                   [f"Can you give me a real example of {s} from your own work?", f"When is {s} the wrong choice?",
                    "What would you use instead in that case?"]),
        "hands_on": (f"How would you use {s} to find yesterday's 10 slowest {dom}?",
                     f"How would you find the 10 slowest {dom} with {s}?",
                     ["A correct, workable approach", "Handles edge cases (ties, missing data, time zones)", "Thinks about speed at real volume"],
                     ["How would you check your answer is right?", "What about records with missing times?",
                      f"What changes if there are {n_rows} of them?"]),
        "scenario": (f"The {s} part of our {dom} system is slow and fragile: what do you do first?" if s
                     else f"In your first month you need to {duty_s}: how do you start?",
                     "What would you do first, and why?",
                     ["Finds out what's actually wrong before changing things", "Prioritises by impact and risk", "Keeps others informed", "Says how they'd know it worked"],
                     ["How would you find out what's actually wrong?", "What would you leave alone for now?",
                      "Who would you talk to first?", "How would you know it worked?"]),
        "real_world": (f"{Dom} are failing for 3% of users after a release, and {s} is involved: what do you check first?" if s
                       else "Something important in this role has gone wrong in front of a customer: what do you do first?",
                       "Something has broken in production. What do you check first?",
                       ["Limits the damage first (rollback, flag, pause)", "Checks logs and recent changes in a sensible order", "Communicates status", "Follows up so it doesn't happen again"],
                       ["When would you roll back instead of fixing forward?", "What would you check, in order?",
                        "Who do you tell, and when?", "How would you stop it happening again?"]),
        "experience": ((f"Your resume mentions \"{_short_quote(rline)}\": what was your own part?" if rline
                        else f"What's the hardest thing you've built with {s} recently, and what was your part?"),
                       "Tell me about this work: what was your part?",
                       ["Their own part, not the team's", "A concrete obstacle and how they handled it", "A measurable result", "What they'd do differently"],
                       ["Which decision there was yours alone?", "What went wrong along the way, and what did you do?",
                        "How did you know it was a success?", "What would you change now?"]),
        "design": (f"How would you design the {s} part of a system handling {n_rows} {dom} a day?",
                   "How would you design this at large scale?",
                   ["Clear main components", "Handles failure and scale", "Names real trade-offs (cost, speed, consistency)", "How they'd roll it out safely"],
                   ["What are the main pieces?", "What happens when one region goes down?",
                    "What would you trade off, and why?", "How would you roll it out safely?"]),
        "behaviour": ("Tell me about a time you disagreed with a teammate or manager: what did you do?",
                      "Tell me about a disagreement at work.",
                      ["A real, specific situation", "How they listened and argued their case", "The outcome", "What they learnt"],
                      ["How did you make your case?", "How did it end?",
                       "What would the other person say about it?", "Would you do anything differently now?"]),
    }
    q, simple, good, fus = T[qtype]
    return {"q": q, "simple": simple, "good": good, "followups": [{"if_missing": k, "q": f} for k, f in enumerate(fus)]}


# ---------------------------------------------------------------------------------------------------- proposing
def _new_id(prep):
    prep["seq"] = int(prep.get("seq") or 0) + 1
    return f"q{prep['seq']}"


SPEAK_MAX = 28   # words: longer questions are hard to read out in an interview


def _words(t):
    return len(re.findall(r"[\w'’-]+", t or ""))


def _short_quote(t, n=10):
    w = (t or "").strip().strip('"').split()
    return " ".join(w[:n]).rstrip(",.;:") + ("…" if len(w) > n else "")


def speakable(q, followups=()):
    """V02.01.05: a question an interviewer can say in one breath: at most one short lead-in sentence and the question.
    The other sentences become follow-ups (instructions like "say it out loud" are dropped), so nothing useful is lost.
    Returns (question, extra_followups, still_long)."""
    q = re.sub(r"\s+", " ", (q or "").strip())
    parts = [x.strip() for x in re.split(r"(?<=[.?!])\s+", q) if x.strip()]
    if len(parts) <= 1 and _words(q) <= SPEAK_MAX:
        return q, [], False
    asks = [x for x in parts if x.endswith("?") and _words(x) >= 4]
    main = asks[0] if asks else parts[0]
    used = [main]
    if parts and parts[0] != main and not parts[0].endswith("?") and _words(parts[0]) + _words(main) <= SPEAK_MAX:
        main, used = parts[0] + " " + main, [parts[0], main]
    if _words(main) > SPEAK_MAX and ":" in main:   # "Without code in front of you: talk me through..." -> the ask itself
        tail = main.split(":", 1)[1].strip()
        if _words(tail) >= 6:
            main = tail[:1].upper() + tail[1:]
    have = {(f.get("q") or "").lower() for f in followups}
    extra = []
    for x in parts:
        if x in used or _words(x) < 4 or re.search(r"(?i)out loud|in about a minute|take your time", x):
            continue
        x = re.sub(r"(?i)^(then|and|also|finally),?\s+", "", x)
        x = x[:1].upper() + x[1:]
        if not x.endswith("?") and re.match(r"(?i)(you|your|the|there|it)\b", x):   # a constraint, not an ask
            x = x.rstrip(".") + ". How does that change your answer?"
        if _words(x) <= 24 and x.lower() not in have:
            extra.append(x)
    return main, extra, _words(main) > SPEAK_MAX


def _question(prep, section, qtype, data, source):
    good = [str(g)[:160] for g in (data.get("good") or []) if str(g).strip()][:5] or ["A specific example", "Their own part", "The result"]
    fus = []
    for f in data.get("followups") or []:
        if isinstance(f, dict) and str(f.get("q") or "").strip():
            try:
                k = int(f.get("if_missing"))
            except (TypeError, ValueError):
                k = len(fus)
            fus.append({"if_missing": max(0, min(len(good) - 1, k)), "q": str(f["q"]).strip()[:300]})
    text = str(data.get("q") or "").strip()[:600]
    long_ = False
    if source != "own":   # the interviewer's own wording is theirs
        text, more, long_ = speakable(text, fus)
        fus += [{"if_missing": max(0, len(good) - 1), "q": m} for m in more]
    simple = str(data.get("simple") or "").strip()[:400]
    if not simple or _words(simple) > SPEAK_MAX:
        simple = simple if simple and not long_ else text
    out = {"id": _new_id(prep), "section": section["key"], "type": qtype, "q": text,
            "simple": simple, "good": good, "followups": fus[:5],
            "model": (str(data.get("model") or "").strip()[:900] or None),
            "minutes": int(data.get("minutes") or TYPES[qtype][2]), "source": source}
    if long_:
        out["long"] = True
    return out


def _ask_claude(job, profile, sections, level, avoid, company_id, skip=()):
    from services.ai import ask_json
    want = [{"section": s["key"], "name": s["name"], "kind": s["kind"], "must": s.get("must"), "years_on_resume": s.get("years"),
             "verified_already": s.get("verified"), "probe_from_earlier_rounds": s.get("probe") or [], "related": s.get("related") or [],
             "types": [t for t in types_for(s, level) if (s["key"], t) not in skip]} for s in sections if s["kind"] != "own"]
    want = [w for w in want if w["types"]]
    if not want:   # V02.01.05: the job's kept questions cover everything: no need to ask Claude
        return []
    mix = LEVELS[level]
    data = ask_json("propose live interview questions in sections", f"""Propose questions for a live interview for {job.title} ({job.level or 'any level'}).
The candidate's level is {mix['label']} ({mix['years']}). {mix['note']}
Job description: \"\"\"{(job.description or '')[:2500]}\"\"\"
Resume: \"\"\"{((profile.resume_text if profile else '') or '')[:3000]}\"\"\"
Questions already asked in earlier rounds (never repeat or reword): {json.dumps(list(avoid or [])[:30])}
Sections, each with the question types to write (one question per type listed):
{json.dumps(want)}
Question types:
{json.dumps({k: v[1] for k, v in TYPES.items()})}
Rules:
- SHORT AND SPEAKABLE: each question is ONE sentence of at most 25 words that an interviewer can read out in one
  breath, e.g. "How would you speed up a slow page that lists 10,000 orders?". No lists, no "Then...", no second part.
- Realistic and specific: use the job's own business and duties and real-sounding numbers. Never a textbook
  definition ("What is X?"). Any twist, constraint, scale question or "when is it the wrong choice" goes into the
  follow-ups, not into the question.
- Own-experience questions name a real project from the resume in a few words (not a long quote). If the resume has
  nothing on it, ask for one specific real example.
- Gap sections (not on the resume): start basic. Claim sections: one quick check that the claim is true.
- Fit the job's field: for non-software jobs use role-plays and business situations, not code.
- Every question has 3-4 points a good answer covers, and 3 follow-ups: each follow-up is what to ask when the
  candidate misses one of those points (if_missing = that point's index). Follow-ups are short too (under 18 words).
- No two questions start the same way.
Return JSON: {{"questions": [{{"section": section key, "type": one of the types, "q": the question, "simple": the same
question in even plainer words, "good": [points], "model": a 2-4 sentence model answer, "minutes": 2-8,
"followups": [{{"if_missing": 0, "q": "..."}}]}}]}}""",
                    lambda: None, company_id, max_tokens=6000, timeout=60)
    if not isinstance(data, dict):
        return []
    return [q for q in data.get("questions") or [] if isinstance(q, dict) and q.get("q") and q.get("type") in TYPES]


def propose(job, profile, prior=(), own=(), level=None, avoid=(), company_id=None, prep=None, only_section=None):
    """Writes the proposals. With `prep` and `only_section`, rewrites that section's unselected questions only."""
    level = level if level in LEVELS else guess_level(job, profile)
    prep = dict(prep or {})
    if not only_section:
        prep.update({"level": level, "sections": build_sections(job, profile, prior, own), "questions": [], "selected": [], "seq": 0})
    sections = prep["sections"]
    every = only_section == "*"
    targets = [s for s in sections if s["kind"] != "own" and (not only_section or every or s["key"] == only_section)]
    tkeys = {s["key"] for s in targets}
    chosen = set(prep.get("selected") or [])
    keep = [q for q in prep.get("questions", []) if q["section"] not in tkeys or q["id"] in chosen] if only_section else []
    avoid = list(avoid or []) + [q["q"] for q in keep]
    # V02.01.05: the job's kept questions come first; Claude only writes what they don't cover
    from services import ibank
    jset = ibank.match_set([q for q in ibank.job_set(job) if q.text not in avoid], targets, lambda s_: types_for(s_, level)) \
        if getattr(job, "id", None) else {}
    got = _ask_claude(job, profile, targets, level, avoid, company_id, skip=set(jset))
    by = {}
    for g in got:
        by.setdefault((g.get("section"), g.get("type")), g)
    # V02.01.04: everything Claude writes goes into the question bank (as drafts), by the section's skill
    secs = {x["key"]: x for x in targets}
    ibank.save(company_id, [{**g, "skill": (secs.get(g.get("section")) or {}).get("skill") or (secs.get(g.get("section")) or {}).get("name"),
                             "level": level, "section": (secs.get(g.get("section")) or {}).get("kind")} for g in got])
    out = list(keep)
    quoted = set()
    used = set(avoid)
    for s in targets:
        for i, t in enumerate(types_for(s, level)):
            if only_section and any(q["section"] == s["key"] and q["type"] == t for q in keep):
                continue
            jq = jset.get((s["key"], t))
            if jq:
                out.append({**_question(prep, s, t, ibank.as_prep(jq), "job"), "bank_id": jq.id})
                continue
            g = by.get((s["key"], t))
            if g:
                out.append(_question(prep, s, t, g, "claude"))
                continue
            # Claude didn't write this one: the question bank first (same skill and type), built-in templates last
            hit = ibank.find(company_id, s.get("skill"), t, used) if s.get("skill") else []
            if hit:
                used.add(hit[0].text)
                out.append({**_question(prep, s, t, ibank.as_prep(hit[0]), "bank"), "bank_id": hit[0].id})
            else:
                out.append(_question(prep, s, t, _builtin(s, t, job, profile, i + len(out), quoted), "builtin"))
    for i, q in enumerate(own or []):
        if not only_section:
            sec = next(s for s in sections if s["key"] == "own")
            out.append({**_question(prep, sec, "experience", {"q": q, "simple": q, "good": [], "followups": []}, "own"), "type": "own"})
    prep["questions"] = out
    prep["ai"] = any(q["source"] == "claude" for q in out)
    prep["written_at"] = datetime.utcnow().isoformat() + "Z"
    if not only_section:
        prep["selected"] = default_pick(prep)
    return prep


def default_pick(prep, n_tech=None, minutes=45, intro=True):
    """Isha's picks: the introduction, your own questions, then n_tech questions by the level's mix (must-have
    sections first, at most two per skill). Without n_tech, as many as fit the interview's minutes."""
    level = prep.get("level") or "mid"
    mix = LEVELS[level]["mix"]
    qs = prep.get("questions") or []
    secs = {s["key"]: s for s in prep.get("sections") or []}
    prio = {"intro": 0, "own": 1, "core": 2, "gap": 3, "domain": 4, "behaviour": 5, "claim": 6}
    picked, used = [], 0
    for q in qs:
        if (q["type"] == "intro" and intro) or q["type"] == "own":
            picked.append(q["id"])
            used += q.get("minutes") or 3
    budget = max(10, int(minutes or 45)) - 2  # a little time for the candidate's own questions
    tech = [q for q in qs if q["type"] not in ("intro", "own")]

    def rank(q):
        sec = secs.get(q["section"]) or {}
        order = types_for(sec, level) if sec else []
        return (0 if q.get("source") == "job" else 1,   # V02.01.05: this job's kept questions are picked first
                prio.get(sec.get("kind"), 9) - (1 if sec.get("must") else 0),
                order.index(q["type"]) if q["type"] in order else 9, -mix.get(q["type"], 0))
    ranked = sorted(tech, key=rank)
    per_section, chosen = {}, []
    # V02.01.01: the first question of each skill section uses a type the earlier sections haven't used yet when it
    # can, so the interview mixes own experience, hands-on, design… instead of the same type for every skill
    seen_types, firsts, sec_order = set(), {}, []
    for q in ranked:
        if q["section"] not in sec_order:
            sec_order.append(q["section"])
    for sk in sec_order:
        cands = [q for q in ranked if q["section"] == sk]
        pick = next((q for q in cands if q.get("source") == "job"), None) or \
            next((q for q in cands if q["type"] not in seen_types), cands[0])
        firsts[sk] = pick["id"]
        seen_types.add(pick["type"])
    ranked = sorted(ranked, key=lambda q: 0 if firsts.get(q["section"]) == q["id"] else 1)
    for rnd in (1, 2, 3, 4):  # breadth first: one per section, then a second for core and gap skills, ...
        for q in ranked:
            if q["id"] in chosen or (n_tech is not None and len(chosen) >= n_tech):
                continue
            sec = secs.get(q["section"]) or {}
            cap = {1: 1, 2: 2 if sec.get("kind") in ("core", "gap") else 1, 3: 3, 4: 9}[rnd]
            if per_section.get(q["section"], 0) >= cap:
                continue
            m = q.get("minutes") or 5
            if n_tech is None and used + m > budget:
                continue
            chosen.append(q["id"])
            per_section[q["section"]] = per_section.get(q["section"], 0) + 1
            used += m
        if n_tech is not None and len(chosen) >= n_tech:
            break
    # keep the section order the proposals have, so the interview flows topic by topic
    order = {q["id"]: i for i, q in enumerate(qs)}
    return picked + sorted(chosen, key=lambda i: order[i])


def to_areas(prep, competencies=()):
    """The chosen questions, in order, as the live plan's areas."""
    from services.scorecard import link_plan
    by = {q["id"]: q for q in prep.get("questions") or []}
    secs = {s["key"]: s for s in prep.get("sections") or []}
    areas, names = [], set()
    for qid in prep.get("selected") or []:
        q = by.get(qid)
        if not q:
            continue
        s = secs.get(q["section"]) or {}
        label = TYPES.get(q["type"], ("Your question",))[0] if q["type"] != "own" else "Your question"
        area = s.get("name") if q["type"] in ("intro",) else f"{s.get('name') or 'Question'} · {label}"
        base, k = area, 2
        while area in names:
            area, k = f"{base} {k}", k + 1
        names.add(area)
        areas.append({"area": area, "q": q["q"], "simple": q.get("simple") or q["q"], "good": q.get("good") or [],
                      "why": SECTION_KINDS.get(s.get("kind"), ("", ""))[1], "own": q["source"] == "own",
                      "qid": q["id"], "section": s.get("name"), "section_kind": s.get("kind"), "type": q["type"],
                      "type_label": label, "source": q["source"], "followups": q.get("followups") or [],
                      "minutes": q.get("minutes"), "model": q.get("model"),
                      **({"competency": s["skill"]} if s.get("skill") in (competencies or []) else {})})
    return link_plan(areas, list(competencies or []))


def summary(prep, minutes=45):
    """What the Prepare screen shows besides the questions: the level table and the checks."""
    by = {q["id"]: q for q in prep.get("questions") or []}
    chosen = [by[i] for i in prep.get("selected") or [] if i in by]
    secs = prep.get("sections") or []
    total = sum(q.get("minutes") or 0 for q in chosen)
    musts = [s for s in secs if s.get("must")]
    missing = [s["name"] for s in musts if not any(q["section"] == s["key"] for q in chosen)]
    types = [q["type"] for q in chosen if q["type"] not in ("intro", "own")]
    repeats = sum(1 for a, b in zip(types, types[1:]) if a == b)
    builtin = sum(1 for q in chosen if q["source"] == "builtin")
    checks = [{"ok": not missing, "text": "Every must-have skill has a question" if not missing else f"No question yet for must-have: {', '.join(missing)}"},
              {"ok": total <= minutes, "text": f"About {total} of {minutes} minutes" + ("" if total <= minutes else ": too long, remove a question")},
              {"ok": len(set(types)) >= min(3, len(types)), "text": f"{len(set(types))} question types" + (f", {repeats} back-to-back repeats" if repeats else "")},
              {"ok": builtin == 0, "text": "All questions written by Claude" if builtin == 0 else f"{builtin} built-in question{'s' if builtin != 1 else ''} (Claude was unavailable): rewrite them when Claude is back"},
              {"ok": all(q.get("followups") for q in chosen if q["source"] != "own"), "text": "Prepared follow-ups ready: they work even if Claude goes down"}]
    return {"minutes": minutes, "total_minutes": total, "checks": checks, "count": len(chosen)}
