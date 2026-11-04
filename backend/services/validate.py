"""One set of input rules for the whole API. The web app mirrors them in src/lib/validate.js, so a field shows the
same message in the browser that the server would return.

Every check returns (clean_value, error_message_or_None). `Checker` collects field errors and turns them into one
400 response: {"error": "<first message>", "fields": {"email": "...", ...}}.
"""
import re
import unicodedata
from datetime import datetime, timezone

from flask import jsonify

# name@domain.tld: no spaces, one @, domain made of labels, a letters-only TLD of 2+ characters.
EMAIL_RE = re.compile(r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*@"
                      r"([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}$")
DEFAULT_COUNTRY = "91"

MSG = {
    "email": "Enter a valid email address, like name@company.com.",
    "phone": "Enter a valid phone number with country code: digits only, 10 to 15 in all.",
    "name": "Enter a name using letters only (2 to 80 characters).",
    "required": "This is required.",
}


def email(v, required=True):
    v = (v or "").strip().lower()
    if not v:
        return "", MSG["required"] if required else None
    if len(v) > 254 or not EMAIL_RE.match(v):
        return v, MSG["email"]
    return v, None


def phone(v, required=False, default_country=DEFAULT_COUNTRY):
    """Accepts +91 98450 00000, 098450-00000, (984) 500 0000 ... Returns E.164: +919845000000."""
    raw = (v or "").strip()
    if not raw:
        return None, MSG["required"] if required else None
    if re.search(r"[^\d+\s\-().]", raw) or raw.count("+") > 1 or ("+" in raw and not raw.startswith("+")):
        return raw, MSG["phone"]
    digits = re.sub(r"\D", "", raw)
    if not raw.startswith("+"):
        digits = digits.lstrip("0")
        if len(digits) == 10:
            digits = default_country + digits
    if not 10 <= len(digits) <= 15 or digits.startswith("0"):
        return raw, MSG["phone"]
    return "+" + digits, None


def _is_name(v):
    """Letters (any script, with their vowel signs and accents) plus space . , ' - between them ("Nair, Vikas");
    starts with a letter."""
    if not unicodedata.category(v[0]).startswith("L"):
        return False
    letters = 0
    for ch in v:
        cat = unicodedata.category(ch)
        if cat.startswith("L"):
            letters += 1
        elif not (cat.startswith("M") or ch in " .,'-’"):
            return False
    # no runs of punctuation ("a--b", "A,,B"), no trailing comma
    return letters >= 2 and not re.search(r"[.,'\-’]{2,}|[ .,'\-’]{3,}", v) and not v.endswith(",")


def person_name(v, required=True):
    v = re.sub(r"\s+", " ", (v or "").strip())
    if not v:
        return "", MSG["required"] if required else None
    if not 2 <= len(v) <= 80 or not _is_name(v):
        return v, MSG["name"]
    return v, None


COMMON_PASSWORDS = {"password", "password1", "password123", "12345678", "123456789", "qwerty123", "iloveyou1", "admin123",
                    "welcome1", "welcome123", "letmein1", "abc12345", "passw0rd", "code2hire", "code2hire1", "india123"}


def password(pw, email_addr=""):
    """At least 8 characters with a letter and a number; not the email name; not a very common password."""
    pw = pw or ""
    if len(pw) < 8:
        return "Use at least 8 characters."
    if len(pw) > 128:
        return "Use at most 128 characters."
    if not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        return "Use letters and at least one number."
    local = (email_addr or "").split("@")[0].lower()
    if (local and len(local) >= 3 and local in pw.lower()) or pw.lower() in COMMON_PASSWORDS:
        return "Pick something harder to guess."
    return None


def text(v, max_len=200, required=False, label="This"):
    v = re.sub(r"[ \t]+", " ", (v or "").strip())
    if not v:
        return None, MSG["required"] if required else None
    if len(v) > max_len:
        return v, f"{label} can be at most {max_len} characters."
    return v, None


def integer(v, lo=None, hi=None, required=False, label="This"):
    if v in (None, ""):
        return None, MSG["required"] if required else None
    try:
        if isinstance(v, bool):
            raise ValueError
        f = float(v)
        if f != int(f):
            raise ValueError
        n = int(f)
    except (TypeError, ValueError):
        return v, f"{label} must be a whole number."
    if lo is not None and n < lo:
        return n, f"{label} must be {lo} or more."
    if hi is not None and n > hi:
        return n, f"{label} must be {hi} or less."
    return n, None


def skills(v, max_items=20):
    """List or comma/semicolon string -> unique, trimmed list (case-insensitive), at most max_items."""
    items = v if isinstance(v, list) else re.split(r"[;,|]", v or "")
    out, seen = [], set()
    for s in items:
        s = re.sub(r"\s+", " ", str(s or "").strip())[:60]
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    if len(out) > max_items:
        return out[:max_items], f"Add at most {max_items} skills."
    return out, None


def when(v, required=False):
    """ISO datetime with a timezone (Z or +05:30) -> naive UTC datetime. A value without a timezone is refused,
    because the server can't know which local time it meant (this caused the 5 h 30 m interview lock-out)."""
    if not v:
        return None, MSG["required"] if required else None
    s = str(v).strip()
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None, "Enter a valid date and time."
    if d.tzinfo is None:
        return None, "The time must include a timezone."
    return d.astimezone(timezone.utc).replace(tzinfo=None), None


class Checker:
    """Collects errors per field. Usage:
        c = Checker(); e = c.add("email", *email(d.get("email"))); ... ; if c: return c.response()
    """

    def __init__(self):
        self.fields = {}

    def add(self, field, value, error):
        if error and field not in self.fields:
            self.fields[field] = error
        return value

    def __bool__(self):
        return bool(self.fields)

    def response(self, code=400):
        """One readable sentence for toasts, plus every field's own message for the form."""
        if len(self.fields) > 1:
            msg = "Please check the highlighted fields."
        else:
            field, msg = next(iter(self.fields.items()))
            if msg == MSG["required"]:
                msg = f"{field.replace('_', ' ').capitalize()} is required."
        return jsonify({"error": msg, "fields": self.fields}), code


def iso(d):
    """Naive UTC datetime -> ISO string marked as UTC, or None."""
    return d.isoformat() + "Z" if d else None
