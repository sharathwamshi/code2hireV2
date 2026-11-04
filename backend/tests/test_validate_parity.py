"""The browser (frontend/src/lib/validate.js) and the server (services/validate.py) must accept and refuse exactly the
same values, so a form never says "fine" and then gets a 400. Skipped when Node isn't installed."""
import json
import os
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services import validate as V  # noqa: E402

FRONT = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src", "lib", "validate.js")
EMAILS = ["a@b.co", "srustipatil41@l.com", "sonu@123", "harish@1234", "sakshi@com", "cypress,playright", "a b@c.com", "x@y.c",
          "Name@Company.COM", "a@-b.com", "first.last+tag@sub.example.co.in", "", "@x.com", "x@.com", "x@x..com"]
PHONES = ["+918867BHBHSBHB", "9845000000", "+91 98450 00000", "098450-00000", "12345", "+1 (415) 555-0100", "91+9845000000", "",
          "+0123456789", "+9198450000001234", "00919845000000"]
NAMES = ["Srusti Gowda", "J. R. R. Tolkien", "O'Brien", "Mary-Jane", "A", "123", "Asha2", "रमेश कुमार", "ಶರತ್ ಎನ್", "José Álvarez",
         "a--  --b", ".Asha", "Nair, Vikas", "Rao,", "A,,B", "Dr. A. Rao", "  x  "]
PASSWORDS = [("short1", ""), ("onlyletters", ""), ("12345678", ""), ("Password123", ""), ("Green7Valley", ""), ("pwtest2026x", "pwtest@m.co")]


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js not installed")
def test_browser_and_server_rules_match():
    script = f"""
import(process.argv[1]).then((v) => {{
  const data = {json.dumps({"e": EMAILS, "p": PHONES, "n": NAMES, "w": PASSWORDS})};
  console.log(JSON.stringify({{
    e: data.e.map((x) => !v.emailError(x, false)),
    p: data.p.map((x) => {{ const r = v.normalisePhone(x); return [!r.error, r.value]; }}),
    n: data.n.map((x) => !v.nameError(x)),
    w: data.w.map(([pw, em]) => !v.passwordError(pw, em)),
  }}));
}});"""
    out = subprocess.run(["node", "--input-type=module", "-e", script, os.path.abspath(FRONT)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    js = json.loads(out.stdout)
    py_e = [V.email(x, required=False)[1] is None for x in EMAILS]
    py_p = [[V.phone(x)[1] is None, V.phone(x)[0] if V.phone(x)[1] is None else None] for x in PHONES]
    py_n = [V.person_name(x)[1] is None for x in NAMES]
    py_w = [V.password(pw, em) is None for pw, em in PASSWORDS]
    assert js["e"] == py_e, list(zip(EMAILS, js["e"], py_e))
    assert [[a, b if a else None] for a, b in js["p"]] == py_p, list(zip(PHONES, js["p"], py_p))
    assert js["n"] == py_n, [(n, a, b) for n, a, b in zip(NAMES, js["n"], py_n) if a != b]
    assert js["w"] == py_w
