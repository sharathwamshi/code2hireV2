import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../../api";
import { AgentNote } from "../../components/Mascot";
import { PageHead } from "../../components/Shell";
import { Avatar, Bar, Btn, Chip, Field, Input, Loading, Modal, ROUND_LABEL, Score, Status, Tabs, Textarea, fmtDate, useAction, useAsync, useToast } from "../../components/ui";
import { InviteModal } from "./Jobs";

export default function Application() {
  const { id } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const { data: a, reload } = useAsync(() => api.get(`/applications/${id}`), [id]);
  const { data: job } = useAsync(() => (a ? api.get(`/jobs/${a.job_id}`) : Promise.resolve(null)), [a?.job_id]);
  const [tab, setTab] = useState("rounds");
  const [modal, setModal] = useState(null);
  const [note, setNote] = useState("");
  const [run, busy] = useAction();
  const [packet, setPacket] = useState(null);
  if (!a) return <Loading />;
  const p = a.profile || {};
  const verdict = (v, extra = {}) => run(() => api.post(`/applications/${id}/verdict`, { verdict: v, ...extra })).then(() => { toast("Done", "good"); setModal(null); reload(); });
  const next = a.current_round + 1 < a.rounds.length ? a.rounds[a.current_round + 1] : null;
  return (
    <>
      <PageHead back={`/app/jobs/${a.job_id}`} title={<span className="row"><Avatar name={a.candidate.name} />{a.candidate.name}</span>}
        sub={<span className="row wrap"><Status s={a.stage} /><span>{a.job_title}</span><span>· {a.candidate.email}</span>{a.candidate.location && <span>· {a.candidate.location}</span>}{p.experience_years != null && <span>· {p.experience_years} yrs</span>}</span>}
        actions={<>
          <Btn onClick={() => api.get(`/applications/${id}/packet`).then(setPacket)}>Hiring packet</Btn>
          {a.can["interviews.run"] && next && <Btn kind="gold" onClick={() => setModal("invite")}>Invite to {next.name}</Btn>}
          {a.can["candidates.move"] && <Btn onClick={() => verdict("hold")}>Hold</Btn>}
          {a.can["candidates.move"] && <Btn kind="danger" onClick={() => setModal("reject")}>Reject</Btn>}
          {a.can["verdict.final"] && <Btn kind="primary" onClick={() => setModal("offer")}>Make offer</Btn>}
          {a.can["verdict.final"] && a.stage === "offer" && <Btn kind="primary" onClick={() => verdict("hired")}>Mark hired</Btn>}
        </>} />
      <div className="split">
        <div className="col" style={{ gap: 16 }}>
          <div className="card pad">
            <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
              {a.rounds.map((r, i) => {
                const att = a.attempts.filter((x) => x.round_index === i).slice(-1)[0];
                return (
                  <div key={i} className="row" style={{ gap: 6 }}>
                    {i > 0 && <span style={{ width: 20, height: 2, background: "var(--line-2)" }} />}
                    <div className="card" style={{ padding: "8px 12px", borderColor: att ? "var(--brand)" : "var(--line)", background: att?.status === "completed" || att?.status === "reviewed" ? "var(--good-soft)" : "#fff", minWidth: 150 }}>
                      <div className="tiny muted">Round {i + 1}</div><b className="small">{r.name || ROUND_LABEL[r.type]}</b>
                      <div>{att ? <Status s={att.status} /> : <span className="tiny faint">Not started</span>}{att?.score != null && <> <Score value={att.score} type={att.round_type} scale={a.scale || 5} /></>}</div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
          <Tabs value={tab} onChange={setTab} tabs={[["rounds", "Rounds and reports"], ["resume", "Resume"], ["notes", `Notes (${(a.notes || []).length})`]]} />
          {tab === "rounds" && (
            <div className="card">
              {!a.attempts.length && <div className="empty">No rounds yet. Invite the candidate to the first round.</div>}
              {a.attempts.map((att) => (
                <div key={att.id} className="list-row">
                  <div className="grow"><b>{att.name}</b><div className="small muted">{ROUND_LABEL[att.round_type]}{att.interviewer ? ` · ${att.interviewer}` : ""} · invited {fmtDate(att.created_at)}{att.completed_at ? ` · done ${fmtDate(att.completed_at)}` : att.deadline_at ? ` · due ${fmtDate(att.deadline_at)}` : ""}</div></div>
                  <Status s={att.status} />
                  {att.warnings > 0 && <Chip kind="warn">{att.warnings} warning{att.warnings > 1 ? "s" : ""}</Chip>}
                  {att.has_video && <Btn size="sm" kind="ghost" title="Watch the interview video" onClick={() => nav(`/app/reports/${att.id}#recording`)}>▶ Video</Btn>}
                  {att.setup && <Chip kind={att.setup.state === "tested" ? "good" : att.setup.state === "needs_help" ? "bad" : "warn"} title={att.setup.text}>{att.setup.state === "tested" ? "Setup tested ✓" : att.setup.state === "needs_help" ? "Needs help with setup" : "Setup check failed"}</Chip>}
                  {att.report ? <><Score value={att.report.overall} /><Chip kind={att.report.recommendation === "proceed" ? "good" : att.report.recommendation === "reject" ? "bad" : "warn"}>{att.report.recommendation}</Chip><Btn size="sm" kind="primary" onClick={() => nav(`/app/reports/${att.id}`)}>Open report</Btn></>
                    : (att.round_type === "f2f_isha" || att.round_type === "f2f_human") && !["completed", "reviewed", "cancelled", "expired"].includes(att.status) ? <Btn size="sm" kind="primary" onClick={() => nav(`/app/isha/${att.id}`)}>Open live room</Btn>
                    : att.status === "paused" ? <Btn size="sm" kind="danger" onClick={() => nav(`/app/reports/${att.id}`)}>Paused: review</Btn> : null}
                </div>
              ))}
              {a.can["interviews.run"] && a.attempts.length > 0 && <div className="list-row"><Btn size="sm" onClick={() => setModal("reinterview")}>Request a re-interview</Btn><span className="small muted">{a.reinterviews} used. Company policy limits re-interviews.</span></div>}
            </div>
          )}
          {tab === "resume" && <div className="card pad"><pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", margin: 0 }}>{p.resume_text || "No resume on file."}</pre></div>}
          {tab === "notes" && (
            <div className="card">
              {(a.notes || []).map((n, i) => <div key={i} className="list-row" style={{ alignItems: "flex-start" }}><Avatar name={n.by || "?"} /><div className="grow"><b className="small">{n.by}</b> <span className="tiny faint">{fmtDate(n.at, true)}</span>{n.kind === "reinterview" && <Chip kind="warn">Re-interview</Chip>}<div>{n.text}</div></div></div>)}
              <form className="list-row" onSubmit={(e) => { e.preventDefault(); if (note.trim()) run(() => api.post(`/applications/${id}/notes`, { text: note })).then(() => { setNote(""); reload(); }); }}>
                <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Add a note for the hiring team…" /><Btn type="submit" kind="primary">Add</Btn>
              </form>
            </div>
          )}
        </div>
        <div className="col" style={{ gap: 16 }}>
          <div className="card pad col">
            <div className="row"><h3>Match</h3><b className="right" style={{ fontSize: 22 }}>{a.match_score ?? "—"}%</b></div>
            <Bar value={a.match_score} />
            {(a.match_reasons?.reasons || []).map((r, i) => <div key={i} className="small">• {r}</div>)}
            {a.match_reasons?.matched?.length > 0 && <div className="row wrap">{a.match_reasons.matched.map((m, i) => <Chip key={i} kind="good">{m}</Chip>)}</div>}
            {a.match_reasons?.missing?.length > 0 && <div className="row wrap">{a.match_reasons.missing.map((m, i) => <Chip key={i} kind="bad">No {m}</Chip>)}</div>}
          </div>
          <div className="card pad col"><h3>Skills</h3><div className="row wrap">{(p.skills || []).map((s, i) => <Chip key={i} kind={s.verified ? "good" : ""}>{s.name} L{s.level}{s.verified ? " ✓ verified" : ""}</Chip>)}</div></div>
          {a.other_applications.length > 0 && <div className="card pad col"><h3>Also applied to</h3>{a.other_applications.map((o) => <div key={o.id} className="row"><a href={`/app/applications/${o.id}`}>{o.job}</a><Status s={o.stage} /></div>)}</div>}
          {a.verdict && <AgentNote agent="hira" title={`Decision: ${a.verdict}`}>{a.verdict_note || "No note."}</AgentNote>}
        </div>
      </div>
      {modal === "invite" && job && <InviteModal job={job} nextIndex={String(a.current_round + 1)} onClose={() => setModal(null)} onInvite={(x) => run(() => api.post(`/applications/${id}/invite`, x), "Invited").then(() => { setModal(null); reload(); })} />}
      {modal === "reject" && <VerdictModal title="Reject candidate" danger onClose={() => setModal(null)} onSubmit={(note) => verdict("reject", { note })} busy={busy} text="The candidate gets a polite message. If your company shares feedback, Disha turns the report into kind, useful notes." />}
      {modal === "offer" && <OfferModal job={job} onClose={() => setModal(null)} onSubmit={(salary, note) => verdict("offer", { salary, note })} busy={busy} />}
      {modal === "reinterview" && job && <Reinterview job={job} a={a} onClose={() => setModal(null)} onDone={reload} />}
      {packet && <Packet p={packet} onClose={() => setPacket(null)} />}
    </>
  );
}

function VerdictModal({ title, text, onClose, onSubmit, busy, danger }) {
  const [note, setNote] = useState("");
  return <Modal title={title} onClose={onClose} footer={<><Btn onClick={onClose}>Cancel</Btn><Btn kind={danger ? "danger" : "primary"} busy={busy} onClick={() => onSubmit(note)}>Confirm</Btn></>}>
    <p>{text}</p><Field label="Reason (kept in the audit log)"><Textarea value={note} onChange={(e) => setNote(e.target.value)} /></Field></Modal>;
}

function OfferModal({ job, onClose, onSubmit, busy }) {
  const [salary, setSalary] = useState("");
  const [note, setNote] = useState("");
  const over = job?.salary_max && +salary > job.salary_max;
  return <Modal title="Make an offer" onClose={onClose} footer={<><Btn onClick={onClose}>Cancel</Btn><Btn kind="primary" busy={busy} onClick={() => onSubmit(salary ? +salary : null, note)}>Create offer</Btn></>}>
    <Field label="Annual salary (₹)" hint={job?.salary_max ? `Band: ₹${job.salary_min?.toLocaleString("en-IN")} – ₹${job.salary_max.toLocaleString("en-IN")}` : "Salary band hidden"}><Input type="number" value={salary} onChange={(e) => setSalary(e.target.value)} /></Field>
    {over && <AgentNote agent="hira" title="Above the band">Company policy may need extra approvals. The offer waits in Approvals until they're given.</AgentNote>}
    <Field label="Note"><Textarea value={note} onChange={(e) => setNote(e.target.value)} /></Field></Modal>;
}

function Reinterview({ job, a, onClose, onDone }) {
  const { data: ivs } = useAsync(() => api.get("/company/interviewers"), []);
  const [f, setF] = useState({ round_index: String(Math.max(0, a.current_round)), reason: "", interviewer_id: "" });
  const [run, busy] = useAction();
  return <Modal title="Request a re-interview" onClose={onClose} footer={<Btn kind="primary" busy={busy} onClick={() => run(() => api.post(`/applications/${a.id}/reinterview`, { ...f, round_index: +f.round_index, interviewer_id: f.interviewer_id || undefined }), "Re-interview sent").then(() => { onClose(); onDone(); })}>Send</Btn>}>
    <Field label="Round"><select className="select" value={f.round_index} onChange={(e) => setF({ ...f, round_index: e.target.value })}>{job.rounds.map((r, i) => <option key={i} value={i}>{i + 1}. {r.name}</option>)}</select></Field>
    {["f2f_isha", "f2f_human"].includes(job.rounds[+f.round_index]?.type) && <Field label="Interviewer"><select className="select" value={f.interviewer_id} onChange={(e) => setF({ ...f, interviewer_id: e.target.value })}><option value="">Choose…</option>{(ivs || []).map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</select></Field>}
    <Field label="Why (shared with the team, logged)"><Textarea value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} /></Field></Modal>;
}

function Packet({ p, onClose }) {
  return (
    <Modal wide title={`Hiring packet: ${p.application.candidate.name}`} onClose={onClose} footer={<Btn onClick={() => window.print()}>Print</Btn>}>
      <div className="row wrap"><Chip kind="brand">{p.job.title}</Chip><Status s={p.application.stage} /><Chip>Match {p.application.match_score}%</Chip></div>
      {p.reports.map((r, i) => (
        <div key={i} className="card pad col">
          <div className="row"><b>{r.round}</b><Score value={r.overall} /><Chip kind={r.recommendation === "proceed" ? "good" : r.recommendation === "reject" ? "bad" : "warn"}>{r.recommendation}</Chip>{r.verdict && <Chip kind="dark">{r.verdict}</Chip>}{r.warnings > 0 && <Chip kind="warn">{r.warnings} warnings</Chip>}</div>
          <p>{r.summary}</p>
          <div className="row wrap">{(r.strengths || []).map((s, j) => <Chip key={j} kind="good">{s}</Chip>)}{(r.gaps || []).map((s, j) => <Chip key={j} kind="bad">{s}</Chip>)}</div>
        </div>
      ))}
      {new Set(p.reports.map((r) => r.recommendation)).size > 1 && <AgentNote agent="hira" title="Rounds disagree">Rounds gave different recommendations. Read the gaps above before deciding.</AgentNote>}
    </Modal>
  );
}
