import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { Disha, Hira, Isha } from "../../components/Mascot";
import { Btn, Field, Input, Textarea } from "../../components/ui";

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

export function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [sp] = useSearchParams();
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e, em = email, p = pw) => {
    e?.preventDefault(); setErr(""); setBusy(true);
    try { const d = await login(em, p); nav(sp.get("next") || (d.must_change_password ? "/password" : d.home)); }
    catch (x) { setErr(x.message); } finally { setBusy(false); }
  };
  return (
    <div className="auth">
      <Art title="Every interview, expert-level." text="Hira screens and interviews. Isha guides live interviews. Disha helps candidates learn, prove skills and get matched." />
      <div className="form"><form onSubmit={submit}>
        <h1>Sign in</h1>
        <Field label="Work or personal email"><Input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <Field label="Password"><Input type="password" autoComplete="current-password" required value={pw} onChange={(e) => setPw(e.target.value)} /></Field>
        {err && <div className="chip bad" style={{ height: "auto", padding: 8 }}>{err}</div>}
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
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (invite) api.get(`/public/jobs/invite/${invite}`).then(setJob).catch(() => {}); }, [invite]);
  const submit = async (e) => {
    e.preventDefault(); setErr(""); setBusy(true);
    try { await signup({ ...f, invite }); nav("/me"); } catch (x) { setErr(x.message); } finally { setBusy(false); }
  };
  return (
    <div className="auth">
      <Art title="Learn. Prove it. Get matched." text="Disha builds your path: find your level, close the gaps with practice, earn verified badges and apply where you fit." />
      <div className="form"><form onSubmit={submit}>
        <h1>Create your profile</h1>
        {job && <div className="agent disha"><Disha size={36} /><div><b>You're applying to {job.title}</b><div className="small muted">{job.company || "Confidential company"} · {job.location}</div></div></div>}
        <Field label="Full name"><Input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label="Email"><Input type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
        <Field label="Password" hint="At least 8 characters"><Input type="password" required minLength={8} value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>
        <Field label="What role are you aiming for?"><Input placeholder="e.g. Senior Python Developer" value={f.goal} onChange={(e) => setF({ ...f, goal: e.target.value })} /></Field>
        <Field label="Paste your resume (optional, you can upload later)"><Textarea value={f.resume_text} onChange={(e) => setF({ ...f, resume_text: e.target.value })} /></Field>
        {err && <div className="chip bad" style={{ height: "auto", padding: 8 }}>{err}</div>}
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
  return (
    <div className="auth"><Art title="Set your own password." text="Your admin gave you a temporary password. Choose one only you know." />
      <div className="form"><form onSubmit={async (e) => { e.preventDefault(); try { await api.post("/auth/change-password", f); const d = await refresh(); nav(d?.home || "/"); } catch (x) { setErr(x.message); } }}>
        <h1>Choose a password</h1>
        <Field label="Temporary password"><Input type="password" value={f.current} onChange={(e) => setF({ ...f, current: e.target.value })} /></Field>
        <Field label="New password" hint="At least 8 characters"><Input type="password" value={f.new} onChange={(e) => setF({ ...f, new: e.target.value })} /></Field>
        {err && <div className="chip bad">{err}</div>}
        <Btn kind="primary" type="submit">Save and continue</Btn>
        {me && <Btn kind="ghost" type="button" onClick={() => nav(me.home)}>Skip for now</Btn>}
      </form></div>
    </div>
  );
}
