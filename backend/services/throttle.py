"""Limits repeated failures (sign-in, invite links, password checks) per email and per IP address.

Counts live in the database (login_throttles), so every gunicorn worker sees the same numbers. Rules:
- per email/account: 5 failures within 15 minutes lock it for 15 minutes;
- per IP address: 30 failures within 15 minutes lock that address for 15 minutes.
A successful sign-in clears the email counter. Locked attempts answer 429 with the minutes left, and the message is the
same whether or not the account exists, so the lock can't be used to discover accounts.
"""
from datetime import datetime, timedelta

from flask import current_app, request

from extensions import db
from models import LoginThrottle

WINDOW = timedelta(minutes=15)
RULES = {"email": (5, timedelta(minutes=15)), "ip": (30, timedelta(minutes=15)), "pw": (5, timedelta(minutes=15)),
         "invite": (20, timedelta(minutes=15)), "signup": (10, timedelta(minutes=30))}


def client_ip():
    """The address our own proxy (nginx) saw: the LAST X-Forwarded-For entry, which the client can't forge (values a
    client sends itself come first). Without a proxy (C2H_TRUST_PROXY=0) the socket address is used."""
    fwd = request.headers.get("X-Forwarded-For", "")
    ip = fwd.split(",")[-1].strip() if fwd and current_app.config.get("TRUST_PROXY", True) else ""
    return (ip or request.remote_addr or "unknown")[:64]


def _row(key):
    return LoginThrottle.query.filter_by(key=key[:190]).first()


def locked(*keys):
    """Minutes left on the longest active lock among keys, or 0."""
    now = datetime.utcnow()
    left = 0
    for k in keys:
        r = _row(k)
        if r and r.locked_until and r.locked_until > now:
            left = max(left, int((r.locked_until - now).total_seconds() // 60) + 1)
    return left


def fail(key):
    """Counts one failure; locks the key when its rule's limit is reached. Commits."""
    kind = key.split(":", 1)[0]
    limit, base = RULES.get(kind, RULES["ip"])
    now = datetime.utcnow()
    r = _row(key)
    if not r:
        r = LoginThrottle(key=key[:190], failures=0, window_start=now)
        db.session.add(r)
    if not r.window_start or now - r.window_start > WINDOW:
        if not (r.locked_until and r.locked_until > now):
            r.failures, r.window_start = 0, now
    r.failures = (r.failures or 0) + 1
    if r.failures >= limit:
        r.locked_until = now + base
        r.failures, r.window_start = 0, now
    db.session.commit()


def clear(key):
    r = _row(key)
    if r:
        db.session.delete(r)
        db.session.commit()


def message(minutes):
    return (f"Too many tries. For your security, please wait {minutes} minute{'s' if minutes != 1 else ''} and try again."
            if minutes else "")
