"""Tests: pass the V02.00.05 system check for an attempt, the way the browser does when every step works."""


def system_check(c, att, headers, role="candidate", mode="full"):
    req = c.get(f"/api/syscheck/requirements?attempt={att}&role={role}&mode={mode}", headers=headers).get_json()["data"]
    steps = {s["key"]: {"status": "pass", "detail": "test"} for s in req["steps"]}
    r = c.post("/api/syscheck", headers=headers, json={"attempt_id": att, "role": role, "mode": mode, "steps": steps,
                                                        "instructions_read": True, "device": {"camera": "Test camera"}})
    assert r.status_code == 200 and r.get_json()["data"]["passed"], r.get_json()
    return r.get_json()["data"]
