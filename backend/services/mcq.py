"""Choosing MCQ questions (BUG-004).

Rules, for job rounds, certification sections and practice tests alike:
  1. Never the same question twice in one test, compared by its text (not just its id), so copies can't slip in.
  2. Questions the candidate saw in earlier attempts come last; unseen ones first.
  3. When the bank is short, Hira writes new questions and is told which ones to avoid. A new question whose text
     already exists is never saved. New questions are saved to the bank as drafts for review (company setting
     mcq.ai_review, on by default); they are used in this one test, and in others only once a person approves them.
  4. If there still aren't enough, the test is shorter rather than padded with copies, and the recruiter is told.
"""
import random
import re
from datetime import datetime, timedelta

from extensions import db
from models import Notification, Question, QuestionVersion, RoundAttempt

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def norm(text):
    """The text a person would call 'the same question': case, spacing and punctuation ignored."""
    return " ".join(_PUNCT.sub(" ", (text or "").lower()).split())


def _skills(att, job):
    return [s["name"] if isinstance(s, dict) else s for s in (job.skills if job else [])] or (att.config or {}).get("skills", [])


def _skey(name):
    return " ".join(_PUNCT.sub(" ", str(name or "").lower()).split())


def bank_skills(company_id=None):
    """{skill name as stored: approved question count} in the company's bank and the global bank."""
    rows = (db.session.query(Question.skill, db.func.count(Question.id))
            .filter(Question.status == "approved", Question.kind == "mcq", (Question.company_id == company_id) | (Question.company_id.is_(None)))
            .group_by(Question.skill).all())
    out = {}
    for name, n in rows:
        if name:
            out[name] = out.get(name, 0) + n
    return out


# V02.01.04: names that mean the same skill. Matching is otherwise exact (ignoring case, punctuation and words like
# "programming"), so "React Native" no longer pulls in React questions and "Java" never pulls in JavaScript.
_ALIASES = [{"javascript", "js", "ecmascript"}, {"typescript", "ts"}, {"postgresql", "postgres", "psql"},
            {"kubernetes", "k8s"}, {"golang", "go"}, {"node", "nodejs", "node js"}, {"react", "reactjs", "react js"},
            {"vue", "vuejs", "vue js"}, {"angular", "angularjs"}, {"c#", "csharp", "c sharp"}, {"c++", "cpp"},
            {"aws", "amazon web services"}, {"gcp", "google cloud", "google cloud platform"}, {"azure", "microsoft azure"},
            {"machine learning", "ml"}, {"sql", "structured query language"}, {"dotnet", "net", "asp net"}]
_GENERIC = {"database", "databases", "api", "apis", "querying", "queries", "query", "scripting", "concepts", "design",
            "services", "cloud", "core", "advanced", "basic", "fundamentals", "skills", "and", "with", "for", "in", "of"}
_SUFFIX = re.compile(r"\b(programming|language|framework|development|developer|basics|fundamentals|lang)\b")


def _canon(name):
    raw = str(name or "").lower().strip()
    for sym, word in (("c#", "csharp"), ("c++", "cpp"), (".net", " dotnet")):
        raw = raw.replace(sym, word)
    k = " ".join(_SUFFIX.sub(" ", _PUNCT.sub(" ", raw)).split())
    k = k.replace(" js", "js") if k.endswith(" js") else k
    for group in _ALIASES:
        if k in {" ".join(_PUNCT.sub(" ", g).split()) for g in group}:
            return sorted(group)[0]
    return k


def match_skills(wanted, company_id=None):
    """CD-005 (V02.00.08), stricter in V02.01.04: the bank's skill names that are the same skill as one asked for:
    same name ignoring capitals and punctuation, "Python programming" = "Python", or a known alias (JS = JavaScript)."""
    have = list(bank_skills(company_id))
    out = []
    for w in wanted or []:
        k = _canon(w)
        if not k:
            continue
        for h in have:
            hk = _canon(h)
            if h in out or not hk:
                continue
            # the same skill, or the skill plus only generic words: "SQL databases" = "SQL", but "React Native" isn't React
            rest = f" {k} ".replace(f" {hk} ", " ", 1).split() if f" {hk} " in f" {k} " else None
            if hk == k or (rest is not None and len(hk) >= 2 and all(w in _GENERIC for w in rest)):
                out.append(h)
    return out


