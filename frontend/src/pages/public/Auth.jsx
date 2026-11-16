import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { Disha, Hira, Isha } from "../../components/Mascot";
import { Btn, Field, Input, Loading, PasswordInput, Textarea, useAsync } from "../../components/ui";
import { PasswordForm } from "../../components/SetPassword";
import { emailError, nameError, passwordError } from "../../lib/validate";

function Art({ title, text }) {
  return (
    <div className="art">
      <Link to="/" className="logo" style={{ color: "#fff" }}>Code<b style={{ color: "var(--gold)" }}>2</b>Hire</Link>
      <div className="col" style={{ gap: 18 }}>
        <div className="row" style={{ gap: 18 }}><span className="bob"><Hira size={92} /></span><span className="bob" style={{ animationDelay: ".6s" }}><Isha size={80} /></span><span className="bob" style={{ animationDelay: "1.2s" }}><Disha size={80} /></span></div>
        <h1 style={{ fontSize: 40, color: "#fff", maxWidth: 480 }}>{title}</h1>
        <p style={{ opacity: .85, maxWidth: 460, fontSize: 16 }}>{text}</p>
      </div>
      <div className="small" style={{ opacity: .7 }}>Powered by AcknowledgerFirst</div>
    </div>
  );
}

/** Only same-site paths are allowed as ?next= (no //evil.com or https://...). */
function safeNext(n) { return n && n.startsWith("/") && !n.startsWith("//") ? n : ""; }

export function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [sp] = useSearchParams();
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [err, setErr] = useState("");
  const [fe, setFe] = useState({});
  const [busy, setBusy] = useState(false);
  const submit = async (e, em = email, p = pw) => {
    e?.preventDefault();
    if (busy) return;
    const f = {}; if (!em.trim()) f.email = "Enter your email."; if (!p) f.password = "Enter your password.";
    setFe(f); setErr("");
    if (Object.keys(f).length) return;
    setBusy(true);
    try { const d = await login(em.trim(), p); nav(safeNext(sp.get("next")) || (d.must_change_password ? "/password" : d.home)); }
    catch (x) { setErr(x.message); } finally { setBusy(false); }
  };
  return (
    <div className="auth">
      <Art title="Every interview, expert-level." text="Hira screens and interviews. Isha guides live interviews. Disha helps candidates learn, prove skills and get matched." />
      <div className="form"><form onSubmit={submit}>
        <h1>Sign in</h1>
        <Field label="Work or personal email" error={fe.email}><Input type="email" autoComplete="email" placeholder="name@company.com" value={email} onChange={(e) => { setEmail(e.target.value); setFe({ ...fe, email: "" }); }} autoFocus /></Field>
        <Field label="Password" error={fe.password}><PasswordInput autoComplete="current-password" value={pw} onChange={(e) => { setPw(e.target.value); setFe({ ...fe, password: "" }); }} /></Field>
        <div className="row" style={{ marginTop: -6 }}><Link className="small right" to={`/forgot${email.trim() ? `?email=${encodeURIComponent(email.trim())}` : ""}`}>Forgot password?</Link></div>
        {err && <div className="chip bad" role="alert" style={{ height: "auto", padding: 8, whiteSpace: "normal" }}>{err}</div>}
        <Btn kind="primary" size="lg" busy={busy} type="submit">Sign in</Btn>
        <div className="small muted">New candidate? <Link to="/signup">Create a free profile</Link></div>
      </form></div>
    </div>
  );
}

/** CP-010 (V02.00.10): ask for a password-reset email. */
export function Forgot() {
  const [sp] = useSearchParams();
  const [email, setEmail] = useState(sp.get("email") || "");
  const [fe, setFe] = useState("");
  const [err, setErr] = useState("");
  const [sent, setSent] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    if (busy) return;
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())) { setFe("Enter the email address you sign in with."); return; }
    setBusy(true); setErr("");
    try { const r = await api.post("/auth/forgot", { email: email.trim() }); setSent(r.message); }
    catch (x) { if (x.fields?.email) setFe(x.fields.email); else setErr(x.message); } finally { setBusy(false); }
  };
  return (
    <div className="auth">
      <Art title="Locked out? It happens." text="We'll email you a link to choose a new password. It works once, for 60 minutes." />
      <div className="form">{sent ? (
        <div className="col" style={{ gap: 14 }} role="status">
          <h1>Check your email</h1>
          <p style={{ margin: 0 }}>{sent}</p>
          <p className="small muted" style={{ margin: 0 }}>Nothing arrived after a few minutes? Check spam, or try again.</p>
          <div className="row"><Btn onClick={() => setSent("")}>Try again</Btn><Link className="btn primary" to="/login">Back to sign in</Link></div>
        </div>) : (
        <form onSubmit={submit} className="col" style={{ gap: 14 }}>
          <h1>Reset your password</h1>
          <p className="small muted" style={{ margin: 0 }}>Enter the email you sign in with and we'll send you a reset link.</p>
          <Field label="Email" error={fe}><Input type="email" autoComplete="email" value={email} onChange={(e) => { setEmail(e.target.value); setFe(""); }} autoFocus placeholder="name@company.com" /></Field>
          {err && <div className="chip bad" role="alert" style={{ height: "auto", padding: 8, whiteSpace: "normal" }}>{err}</div>}
          <Btn kind="primary" size="lg" busy={busy} type="submit">Email me a reset link</Btn>
          <div className="small"><Link to="/login">Back to sign in</Link></div>
        </form>)}
      </div>
    </div>
  );
}

