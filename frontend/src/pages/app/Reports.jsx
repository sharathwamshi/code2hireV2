import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, getToken } from "../../api";
import DataTable from "../../components/DataTable";
import { AgentNote } from "../../components/Mascot";
import { DISPUTE_LABEL, DisputeReview } from "../admin/Admin";
import ReportView from "../../components/ReportView";
import { PageHead } from "../../components/Shell";
import { Btn, Chip, Field, Integrity, Input, Loading, Modal, ROUND_LABEL, Score, Seg, Select, Status, Textarea, fmtDate, useAction, useAsync, useToast, useConfirm } from "../../components/ui";

export function ReportsList() {
  const nav = useNavigate();
  return (
    <>
      <PageHead title="Reports" sub="Every round's report. Hira recommends; a named person reviews and decides." />
      <DataTable endpoint="/reports" defaultSort="created" onRow={(r) => nav(`/app/reports/${r.attempt_id}`)} searchPlaceholder="Search candidate…"
        filters={[{ key: "status", label: "Status", options: [{ value: "awaiting_review", label: "To review" }, { value: "reviewed", label: "Reviewed" }, { value: "shared", label: "Shared" }] },
          { key: "recommendation", label: "Recommendation", options: ["proceed", "hold", "reject"] },
          { key: "type", label: "Round", options: Object.entries(ROUND_LABEL).map(([value, label]) => ({ value, label })) },
          { key: "disputed", label: "Disputes", options: [{ value: "true", label: "Disputed only" }] }]}
        columns={[{ key: "candidate", label: "Candidate", sort: "candidate", render: (r) => <b>{r.candidate}</b> }, { key: "job", label: "Job" },
          { key: "round", label: "Round", render: (r) => <span className="small">{r.round}</span> },
          { key: "overall", label: "Score", sort: "overall", render: (r) => <Score value={r.overall} scale={r.scale} pct /> },
          { key: "recommendation", label: "Recommends", render: (r) => <Status s={r.recommendation} /> },
          { key: "verdict", label: "Decision", render: (r) => r.verdict ? <Chip kind="dark">{r.verdict}</Chip> : "—" },
          { key: "warnings", label: "Integrity", render: (r) => <Integrity count={r.warnings} /> },
          { key: "status", label: "Status", sort: "status", render: (r) => <span className="row"><Status s={r.status} />{r.disputed && <Chip kind="bad">Disputed</Chip>}</span> },
          { key: "completed_at", label: "Completed", sort: "created", render: (r) => fmtDate(r.completed_at) }]} />
    </>
  );
}

