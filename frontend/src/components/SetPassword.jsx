import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { api, setToken } from "../api";
import { useAuth } from "../auth";
import { Disha } from "./Mascot";
import { Btn, Field, Modal, PasswordInput, useToast } from "./ui";
import { passwordError } from "../lib/validate";

function strength(p) {
  let s = 0;
  if (p.length >= 8) s++; if (p.length >= 12) s++;
  if (/[A-Z]/.test(p) && /[a-z]/.test(p)) s++; if (/\d/.test(p)) s++; if (/[^A-Za-z0-9]/.test(p)) s++;
  return Math.min(4, s);
}

export function PasswordForm({ needCurrent, onDone, cta = "Save password" }) {
  const toast = useToast();
  const { me, setMe } = useAuth();
  const [f, setF] = useState({ current: "", new: "", again: "" });
  const [fe, setFe] = useState({});
  const [busy, setBusy] = useState(false);
  const st = strength(f.new);
  const rule = f.new ? passwordError(f.new, me?.user?.email) : "";
  const mismatch = f.again && f.new !== f.again ? "The two passwords don't match." : "";
  const save = async (e) => {
    e?.preventDefault();
    if (busy) return;
    const x = {};
    if (needCurrent && !f.current) x.current = "Enter your current password.";
    const pe = passwordError(f.new, me?.user?.email); if (pe) x.new = pe;
    if (f.new !== f.again) x.again = "The two passwords don't match.";
    setFe(x);
    if (Object.keys(x).length) return;
    setBusy(true);
    try {
      const r = await api.post("/auth/change-password", { current: f.current, new: f.new });
      setToken(r.token); setMe(r); toast("Password saved. Next time, sign in with your email and this password.", "good"); onDone?.();
    } catch (y) { if (y.fields) setFe(y.fields); else toast(y.message, "bad"); } finally { setBusy(false); }
  };
  return (
    <form className="col" style={{ gap: 12 }} onSubmit={save}>
      {needCurrent && <Field label="Current password" required error={fe.current}><PasswordInput value={f.current} onChange={(e) => setF({ ...f, current: e.target.value })} autoComplete="current-password" /></Field>}
      <Field label="New password" required error={fe.new || rule} hint="At least 8 characters, with letters and a number.">
        <PasswordInput value={f.new} onChange={(e) => { setF({ ...f, new: e.target.value }); setFe({ ...fe, new: "" }); }} autoComplete="new-password" autoFocus={!needCurrent} maxLength={128} />
      </Field>
      {f.new && <div className="row small"><div className="grow bar" style={{ height: 6 }}><i style={{ width: `${(st + 1) * 20}%`, background: ["#C5283D", "#E08A1E", "#E0B21E", "#12805C", "#12805C"][st] }} /></div><span style={{ width: 70 }}>{["Too weak", "Weak", "Fair", "Good", "Strong"][st]}</span></div>}
      <Field label="Type it again" required error={fe.again || mismatch}><PasswordInput value={f.again} onChange={(e) => { setF({ ...f, again: e.target.value }); setFe({ ...fe, again: "" }); }} autoComplete="new-password" maxLength={128} /></Field>
      <Btn kind="primary" type="submit" busy={busy} disabled={!f.new || !f.again || !!rule || !!mismatch}>{cta}</Btn>
    </form>
  );
}

/** Banner + modal for people who came in through their personal link and haven't set a password yet. */
export default function SetPasswordPrompt() {
  const { me } = useAuth();
  const loc = useLocation();
  const [open, setOpen] = useState(false);
  useEffect(() => { if (me?.link_session && me?.must_change_password && new URLSearchParams(loc.search).get("welcome")) setOpen(true); }, [me?.link_session]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!me?.must_change_password || !me?.link_session) return null;
  let must = false;
  try { must = localStorage.getItem("c2h_must_pw") === "1"; } catch { /* private mode */ }
  return (
    <>
      <div className="pw-banner"><Disha size={34} /><div className="grow"><b>Set your password</b><div className="small muted">You came in with your personal link. Set a password so you can sign in on any device. The link stops working once you do.</div></div>
        <Btn kind="primary" onClick={() => setOpen(true)}>Set password</Btn></div>
      {(open || must) && <Modal title="Choose your password" onClose={() => !must && setOpen(false)}>
        <div className="row"><Disha size={48} mood="happy" /><div><b>Welcome to Code2Hire, {me.user.name.split(" ")[0]}!</b><div className="small muted">Your account email is <b>{me.user.email}</b>.</div></div></div>
        <PasswordForm onDone={() => { setOpen(false); try { localStorage.removeItem("c2h_must_pw"); } catch { /* ignore */ } }} cta="Save and continue" />
        {!must && <Btn kind="ghost" onClick={() => setOpen(false)}>Later</Btn>}
      </Modal>}
    </>
  );
}
