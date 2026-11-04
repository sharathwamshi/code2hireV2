import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { AgentNote, Disha } from "../../components/Mascot";
import ReportView from "../../components/ReportView";
import { PageHead } from "../../components/Shell";
import { PasswordForm } from "../../components/SetPassword";
import { Bar, Btn, Chip, Empty, Field, Input, Loading, Modal, ROUND_LABEL, Ring, Score, Select, Seg, Status, Textarea, fmtDate, fmtTime, inr, useAction, useAsync, useToast, useConfirm } from "../../components/ui";

export function Home() {
  const nav = useNavigate();
  const { data: d, reload } = useAsync(() => api.get("/me"), []);
  const [path, setPath] = useState(null);
  const [goal, setGoal] = useState("");
  const [run, busy] = useAction();
  if (!d) return <Loading />;
  return (
    <>
      <PageHead title={`Hi ${d.user.name.split(" ")[0]}`} sub="Learn, prove your skills and get matched. Disha keeps track." />
      {d.invites.length > 0 && (
        <div className="card">
          <div className="card-h"><h3>Waiting for you</h3><Chip kind="brand">{d.invites.length}</Chip></div>
          {d.invites.map((i) => <div key={i.attempt_id} className="list-row"><div className="grow"><b>{i.name}</b><div className="small muted">{i.job} · {ROUND_LABEL[i.type]}{i.deadline_at ? ` · complete by ${fmtDate(i.deadline_at, true)}` : ""}</div></div>
            <Status s={i.status} />{i.type !== "f2f_isha" && i.type !== "f2f_human" ? <Btn kind="primary" onClick={() => nav(`/room/${i.attempt_id}`)}>{i.status === "in_progress" || i.status === "paused" ? "Continue" : "Start"}</Btn> : <><span className="small muted">{i.scheduled_at ? "Live · " + fmtDate(i.scheduled_at, true) : "Live video interview"}</span><JoinButton item={i} onJoin={() => nav(`/room/${i.attempt_id}`)} /></>}</div>)}
        </div>
      )}
      <div className="grid g4">
        <div className="card stat row"><Ring value={d.completeness.pct} label={d.completeness.pct + "%"} /><div><div className="l">Profile</div><div className="small">{d.completeness.missing.length ? "Add " + d.completeness.missing.slice(0, 2).join(", ") : "Complete"}</div></div></div>
        <div className="card stat"><div className="l">Verified skills</div><div className="v">{d.stats.verified_skills}</div></div>
        <div className="card stat"><div className="l">Badges and certificates</div><div className="v">{d.stats.badges}</div></div>
        <div className="card stat"><div className="l">Applications</div><div className="v">{d.stats.applications}</div></div>
      </div>
      <div className="split">
        <div className="card pad col">
          <div className="row"><Disha size={60} mood={path ? "happy" : "idle"} /><div><h3>Disha's path for you</h3><div className="small muted">{d.goal ? `Goal: ${d.goal}` : "Tell me the role you're aiming for."}</div></div></div>
          <form className="row" onSubmit={(e) => { e.preventDefault(); run(() => api.post("/me/path", { goal: goal || d.goal })).then((p) => { setPath(p); reload(); }); }}>
            <Input value={goal} onChange={(e) => setGoal(e.target.value)} placeholder={d.goal || "e.g. Senior Python Developer"} /><Btn kind="primary" type="submit" busy={busy}>Show my path</Btn></form>
          {path && path.steps.map((s, i) => <div key={i} className="agent disha" style={{ padding: 12 }}><span className="chip disha">Step {i + 1}</span><div><b>{s.t}</b><div className="small">{s.d}</div></div></div>)}
          <div className="row wrap"><Btn onClick={() => nav("/me/skills")}>Take a skill check</Btn><Btn onClick={() => nav("/me/practice")}>Practise an interview</Btn><Btn onClick={() => nav("/me/jobs")}>See matching jobs</Btn></div>
        </div>
        <div className="card pad col"><h3>Your skills</h3>
          {(d.profile.skills || []).map((s, i) => <div key={i} className="row"><span className="grow">{s.name}</span>{s.verified ? <Chip kind="good">L{s.level} ✓ verified</Chip> : <Chip>L{s.level} self-reported</Chip>}</div>)}
          {!d.profile.skills?.length && <span className="muted small">Add your resume and Disha will find your skills.</span>}
          <Btn size="sm" onClick={() => nav("/me/profile")}>Edit profile</Btn>
        </div>
      </div>
    </>
  );
}

