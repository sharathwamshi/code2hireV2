"""V02.00.12 data fixes (migration 010 / Alembic 0011). No schema change. Safe to run more than once.

1. Freeze old MCQ attempts: an attempt started before V02.00.11 may have no question snapshot, so it would read
   the live question. Each such attempt gets a snapshot of the questions as they are now, before step 2 changes them.
2. Rebalance the question bank (A2): the starter bank and Hira's questions put the right answer at option B far too
   often. Each question's options are reordered so the right answers spread evenly over A-D. The answer index moves
   with them, the version goes up and a version row "Options reordered (V02.00.12)" is saved. Questions with an
   "All of the above"-type option are left as they are, since their order carries meaning.
3. Who sent each invite (B5 / F3): round_attempts.result.invited_by, filled from the audit log ("round.invite").

Uses plain SQL through one connection, so it runs the same from Alembic, from the command line and on SQLite:
    python -m services.data_v12            (uses DATABASE_URL, like the app)
"""
import json
import re
from datetime import datetime

from sqlalchemy import text

NOTE = "Options reordered (V02.00.12)"
_FIXED = re.compile(r"\b(all|none|both|neither)\b.*\b(above|of these|a and b|b and c)\b", re.I)
CONTENT = ("text", "code", "options", "answer", "explanation", "skill", "level", "tags", "time_seconds")


def _j(v, default=None):
    if v is None:
        return default
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return default


def _dump(v):
    return json.dumps(v)


def _snap(row):
    d = {k: row[k] for k in CONTENT}
    for k in ("options", "tags"):
        d[k] = _j(d[k], [])
    d["version"] = row["version"] or 1
    return d


def freeze_old_attempts(conn):
    qrows = {r["id"]: r for r in conn.execute(text(f"SELECT id, version, {', '.join(CONTENT)} FROM questions")).mappings()}
    n = 0
    for a in conn.execute(text("SELECT id, result FROM round_attempts WHERE round_type = 'mcq'")).mappings().all():
        res = _j(a["result"], {}) or {}
        ids = res.get("question_ids") or []
        if not ids:
            continue
        snap = dict(res.get("qsnap") or {})
        missing = [i for i in ids if str(i) not in snap and i in qrows]
        if not missing:
            continue
        for i in missing:
            snap[str(i)] = _snap(qrows[i])
        res["qsnap"] = snap
        conn.execute(text("UPDATE round_attempts SET result = :r WHERE id = :i"), {"r": _dump(res), "i": a["id"]})
        n += 1
    return n


def rebalance_bank(conn):
    done = {r[0] for r in conn.execute(text("SELECT DISTINCT question_id FROM question_versions WHERE note = :n"), {"n": NOTE})}
    rows = conn.execute(text(f"SELECT id, version, {', '.join(CONTENT)} FROM questions ORDER BY id")).mappings().all()
    n, slot = 0, 0
    now = datetime.utcnow()
    for r in rows:
        if r["id"] in done:
            continue
        opts = _j(r["options"], []) or []
        try:
            ans = int(r["answer"])
        except (TypeError, ValueError):
            continue
        if len(opts) < 2 or not 0 <= ans < len(opts) or any(_FIXED.search(str(o)) for o in opts):
            continue
        k = slot % len(opts)  # A, B, C, D, A, B, ... over the whole bank
        slot += 1
        new = list(opts)
        new.insert(k, new.pop(ans))
        ver = (r["version"] or 1) + 1
        conn.execute(text("UPDATE questions SET options = :o, answer = :a, version = :v WHERE id = :i"),
                     {"o": _dump(new), "a": k, "v": ver, "i": r["id"]})
        snap = {**_snap(r), "options": new, "answer": k}
        snap.pop("version", None)
        conn.execute(text("INSERT INTO question_versions (created_at, question_id, version, snapshot, note) VALUES (:c, :q, :v, :s, :n)"),
                     {"c": now, "q": r["id"], "v": ver, "s": _dump(snap), "n": NOTE})
        n += 1
    return n


def backfill_invited_by(conn):
    logs = {}
    for l in conn.execute(text("SELECT target_id, actor_id, detail, created_at FROM audit_logs "
                               "WHERE action = 'round.invite' AND target_type = 'application' AND actor_id IS NOT NULL "
                               "ORDER BY created_at")).mappings():
        d = _j(l["detail"], {}) or {}
        logs.setdefault((l["target_id"], d.get("round")), []).append((l["created_at"], l["actor_id"]))
    n = 0
    for a in conn.execute(text("SELECT id, application_id, round_index, created_at, result FROM round_attempts "
                               "WHERE application_id IS NOT NULL")).mappings().all():
        res = _j(a["result"], {}) or {}
        if res.get("invited_by"):
            continue
        cands = logs.get((a["application_id"], a["round_index"])) or []
        created = a["created_at"]
        if isinstance(created, str):
            created = datetime.fromisoformat(created)
        best = None
        for at, actor in cands:  # the invite logged closest to when the attempt was made
            at = datetime.fromisoformat(at) if isinstance(at, str) else at
            gap = abs((at - created).total_seconds()) if at and created else 1e9
            if gap <= 120 and (best is None or gap < best[0]):
                best = (gap, actor)
        if best:
            res["invited_by"] = best[1]
            conn.execute(text("UPDATE round_attempts SET result = :r WHERE id = :i"), {"r": _dump(res), "i": a["id"]})
            n += 1
    return n


def run(conn):
    out = {"attempts_frozen": freeze_old_attempts(conn)}
    out["questions_reordered"] = rebalance_bank(conn)
    out["invites_backfilled"] = backfill_invited_by(conn)
    return out


if __name__ == "__main__":
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from sqlalchemy import create_engine
    from config import Config
    eng = create_engine(Config.SQLALCHEMY_DATABASE_URI)
    with eng.begin() as c:
        print(run(c))