export function ReportPage() {
  const { attemptId } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const [aud, setAud] = useState("internal");
  const { data: r, reload, setData } = useAsync(() => api.get(`/reports/by-attempt/${attemptId}`), [attemptId]);
  const [review, setReview] = useState(false);
  const [share, setShare] = useState(false);
  const [tx, setTx] = useState(null);
  const [ev, setEv] = useState(null);
  const [run, busy] = useAction();
  const ask = useConfirm();
  const [disp, setDisp] = useState(false);
  if (!r) return <Loading />;
  if (r.pending) {
    const a = r.attempt;
    return (
      <>
        <PageHead back="/app/reports" title="Report not ready yet" sub={`${ROUND_LABEL[a.round_type]} · status ${a.status}`} />
        {a.status === "paused" ? (
          <div className="card pad col">
            <AgentNote agent="hira" title={`Paused: ${a.pause_reason}`}>The candidate is waiting. Look at the events below, then let them continue or end the round. Ending it scores what they've done so far.</AgentNote>
            {a.integrity_events.map((e) => <div key={e.id} className="row small"><Chip kind={e.counted ? "warn" : ""}>{e.event_type}</Chip>{e.note}<span className="faint">{fmtDate(e.created_at, true)}</span></div>)}
            <div className="row"><Btn kind="primary" busy={busy} onClick={() => run(() => api.post(`/rounds/${attemptId}/resume`, { note: "Allowed to continue" }), "Candidate can continue").then(reload)}>Let them continue</Btn>
              <Btn busy={busy} onClick={() => run(() => api.post(`/rounds/${attemptId}/resume`, { reset_warnings: true }), "Continued with warnings reset").then(reload)}>Continue and reset warnings</Btn>
              <Btn kind="danger" busy={busy} onClick={() => run(() => api.post(`/rounds/${attemptId}/resume`, { end: true }), "Round ended and scored").then(reload)}>End the round</Btn></div>
          </div>
        ) : <div className="card pad">The candidate hasn't finished this round yet. You'll get a notification when the report is ready.</div>}
      </>
    );
  }
  const loadAud = async (a) => { setAud(a); setData(await api.get(`/reports/${r.id}`, { audience: a })); };
  return (
    <>
      <PageHead back={r.application_id ? `/app/applications/${r.application_id}` : "/app/reports"} title={`${r.round} report`} sub={`${r.candidate?.name} · ${r.job?.title}`}
        actions={<>
          <Seg value={aud} onChange={loadAud} options={[["internal", "Internal"], ["hiring_manager", "Hiring manager"], ["client", "Client view"], ["candidate", "Candidate view"]]} />
          <Btn onClick={() => api.get(`/reports/${r.id}/transcript`).then(setTx)}>Transcript and events</Btn>
          {r.can?.review && <Btn kind="primary" onClick={() => setReview(true)}>{r.status === "awaiting_review" ? "Review" : "Edit review"}</Btn>}
          {r.can?.share && <Btn onClick={() => setShare(true)}>Share</Btn>}
        </>} />
      {r.status === "awaiting_review" && <AgentNote agent="hira" title="Waiting for a person">Check the evidence, change any score you disagree with (with a reason), and record your verdict. Nothing is shared until someone reviews it.</AgentNote>}
      {(r.dispute_status === "open") && <AgentNote agent="disha" title="The candidate raised a concern" action={r.can?.review && <Btn size="sm" kind="primary" onClick={() => setDisp(true)}>Review and decide</Btn>}>“{r.dispute_note}”</AgentNote>}
      {r.dispute_status && r.dispute_status !== "open" && <AgentNote agent="disha" title={`Concern resolved: ${DISPUTE_LABEL[r.dispute_status] || r.dispute_status}`}>{r.dispute_resolution}</AgentNote>}
      {disp && <DisputeReview row={{ id: r.id, candidate: r.candidate?.name, note: r.dispute_note, status: "open" }} onClose={() => setDisp(false)} onDone={() => { setDisp(false); reload(); }} />}
      {aud !== "internal" && <Chip kind="info">Previewing what the {aud.replace("_", " ")} sees</Chip>}
      {r.recording?.length > 0 && aud !== "client" && aud !== "candidate" && (
        <div className="card pad col"><div className="row"><h3>Call recording</h3><span className="small muted">{r.recording.map((p) => Math.round((p.seconds || 0) / 60) + " min").join(" + ")} · every view is logged</span></div>
          {r.recording.map((p) => <video key={p.part} controls preload="metadata" style={{ width: "100%", maxHeight: 420, background: "#000", borderRadius: 10 }} src={`/api/call/${r.attempt_id}/recording/${p.part}?token=${encodeURIComponent(getToken() || "")}`} />)}
        </div>
      )}
      <ReportView r={r} onEvidence={setEv} />
      {review && <Review r={r} onClose={() => setReview(false)} onDone={() => { setReview(false); reload(); toast("Review saved as a new version", "good"); }} />}
      {share && <Share r={r} onClose={() => setShare(false)} onDone={reload} />}
      {ev && <Modal title={ev.name} onClose={() => setEv(null)}><div className="row"><Score value={ev.score} /><Chip>{ev.level}</Chip>{ev.ai_score != null && <Chip kind="isha">Isha live: {ev.ai_score}</Chip>}</div>
        {ev.evidence ? <div className="quote">“{ev.evidence}”</div> : <p className="muted">No quote recorded.</p>}{ev.time && <div className="small muted">At {ev.time}</div>}{ev.note && <p>{ev.note}</p>}
        <Btn onClick={() => { setEv(null); api.get(`/reports/${r.id}/transcript`).then(setTx); }}>Open in transcript</Btn></Modal>}
      {tx && <Modal wide title="Transcript and integrity events" onClose={() => setTx(null)}>
        {tx.integrity.length > 0 && <div className="row wrap">{tx.integrity.map((e) => <Chip key={e.id} kind={e.counted ? "warn" : ""}>{e.event_type} · {fmtDate(e.created_at, true)}</Chip>)}</div>}
        {!tx.turns.length && <p className="muted">No spoken turns for this round.</p>}
        {tx.turns.map((t) => <div key={t.id} className="row" style={{ alignItems: "flex-start" }}><Chip kind={t.speaker === "candidate" ? "info" : t.speaker === "ai" ? "brand" : "isha"} style={{ width: 96 }}>{t.speaker === "ai" ? "Hira" : t.speaker}</Chip>
          <span className="tiny faint mono" style={{ width: 44 }}>{Math.floor((t.at_seconds || 0) / 60)}:{String((t.at_seconds || 0) % 60).padStart(2, "0")}</span>
          <div className="grow">{t.text}{t.analysis?.tags?.length > 0 && <div className="row wrap">{t.analysis.tags.map((g, i) => <Chip key={i} kind={g.type === "good" ? "good" : g.type === "flag" ? "bad" : g.type === "vague" ? "warn" : "info"}>{g.label}</Chip>)}</div>}</div></div>)}
      </Modal>}
    </>
  );
}