export function Jobs() {
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("match");
  const [page, setPage] = useState(1);
  const { data } = useAsync(() => api.get("/me/jobs", { q, sort, page }), [q, sort, page]);
  return (
    <>
      <PageHead title="Jobs for you" sub="Ranked by how well your skills match. Verified skills count more." actions={<Seg value={sort} onChange={setSort} options={[["match", "Best match"], ["posted", "Newest"]]} />} />
      <Input placeholder="Search title, company, skill or city…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
      {!data ? <Loading /> : !data.items.length ? <Empty title="No jobs match" mascot={<Disha size={70} />} /> : (
        <div className={"card-grid" + (data.items.length < 3 ? " few" : "")}>{data.items.map((j) => (
          <div key={j.id} className="card pad col" style={{ cursor: "pointer" }} role="link" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && nav(`/me/jobs/${j.id}`)} onClick={() => nav(`/me/jobs/${j.id}`)}>
            <div className="row"><h3 className="grow">{j.title}</h3><Ring value={j.match} label={j.match + "%"} /></div>
            <div className="small muted">{j.company || "Confidential"} · {j.location} · {j.work_mode}</div>
            <div className="row wrap">{j.matched.slice(0, 3).map((m, i) => <Chip key={i} kind="good">{m}</Chip>)}{j.missing.slice(0, 2).map((m, i) => <Chip key={i} kind="bad">No {m}</Chip>)}</div>
            {j.salary && <div className="small b">{inr(j.salary[0])} – {inr(j.salary[1])}</div>}
            {j.applied ? <Chip kind="info">Applied</Chip> : <span className="small" style={{ color: "var(--brand)" }}>View and apply →</span>}
          </div>))}
          {data.items.length < 3 && page === 1 && !q && (
            <div className="card pad col tip-card">
              <div className="row"><Disha size={44} /><h3>Want more matches?</h3></div>
              <span className="small">New jobs are added every week. These help Disha find more for you:</span>
              <ul className="small" style={{ margin: 0, paddingLeft: 18 }}><li>Add your skills and a headline to your profile</li><li>Prove a skill with a short check to earn a verified badge</li><li>Let all employers see your profile</li></ul>
              <div className="row wrap"><Btn size="sm" kind="primary" onClick={() => nav("/me/profile")}>Update profile</Btn><Btn size="sm" onClick={() => nav("/me/skills")}>Prove a skill</Btn></div>
            </div>)}
        </div>
      )}
      {data?.pages > 1 && <div className="row"><Btn disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Btn><span>Page {page} of {data.pages}</span><Btn disabled={page >= data.pages} onClick={() => setPage(page + 1)}>Next</Btn></div>}
    </>
  );
}

