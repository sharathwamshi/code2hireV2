"""V02.01.01: review the whole interview from its transcript.

During a live interview with Isha, answers are filed under the question that is current. If the interviewer never
marks a question as asked (and Isha didn't hear it), everything lands under one question and the rest look "not
asked". Nothing is lost: every sentence is saved in order (the transcript, `turns`). This module reads the WHOLE
transcript when the interview ends and decides afresh:

- which plan questions were asked (and when), in any order, in the interviewer's own words;
- which part of the transcript answers each one, follow-ups included;
- questions the interviewer asked that weren't in the plan;
- what each answer covered of its good points, and a score.

With Claude, Claude reads the transcript. Without it, a keyword method does the same job more roughly: interviewer
turns that match a plan question start that question; when the interviewer's voice wasn't captured at all, each
candidate sentence goes to the plan question its words fit best.

The live log is kept (result.areas_log_live) and the reviewed one replaces result.areas_log, which the scorecard and
the report read. Ratings the interviewer gave per question are carried over to the same question.
"""
import json
import re
from datetime import datetime

from services.ai import ask_json

_STOP = set("a an the and or but to of in on for with about your you we our is are was were be been do does did can could would "
            "should will what how why when where which who me my i it this that there their them they as at by from so if then than "
            "tell walk talk through please just like really kind sort bit".split())


