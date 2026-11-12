"""Isha's draft scorecard (V02.00.08, F2F-004 / SA-010).

The scorecard is scored against the job's competencies (its rubric), not against Isha's plan areas. Each plan
question is linked to a competency when the plan is made; answers to it count towards that competency. Every
competency gets a score and its strongest quote when there is evidence, or a plain reason when there isn't. The
recommendation and the summary are pre-filled. The interviewer changes anything they disagree with.
"""
import re

from services import ai

_WORD = re.compile(r"[a-z0-9+#.]+")


def _words(t):
    return {w for w in _WORD.findall((t or "").lower()) if len(w) > 2}


def competencies(job):
    """The job's competency names, in order. A job without a rubric falls back to its skills."""
    names = [r["name"] for r in (job.rubric or []) if isinstance(r, dict) and r.get("name")] if job else []
    if not names and job:
        names = [s["name"] if isinstance(s, dict) else s for s in (job.skills or [])][:6]
    return names


def link(area, comps):
    """The competency a plan question belongs to: the one it names, or the one sharing the most words with it."""
    if not comps:
        return None
    if area.get("competency") in comps:
        return area["competency"]
    text = " ".join(str(area.get(k) or "") for k in ("area", "q", "why"))
    low = text.lower()
    for c in comps:
        if c.lower() in low:
            return c
    aw = _words(text)
    best, score = None, 0
    for c in comps:
        s = len(aw & _words(c))
        if s > score:
            best, score = c, s
    return best


def link_plan(areas, comps):
    """Adds "competency" to each plan question except Wrap-up. A question that names no competency (a general one)
    goes to the competency with the fewest questions so far, so every answer counts towards the scorecard."""
    out, used = [], {c: 0 for c in comps or []}
    for a in areas or []:
        a = dict(a)
        if str(a.get("area", "")).lower() != "wrap-up" and comps:
            c = link(a, comps)
            a["competency"] = c or min(comps, key=lambda x: used[x])
            used[a["competency"]] += 1
        out.append(a)
    return out


def _evidence(att, job, comps):
    """{competency: {"entries": [...], "sentences": [...], "scores": [...], "asked": bool}}"""
    res = att.result or {}
    brief = {a["area"]: a for a in (att.brief or {}).get("areas", [])}
    ev = {c: {"entries": [], "sentences": [], "scores": [], "asked": False} for c in comps}
    for e in res.get("areas_log", []):
        if str(e.get("area", "")).lower() == "wrap-up":
            continue
        c = e.get("competency") or (brief.get(e.get("area")) or {}).get("competency") or link({**(brief.get(e.get("area")) or {}), **e}, comps)
        if c not in ev:  # an older plan without links: the competency with the least evidence so far
            if not ev:
                continue
            c = min(ev, key=lambda k: len(ev[k]["entries"]))
        ev[c]["asked"] = True
        ev[c]["entries"].append(e)
        ev[c]["sentences"] += [s for s in e.get("sentences") or [] if s]
        if e.get("score") and e.get("sentences"):
            ev[c]["scores"].append(float(e["score"]))
    return ev


def _recommend(avg):
    if avg is None:
        return "hold"
    return "proceed" if avg >= 3.5 else ("hold" if avg >= 2.5 else "reject")


