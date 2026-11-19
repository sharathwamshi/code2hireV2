"""Candidate profile rules shared by the candidate portal and the hiring team (V02.00.10).

- strength(p, user): ONE profile-strength formula used on every page (HOM-02, PRF-01). Every item counts and each
  one is strict: a phone needs 10+ digits, skills need at least 5, the name needs a first and a last name.
- next_steps(p, user): the 5-step checklist on Home (HOM-06).
- read_resume / resume_plan / apply_resume: a new resume REPLACES the skills read from the old one (CP-004); skills
  the person added by hand, and verified skills, stay. The candidate (or the hiring team) sees what will be added and
  removed before it is saved (PRF-09).
"""
import re

from services import ai
from services.skills import canon, same

STRENGTH = [  # key, label, weight, where to fix it
    ("name", "Your name", 5, "/me/profile#f-name"),
    ("resume", "Resume", 15, "/me/profile#resume"),
    ("headline", "Headline", 10, "/me/profile#f-headline"),
    ("location", "City", 10, "/me/profile#f-location"),
    ("phone", "Phone", 10, "/me/profile#f-phone"),
    ("experience", "Years of experience", 10, "/me/profile#f-experience"),
    ("skills", "At least 5 skills", 10, "/me/profile#skills"),
    ("goal", "Target role", 10, "/me#path"),
    ("verified", "A verified skill", 20, "/me/skills"),
]


def _checks(p, user):
    name = (user.name or "").strip() if user else ""
    phone_digits = re.sub(r"\D", "", (p.phone or "") if p else "")
    head = ((p.headline or "") if p else "").strip()
    return {
        # F6 (V02.00.12): many people have one name only, so a real name of 2+ letters counts (not the email's start)
        "name": len(re.sub(r"[^\w]", "", name)) >= 2 and not (getattr(user, "email", None) and name.lower() == user.email.split("@")[0].lower()),
        "resume": bool(p and p.resume_text and len(p.resume_text.strip()) >= 200),
        "headline": len(head) >= 3 and head.lower() != name.lower(),
        "location": bool(p and (p.location or "").strip()),
        "phone": 10 <= len(phone_digits) <= 15,
        "experience": bool(p and p.experience_years is not None),
        "skills": bool(p and len(p.skills or []) >= 5),
        "goal": bool(p and [r for r in (p.target_roles or []) if r and r != "your next role"]),
        "verified": bool(p and any(s.get("verified") for s in p.skills or [])),
    }


def strength(p, user):
    c = _checks(p, user)
    items = [{"key": k, "label": lbl, "weight": w, "done": c[k], "link": link} for k, lbl, w, link in STRENGTH]
    pct = sum(i["weight"] for i in items if i["done"])
    return {"pct": pct, "items": items, "missing": [i["label"] for i in items if not i["done"]]}


def next_steps(p, user, practice_count=0):
    c = _checks(p, user)
    steps = [
        {"key": "skills", "label": "Add at least 5 skills", "done": c["skills"], "action": "Add skills", "link": "/me/profile#skills"},
        {"key": "about", "label": "Add a headline and your city", "done": c["headline"] and c["location"], "action": "Add details", "link": "/me/profile#f-headline"},
        {"key": "resume", "label": "Upload your resume", "done": c["resume"], "action": "Upload resume", "link": "/me/profile#resume"},
        {"key": "check", "label": "Take your first skill check", "done": c["verified"], "action": "Take a check", "link": "/me/skills"},
        {"key": "practice", "label": "Practise your first interview", "done": practice_count > 0, "action": "Practise", "link": "/me/practice"},
    ]
    return {"steps": steps, "done": sum(1 for s in steps if s["done"]), "total": len(steps)}


def read_resume(text, company_id=None):
    """Fields and skills from a resume (Claude when available, else pattern matching), names in canonical spelling."""
    f = ai.resume_fields(text, company_id=company_id) or {}
    skills = []
    for s in (f.get("skills") or []) + ai.extract_skills(text):
        s = canon(s)
        if s and not any(same(s, x) for x in skills):
            skills.append(s)
    f["skills"] = skills[:25]
    return f


def resume_plan(p, fields):
    """What saving this resume would change: skills to add, skills from the OLD resume to remove, and fields to fill."""
    new = fields.get("skills") or []
    have = list(p.skills or []) if p else []
    add = [s for s in new if not any(same(s, h.get("name")) for h in have)]
    remove = [h["name"] for h in have if h.get("source") == "resume" and not h.get("verified")
              and not any(same(h.get("name"), s) for s in new)]
    keep = [h["name"] for h in have if h["name"] not in remove]
    fill = {}
    for k in ("headline", "location", "phone", "experience_years"):
        v = fields.get(k)
        cur = getattr(p, k, None) if p else None
        if v not in (None, "") and cur in (None, ""):
            fill[k] = v
    return {"add": add, "remove": remove, "keep": keep, "fill": fill}


def apply_resume(p, text, plan, add=None, remove=None, fill=None):
    """Save the resume and apply the plan (or only the parts the person ticked)."""
    add = plan["add"] if add is None else [s for s in add if s]
    remove = plan["remove"] if remove is None else remove
    fill = plan["fill"] if fill is None else fill
    p.resume_text = text[:30000]
    skills = [dict(s) for s in (p.skills or []) if not (s["name"] in remove and s.get("source") == "resume" and not s.get("verified"))]
    for s in add:
        if not any(same(s, x["name"]) for x in skills):
            skills.append({"name": canon(s), "level": 2, "verified": False, "source": "resume"})
    p.skills = skills
    for k, v in (fill or {}).items():
        if k in ("headline", "location", "phone"):
            setattr(p, k, str(v)[:200])
        elif k == "experience_years":
            try:
                p.experience_years = float(v)
            except (TypeError, ValueError):
                pass
    return {"added": add, "removed": remove, "filled": list((fill or {}).keys())}