def base_pool(att, job, folder_ids=None, skills=None, level=None):
    company_id = job.company_id if job else None
    pool = Question.query.filter(Question.status == "approved", Question.kind == "mcq",
                                 (Question.company_id == company_id) | (Question.company_id.is_(None)))
    if folder_ids:
        from routes.qbank import descendants
        ids = descendants(folder_ids, company_id) | descendants(folder_ids, None)
        return pool.filter(Question.folder_id.in_(ids or [0]))
    if skills:
        names = list(dict.fromkeys(list(skills) + match_skills(skills, company_id)))
        pool = pool.filter(Question.skill.in_(names))
    else:  # V02.01.04: no skills and no folders: nothing to match, never the whole bank
        return pool.filter(Question.id == -1)
    if level:
        pool = pool.filter(Question.level >= max(1, int(level) - 1), Question.level <= int(level) + 1)
    return pool


def unique(questions):
    """Drops questions whose text repeats another's. Keeps the newest version (highest id) of each text."""
    out, seen = [], set()
    for q in sorted(questions, key=lambda q: -(q.id or 0)):
        k = norm(q.text)
        if k and k not in seen:
            seen.add(k)
            out.append(q)
    return out


def seen_before(att):
    """(ids, texts) of questions this candidate was shown in their other MCQ attempts."""
    from services.pipeline import context
    _, _, cand, _ = context(att)
    if not cand:
        return set(), set()
    from models import Application, CertAttempt
    app_ids = [a.id for a in Application.query.filter_by(candidate_id=cand.id).all()]
    cert_ids = [c.id for c in CertAttempt.query.filter_by(user_id=cand.id).all()]
    q = RoundAttempt.query.filter(RoundAttempt.round_type == "mcq", RoundAttempt.id != att.id,
                                  (RoundAttempt.application_id.in_(app_ids or [0])) | (RoundAttempt.practice_user_id == cand.id) |
                                  (RoundAttempt.cert_attempt_id.in_(cert_ids or [0])))
    ids, texts = set(), set()
    for prev in q.all():
        res = prev.result or {}
        ids.update(int(i) for i in res.get("question_ids") or [])
        texts.update(norm(v.get("text")) for v in (res.get("qsnap") or {}).values())
    return ids, texts


def _existing_texts(company_id):
    rows = db.session.query(Question.text).filter((Question.company_id == company_id) | (Question.company_id.is_(None)),
                                                  Question.status != "archived").all()
    return {norm(t) for (t,) in rows}


def save_generated(items, company_id, skills, review=True, folder_id=None, tags=None, note="Drafted by Hira"):
    """Saves AI-written questions, skipping any whose text is already in the bank (or repeats another in this batch).
    CD-005 (V02.00.08): built-in filler questions (written without Claude) are never saved to a bank. They come back
    unsaved, with a negative id, and are used in this one test through its snapshot."""
    taken = _existing_texts(company_id)
    out = []
    temp_id = 0
    # V02.01.04: Claude sometimes puts most right answers in one place; spread them over A-D before saving
    targets = balanced_targets(len(items or []), 4)
    items = [place_answer(it, t) if len(it.get("options") or []) >= 4 else it for it, t in zip(items or [], targets)]
    for it in items or []:
        text = str(it.get("text") or "").strip()
        opts = [str(o) for o in (it.get("options") or []) if str(o).strip()][:6]
        k = norm(text)
        if not k or k in taken or len(opts) < 2 or len({norm(o) for o in opts}) < len(opts):
            continue
        taken.add(k)
        try:
            ans = int(it.get("answer", 0))
        except (TypeError, ValueError):
            continue
        if not 0 <= ans < len(opts):
            continue
        q = Question(company_id=company_id, folder_id=folder_id, skill=(it.get("skill") or (skills[0] if skills else "General"))[:80],
                     level=max(1, min(5, int(it.get("level") or 3))), text=text[:4000], code=it.get("code") or None, options=opts,
                     answer=ans, explanation=it.get("explanation"), tags=tags or [], status="pending" if review else "approved",
                     source="ai", version=1)
        if it.get("fallback"):
            temp_id -= 1
            q.id = temp_id
            q.status = "filler"
            out.append(q)
            continue
        db.session.add(q)
        db.session.flush()
        db.session.add(QuestionVersion(question_id=q.id, version=1, snapshot=q.snapshot(), note=note))
        out.append(q)
    return out