export function JobView() {
  const { id } = useParams();
  const nav = useNavigate();
  const { data: j, reload } = useAsync(() => api.get(`/me/jobs/${id}`), [id]);
  const [run, busy] = useAction();
  if (!j) return <Loading />;
  return (
    <>
      <PageHead back="/me/jobs" title={j.title} sub={`${j.company || "Confidential company"} · ${j.location} · ${j.work_mode} · ${j.level}`}
        actions={j.applied ? <Chip kind="info">You've applied</Chip> : <Btn kind="primary" busy={busy} onClick={() => run(() => api.post(`/me/jobs/${id}/apply`), "Applied! Watch your inbox for the first round.").then(reload)}>Apply</Btn>} />
      <div className="split">
        <div className="card pad col"><p style={{ whiteSpace: "pre-wrap" }}>{j.description}</p>
          <h3>How hiring works here</h3><div className="row wrap">{j.rounds.map((r, i) => <Chip key={i} kind="brand">{i + 1}. {r.name}</Chip>)}</div>
          {j.salary && <div>Salary {inr(j.salary[0])} – {inr(j.salary[1])}</div>}</div>
        <div className="col" style={{ gap: 16 }}>
          <div className="card pad col"><div className="row"><Ring value={j.match} label={j.match + "%"} /><h3>Your match</h3></div>
            {j.matched.map((m, i) => <div key={i} className="small" style={{ color: "var(--good)" }}>✓ {m}</div>)}
            {j.missing.map((m, i) => <div key={i} className="small" style={{ color: "var(--bad)" }}>✗ {m}</div>)}</div>
          {j.missing.length > 0 && <AgentNote agent="disha" title="Close the gap" action={<Btn size="sm" onClick={() => api.post("/me/learning", { skill: j.missing[0], goal: j.title }).then(() => nav("/me/learning"))}>Start a {j.missing[0]} path</Btn>}>Learning {j.missing.join(", ")} would raise your match. A verified badge raises it most.</AgentNote>}
        </div>
      </div>
    </>
  );
}

/** Join is only active inside the join window; before that it says when it opens, and switches on by itself. */
function JoinButton({ item, onJoin, size, label = "📹 Join video interview" }) {
  const [, tick] = useState(0);
  const opens = item.opens_at ? new Date(item.opens_at) : null;
  const open = item.can_join || (opens && Date.now() >= opens.getTime());
  useEffect(() => {
    if (open || !opens) return undefined;
    const ms = Math.min(opens.getTime() - Date.now() + 500, 30000);
    const t = setTimeout(() => tick((x) => x + 1), Math.max(500, ms));
    return () => clearTimeout(t);
  });
  if (open) return <Btn size={size} kind="primary" onClick={onJoin}>{label}</Btn>;
  const mins = opens ? Math.round((opens.getTime() - Date.now()) / 60000) : null;
  const when = opens ? (mins < 60 ? `in ${mins} min` : opens.toDateString() === new Date().toDateString() ? `at ${fmtTime(opens)}` : fmtDate(opens, true)) : "later";
  return <Btn size={size} disabled title="The room opens shortly before the interview starts.">Opens {when}</Btn>;
}

export function Applications() {
  const nav = useNavigate();
  const { data, reload } = useAsync(() => api.get("/me/applications"), []);
  const [run] = useAction();
  const ask = useConfirm();
  if (!data) return <Loading />;
  if (!data.length) return <><PageHead title="My applications" /><Empty title="No applications yet" mascot={<Disha size={70} />} action={<Btn kind="primary" onClick={() => nav("/me/jobs")}>Find jobs</Btn>} /></>;
  return (
    <>
      <PageHead title="My applications" sub="Where you stand in every hiring process." />
      {data.map((a) => (
        <div key={a.id} className="card pad col">
          <div className="row"><div className="grow"><h3>{a.job.title}</h3><div className="small muted">{a.job.company || "Confidential"} · applied {fmtDate(a.applied)}</div></div><Chip kind={a.raw_stage === "offer" || a.raw_stage === "hired" ? "good" : a.raw_stage === "rejected" ? "bad" : "brand"}>{a.stage}</Chip></div>
          <div className="row wrap">{a.steps.map((s, i) => (
            <div key={i} className="row" style={{ gap: 6 }}>{i > 0 && <span style={{ width: 16, height: 2, background: "var(--line-2)" }} />}
              <div className="card" style={{ padding: "8px 12px", background: s.status === "completed" || s.status === "reviewed" ? "var(--good-soft)" : s.attempt_id ? "var(--brand-soft)" : "#fff" }}>
                <b className="small">{s.name}</b><div className="tiny">{s.status === "upcoming" ? "Upcoming" : <Status s={s.status} />}</div>
                {["invited", "scheduled", "in_progress", "paused"].includes(s.status) && (s.type.startsWith("f2f") ? <JoinButton item={s} size="sm" label="Join call" onJoin={() => nav(`/room/${s.attempt_id}`)} /> : <Btn size="sm" kind="primary" onClick={() => nav(`/room/${s.attempt_id}`)}>Open</Btn>)}
                {s.scheduled_at && s.type.startsWith("f2f") && <div className="tiny muted">{fmtDate(s.scheduled_at, true)}</div>}
              </div></div>))}</div>
          {!["rejected", "withdrawn", "hired"].includes(a.raw_stage) && <Btn size="sm" kind="ghost" className="right" onClick={async () => (await ask({ title: "Withdraw this application?", text: "The hiring team will see that you withdrew. You can't undo this.", yes: "Withdraw", danger: true })) && run(() => api.post(`/me/applications/${a.id}/withdraw`), "Withdrawn").then(reload)}>Withdraw</Btn>}
        </div>
      ))}
    </>
  );
}

export function Practice() {
  const nav = useNavigate();
  const { data, reload } = useAsync(() => api.get("/me/practice"), []);
  const [f, setF] = useState({ type: "ai_interview", role: "", skills: "", difficulty: "medium", questions: 4 });
  const [run, busy] = useAction();
  const [view, setView] = useState(null);
  return (
    <>
      <PageHead title="Practice interviews" sub="Private mock interviews and quizzes. Employers never see these." />
      <div className="split">
        <div className="card">
          <div className="card-h"><h3>Your practice</h3></div>
          {!data ? <Loading /> : !data.filter((p) => !p.skill_check).length ? <div className="empty">No practice yet. Start one on the right.</div> :
            data.filter((p) => !p.skill_check).map((p) => <div key={p.id} className="list-row"><div className="grow"><b>{p.title}</b><div className="small muted">{ROUND_LABEL[p.type]} · {fmtDate(p.created_at)}</div></div><Status s={p.status} />
              {p.score != null && <Score value={p.score} type={p.type} pct />}
              {p.report ? <Btn size="sm" onClick={() => setView(p)}>Feedback</Btn> : <Btn size="sm" kind="primary" onClick={() => nav(`/room/${p.id}`)}>Open</Btn>}</div>)}
        </div>
        <form className="card pad col" onSubmit={(e) => { e.preventDefault(); run(() => api.post("/me/practice", { ...f, skills: f.skills.split(",").map((s) => s.trim()).filter(Boolean) })).then((r) => nav(`/room/${r.attempt_id}`)); }}>
          <Disha size={56} /><h3>New practice</h3>
          <Field label="Kind"><Seg value={f.type} onChange={(v) => setF({ ...f, type: v })} options={[["ai_interview", "Voice interview with Hira"], ["mcq", "Quiz"]]} /></Field>
          <Field label="Role"><Input value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })} placeholder="e.g. Backend developer" /></Field>
          <Field label="Skills (comma separated)" hint="Leave empty to use your profile skills"><Input value={f.skills} onChange={(e) => setF({ ...f, skills: e.target.value })} /></Field>
          <div className="grid g2"><Field label="Difficulty"><Select value={f.difficulty} onChange={(v) => setF({ ...f, difficulty: v })} options={["easy", "medium", "hard"]} /></Field>
            <Field label="Questions"><Input type="number" value={f.questions} onChange={(e) => setF({ ...f, questions: +e.target.value })} /></Field></div>
          <Btn kind="primary" type="submit" busy={busy}>Start practising</Btn>
        </form>
      </div>
      {view && <Modal wide title={view.title} onClose={() => { setView(null); reload(); }}><ReportView r={{ sections: view.report, overall: view.report.overall ?? (view.type === "mcq" ? view.score / 20 : view.score), round: view.title, type: view.type, recommendation: null, version: 1, scale: 5, candidate: { name: "You" }, job: { title: "Practice" } }} /></Modal>}
    </>
  );
}

