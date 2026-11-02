import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { api, setToken } from "../api";
import { useAuth } from "../auth";
import { Disha } from "./Mascot";
import { Btn, Field, Input, Modal, useToast } from "./ui";

function strength(p) {
  let s = 0;
  if (p.length >= 8) s++; if (p.length >= 12) s++;
  if (/[A-Z]/.test(p) && /[a-z]/.test(p)) s++; if (/\d/.test(p)) s++; if (/[^A-Za-z0-9]/.test(p)) s++;
  return Math.min(4, s);
}

export function PasswordForm({ needCurrent, onDone, cta = "Save password" }) {
  const toast = useToast();
  const { setMe } = useAuth();
  const [f, setF] = useState({ current: "", new: "", again: "" });
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const st = strength(f.new);
  const save = async () => {
    if (f.new !== f.again) { toast("The two passwords don't match.", "bad"); return; }
    setBusy(true);
    try {
      const r = await api.post("/auth/change-password", { current: f.current, new: f.new });
      setToken(r.token); setMe(r); toast("Password saved. Next time, sign in with your email and this password.", "good"); onDone?.();
    } catch (e) { toast(e.message, "bad"); } finally { setBusy(false); }
  };
  return (
    <div className="col" style={{ gap: 12 }}>
      {needCurrent && <Field label="Current password"><Input type={show ? "text" : "password"} value={f.current} onChange={(e) => setF({ ...f, current: e.target.value })} autoComplete="current-password" /></Field>}
      <Field label="New password" hint="At least 8 characters. Mix letters, numbers and a symbol.">
        <Input type={show ? "text" : "password"} value={f.new} onChange={(e) => setF({ ...f, new: e.target.value })} autoComplete="new-password" autoFocus={!needCurrent} />
      </Field>
      {f.new && <div className="row small"><div className="grow bar" style={{ height: 6 }}><i style={{ width: `${(st + 1) * 20}%`, background: ["#C5283D", "#E08A1E", "#E0B21E", "#12805C", "#12805C"][st] }} /></div><span style={{ width: 70 }}>{["Too weak", "Weak", "Fair", "Good", "Strong"][st]}</span></div>}
      <Field label="Type it again"><Input type={show ? "text" : "password"} value={f.again} onChange={(e) => setF({ ...f, again: e.target.value })} autoComplete="new-password" /></Field>
      <label className="check small"><input type="checkbox" checked={show} onChange={(e) => setShow(e.target.checked)} />Show password</label>
      <Btn kind="primary" busy={busy} disabled={f.new.length < 8 || !f.again} onClick={save}>{cta}</Btn>
    </div>
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