function Review({ r, onClose, onDone }) {
  const comps = r.sections?.competencies || [];
  const [edits, setEdits] = useState(comps.map((c) => ({ name: c.name, score: c.score, reason: "" })));
  const [verdict, setVerdict] = useState(r.verdict || r.recommendation || "proceed");
  const [note, setNote] = useState(r.note || "");
  const [run, busy] = useAction();
  const changed = edits.filter((e, i) => e.score !== comps[i].score);
  return (
    <Modal wide title="Review report" onClose={onClose} footer={<><Btn onClick={onClose}>Cancel</Btn><Btn kind="primary" busy={busy} onClick={() => run(() => api.post(`/reports/${r.id}/review`, { edits: changed, verdict, note })).then(onDone)}>Save review</Btn></>}>
      {comps.length > 0 && <div className="tbl-wrap"><table className="tbl"><thead><tr><th>Competency</th><th>AI / interviewer</th><th>Your score</th><th>Reason if changed</th></tr></thead><tbody>
        {edits.map((e, i) => <tr key={e.name}><td className="b">{e.name}</td><td><Score value={comps[i].score} /></td>
          <td style={{ width: 110 }}><Select value={String(e.score ?? "")} onChange={(v) => { const x = [...edits]; x[i] = { ...e, score: v === "" ? null : +v }; setEdits(x); }} options={["", "1", "1.5", "2", "2.5", "3", "3.5", "4", "4.5", "5"]} /></td>
          <td>{e.score !== comps[i].score && <Input placeholder="Required" value={e.reason} onChange={(ev) => { const x = [...edits]; x[i] = { ...e, reason: ev.target.value }; setEdits(x); }} />}</td></tr>)}
      </tbody></table></div>}
      <Field label="Your verdict for this round"><Seg value={verdict} onChange={setVerdict} options={[["proceed", "Proceed"], ["hold", "Hold"], ["reject", "Do not proceed"]]} /></Field>
      <Field label="Note for the team"><Textarea value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      <p className="small muted">Saving creates version {r.version + 1}. The original AI report is kept.</p>
    </Modal>
  );
}

function Share({ r, onClose, onDone }) {
  const [aud, setAud] = useState("client");
  const [days, setDays] = useState(7);
  const [res, setRes] = useState(null);
  const [run, busy] = useAction();
  return (
    <Modal title="Share report" onClose={onClose} footer={res ? <Btn onClick={onClose}>Done</Btn> : <Btn kind="primary" busy={busy} onClick={() => run(() => api.post(`/reports/${r.id}/share`, { audience: aud, days })).then((x) => { setRes(x || {}); onDone(); })}>Share</Btn>}>
      {!res ? <>
        <Field label="Share with"><Seg value={aud} onChange={setAud} options={[["client", "Client (link)"], ["hiring_manager", "Hiring manager (link)"], ["candidate", "Candidate (feedback)"]]} /></Field>
        {aud !== "candidate" ? <Field label="Link expires after (days)"><Input type="number" value={days} onChange={(e) => setDays(+e.target.value)} /></Field>
          : <AgentNote agent="disha">Disha turns this report into kind, specific feedback without scores or internal notes. The candidate can raise a concern if something looks wrong.</AgentNote>}
        <p className="small muted">Your company settings decide what each audience can see (use the view switch to preview). Sharing is logged and may need approval.</p>
      </> : res.approval ? <p>Sharing needs approval under company policy. It's waiting in Approvals.</p>
        : res.link ? <><p>Anyone with this link can read the {aud.replace("_", " ")} version until {fmtDate(res.expires_at)}.</p><div className="card pad mono small">{window.location.origin + res.link}</div>
          <Btn onClick={() => navigator.clipboard?.writeText(window.location.origin + res.link)}>Copy link</Btn></> : <p>Feedback sent to the candidate.</p>}
    </Modal>
  );
}