export function Skills() {
  const nav = useNavigate();
  const { data: badges } = useAsync(() => api.get("/me/badges"), []);
  const { data: me } = useAsync(() => api.get("/me"), []);
  const [f, setF] = useState({ skill: "", level: 2 });
  const [run, busy] = useAction();
  return (
    <>
      <PageHead title="Skill checks and badges" sub="Short proctored quizzes. Pass one and that skill shows as verified to employers." />
      <div className="split">
        <div className="col" style={{ gap: 16 }}>
          <div className="grid g3">{(badges || []).map((b) => (
            <div key={b.id} className="card pad col" style={{ alignItems: "center", textAlign: "center", opacity: b.revoked ? .5 : 1 }}>
              <div style={{ width: 70, height: 70, borderRadius: "50%", background: b.kind === "certificate" ? "var(--gold)" : "var(--brand-soft)", display: "grid", placeItems: "center", fontWeight: 900, fontSize: 18 }}>{b.level ? "L" + b.level : "★"}</div>
              <b>{b.title}</b><span className="tiny muted">{b.issuer} · {b.grade || b.kind}</span>
              <span className="tiny mono">{b.code}</span>{b.revoked && <Chip kind="bad">Revoked</Chip>}
              <Link className="small" to={`/verify/${b.code}`}>Verification page</Link>
            </div>))}</div>
          {badges && !badges.length && <Empty title="No badges yet" mascot={<Disha size={70} />} text="Take a skill check on the right. It takes about 12 minutes." />}
        </div>
        <form className="card pad col" onSubmit={(e) => { e.preventDefault(); run(() => api.post("/me/skill-check", f)).then((r) => nav(`/room/${r.attempt_id}`)); }}>
          <h3>Take a skill check</h3>
          <Field label="Skill"><Input list="myskills" value={f.skill} onChange={(e) => setF({ ...f, skill: e.target.value })} placeholder="e.g. Python" /><datalist id="myskills">{(me?.profile.skills || []).map((s) => <option key={s.name} value={s.name} />)}</datalist></Field>
          <Field label="Level"><Select value={String(f.level)} onChange={(v) => setF({ ...f, level: +v })} options={"12345".split("").map((l) => ({ value: l, label: "Level " + l }))} /></Field>
          <p className="small muted">8 questions · 12 minutes · fullscreen and camera on · score 70% to earn the badge.</p>
          <Btn kind="primary" type="submit" busy={busy} disabled={!f.skill}>Start skill check</Btn>
        </form>
      </div>
    </>
  );
}