/** CP-010: the link from the reset email. */
export function ResetPassword() {
  const { token } = useParams();
  const nav = useNavigate();
  const { data, error } = useAsync(() => api.get(`/auth/reset/${token}`), [token]);
  return (
    <div className="auth">
      <Art title="Choose a new password." text="After this, sign in with your email and the new password." />
      <div className="form">
        {error ? <div className="col" style={{ gap: 14 }}><h1>This link doesn't work</h1><p style={{ margin: 0 }}>{String(error)}</p>
          <div className="row"><Link className="btn primary" to="/forgot">Send a new link</Link><Link className="btn" to="/login">Sign in</Link></div></div>
          : !data ? <Loading /> : <div className="col" style={{ gap: 14 }}>
            <h1>New password</h1><p className="small muted" style={{ margin: 0 }}>For {data.email}</p>
            <PasswordForm resetToken={token} email={data.email} cta="Save and sign in" onDone={(r) => nav(r?.home || "/")} />
          </div>}
      </div>
    </div>
  );
}

export function Signup() {
  const { signup } = useAuth();
  const nav = useNavigate();
  const [sp] = useSearchParams();
  const invite = sp.get("invite");
  const [job, setJob] = useState(null);
  const [f, setF] = useState({ name: "", email: "", password: "", goal: "", resume_text: "" });
  const [err, setErr] = useState("");
  const [fe, setFe] = useState({});
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (invite) api.get(`/public/jobs/invite/${invite}`).then(setJob).catch(() => {}); }, [invite]);
  const set = (k, v) => { setF({ ...f, [k]: v }); if (fe[k]) setFe({ ...fe, [k]: "" }); };
  const submit = async (e) => {
    e.preventDefault();
    if (busy) return;
    const x = { name: nameError(f.name), email: emailError(f.email), password: passwordError(f.password, f.email) };
    Object.keys(x).forEach((k) => !x[k] && delete x[k]);
    setFe(x); setErr("");
    if (Object.keys(x).length) return;
    setBusy(true);
    try { await signup({ ...f, name: f.name.trim(), email: f.email.trim(), invite }); nav("/me"); }
    catch (y) { setErr(y.fields ? "" : y.message); if (y.fields) setFe(y.fields); } finally { setBusy(false); }
  };
  return (
    <div className="auth">
      <Art title="Learn. Prove it. Get matched." text="Disha builds your path: find your level, close the gaps with practice, earn verified badges and apply where you fit." />
      <div className="form"><form onSubmit={submit}>
        <h1>Create your profile</h1>
        {job && <div className="agent disha"><Disha size={36} /><div><b>You're applying to {job.title}</b><div className="small muted">{job.company || "Confidential company"} · {job.location}</div></div></div>}
        <Field label="Full name" required error={fe.name}><Input autoComplete="name" placeholder="e.g. Asha Rao" maxLength={80} value={f.name} onChange={(e) => set("name", e.target.value)} /></Field>
        <Field label="Email" required error={fe.email}><Input type="email" autoComplete="email" placeholder="name@example.com" maxLength={254} value={f.email} onChange={(e) => set("email", e.target.value)} /></Field>
        <Field label="Password" required error={fe.password} hint="At least 8 characters, with letters and a number."><PasswordInput autoComplete="new-password" maxLength={128} value={f.password} onChange={(e) => set("password", e.target.value)} /></Field>
        <Field label="What role are you aiming for?"><Input placeholder="e.g. Senior Python Developer" maxLength={120} value={f.goal} onChange={(e) => set("goal", e.target.value)} /></Field>
        <Field label="Paste your resume (optional, you can upload later)"><Textarea value={f.resume_text} maxLength={20000} onChange={(e) => set("resume_text", e.target.value)} /></Field>
        {err && <div className="chip bad" role="alert" style={{ height: "auto", padding: 8, whiteSpace: "normal" }}>{err}</div>}
        <Btn kind="primary" size="lg" busy={busy} type="submit">Create profile</Btn>
        <div className="small muted">Already have an account? <Link to="/login">Sign in</Link></div>
      </form></div>
    </div>
  );
}

export function ChangePassword() {
  const nav = useNavigate();
  const { me, refresh } = useAuth();
  const [f, setF] = useState({ current: "", new: "" });
  const [err, setErr] = useState("");
  const [fe, setFe] = useState({});
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    if (busy) return;
    const x = {}; if (!f.current) x.current = "Enter the temporary password."; const pe = passwordError(f.new, me?.user?.email); if (pe) x.new = pe;
    setFe(x); setErr("");
    if (Object.keys(x).length) return;
    setBusy(true);
    try { await api.post("/auth/change-password", f); const d = await refresh(); nav(d?.home || "/"); }
    catch (y) { if (y.fields) setFe(y.fields); else setErr(y.message); } finally { setBusy(false); }
  };
  return (
    <div className="auth"><Art title="Set your own password." text="Your admin gave you a temporary password. Choose one only you know." />
      <div className="form"><form onSubmit={submit}>
        <h1>Choose a password</h1>
        <Field label="Temporary password" required error={fe.current}><PasswordInput autoComplete="current-password" value={f.current} onChange={(e) => setF({ ...f, current: e.target.value })} /></Field>
        <Field label="New password" required error={fe.new} hint="At least 8 characters, with letters and a number."><PasswordInput autoComplete="new-password" value={f.new} onChange={(e) => setF({ ...f, new: e.target.value })} /></Field>
        {err && <div className="chip bad" role="alert" style={{ height: "auto", padding: 8, whiteSpace: "normal" }}>{err}</div>}
        <Btn kind="primary" type="submit" busy={busy}>Save and continue</Btn>
        {me && <Btn kind="ghost" type="button" onClick={() => nav(me.home)}>Skip for now</Btn>}
      </form></div>
    </div>
  );
}
