import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api";
import { Disha, Hira } from "../../components/Mascot";
import ReportView from "../../components/ReportView";
import { Btn, Chip, Empty, Input, Loading, fmtDate, inr, useAsync } from "../../components/ui";

export function PublicBar() {
  return (
    <header className="top" style={{ position: "sticky" }}>
      <Link to="/" className="logo">Code<b>2</b>Hire</Link><span className="powered">Powered by AcknowledgerFirst</span>
      <div className="right row"><Link className="btn sm ghost" to="/jobs">Jobs</Link><Link className="btn sm ghost" to="/verify">Verify a credential</Link><Link className="btn sm" to="/login">Sign in</Link><Link className="btn sm primary" to="/signup">Get started</Link></div>
    </header>
  );
}

export function Verify() {
  const { code: initial } = useParams();
  const [code, setCode] = useState(initial || "");
  const [res, setRes] = useState(null);
  const [err, setErr] = useState("");
  const check = async (c = code) => { setErr(""); setRes(null); try { setRes(await api.get(`/public/verify/${encodeURIComponent(c.trim())}`)); } catch (e) { setErr(e.message); } };
  useEffect(() => { if (initial) check(initial); }, [initial]); // eslint-disable-line react-hooks/exhaustive-deps
  const tone = res?.state === "valid" ? "good" : "bad";
  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)" }}>
      <PublicBar />
      <div className="page" style={{ maxWidth: 720 }}>
        <h1>Verify a Code2Hire credential</h1>
        <p className="muted">Enter the verification ID printed on the certificate or badge, for example C2H-PYT3-482910.</p>
        <form className="row" onSubmit={(e) => { e.preventDefault(); check(); }}>
          <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder="C2H-XXX0-000000" aria-label="Verification ID" />
          <Btn kind="primary" type="submit">Verify</Btn>
        </form>
        {err && <div className="card pad" style={{ background: "var(--bad-soft)" }}><b style={{ color: "var(--bad)" }}>{err}</b></div>}
        {res && (
          <div className="card pad col" style={{ gap: 12, borderTop: `4px solid var(--${tone})` }}>
            <div className="row"><Chip kind={tone}>{res.state === "valid" ? "✓ Valid" : res.state === "expired" ? "Expired" : "Revoked"}</Chip><span className="mono small right">{res.code}</span></div>
            <h2>{res.title}</h2>
            <div className="grid g2">
              <div><div className="small muted">Holder</div><b>{res.holder}</b></div>
              <div><div className="small muted">Issuer</div><b>{res.issuer}</b></div>
              <div><div className="small muted">Skill and level</div><b>{res.skill ? `${res.skill} · L${res.level}` : "—"}</b></div>
              <div><div className="small muted">Grade</div><b>{res.grade || "—"}</b></div>
              <div><div className="small muted">Issued</div><b>{fmtDate(res.issued)}</b></div>
              <div><div className="small muted">Valid until</div><b>{fmtDate(res.expires)}</b></div>
            </div>
            {res.revoke_reason && <div className="small" style={{ color: "var(--bad)" }}>Revoked: {res.revoke_reason}</div>}
          </div>
        )}
      </div>
    </div>
  );
}

export function SharedReport() {
  const { token } = useParams();
  const { data, error, loading } = useAsync(() => api.get(`/public/shared/${token}`), [token]);
  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)" }}>
      <PublicBar />
      <div className="page" style={{ maxWidth: 1100 }}>
        {loading && <Loading />}
        {error && <Empty title="This link isn't available" text={error} mascot={<Hira size={80} />} />}
        {data && <><div className="chip info">Shared report · read only</div><ReportView r={data} /></>}
      </div>
    </div>
  );
}

export function PublicJobs() {
  const { data, loading } = useAsync(() => api.get("/public/jobs"), []);
  const [q, setQ] = useState("");
  const rows = (data || []).filter((j) => !q || JSON.stringify(j).toLowerCase().includes(q.toLowerCase()));
  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)" }}>
      <PublicBar />
      <div className="page" style={{ maxWidth: 1100 }}>
        <div className="row wrap"><h1>Open jobs</h1><div className="right" style={{ width: 320 }}><Input placeholder="Search title, skill, city…" value={q} onChange={(e) => setQ(e.target.value)} /></div></div>
        <div className="agent disha"><Disha size={44} /><div>Sign up and Disha will show how well you match each job, and what to learn to match better.</div><Link className="btn primary right" to="/signup">Create profile</Link></div>
        {loading && <Loading />}
        <div className="grid g3">
          {rows.map((j) => (
            <div key={j.id} className="card pad col">
              <h3>{j.title}</h3>
              <div className="small muted">{j.company || "Confidential"} · {j.location} · {j.work_mode}</div>
              <div className="row wrap">{(j.skills || []).slice(0, 5).map((s, i) => <Chip key={i}>{s.name || s}</Chip>)}</div>
              {j.salary && <div className="small b">{inr(j.salary[0])} – {inr(j.salary[1])}</div>}
              <Link className="btn sm right" to="/signup">Apply</Link>
            </div>
          ))}
        </div>
        {data && !rows.length && <Empty title="No jobs match" />}
      </div>
    </div>
  );
}