export function Learning() {
  const { data, reload } = useAsync(() => api.get("/me/learning"), []);
  const [skill, setSkill] = useState("");
  const [run, busy] = useAction();
  return (
    <>
      <PageHead title="Learning paths" sub="Short, ordered topics with practice prompts. Disha builds them around your goal." />
      <form className="agent disha" style={{ alignItems: "center" }} onSubmit={(e) => { e.preventDefault(); run(() => api.post("/me/learning", { skill }), "Path ready").then(() => { setSkill(""); reload(); }); }}>
        <Disha size={40} /><Input value={skill} onChange={(e) => setSkill(e.target.value)} placeholder="What do you want to learn? e.g. Kafka, SQL joins, System design" /><Btn kind="primary" type="submit" busy={busy} disabled={!skill}>Build path</Btn></form>
      {!data ? <Loading /> : !data.length ? <Empty title="No paths yet" /> : data.map((lp) => {
        const done = lp.topics.filter((t) => t.done).length;
        return (
          <div key={lp.id} className="card">
            <div className="card-h"><div className="grow"><h3>{lp.title}</h3><div className="small muted">{lp.reason}</div></div><div style={{ width: 160 }}><Bar value={done} max={lp.topics.length} tone="good" /></div><b className="small">{done}/{lp.topics.length}</b>
              <Btn size="sm" kind="ghost" onClick={() => api.del(`/me/learning/${lp.id}`).then(reload)}>✕</Btn></div>
            {lp.topics.map((t, i) => <div key={i} className="list-row" style={{ alignItems: "flex-start" }}>
              <input type="checkbox" checked={!!t.done} onChange={(e) => api.patch(`/me/learning/${lp.id}/topics/${i}`, { done: e.target.checked }).then(reload)} aria-label={`Mark ${t.title} done`} />
              <div className="grow"><b style={{ textDecoration: t.done ? "line-through" : "none" }}>{i + 1}. {t.title}</b><div className="small">{t.summary}</div>{(t.practice || []).map((p, j) => <div key={j} className="small muted">• {p}</div>)}</div></div>)}
          </div>);
      })}
    </>
  );
}

