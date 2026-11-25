"""V02.01.02: a scorecard needs a decision for every selected question with no answer. Older tests skip them all
(and don't show them on the report), which is what happened before."""


def skip_unanswered(c, att, headers):
    r = c.get(f"/api/isha/{att}", headers=headers).get_json() or {}
    st = (r.get("data") or {}).get("state") or {}
    # V02.01.06: a reason, in case the test's recommendation differs from Isha's (ignored when it doesn't)
    return {"question_decisions": [{"area": u["area"], "skip": True} for u in st.get("unanswered") or []], "rec_reason": "My own judgement"}