def pick(att, job, n, allow_ai=True):
    """Returns (questions, info). info = {"wanted", "got", "short", "generated", "repeats"}.
    allow_ai=False (V02.00.12, F9): use the bank only. Papers drawn at invite never wait for the AI, so inviting many
    candidates at once can't time out; the reviewer can ask Hira for more questions from the paper review."""
    from services import ai
    from services.settings import resolve
    cfg = att.config or {}
    skills, level = _skills(att, job), cfg.get("level")
    company_id = job.company_id if job else None
    folder_ids = cfg.get("mcq.folder_ids") or []
    pool = unique(base_pool(att, job, folder_ids, skills, level).all())
    practice = bool(att and att.practice_user_id and not cfg.get("skill_check"))
    if practice and len(pool) < n and level:  # CD-005: practice widens to every level before writing anything new
        pool = unique(base_pool(att, job, folder_ids, skills, None).all())
    seen_ids, seen_texts = seen_before(att)
    fresh = [q for q in pool if q.id not in seen_ids and norm(q.text) not in seen_texts]
    repeat = [q for q in pool if q not in fresh]
    random.shuffle(fresh)
    random.shuffle(repeat)
    # questions people wrote (the superadmin's or the company's) come before AI-written ones
    fresh.sort(key=lambda q: 1 if q.source == "ai" else 0)
    generated = []
    # BUG-001 (V02.00.09): a practice quiz is mostly written fresh by Hira (practice.ai_share, default 80%); the rest
    # comes from the bank. Skill checks and hiring rounds keep using the bank first.
    want_ai = 0
    if practice and not folder_ids:
        share = max(0, min(100, int(resolve("practice.ai_share")[0] or 0)))
        want_ai = round(n * share / 100)
    bank_n = n - want_ai
    need = max(want_ai, n - len(fresh)) if practice else n - len(fresh)
    if need > 0 and not folder_ids and allow_ai:  # chosen folders are used as they are; never generate into them
        avoid = [q.text for q in pool][:60]
        items = ai.generate_mcq(skills or ["General aptitude"], int(level or 3), need, company_id=company_id, avoid=avoid)
        # practice and skill checks write into the global bank, so a person always reviews those first (CD-005)
        review = bool(resolve("mcq.ai_review", company_id=company_id, team_id=job.team_id if job else None,
                              job_id=job.id if job else None)[0]) if job else True
        claude_down = bool(items) and all(x.get("fallback") for x in items)
        generated = save_generated(items, company_id, skills, review=review)
        # V02.01.04: built-in filler questions (written when Claude failed) are never used, practice included: they
        # read as unrelated. A test is shorter rather than padded, and says its questions came from the bank.
        generated = [q for q in generated if (q.id or 0) > 0]
        texts = {norm(q.text) for q in fresh + repeat}
        generated = [q for q in generated if norm(q.text) not in texts]
    if practice and want_ai:
        real = [q for q in generated if (q.id or 0) >= 0]
        filler = [q for q in generated if (q.id or 0) < 0]
        head = fresh[:bank_n] + real[:want_ai]
        rest = fresh[bank_n:] + real[want_ai:]  # when Hira wrote fewer, the bank fills the gap before any filler
        chosen = (head + rest + filler + repeat)[:n]
        random.shuffle(chosen)
        generated = [q for q in generated if q in chosen]
    else:
        chosen = (fresh + generated + repeat)[:n]
    info = {"wanted": n, "got": len(chosen), "short": len(chosen) < n, "generated": len(generated),
            "repeats": sum(1 for q in chosen if q in repeat),
            "bank_only": not generated, "claude_down": bool(locals().get("claude_down"))}
    info["filler"] = sum(1 for q in chosen if (q.id or 0) < 0)
    if generated and job and any(q.status == "pending" for q in generated):
        _tell(job, "New questions to review", f"Hira wrote {len(generated)} new question{'s' if len(generated) != 1 else ''} for {job.title}. "
              "They were used once and wait in the question bank as drafts until someone approves them.", f"/app/questions?status=pending&job={job.id}")
    if info["short"] and job:
        _tell(job, "MCQ round is short of questions",
              f"{job.title}: a candidate got {len(chosen)} of {n} questions because the question bank doesn't have enough different ones. "
              "Add or approve questions, or lower the number of questions.", f"/app/jobs/{job.id}")
    return chosen, info


def _tell(job, title, body, link):
    """Once a day per job and message, so a busy round doesn't flood anyone."""
    from services.audit import notify_roles
    since = datetime.utcnow() - timedelta(hours=24)
    if Notification.query.filter(Notification.title == title, Notification.link == link, Notification.created_at > since).first():
        return
    notify_roles(job.company_id, ["recruiter", "manager"], title, body, link)