export function Certs() {
  const nav = useNavigate();
  const { data: cat } = useAsync(() => api.get("/certs-catalog"), []);
  const { data: mine } = useAsync(() => api.get("/me/certifications"), []);
  const [run] = useAction();
  return (
    <>
      <PageHead title="Certifications" sub="Proctored exams that issue a verifiable certificate." />
      {mine?.length > 0 && <div className="card"><div className="card-h"><h3>Your attempts</h3></div>{mine.map((a) => (
        <div key={a.id} className="list-row" style={{ flexDirection: "column", alignItems: "stretch", gap: 8 }}>
          <div className="row wrap">
            <div className="grow"><b>{a.cert}</b><div className="small muted">{fmtDate(a.created_at)} · {a.progress ? `${a.progress.done} of ${a.progress.total} sections done` : `${a.sections} sections`}</div></div>
            {a.final && a.score != null ? <Chip kind={a.passed ? "good" : "bad"}>Score {Number(a.score).toFixed(1)}%</Chip> : <Chip>Progress {a.progress ? Math.round((100 * a.progress.done) / Math.max(1, a.progress.total)) : 0}%</Chip>}
            {a.grade && <Chip kind="good">{a.grade}</Chip>}<Status s={a.status} />
            {a.next_attempt_id && <Btn size="sm" kind="primary" onClick={() => nav(`/room/${a.next_attempt_id}`)}>Continue</Btn>}
          </div>
          {a.breakdown?.length > 0 && <div className="tbl-wrap"><table className="tbl small"><thead><tr><th>Section</th><th>Your score</th><th>Weight</th><th>Points toward total</th></tr></thead><tbody>
            {a.breakdown.map((b, i) => <tr key={i}><td>{b.name}</td><td>{b.done ? `${Number(b.pct).toFixed(1)}%` : <span className="faint">Not done yet</span>}{b.minimum ? <span className="tiny muted"> (minimum {b.minimum}%)</span> : null}</td><td>{b.weight}% of total</td><td>{b.points != null ? b.points.toFixed(1) : "—"}</td></tr>)}
            {a.final && <tr><td className="b">Total</td><td /><td>{a.breakdown.reduce((x, b) => x + b.weight, 0)}%</td><td className="b">{Number(a.score).toFixed(1)}%</td></tr>}
          </tbody></table></div>}
        </div>))}</div>}
      {!cat ? <Loading /> : <div className="grid g3">{cat.map((c) => (
        <div key={c.id} className="card pad col">
          <div className="row"><h3 className="grow">{c.name}</h3>{c.verified && <Chip kind="brand">Code2Hire Verified</Chip>}</div>
          <div className="small muted">{c.issuer} · Level {c.level} · {c.minutes} min · valid {c.validity_months} months · {c.fee ? "₹" + c.fee : "Free"}</div>
          <div className="row wrap">{c.sections.map((s, i) => <Chip key={i} title="Share of the final score">{s.name || ROUND_LABEL[s.type]} · weight {s.weight}%</Chip>)}</div>
          {c.eligible ? <Btn kind="primary" onClick={() => run(() => api.post(`/certs/${c.id}/start`)).then((r) => nav(`/room/${r.attempt_id}`))}>{c.why || "Start exam"}</Btn> : <span className="small" style={{ color: "var(--warn)" }}>{c.why}</span>}
        </div>))}</div>}
    </>
  );
}

