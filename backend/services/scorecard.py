"""Isha's draft scorecard (V02.00.08, F2F-004 / SA-010).

The scorecard is scored against the job's competencies (its rubric), not against Isha's plan areas. Each plan
question is linked to a competency when the plan is made; answers to it count towards that competency. Every
competency gets a score and its strongest quote when there is evidence, or a plain reason when there isn't. The
recommendation and the summary are pre-filled. The interviewer changes anything they disagree with.
"""
import re

from extensions import db
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


def _mentions(text, comp):
    """True when the text talks about the competency: its name, or most of its longer words."""
    low = (text or "").lower()
    if comp.lower() in low:
        return True
    head = re.split(r"[(,/:]| - ", comp)[0].strip().lower()  # "SQL (joins, window functions)" -> "sql"
    if head and re.search(r"(?<![a-z0-9])" + re.escape(head) + r"(?![a-z0-9])", low):
        return True
    cw = {w for w in _words(comp) if len(w) > 3}
    return bool(cw) and len(cw & _words(text)) >= max(1, (len(cw) + 1) // 2)


def _evidence(att, job, comps):
    """{competency: {"entries": [...], "sentences": [...], "scores": [...], "asked": bool, "elsewhere": bool}}
    N2 (V02.00.09): answers given under Wrap-up (or the Opening) are no longer thrown away. They count towards the
    competency they talk about. A competency with no answers of its own picks up sentences that mention it anywhere."""
    res = att.result or {}
    brief = {a["area"]: a for a in (att.brief or {}).get("areas", [])}
    ev = {c: {"entries": [], "sentences": [], "scores": [], "asked": False, "elsewhere": False} for c in comps}
    loose = []  # sentences from Wrap-up / Opening / unlinked entries
    for e in res.get("areas_log", []):
        area = str(e.get("area", "")).lower()
        if area in ("wrap-up", "opening"):
            loose += [s for s in e.get("sentences") or [] if s]
            continue
        c = e.get("competency") or (brief.get(e.get("area")) or {}).get("competency") or link({**(brief.get(e.get("area")) or {}), **e}, comps)
        if c not in ev:  # an older plan without links: the competency with the least evidence so far
            if not ev:
                continue
            c = min(ev, key=lambda k: len(ev[k]["entries"]))
        ev[c]["asked"] = True
        ev[c]["entries"].append(e)
        ev[c]["sentences"] += [s for s in e.get("sentences") or [] if s]
        if e.get("rating"):  # V02.00.13: the interviewer's own rating in the room counts first
            ev[c].setdefault("ratings", []).append(float(e["rating"]))
        if e.get("score") and e.get("sentences"):
            ev[c]["scores"].append(float(e["score"]))
    for s in loose:  # a Wrap-up sentence about SQL counts for SQL
        for c in comps:
            if _mentions(s, c):
                ev[c]["sentences"].append(s)
                ev[c]["elsewhere"] = ev[c]["elsewhere"] or not ev[c]["entries"]
    everything = [s for e in res.get("areas_log", []) for s in (e.get("sentences") or []) if s]
    for c in comps:  # still nothing: anything said anywhere in the interview that mentions it
        if not ev[c]["sentences"]:
            hits = [s for s in everything if _mentions(s, c)]
            if hits:
                ev[c]["sentences"] = hits
                ev[c]["elsewhere"] = True
    return ev


def _recommend(avg):
    if avg is None:
        return "hold"
    return "proceed" if avg >= 3.5 else ("hold" if avg >= 2.5 else "reject")


def draft(att, job, cand_name="The candidate", use_ai=True):
    """Returns {"competencies": [...], "recommendation", "summary", "overall", "captured"}."""
    comps = competencies(job)
    res = att.result or {}
    log_ = res.get("areas_log", [])
    if not comps:  # nothing to score against: use the questions asked, as before
        comps = [e["area"] for e in log_ if e.get("sentences") and str(e.get("area", "")).lower() != "wrap-up"]
    ev = _evidence(att, job, comps)
    captured = sum(len(e.get("sentences") or []) for e in log_)  # sentences heard, each once
    rows = []
    for c in comps:
        v = ev.get(c) or {"sentences": [], "scores": [], "asked": False, "entries": []}
        if v.get("ratings"):  # rated by the interviewer during the interview
            r_ = v["ratings"]
            rows.append({"name": c, "score": max(1, min(5, int(round(sum(r_) / len(r_))))), "quote": max(v["sentences"], key=len)[:400] if v["sentences"] else "",
                         "ai_score": round(sum(v["scores"]) / len(v["scores"]), 1) if v["scores"] else None, "rated": True,
                         "questions": [e.get("q") for e in v["entries"]][:4]})
        elif v["sentences"]:
            score = round(sum(v["scores"]) / len(v["scores"])) if v["scores"] else 3
            quote = max(v["sentences"], key=len)
            rows.append({"name": c, "score": max(1, min(5, int(score))), "quote": quote[:400], "ai_score": round(sum(v["scores"]) / len(v["scores"]), 1) if v["scores"] else None,
                         "questions": [e.get("q") for e in v["entries"]][:4],
                         **({"elsewhere": True, "reason": "Not asked directly; scored from what the candidate said about it elsewhere in the interview."} if v.get("elsewhere") and not v["entries"] else {})})
        else:
            reason = "Asked, but no answer was captured (captions may have been off)." if v["asked"] else "Not asked in this interview."
            rows.append({"name": c, "score": None, "quote": "", "not_covered": True, "reason": reason})

    # Claude improves the scores, quotes and summary when it's available; the computed draft above is the fallback
    evidence = [{"competency": c, "questions": [e.get("q") for e in (ev.get(c) or {}).get("entries", [])][:4],
                 "answers": (ev.get(c) or {}).get("sentences", [])[-12:], "live_scores": (ev.get(c) or {}).get("scores", [])} for c in comps]
    topics = (res.get("review") or {}).get("topics") or []
    ai_extra = {}
    if captured and use_ai:
        def fb():
            return None
        out = ai.ask_json("draft an interview scorecard", f"""Draft the interviewer's scorecard for {job.title if job else 'this role'}.
You are Isha: judge the whole conversation, not only the planned questions. You assess; you don't decide whether the
candidate moves forward (the interviewer and the hiring team do).
Score each competency 1-5 from anything the candidate said in the interview. If there's no evidence for it, score null.
What each score means: 1 wrong or no substance; 2 basic, with clear gaps; 3 solid, what the role needs; 4 strong, with
evidence, reasons and results; 5 exceptional depth or leadership.
Evidence per competency (questions asked, the candidate's sentences, Isha's live 1-5 scores):
{__import__('json').dumps(evidence)[:10000]}
Every topic the candidate talked about, planned or not: {__import__('json').dumps(topics)[:4000]}
Return JSON: {{"competencies": [{{"name": exact competency name, "score": 1-5 integer or null, "quote": the single strongest exact quote from the answers}}],
"summary": 2-3 sentences for the hiring team, specific and fair, with no hiring recommendation,
"confidence": "high" | "medium" | "low" (how sure, given how much was heard), "reason": one sentence: what the evidence shows overall,
"strengths": up to 3 short phrases, "concerns": up to 3 short phrases,
"flags": up to 3 short phrases about contradictions with the resume, vague claims or important things never covered (or [])}}""", fb,
                           job.company_id if job else None, max_tokens=2000)
        if isinstance(out, dict):
            by = {str(x.get("name")): x for x in out.get("competencies") or [] if isinstance(x, dict)}
            for r in rows:
                x = by.get(r["name"])
                if not x or r.get("not_covered") or r.get("rated"):  # never overrides the interviewer's own rating
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
            lst = lambda k: [str(x)[:120] for x in (out.get(k) or []) if isinstance(x, str) and x.strip()][:3]  # noqa: E731
            ai_extra = {"confidence": out.get("confidence") if out.get("confidence") in ("high", "medium", "low") else None,
                        "reason": str(out.get("reason") or "").strip()[:300], "strengths": lst("strengths"), "concerns": lst("concerns"), "flags": lst("flags")}
        else:
            ai_summary, ai_rec = "", None
    else:
        ai_summary, ai_rec = "", None

    if not ai_summary and topics:
        # V02.01.06: without Claude, a competency's score also counts what the candidate said about it anywhere in the
        # interview (Isha's whole-conversation topics), not only the planned question's points
        by_t = {str(t["topic"]).lower(): t for t in topics}
        for r in rows:
            t = by_t.get(str(r["name"]).lower())
            if t and not r.get("rated"):
                if r.get("score"):
                    r["score"] = max(1, min(5, int(round((r["score"] + t["score"]) / 2 + 0.01))))
                else:
                    r.update(score=t["score"], quote=t.get("evidence") or "", elsewhere=True, not_covered=False,
                             reason="Not asked directly; scored from what the candidate said about it elsewhere in the interview.")
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
    for r in rows:  # what Isha suggested, so the screen can ask "why do you disagree?" when someone changes it
        r["suggested"] = r.get("score")
    isha = decide(att, rows, rec, avg, captured, topics, ai_extra, log_)
    # V02.01.07: Isha assesses; the recommendation is the interviewer's alone, so none is suggested
    return {"competencies": rows, "recommendation": None, "summary": summary, "overall": avg, "captured": captured,
            "ai": bool(use_ai and captured and (ai_summary or ai_extra)), "isha": isha}   # true only when Claude answered


ENOUGH = 6   # candidate sentences: below this, Isha says "not enough evidence" instead of guessing


def decide(att, rows, rec, avg, captured, topics, ai_extra, log_):
    """Isha's assessment (V02.01.07: no hiring recommendation; that's the interviewer's): how sure she is, a one-line
    summary of the evidence, strengths, concerns, red flags and where the candidate stands among this job's candidates."""
    scored = [r for r in rows if r.get("score")]
    covered = len(scored) / len(rows) if rows else 0
    if captured < ENOUGH:
        return {"insufficient": True, "confidence": "low", "overall": avg,
                "reason": f"Not enough evidence: only {captured} sentence{'s' if captured != 1 else ''} from the candidate were heard. "
                          "Transcribe the video, or score it from your own notes.",
                "strengths": [], "concerns": [], "flags": [], "topics": topics, "rank": None}
    conf = ai_extra.get("confidence") or ("high" if captured >= 25 and covered >= .75 else "medium" if captured >= 12 and covered >= .5 else "low")
    strengths = ai_extra.get("strengths") or [r["name"] for r in sorted(scored, key=lambda r: -r["score"]) if r["score"] >= 4][:3]
    concerns = ai_extra.get("concerns") or [r["name"] for r in sorted(scored, key=lambda r: r["score"]) if r["score"] < 3][:3]
    flags = ai_extra.get("flags")
    if flags is None or not ai_extra:
        flags = [f"{r['name']}: not covered" for r in rows if r.get("not_covered")][:2]
        flags += [f"Said it differently from the resume: “{t}”" for e in log_ for t in (x.get("label") for x in e.get("tags") or [] if x.get("type") == "flag") if t][:1]
    reason = ai_extra.get("reason") or (f"An average of {avg} out of 5 over {len(scored)} competenc{'y' if len(scored) == 1 else 'ies'}"
                                         + (f", strongest in {', '.join(strengths[:2])}" if strengths else "")
                                         + (f", weaker in {', '.join(concerns[:2])}" if concerns else "") + ".")
    return {"insufficient": False, "confidence": conf, "overall": avg, "reason": reason, "strengths": strengths,
            "concerns": concerns, "flags": flags, "topics": topics, "rank": rank(att, avg)}


def rank(att, avg):
    """Where this interview stands among the same job's interviews of the same kind that Isha has scored:
    {"place", "of", "same_set"} (same_set: they were asked the job's kept questions). None with fewer than 2."""
    if avg is None:
        return None
    from models import Application, RoundAttempt
    app_ = db.session.get(Application, att.application_id) if att.application_id else None
    if not app_:
        return None
    others = (RoundAttempt.query.join(Application, Application.id == RoundAttempt.application_id)
              .filter(Application.job_id == app_.job_id, RoundAttempt.round_type == att.round_type, RoundAttempt.id != att.id,
                      RoundAttempt.status.in_(("in_progress", "completed", "reviewed", "not_finished"))).all())
    vals = []
    for o in others:
        d_ = (o.result or {}).get("draft_scorecard") or {}
        v = (d_.get("isha") or {}).get("overall") or d_.get("overall")
        if isinstance(v, (int, float)):
            vals.append(v)
    if not vals:
        return None
    jobq = any(a.get("source") == "job" for a in (att.brief or {}).get("areas", []))
    return {"place": 1 + sum(1 for v in vals if v > avg), "of": len(vals) + 1, "same_set": jobq}
