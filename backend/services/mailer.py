"""Email through the platform's SMTP server (V02.00.10).

The superadmin enters the SMTP details under Platform settings -> Integrations -> Email (SMTP). Used for password
reset links (CP-010). In tests (app.config TESTING) mail is kept in OUTBOX instead of being sent.
"""
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from flask import current_app

from services.settings import platform_secret

OUTBOX = []  # tests read sent mail here
KEYS = ("smtp_host", "smtp_port", "smtp_security", "smtp_username", "smtp_password", "smtp_from_email", "smtp_from_name", "smtp_reply_to")


class MailError(Exception):
    pass


def config():
    c = {k: platform_secret(k) for k in KEYS}
    try:
        c["smtp_port"] = int(c.get("smtp_port") or 0) or (465 if c.get("smtp_security") == "ssl" else 587)
    except ValueError:
        c["smtp_port"] = 587
    c["smtp_security"] = (c.get("smtp_security") or "starttls").lower()
    c["smtp_from_name"] = c.get("smtp_from_name") or "Code2Hire"
    return c


def configured():
    c = config()
    return bool(c.get("smtp_host") and c.get("smtp_from_email"))


def _explain(e):
    msg = str(e)
    if isinstance(e, smtplib.SMTPAuthenticationError):
        return "The SMTP server refused the username or password."
    if isinstance(e, (smtplib.SMTPConnectError, ConnectionRefusedError)):
        return "Couldn't connect to the SMTP server. Check the host and port."
    if isinstance(e, TimeoutError) or "timed out" in msg:
        return "The SMTP server didn't answer in time. Check the host, port and security setting."
    if isinstance(e, ssl.SSLError):
        return "The secure connection failed. Try STARTTLS on port 587 or SSL on port 465."
    if isinstance(e, smtplib.SMTPRecipientsRefused):
        return "The SMTP server refused the recipient address."
    if isinstance(e, smtplib.SMTPSenderRefused):
        return "The SMTP server refused the From address. Use an address your SMTP account may send from."
    return "Sending failed: " + msg[:200]


def send(to, subject, text, html=None, cfg=None):
    """Send one email. Raises MailError with a plain sentence when it can't."""
    c = cfg or config()
    if not (c.get("smtp_host") and c.get("smtp_from_email")):
        raise MailError("Email isn't set up yet. The superadmin adds the SMTP details under Platform settings.")
    m = EmailMessage()
    m["Subject"] = subject
    m["From"] = formataddr((c["smtp_from_name"], c["smtp_from_email"]))
    m["To"] = to
    if c.get("smtp_reply_to"):
        m["Reply-To"] = c["smtp_reply_to"]
    m["Message-ID"] = make_msgid(domain=c["smtp_from_email"].split("@")[-1])
    m.set_content(text)
    if html:
        m.add_alternative(html, subtype="html")
    if current_app.config.get("TESTING"):
        OUTBOX.append({"to": to, "subject": subject, "text": text, "html": html})
        return True
    try:
        if c["smtp_security"] == "ssl":
            s = smtplib.SMTP_SSL(c["smtp_host"], c["smtp_port"], timeout=20, context=ssl.create_default_context())
        else:
            s = smtplib.SMTP(c["smtp_host"], c["smtp_port"], timeout=20)
            if c["smtp_security"] == "starttls":
                s.starttls(context=ssl.create_default_context())
        with s:
            if c.get("smtp_username"):
                s.login(c["smtp_username"], c.get("smtp_password") or "")
            s.send_message(m)
    except MailError:
        raise
    except Exception as e:  # noqa: BLE001 - every failure becomes one plain sentence
        raise MailError(_explain(e)) from e
    return True


def layout(title, lines, button=None, url=None, foot=None):
    """A plain, readable HTML email that also works without images."""
    body = "".join(f"<p style='margin:0 0 14px'>{l}</p>" for l in lines)
    btn = (f"<p style='margin:22px 0'><a href='{url}' style='background:#5B3FFF;color:#fff;padding:12px 20px;border-radius:8px;"
           f"text-decoration:none;font-weight:600;display:inline-block'>{button}</a></p>"
           f"<p style='font-size:13px;color:#5B6478'>If the button doesn't work, copy this link into your browser:<br>{url}</p>") if button else ""
    return (f"<div style='font-family:Segoe UI,Arial,sans-serif;max-width:560px;margin:auto;color:#14213D;font-size:15px;line-height:1.5'>"
            f"<div style='font-size:20px;font-weight:800;margin:8px 0 18px'>Code<span style='color:#5B3FFF'>2</span>Hire</div>"
            f"<h2 style='font-size:19px;margin:0 0 14px'>{title}</h2>{body}{btn}"
            f"<p style='font-size:12px;color:#8A93A6;margin-top:28px'>{foot or 'You received this because of your Code2Hire account.'}</p></div>")
