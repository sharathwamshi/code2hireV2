import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { Disha, Hira, Isha } from "../../components/Mascot";
import { Btn, Field, Input, PasswordInput, Textarea } from "../../components/ui";
import { emailError, nameError, passwordError } from "../../lib/validate";

const DEMO = [
  ["super@code2hire.ai", "Superadmin"], ["admin@acme.test", "Company Admin"], ["priya@acme.test", "Manager + Interviewer"],
  ["rahul@acme.test", "Recruiter + Interviewer"], ["anita@acme.test", "Interviewer"], ["vikram@acme.test", "Hiring manager"],
  ["arjun@demo.test", "Candidate (MCQ invite)"], ["meera@demo.test", "Candidate (AI interview)"],
];

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
        {err && <div className="chip bad" role="alert" style={{ height: "auto", padding: 8, whiteSpace: "normal" }}>{err}</div>}
        <Btn kind="primary" size="lg" busy={busy} type="submit">Sign in</Btn>
        <div className="small muted">New candidate? <Link to="/signup">Create a free profile</Link></div>
        <div className="divider" />
        <div className="small b">Demo accounts (password Code2Hire@123)</div>
        <div className="demo-acc">{DEMO.map(([e, l]) => <button type="button" key={e} onClick={() => submit(null, e, "Code2Hire@123")}><b>{l}</b><br /><span className="muted">{e}</span></button>)}</div>
      </form></div>
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
