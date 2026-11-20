"""V02.01.02: a scorecard needs a decision for every selected question with no answer. Older tests skip them all
(and don't show them on the report), which is what happened before."""


def skip_unanswered(c, att, headers):
    r = c.get(f"/api/isha/{att}", headers=headers).get_json() or {}
    st = (r.get("data") or {}).get("state") or {}
    return {"question_decisions": [{"area": u["area"], "skip": True} for u in st.get("unanswered") or []]}