export function Feedback() {
  const { data, reload } = useAsync(() => api.get("/me/feedback"), []);
  const [d, setD] = useState(null);
  const [run, busy] = useAction();
  if (!data) return <Loading />;
  return (
    <>
      <PageHead title="Feedback" sub="What employers shared after your rounds." />
      {!data.length && <Empty title="No feedback yet" mascot={<Disha size={70} />} text="When a company shares feedback, Disha turns it into clear next steps here." />}
      {data.map((r) => <div key={r.id} className="card pad col"><div className="row"><h3 className="grow">{r.job.title} · {r.round}</h3>{r.disputed ? <Chip kind="warn">Concern raised</Chip> : <Btn size="sm" kind="ghost" onClick={() => setD({ id: r.id, note: "" })}>Something looks wrong?</Btn>}</div><ReportView r={r} /></div>)}
      {d && <Modal title="Raise a concern" dirty={!!d.note.trim()} onClose={() => setD(null)} footer={(close) => <><Btn onClick={close}>Cancel</Btn><Btn kind="primary" busy={busy} disabled={d.note.trim().length < 10} onClick={() => run(() => api.post(`/me/feedback/${d.id}/dispute`, { note: d.note.trim() }), "Sent to the hiring team").then(() => { setD(null); reload(); }).catch(() => {})}>Send</Btn></>}>
        <p style={{ margin: 0 }}>Tell the team what you think is wrong, for example a technical problem during the round. A person will look into it and you'll see their answer here.</p>
        <Field label="What went wrong?" required hint={`${d.note.trim().length < 10 ? "At least 10 characters. " : ""}${2000 - d.note.length} characters left.`}><Textarea value={d.note} maxLength={2000} onChange={(e) => setD({ ...d, note: e.target.value })} autoFocus /></Field></Modal>}
    </>
  );
}