def coverage(job, cfg, n):
    """For round setup: how many different questions the bank has for this round."""
    folder_ids = cfg.get("mcq.folder_ids") or []
    skills = [s["name"] if isinstance(s, dict) else s for s in (job.skills or [])]
    pool = unique(base_pool(None, job, folder_ids, None if folder_ids else skills, None).all())
    by = {}
    for q in pool:
        by[q.skill or "General"] = by.get(q.skill or "General", 0) + 1
    pending = Question.query.filter(Question.status == "pending", Question.kind == "mcq",
                                    (Question.company_id == job.company_id) | (Question.company_id.is_(None))).count()
    have = len(pool)
    parts = ", ".join(f"{k} {v}" for k, v in sorted(by.items(), key=lambda x: -x[1])[:6])
    if have >= n * 2:
        msg = f"{n} questions per test from {have} available ({parts}). Retakes can get different questions."
    elif have >= n:
        msg = f"{n} questions per test from {have} available ({parts}). Retakes will repeat some questions; add more for variety."
    elif folder_ids:
        msg = f"Only {have} questions in the chosen folders, so tests will have {have} instead of {n}. Add questions or choose more folders."
    else:
        # A4 (V02.00.12): papers are drawn from the bank at invite, so a short bank means a short paper until someone adds more
        msg = (f"Only {have} approved questions for this job's skills{f' ({parts})' if parts else ''}, so each paper starts with {have} "
               f"instead of {n}. Add questions to the bank, or press \"Ask Hira for more\" while reviewing a paper.")
    if pending:
        msg += f" {pending} draft question{'s' if pending != 1 else ''} wait for review."
    return {"available": have, "by_skill": by, "wanted": n, "short": have < n, "pending": pending, "message": msg}

# ---------------------------------------------------------------- A2 (V02.00.12): balanced answers

_FIXED = re.compile(r"\b(all|none|both|neither)\b.*\b(above|of these|a and b|b and c)\b", re.I)


def shuffle_entry(d, rng=None):
    """A question snapshot with its options in a new random order and the answer index moved with them.
    Every paper shuffles its options, so the correct answer isn't always in the same place (the starter bank and
    Hira's questions leaned heavily towards B). Options like "All of the above" keep their place, because their
    meaning depends on it."""
    rng = rng or random
    opts = list(d.get("options") or [])
    try:
        ans = int(d.get("answer"))
    except (TypeError, ValueError):
        return d
    if len(opts) < 2 or not 0 <= ans < len(opts):
        return d
    movable = [i for i, o in enumerate(opts) if not _FIXED.search(str(o))]
    order = list(range(len(opts)))
    shuffled = movable[:]
    rng.shuffle(shuffled)
    for slot, src in zip(movable, shuffled):
        order[slot] = src
    return {**d, "options": [opts[i] for i in order], "answer": order.index(ans), "option_order": order}


def place_answer(d, target, rng=None):
    """V02.01.04: like shuffle_entry, but the correct option lands at `target` when it can (options whose meaning
    depends on their place, like "All of the above", stay put)."""
    rng = rng or random
    d2 = shuffle_entry(d, rng)
    opts = list(d2.get("options") or [])
    try:
        ans = int(d2.get("answer"))
    except (TypeError, ValueError):
        return d2
    if not (0 <= target < len(opts)) or ans == target or _FIXED.search(str(opts[target])) or _FIXED.search(str(opts[ans])):
        return d2
    order = list(d2.get("option_order") or range(len(opts)))
    opts[ans], opts[target] = opts[target], opts[ans]
    order[ans], order[target] = order[target], order[ans]
    return {**d2, "options": opts, "answer": target, "option_order": order}


def answer_split(snaps):
    """{"A": n, "B": n, ...}: where the correct answers sit across a paper."""
    out = {}
    for d in snaps:
        try:
            a = int(d.get("answer"))
        except (TypeError, ValueError, AttributeError):
            continue
        k = "ABCDEF"[a] if 0 <= a < 6 else "?"
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items()))


def balanced_targets(n, width=4, have=None, rng=None):
    """n answer positions spread evenly over A-D, topping up whatever the paper already has (have = {index: count})."""
    rng = rng or random
    have = dict(have or {})
    out = []
    for _ in range(n):
        low = min(have.get(i, 0) for i in range(width))
        choices = [i for i in range(width) if have.get(i, 0) == low]
        t = rng.choice(choices)
        have[t] = have.get(t, 0) + 1
        out.append(t)
    return out


def shuffled_snap(questions_or_snaps, rng=None, have=None):
    """{str(id): shuffled snapshot} for Question rows or (id, snapshot) pairs.
    V02.01.04: the correct answers are spread evenly across the positions (no letter more than a quarter of the paper,
    plus one), on top of the positions the paper already has (have = {index: count})."""
    items = []
    for item in questions_or_snaps:
        if isinstance(item, tuple):
            qid, snap = item
        else:
            qid, snap = item.id, {**item.snapshot(), "version": item.version or 1}
        items.append((qid, snap))
    targets = balanced_targets(len(items), 4, have, rng)
    out = {}
    for (qid, snap), t in zip(items, targets):
        out[str(qid)] = place_answer(snap, t, rng) if len(snap.get("options") or []) >= 4 else shuffle_entry(snap, rng)
    return out