def _stem(w):
    for suf in ("ing", "ies", "es", "ed", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def _content(text):
    """Content words, lightly stemmed (checks/check, indexes/index), without punctuation."""
    out = []
    for w in re.findall(r"[a-z0-9+#]+(?:\.[a-z0-9]+)*", (text or "").lower()):
        if w not in _STOP and len(w) > 2:
            out.append(_stem(w))
    return out

MAX_TURNS = 400


def transcript(att):
    """Every saved turn of the interview, in order: [{i, who: interviewer|candidate, text, at}]."""
    from models import Turn
    out = []
    for t in Turn.query.filter_by(attempt_id=att.id).order_by(Turn.seq, Turn.id).all():
        if t.speaker not in ("interviewer", "candidate") or not (t.text or "").strip():
            continue
        out.append({"i": len(out), "who": t.speaker, "text": " ".join(t.text.split())[:1500], "at": t.at_seconds or 0})
    return out[-MAX_TURNS:]


def _overlap(text, q):
    """Share of the question's content words that appear in the text (0-1). At least two words must be shared, so a
    short question (the Wrap-up) isn't matched by one common word."""
    qw = set(_content(q))
    if len(qw) < 2:
        return 0.0
    shared = len(qw & set(_content(text)))
    return shared / len(qw) if shared >= 2 else 0.0


def coverage(good, answer):
    """full / partial / none per good point, from the words of the answer."""
    words = set(_content(answer))
    out = []
    for g in good or []:
        key = [w for w in _content(g) if len(w) > 3]
        if not key:
            out.append("none")
            continue
        hit = len([w for w in key if w in words]) / len(key)
        out.append("full" if hit >= 0.6 else "partial" if hit > 0 else "none")
    return out


def score_from(cov, answer):
    n = len(cov)
    words = len((answer or "").split())
    if not words:
        return None
    if not n:
        return 3.0 if words >= 25 else 2.0
    got = sum(1 if c == "full" else 0.5 if c == "partial" else 0 for c in cov) / n
    return max(1.0, min(5.0, round((1 + 4 * got) * 2) / 2))


def _plan(att):
    return [a for a in (att.brief or {}).get("areas", []) if not a.get("skipped")]


# ---------------------------------------------------------------------------------------------------- keyword method
def _segment_keywords(turns, plan):
    """[{area|None, q, kind: plan|followup|other, turns: [i...]}] without Claude."""
    segs, started = [], set()
    has_iv = any(t["who"] == "interviewer" for t in turns)
    if has_iv:
        cur = None
        for t in turns:
            if t["who"] == "interviewer":
                best, bs = None, 0.0
                for a in plan:
                    if a["area"] in started:
                        continue
                    s = max(_overlap(t["text"], a.get("q")), _overlap(t["text"], a.get("simple")))
                    if s > bs:
                        best, bs = a, s
                if best and bs >= 0.35:
                    cur = {"area": best["area"], "q": t["text"], "kind": "plan", "turns": [t["i"]], "parent": None}
                    started.add(best["area"])
                    segs.append(cur)
                elif len(t["text"].split()) >= 4 and ("?" in t["text"] or re.match(r"(?i)^(how|what|why|when|where|which|who|can|could|would|tell|walk|explain|describe|give)\b", t["text"])):
                    # a follow-up picks up words from the question or the answer just before it; otherwise it's a new
                    # question that wasn't in the plan
                    prev = next((s for s in reversed(segs) if s["kind"] == "plan"), None)
                    ctx = set()
                    if prev:
                        p = next((a for a in plan if a["area"] == prev["area"]), {})
                        ctx = set(_content(p.get("q"))) | set(_content(" ".join(turns[i]["text"] for i in (cur or prev)["turns"][-4:])))
                    is_fu = bool(prev) and (len(set(_content(t["text"])) & ctx) >= 1
                                            # a short question that points back ("your part in that", "why did you…")
                                            or (len(t["text"].split()) <= 14 and bool(_BACKREF.search(t["text"]))))
                    small = not is_fu and len(t["text"].split()) <= 15 and bool(_SMALL.search(t["text"]))
                    parent = prev["area"] if is_fu else None
                    cur = {"area": parent, "q": t["text"], "kind": "followup" if is_fu else "smalltalk" if small else "other",
                           "turns": [t["i"]], "parent": parent}
                    segs.append(cur)
                elif cur:
                    cur["turns"].append(t["i"])
            else:
                if cur is None:
                    cur = {"area": None, "q": "", "kind": "other", "turns": [], "parent": None}
                    segs.append(cur)
                cur["turns"].append(t["i"])
        return _refit(segs, turns, plan)
    # only the candidate was captured: each sentence goes to the plan question its words fit best, in runs
    cur = None
    for t in turns:
        best, bs = None, 0.0
        for a in plan:
            text = " ".join([a.get("q") or "", " ".join(a.get("good") or []), a.get("competency") or "", a.get("section") or ""])
            s = _overlap(t["text"], text)
            if s > bs:
                best, bs = a, s
        area = best["area"] if best and bs >= 0.12 else (cur["area"] if cur else None)
        if cur and area == cur["area"]:
            cur["turns"].append(t["i"])
        else:
            cur = {"area": area, "q": "", "kind": "plan" if area else "other", "turns": [t["i"]], "parent": None}
            segs.append(cur)
    # one question answered in two runs becomes one segment
    merged = {}
    out = []
    for s in segs:
        if s["area"] and s["area"] in merged:
            merged[s["area"]]["turns"] += s["turns"]
        else:
            out.append(s)
            if s["area"]:
                merged[s["area"]] = s
    return out


def _fit_text(a):
    return " ".join([a.get("q") or "", " ".join(a.get("good") or []), a.get("competency") or "", a.get("section") or ""])


def _refit(segs, turns, plan):
    """A question marked as asked is only a hint. An answer that clearly fits another planned question (the
    interviewer asked it without marking it, or the candidate answered a different one) moves there. "Clearly" means
    it uses words only that other question has (its skill, its terms) and none that only the current one has."""
    texts = {a["area"]: set(_content(_fit_text(a))) for a in plan if a["area"] != "Wrap-up"}
    count = {}
    for ws in texts.values():
        for w in ws:
            count[w] = count.get(w, 0) + 1
    own_words = {area: {w for w in ws if count[w] == 1} for area, ws in texts.items()}
    names = {a["area"]: set(_content((a.get("competency") or "") + " " + (a.get("section") or ""))) & own_words.get(a["area"], set())
             for a in plan if a["area"] in texts}
    by_area = {s["area"]: s for s in segs if s["kind"] == "plan" and s["area"]}
    extra = []
    for s in list(segs):
        if s["kind"] != "plan" or not s["area"] or s["area"] not in texts:
            continue
        keep = []
        for i in s["turns"]:
            t = turns[i]
            if t["who"] != "candidate" or len(t["text"].split()) < 6:
                keep.append(i)
                continue
            words = set(_content(t["text"]))
            mine = len(words & own_words[s["area"]])
            best, bs, named = None, 0, False
            for area, ow in own_words.items():
                if area != s["area"]:
                    v = len(words & ow)
                    if v > bs:
                        best, bs, named = area, v, bool(words & names[area])
            # it names the other question's skill, or uses many words only that question has
            if best and ((named and bs >= 1) or bs >= 4) and mine == 0 and len(words & texts[best]) >= len(words & texts[s["area"]]):
                tgt = by_area.get(best)
                if not tgt:
                    tgt = {"area": best, "q": "", "kind": "plan", "turns": [], "parent": None, "unmarked": True}
                    by_area[best] = tgt
                    extra.append(tgt)
                tgt["turns"].append(i)
            else:
                keep.append(i)
        s["turns"] = keep
    for x in extra:
        x["turns"].sort()
    return segs + extra


# ---------------------------------------------------------------------------------------------------- Claude
def _segment_claude(turns, plan, company_id=None):
    lines = [f"{t['i']} [{t['who']}] {t['text'][:500]}" for t in turns]
    data = ask_json("map a live interview transcript to its questions", f"""Below is the full transcript of a live job interview, one numbered turn per line,
and the interviewer's question plan. The interviewer may have asked plan questions in any order, in their own words,
or not at all, and asked other questions too. If only the candidate's turns are present, infer the questions from
what the candidate talks about.

Plan: {json.dumps([{'area': a['area'], 'q': a.get('q'), 'good': a.get('good') or []} for a in plan])}

Transcript:
{chr(10).join(lines)}

Lines marked [interviewer] that repeat a plan question word for word are the interviewer marking that question as
asked: treat them as strong hints of where that question starts. Greetings, "can you hear me", scheduling and other
small talk are their own segments of kind "smalltalk".
Split the transcript into segments, in order. Each segment is one question and its answer. Return JSON:
{{"segments": [{{"area": the plan area it answers, or null if none,
  "kind": "plan" (a plan question) | "followup" (a follow-up on the previous plan question) | "other" (a question not in the plan) | "smalltalk",
  "q": the question as the interviewer asked it (or a short description if not captured),
  "turns": [turn numbers in this segment],
  "coverage": for plan segments, one of "full" | "partial" | "none" per good point of that area,
  "score": 1-5 for the answer, or null if there was no real answer}}]}}
Every turn number belongs to exactly one segment. Don't invent turns.""", lambda: None, company_id, max_tokens=4000, timeout=60)
    if not isinstance(data, dict) or not isinstance(data.get("segments"), list):
        return None
    names = {a["area"] for a in plan}
    seen, out = set(), []
    for s in data["segments"]:
        if not isinstance(s, dict):
            continue
        ids = []
        for i in s.get("turns") or []:
            try:
                i = int(i)
            except (TypeError, ValueError):
                continue
            if 0 <= i < len(turns) and i not in seen:
                ids.append(i)
                seen.add(i)
        if not ids:
            continue
        area = s.get("area") if s.get("area") in names else None
        kind = s.get("kind") if s.get("kind") in ("plan", "followup", "other", "smalltalk") else ("plan" if area else "other")
        out.append({"area": area, "q": str(s.get("q") or "")[:400], "kind": kind if area or kind in ("other", "smalltalk") else "other",
                    "turns": sorted(ids), "coverage": s.get("coverage") if isinstance(s.get("coverage"), list) else None,
                    "score": s.get("score") if isinstance(s.get("score"), (int, float)) else None, "parent": None})
    missing = [t["i"] for t in turns if t["i"] not in seen]
    if missing:  # Claude skipped some turns: give them to the segment just before them
        for i in missing:
            prev = max((s for s in out if s["turns"] and s["turns"][0] <= i), key=lambda s: s["turns"][0], default=None)
            (prev or out[0] if out else {"turns": []})["turns"].append(i)
        for s in out:
            s["turns"] = sorted(set(s["turns"]))
    return out


# ---------------------------------------------------------------------------------------------------- the review
_BACKREF = re.compile(r"(?i)\b(that|this|it|there|those|them|you mentioned|you said|your (own )?part)\b")
_SMALL = re.compile(r"(?i)\b(hello|hi|hey|good (morning|afternoon|evening)|can you hear|hear me|audio|mute|unmute|"
                    r"camera|screen|connection|thank you|thanks|bye|see you|nice to meet)\b")


def entry_map(log_):
    """The summary rows the scorecard shows: one per question, follow-up or extra question (small talk left out)."""
    return [{"area": e["area"], "q": e.get("q"), "type": e.get("type") or "main", "at": e.get("at") or 0,
             "sentences": len(e.get("sentences") or []), "quotes": list(e.get("sentences") or []),
             "covered": (e.get("coverage") or []).count("full"), "points": len(e.get("good") or []),
             "good": e.get("good") or [], "coverage": e.get("coverage") or [],
             "score": e.get("rating") or e.get("score"), "index": k}
            for k, e in enumerate(log_) if e.get("type") != "smalltalk"]


def rescore(e):
    """Coverage and score of one entry again from its sentences (after a quote was moved)."""
    answer = " ".join(e.get("sentences") or [])
    e["coverage"] = coverage(e.get("good") or [], answer)
    e["score"] = e["score_ai"] = score_from(e["coverage"], answer)
    e["coverage_ai"] = e["coverage"]
    return e


def review(att, company_id=None, use_ai=True):
    """Re-files the interview under its questions. Returns the summary saved as result.review.

    What the interviewer decided during the interview stands: a question they marked as asked (or Isha heard), and an
    answer they moved to a question, keep their answers. Everything else (answers that were only "assumed" under the
    next question, or never filed) is re-filed from the transcript."""
    turns = transcript(att)
    plan = _plan(att)
    res = dict(att.result or {})
    live = res.get("areas_log_live") if res.get("areas_log_live") is not None else (res.get("areas_log") or [])
    if not turns:
        out = {"at": datetime.utcnow().isoformat() + "Z", "source": "none", "turns": 0, "asked": 0, "of": len(plan),
               "not_asked": [a["area"] for a in plan if a["area"] != "Wrap-up"], "extra": 0, "kept": 0, "refiled": 0}
        res["review"] = out
        att.result = res
        return out
    # Decided with the user: nothing is filed during the interview. "Mark as asked" clicks are only hints (they're in
    # the transcript as the interviewer asking that question), so everything is re-filed from the whole transcript.
    kept = []
    kept_sents = {x for e in kept for x in (e.get("sentences") or [])}
    kept_iv = {((x.get("t") or x.get("text")) if isinstance(x, dict) else x) for e in kept for x in [e.get("q")] + list(e.get("said") or []) if x}
    rest = [t for t in turns if not ((t["who"] == "candidate" and t["text"] in kept_sents) or (t["who"] == "interviewer" and t["text"] in kept_iv))]
    rest = [dict(t, i=k) for k, t in enumerate(rest)]
    taken = {e["area"] for e in kept if e.get("type") in (None, "main") and e.get("followup_of") is None}
    plan_rest = [a for a in plan if a["area"] not in taken]
    by_area = {a["area"]: a for a in plan}
    segs, source = [], "keywords"
    if any(t["who"] == "candidate" for t in rest):
        if use_ai:
            got = _segment_claude(rest, plan_rest, company_id)
            if got:
                segs, source = got, "claude"
        if not segs:
            segs = _segment_keywords(rest, plan_rest)
    elif kept:
        source = "live"
    started = {s["area"]: s for s in segs if s["kind"] == "plan" and s.get("area")}
    for s in list(segs):
        # a stretch with no question: an answer that fits a planned topic goes there; greetings and short chat are
        # small talk; anything else stays as "Not in the plan" so no answer is ever lost
        if s["kind"] == "other" and not s.get("q"):
            txt = " ".join(rest[i]["text"] for i in s["turns"])
            best, bs = None, 0.0
            for a in plan_rest:
                if a["area"] != "Wrap-up":
                    v = _overlap(txt, _fit_text(a))
                    if v > bs:
                        best, bs = a, v
            intro = next((a for a in plan_rest if a.get("type") == "intro" and a["area"] not in started), None)
            skills = set(_content(" ".join((a.get("competency") or "") + " " + (a.get("section") or "") for a in plan)))
            if bs < 0.12 and intro and s is segs[0] and not _SMALL.search(txt):
                best, bs = intro, 1.0   # the candidate's opening words, before any question: the introduction
            if (_SMALL.search(txt) and bs < 0.12) or len(txt.split()) < 6:
                s["kind"] = "smalltalk"
            elif best and bs >= 0.12:
                if best["area"] in started:
                    started[best["area"]]["turns"] = sorted(started[best["area"]]["turns"] + s["turns"])
                    segs.remove(s)
                else:
                    s.update(area=best["area"], kind="plan")
                    started[best["area"]] = s
            elif len(txt.split()) < 25 and not (set(_content(txt)) & skills):
                s["kind"] = "smalltalk"
    new = []
    for s in segs:
        cand = [rest[i] for i in s["turns"] if rest[i]["who"] == "candidate"]
        ivs = [rest[i] for i in s["turns"] if rest[i]["who"] == "interviewer"]
        after, n_ = {}, 0
        for i in s["turns"]:  # where each interviewer remark falls among the answer's sentences (as during the interview)
            if rest[i]["who"] == "candidate":
                n_ += 1
            else:
                after[id(rest[i])] = n_
        if not cand and not ivs:
            continue
        answer = " ".join(t["text"] for t in cand)
        p = by_area.get(s["area"]) or {}
        if s["kind"] == "smalltalk":
            new.append({"area": "Small talk", "q": "Small talk", "type": "smalltalk", "good": [], "sentences": [t["text"] for t in cand],
                        "said": [{"t": t["text"], "after": after.get(id(t), 0), "at": t["at"]} for t in ivs], "tags": [], "score": None, "coverage": [],
                        "at": rest[s["turns"][0]]["at"] if s["turns"] else 0, "reviewed": True})
            continue
        if s["kind"] == "plan" and p:
            good, q, typ = p.get("good") or [], p.get("q"), "main"
        else:
            q = s.get("q") or (ivs[0]["text"] if ivs else "") or "Not in the plan"
            from services.ai import expected_points
            good = expected_points(q, s.get("area")) if s.get("q") or ivs else []   # what a good answer to that question covers
            typ = "Follow-up" if s["kind"] == "followup" else "own"
        cov = s.get("coverage") if s.get("coverage") and len(s["coverage"]) == len(good) else coverage(good, answer)
        cov = [c if c in ("full", "partial", "none") else "none" for c in cov]
        sc = s.get("score") if s.get("score") is not None else score_from(cov, answer)
        area = s["area"] or "Not in the plan"
        asked_as = ivs[0]["text"] if ivs else None
        said = [{"t": t["text"], "after": after.get(id(t), 0), "at": t["at"]} for t in (ivs if typ == "main" else ivs[1:]) if t["text"] != asked_as]
        new.append({"area": area, "q": q, "type": typ, "good": good, "sentences": [t["text"] for t in cand], "tags": [],
                    "score": sc, "score_ai": sc, "coverage": cov, "coverage_ai": cov,
                    "at": rest[s["turns"][0]]["at"] if s["turns"] else 0, "reviewed": True, "asked_as": asked_as, "said": said})
    ratings = {}
    for e in live:  # a rating given during the interview carries over to that question after the review
        if e.get("rating") and e.get("type") in (None, "main") and e.get("followup_of") is None:
            ratings.setdefault(e.get("area"), e["rating"])
    log_ = sorted(kept + new, key=lambda e: (e.get("at") or 0))
    main_at = {}
    for k, e in enumerate(log_):
        if e.get("type") in (None, "main") and e.get("followup_of") is None and e["area"] in by_area:
            main_at.setdefault(e["area"], k)
            if e.get("reviewed") and e["area"] in ratings and "rating" not in e:
                e["rating"] = ratings.pop(e["area"])
        elif e.get("type") not in (None, "main", "own", "smalltalk"):
            parent = max((i for a_, i in main_at.items() if a_ == e["area"]), default=None)
            e["followup_of"] = parent
    asked = [a["area"] for a in plan if a["area"] in main_at]
    out = {"at": datetime.utcnow().isoformat() + "Z", "source": source, "turns": len(turns), "asked": len(asked), "of": len(plan),
           "not_asked": [a["area"] for a in plan if a["area"] not in main_at and a["area"] != "Wrap-up"],
           "voices_separated": any(t["who"] == "interviewer" and t["text"] not in {a.get("q") for a in plan} for t in turns),
           "smalltalk": len([e for e in log_ if e.get("type") == "smalltalk"]),
           "extra": len([e for e in log_ if e.get("type") == "own" and e.get("reviewed")]),
           "followups": len([e for e in log_ if e.get("type") not in (None, "main", "own", "smalltalk")]),
           "kept": len(kept), "refiled": len(new),
           "map": entry_map(log_)}
    if res.get("areas_log_live") is None:
        res["areas_log_live"] = res.get("areas_log") or []
    res["areas_log"] = log_
    res["current"] = None
    res["review"] = out
    att.result = res
    return out


def live_topics(att):
    """During the interview: which planned topics have come up so far, from the WHOLE transcript (nothing is filed).
    Each topic: state none | touched | well, the points heard so far, and whether the interviewer marked it as asked.
    The topic being discussed now is the one the last few candidate sentences fit best."""
    turns = transcript(att)
    plan = [a for a in _plan(att) if a.get("area") != "Wrap-up"]
    cand = [t for t in turns if t["who"] == "candidate"]
    ivs = [t for t in turns if t["who"] == "interviewer"]
    all_text = " ".join(t["text"] for t in cand)
    recent = " ".join(t["text"] for t in cand[-3:])
    out, now, best = [], None, 0.0
    # words only one topic has (its skill, its terms): words every question shares ("explain", "example") don't
    # make a topic count as touched
    texts = {a["area"]: set(_content(_fit_text(a))) for a in plan}
    count = {}
    for ws in texts.values():
        for w in ws:
            count[w] = count.get(w, 0) + 1
    heard = set(_content(all_text))
    for a in plan:
        good = a.get("good") or []
        own = {w for w in texts[a["area"]] if count[w] == 1}
        mine = bool(heard & own) or not own
        comp = a.get("competency") or ""
        if comp and a["area"].split(" · ")[0].strip().lower() == comp.lower():
            mine = bool(heard & set(_content(comp)))   # a skill's topic needs the skill to come up (SQL, AWS…)
        # a point is judged on its own words, without the template words most questions share ("explanation",
        # "example", "wrong choice"), so "A correct, plain explanation of SQL" needs SQL to be heard
        common = {w for w, k in count.items() if k >= 3}
        own_good = [" ".join(w for w in _content(g) if w not in common) or g for g in good]
        cov = coverage(own_good, all_text) if all_text and mine else ["none"] * len(good)
        asked = any(t["text"] == a.get("q") or max(_overlap(t["text"], a.get("q")), _overlap(t["text"], a.get("simple"))) >= 0.35 for t in ivs)
        full = cov.count("full")
        part = cov.count("partial")
        if good and full >= max(1, round(0.6 * len(good))):
            state = "well"
        elif asked or full or part:
            state = "touched"
        else:
            state = "none"
        fit = (_overlap(recent, " ".join([a.get("q") or "", " ".join(good)])) + 0.2 * len(set(_content(recent)) & own)) if recent and mine else 0
        if fit > best:
            best, now = fit, a["area"]
        out.append({"area": a["area"], "state": state, "asked": asked, "coverage": cov, "good": good,
                    "missing": [g for g, c in zip(good, cov) if c != "full"]})
    return {"topics": out, "now": now if best >= 0.12 else None, "turns": len(turns),
            "heard": len(cand), "voices": bool(ivs)}