export function Profile() {
  const { logout } = useAuth();
  const nav = useNavigate();
  const toast = useToast();
  const { data, reload } = useAsync(() => api.get("/me"), []);
  const [f, setF] = useState(null);
  const [text, setText] = useState("");
  const [fe, setFe] = useState({});
  const [run, busy] = useAction();
  const ask = useConfirm();
  if (!data) return <Loading />;
  const p = f || { name: data.user.name, headline: data.profile.headline || "", location: data.profile.location || "", phone: data.profile.phone || "", experience_years: data.profile.experience_years || "", visibility: data.profile.visibility, skills: data.profile.skills || [] };
  const upload = async (file) => { const fd = new FormData(); fd.append("file", file); try { const r = await api.post("/me/resume", fd); toast(`Resume read. Found ${r.found_skills.length} new skills.`, "good"); setF(null); reload(); } catch (e) { toast(e.message, "bad"); } };
  return (
    <>
      <PageHead title="Profile and privacy" />
      <div className="grid g2">
        <div className="card pad col"><h3>About you</h3>
          <div className="grid g2"><Field label="Name" required error={fe.name}><Input value={p.name} maxLength={80} onChange={(e) => setF({ ...p, name: e.target.value })} /></Field><Field label="Headline" error={fe.headline}><Input value={p.headline} maxLength={120} placeholder="e.g. Backend developer" onChange={(e) => setF({ ...p, headline: e.target.value })} /></Field>
            <Field label="City" error={fe.location}><Input value={p.location} maxLength={120} placeholder="e.g. Bengaluru" onChange={(e) => setF({ ...p, location: e.target.value })} /></Field><Field label="Phone" error={fe.phone} hint="With country code, e.g. +91 98450 00000"><Input type="tel" inputMode="tel" maxLength={20} value={p.phone} onChange={(e) => setF({ ...p, phone: e.target.value.replace(/[^\d+\s\-()]/g, "") })} /></Field>
            <Field label="Years of experience" error={fe.experience_years}><Input type="number" min={0} max={60} step={1} value={p.experience_years ?? ""} onChange={(e) => setF({ ...p, experience_years: e.target.value === "" ? "" : Number(e.target.value) })} /></Field>
            <Field label="Who can see my profile"><Select value={p.visibility} onChange={(v) => setF({ ...p, visibility: v })} options={[{ value: "applied", label: "Only companies I apply to" }, { value: "everyone", label: "All employers on Code2Hire" }, { value: "nobody", label: "Nobody" }]} /></Field></div>
          <b className="small">Skills</b>
          {p.skills.map((s, i) => <div key={i} className="row"><span className="grow">{s.name}</span>{s.verified ? <Chip kind="good">L{s.level} verified</Chip> : <><div style={{ width: 110 }}><Select value={String(s.level)} onChange={(v) => setF({ ...p, skills: p.skills.map((x, j) => j === i ? { ...x, level: +v } : x) })} options={"12345".split("")} /></div><Btn size="sm" kind="ghost" onClick={() => setF({ ...p, skills: p.skills.filter((_, j) => j !== i) })}>✕</Btn></>}</div>)}
          <form className="row" onSubmit={(e) => { e.preventDefault(); const v = e.target.sk.value.trim(); if (v) { setF({ ...p, skills: [...p.skills, { name: v, level: 2 }] }); e.target.reset(); } }}><Input name="sk" placeholder="Add a skill" /><Btn type="submit">Add</Btn></form>
          <Btn kind="primary" busy={busy} onClick={() => { setFe({}); run(() => api.patch("/me/profile", { ...p, experience_years: p.experience_years === "" ? null : p.experience_years }), "Saved").then(() => { setF(null); reload(); }).catch((e) => e.fields && setFe(e.fields)); }}>Save profile</Btn>
        </div>
        <div className="col" style={{ gap: 16 }}>
          <div className="card pad col"><h3>Resume</h3>
            <label className="btn" style={{ alignSelf: "flex-start" }}>Upload PDF, DOCX or TXT<input type="file" accept=".pdf,.docx,.txt" hidden onChange={(e) => e.target.files[0] && upload(e.target.files[0])} /></label>
            <Field label="Or paste it"><Textarea value={text} onChange={(e) => setText(e.target.value)} placeholder={data.profile.resume_text ? "Paste a new version to replace the current one" : ""} /></Field>
            <Btn disabled={text.length < 20} onClick={() => run(() => api.post("/me/resume", { text }), "Resume saved").then(() => { setText(""); setF(null); reload(); })}>Save pasted resume</Btn>
            {data.profile.resume_text && <details><summary className="small">Current resume</summary><pre className="small" style={{ whiteSpace: "pre-wrap", fontFamily: "inherit" }}>{data.profile.resume_text}</pre></details>}
          </div>
          <div className="card pad col"><h3>Password</h3>
            {data && <PwCard />}
          </div>
          <div className="card pad col"><h3>Your data</h3>
            <Btn onClick={() => api.get("/me/export").then((d) => { const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([JSON.stringify(d, null, 2)], { type: "application/json" })); a.download = "code2hire-my-data.json"; a.click(); })}>Download my data</Btn>
            <Btn kind="danger" onClick={async () => { const c = await ask({ title: "Delete your account?", text: "This removes your personal data and signs you out. It can't be undone.", input: { label: "Type DELETE to confirm", required: true, match: "DELETE" }, yes: "Delete my account", danger: true }); if (c === "DELETE") run(() => api.del("/me", { confirm: "DELETE" })).then(() => { logout(); nav("/"); }); }}>Delete my account</Btn>
          </div>
        </div>
      </div>
    </>
  );
}

function PwCard() {
  const { me } = useAuth();
  const [open, setOpen] = useState(false);
  const viaLink = me?.link_session && me?.must_change_password;
  if (!open) return <div className="row"><span className="small muted grow">{viaLink ? "You haven't set a password yet." : "Change the password you sign in with."}</span><Btn onClick={() => setOpen(true)}>{viaLink ? "Set password" : "Change password"}</Btn></div>;
  return <PasswordForm needCurrent={!viaLink} onDone={() => setOpen(false)} />;
}