def draft(att, job, cand_name="The candidate"):
    """Returns {"competencies": [...], "recommendation", "summary", "overall", "captured"}."""
    comps = competencies(job)
    res = att.result or {}
    log_ = res.get("areas_log", [])
    if not comps:  # nothing to score against: use the questions asked, as before
        comps = [e["area"] for e in log_ if e.get("sentences") and str(e.get("area", "")).lower() != "wrap-up"]
    ev = _evidence(att, job, comps)
    captured = sum(len(v["sentences"]) for v in ev.values())
    rows = []
    for c in comps:
        v = ev.get(c) or {"sentences": [], "scores": [], "asked": False, "entries": []}
        if v["sentences"]:
            score = round(sum(v["scores"]) / len(v["scores"])) if v["scores"] else 3
            quote = max(v["sentences"], key=len)
            rows.append({"name": c, "score": max(1, min(5, int(score))), "quote": quote[:400], "ai_score": round(sum(v["scores"]) / len(v["scores"]), 1) if v["scores"] else None,
                         "questions": [e.get("q") for e in v["entries"]][:4]})
        else:
            reason = "Asked, but no answer was captured (captions may have been off)." if v["asked"] else "Not asked in this interview."
            rows.append({"name": c, "score": None, "quote": "", "not_covered": True, "reason": reason})

    # Claude improves the scores, quotes and summary when it's available; the computed draft above is the fallback
    evidence = [{"competency": c, "questions": [e.get("q") for e in (ev.get(c) or {}).get("entries", [])][:4],
                 "answers": (ev.get(c) or {}).get("sentences", [])[-12:], "live_scores": (ev.get(c) or {}).get("scores", [])} for c in comps]
    if captured:
        def fb():
            return None
        out = ai.ask_json("draft an interview scorecard", f"""Draft the interviewer's scorecard for {job.title if job else 'this role'}.
Score each competency 1-5 only from the candidate's answers given. If a competency has no answers, return score null.
Evidence per competency (questions asked, the candidate's sentences, Isha's live 1-5 scores):
{__import__('json').dumps(evidence)[:12000]}
Return JSON: {{"competencies": [{{"name": exact competency name, "score": 1-5 integer or null, "quote": the single strongest exact quote from the answers}}],
"summary": 2-3 sentences for the hiring team, specific and fair, "recommendation": "proceed" | "hold" | "reject"}}""", fb,
                           job.company_id if job else None, max_tokens=1800)
        if isinstance(out, dict):
            by = {str(x.get("name")): x for x in out.get("competencies") or [] if isinstance(x, dict)}
            for r in rows:
                x = by.get(r["name"])
                if not x or r.get("not_covered"):
                    continue
                try:
                    s = int(x.get("score")) if x.get("score") is not None else None
                except (TypeError, ValueError):
                    s = None
                if s and 1 <= s <= 5:
                    r["score"] = s
                q = str(x.get("quote") or "").strip()
                if q and any(q.lower()[:40] in t.lower() for t in (ev.get(r["name"]) or {}).get("sentences", [])):
                    r["quote"] = q[:400]
            ai_summary = str(out.get("summary") or "").strip()
            ai_rec = out.get("recommendation") if out.get("recommendation") in ("proceed", "hold", "reject") else None
        else:
            ai_summary, ai_rec = "", None
    else:
        ai_summary, ai_rec = "", None

    scored = [r["score"] for r in rows if r.get("score")]
    avg = round(sum(scored) / len(scored), 1) if scored else None
    rec = ai_rec or _recommend(avg)
    if ai_summary:
        summary = ai_summary
    elif scored:
        strong = [r["name"] for r in rows if (r.get("score") or 0) >= 4]
        weak = [r["name"] for r in rows if r.get("score") and r["score"] < 3]
        missing = [r["name"] for r in rows if r.get("not_covered")]
        bits = [f"{cand_name} averaged {avg} out of 5 across {len(scored)} competenc{'y' if len(scored) == 1 else 'ies'}."]
        if strong:
            bits.append("Strongest in " + ", ".join(strong[:3]) + ".")
        if weak:
            bits.append("Weaker in " + ", ".join(weak[:3]) + ".")
        if missing:
            bits.append("Not assessed: " + ", ".join(missing[:4]) + ".")
        summary = " ".join(bits)
    else:
        summary = ("No answers were captured, so Isha couldn't score this interview. Score each competency from your own "
                   "notes, or check the transcript and the video.")
    return {"competencies": rows, "recommendation": rec, "summary": summary, "overall": avg, "captured": captured}
