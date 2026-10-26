import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import DataTable from "../../components/DataTable";
import { AgentNote, Hira } from "../../components/Mascot";
import SettingsEditor, { VoiceSelect, VoicesMulti, companySettings } from "../../components/Settings";
import { PageHead } from "../../components/Shell";
import { Bar, Btn, Chip, Field, Input, Loading, Modal, ROUND_LABEL, Select, Status, Switch, Tabs, Textarea, fmtDate, inr, useAction, useAsync, useToast } from "../../components/ui";
import { RoundsEditor } from "../admin/Admin";

export function JobsList() {
  const nav = useNavigate();
  const { can } = useAuth();
  const [mine, setMine] = useState(false);
  return (
    <>
      <PageHead title="Jobs" sub="Every job you can see. Click one to open its candidates."
        actions={can("jobs.create") && <Btn kind="primary" onClick={() => nav("/app/jobs/new")}>New job with Hira</Btn>} />
      <DataTable endpoint="/jobs" defaultSort="created" onRow={(r) => nav(`/app/jobs/${r.id}`)} params={{ mine: mine ? "true" : "" }}
        toolbar={<label className="check small"><input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} />Only mine</label>}
        filters={[{ key: "status", label: "Status", options: [["live", "Live"], ["draft", "Draft"], ["pending_approval", "Awaiting approval"], ["closed", "Closed"]].map(([value, label]) => ({ value, label })) },
          { key: "visibility", label: "Visibility", options: ["public", "private", "internal"] }]}
        columns={[
          { key: "title", label: "Job", sort: "title", render: (r) => <div><b>{r.title}</b><div className="tiny muted">{r.level} · {r.location} · {r.work_mode}</div></div> },
          { key: "status", label: "Status", sort: "status", render: (r) => <Status s={r.status} /> },
          { key: "visibility", label: "Visibility", render: (r) => <Chip>{r.visibility}</Chip> },
          { key: "applications", label: "Applicants", render: (r) => <b>{r.applications}</b> },
          { key: "in_review", label: "To review", render: (r) => r.in_review ? <Chip kind="warn">{r.in_review}</Chip> : "—" },
          { key: "hired", label: "Hired", render: (r) => `${r.hired} / ${r.hires_target}` },
          { key: "team", label: "Team" }, { key: "owner", label: "Owner" },
          { key: "deadline", label: "Deadline", sort: "deadline", render: (r) => r.deadline ? fmtDate(r.deadline) : "—" },
        ]} />
    </>
  );
}

// ---------------------------------------------------------------- new job: Hira drafts, you edit, in 5 steps

const STEPS = ["Describe", "Skills", "Rounds", "Details", "Review"];

export function JobNew() {
  const nav = useNavigate();
  const toast = useToast();
  const [step, setStep] = useState(0);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState({ title: "", summary: "", description: "", skills: [], level: "Mid", rounds: [], questions: [], location: "Bengaluru", work_mode: "hybrid", visibility: "private", hires_target: 1 });
  const { data: tpl } = useAsync(() => api.get("/templates"), []);
  const { data: comp } = useAsync(() => api.get("/company"), []);
  const draft = async () => {
    setBusy(true);
    try { const d = await api.post("/jobs/draft", { text }); setJob({ ...job, ...d }); setStep(1); toast("Hira drafted the plan. Check each step.", "good"); }
    catch (e) { toast(e.message, "bad"); } finally { setBusy(false); }
  };
  const create = async (publish) => {
    setBusy(true);
    try {
      const j = await api.post("/jobs", job);
      if (publish) { const p = await api.post(`/jobs/${j.id}/publish`); toast(p.approval ? "Sent for approval (company policy)." : "Published.", "good"); }
      nav(`/app/jobs/${j.id}`);
    } catch (e) { toast(e.message, "bad"); } finally { setBusy(false); }
  };
  const set = (k, v) => setJob({ ...job, [k]: v });
  return (
    <>
      <PageHead back="/app/jobs" title="New job" sub="Paste anything about the role. Hira drafts the plan; you check every step." />
      <div className="card">
        <div className="stepper" style={{ borderBottom: "1px solid var(--line)" }}>
          {STEPS.map((s, i) => <span key={s} style={{ display: "contents" }}>{i > 0 && <span className="sep" />}
            <button className={"st " + (i === step ? "on" : i < step ? "done" : "")} onClick={() => (i <= step || job.title) && setStep(i)}><i>{i < step ? "✓" : i + 1}</i>{s}</button></span>)}
        </div>
        <div className="card-b col" style={{ gap: 16, minHeight: 360 }}>
          {step === 0 && (
            <>
              <AgentNote agent="hira" title="Paste a JD, an email from the hiring manager, or just a line">For example: “Senior Java engineer, Spring Boot, Kafka, 5+ years, Bengaluru hybrid”. I'll draft skills with levels, rounds and first questions.</AgentNote>
              <Textarea style={{ minHeight: 200 }} value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste the job description here…" />
              <div className="row wrap"><Btn kind="primary" busy={busy} disabled={text.trim().length < 5} onClick={draft}>Draft with Hira</Btn><Btn kind="ghost" onClick={() => setStep(1)}>Start from scratch</Btn>
                {tpl?.length > 0 && <div className="right row"><span className="small muted">or start from a template</span><div style={{ width: 240 }}><Select value="" onChange={(id) => { const t = tpl.find((x) => String(x.id) === id); if (t) { setJob({ ...job, rounds: t.rounds, rubric: t.rubric, template_id: t.id }); toast(`Template “${t.name}” applied`); } }} options={[{ value: "", label: "Choose template…" }, ...tpl.map((t) => ({ value: String(t.id), label: t.name + (t.global ? " (global)" : "") }))]} /></div></div>}
              </div>
            </>
          )}
          {step === 1 && (
            <>
              <div className="grid g2"><Field label="Job title"><Input value={job.title} onChange={(e) => set("title", e.target.value)} /></Field>
                <Field label="Level"><Select value={job.level} onChange={(v) => set("level", v)} options={["Junior", "Mid", "Senior", "Lead"]} /></Field></div>
              <Field label="Description"><Textarea value={job.description} onChange={(e) => set("description", e.target.value)} /></Field>
              <b>Skills and levels</b>
              <SkillsEditor skills={job.skills} onChange={(s) => set("skills", s)} />
            </>
          )}
          {step === 2 && (
            <>
              <AgentNote agent="hira">Rounds run in this order. Each round inherits your company's settings (questions, time, voice, integrity, pass rules); you can fine-tune them per round after creating the job.</AgentNote>
              <RoundsEditor rounds={job.rounds} onChange={(r) => set("rounds", r)} />
              {job.questions?.length > 0 && <div className="col"><b>First interview questions Hira drafted</b>{job.questions.map((q, i) => <div key={i} className="quote">{q}</div>)}</div>}
            </>
          )}
          {step === 3 && (
            <div className="grid g2">
              <Field label="Location"><Input value={job.location} onChange={(e) => set("location", e.target.value)} /></Field>
              <Field label="Work mode"><Select value={job.work_mode} onChange={(v) => set("work_mode", v)} options={["onsite", "hybrid", "remote"]} /></Field>
              <Field label="Team"><Select value={String(job.team_id || "")} onChange={(v) => set("team_id", v ? +v : null)} options={[{ value: "", label: "No team" }, ...(comp?.teams || []).map((t) => ({ value: String(t.id), label: t.name }))]} /></Field>
              <Field label="Visibility" hint="Public shows on the Code2Hire job board. Private is invite-link only. Internal is for employees."><Select value={job.visibility} onChange={(v) => set("visibility", v)} options={["private", "public", "internal"]} /></Field>
              <Field label="Salary from (₹ / year)"><Input type="number" value={job.salary_min || ""} onChange={(e) => set("salary_min", +e.target.value || null)} /></Field>
              <Field label="Salary to (₹ / year)"><Input type="number" value={job.salary_max || ""} onChange={(e) => set("salary_max", +e.target.value || null)} /></Field>
              <label className="check"><input type="checkbox" checked={!!job.salary_visible} onChange={(e) => set("salary_visible", e.target.checked)} />Show salary to candidates</label>
              <Field label="Hires needed"><Input type="number" value={job.hires_target} onChange={(e) => set("hires_target", +e.target.value)} /></Field>
              <Field label="Deadline"><Input type="date" value={job.deadline || ""} onChange={(e) => set("deadline", e.target.value)} /></Field>
              <Field label="Client name (agencies)"><Input value={job.client_name || ""} onChange={(e) => set("client_name", e.target.value)} /></Field>
              <label className="check"><input type="checkbox" checked={!!job.client_hidden} onChange={(e) => set("client_hidden", e.target.checked)} />Hide company name from candidates (confidential)</label>
            </div>
          )}
          {step === 4 && (
            <div className="col">
              <h2>{job.title || "Untitled role"}</h2>
              <div className="row wrap"><Chip>{job.level}</Chip><Chip>{job.location}</Chip><Chip>{job.work_mode}</Chip><Chip kind="brand">{job.visibility}</Chip>{job.salary_max && <Chip>{inr(job.salary_min)} – {inr(job.salary_max)}</Chip>}</div>
              <div className="row wrap">{job.skills.map((s, i) => <Chip key={i} kind={s.must ? "brand" : ""}>{s.name} L{s.level}{s.must ? " · must" : ""}</Chip>)}</div>
              <div className="row wrap">{job.rounds.map((r, i) => <Chip key={i} kind="info">{i + 1}. {r.name || ROUND_LABEL[r.type]}</Chip>)}</div>
              <p className="muted">{job.description}</p>
            </div>
          )}
        </div>
        <div className="modal-f">
          {step > 0 && <Btn onClick={() => setStep(step - 1)}>Back</Btn>}
          {step > 0 && step < 4 && <Btn kind="primary" onClick={() => setStep(step + 1)}>Next</Btn>}
          {step === 4 && <><Btn busy={busy} onClick={() => create(false)}>Save as draft</Btn><Btn kind="primary" busy={busy} onClick={() => create(true)}>Create and publish</Btn></>}
        </div>
      </div>
    </>
  );
}

function SkillsEditor({ skills, onChange }) {
  const [n, setN] = useState("");
  return (
    <div className="col">
      {skills.map((s, i) => (
        <div key={i} className="row">
          <Input value={s.name} onChange={(e) => { const x = [...skills]; x[i] = { ...s, name: e.target.value }; onChange(x); }} />
          <div style={{ width: 120 }}><Select value={String(s.level)} onChange={(v) => { const x = [...skills]; x[i] = { ...s, level: +v }; onChange(x); }} options={["1", "2", "3", "4", "5"].map((l) => ({ value: l, label: "Level " + l }))} /></div>
          <label className="check small" style={{ width: 110 }}><input type="checkbox" checked={!!s.must} onChange={(e) => { const x = [...skills]; x[i] = { ...s, must: e.target.checked }; onChange(x); }} />Must-have</label>
          <Btn size="sm" kind="ghost" onClick={() => onChange(skills.filter((_, j) => j !== i))} aria-label="Remove skill">✕</Btn>
        </div>
      ))}
      <form className="row" onSubmit={(e) => { e.preventDefault(); if (n.trim()) { onChange([...skills, { name: n.trim(), level: 3, must: false }]); setN(""); } }}>
        <Input placeholder="Add a skill" value={n} onChange={(e) => setN(e.target.value)} /><Btn type="submit">Add</Btn>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------- job detail

export function JobDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const [tab, setTab] = useState("candidates");
  const { data: job, reload, error } = useAsync(() => api.get(`/jobs/${id}`), [id]);
  const [run, busy] = useAction();
  if (error) return <div className="card pad">{error}</div>;
  if (!job) return <Loading />;
  const link = window.location.origin + job.invite_link;
  return (
    <>
      <PageHead back="/app/jobs" title={job.title}
        sub={<span className="row wrap"><Status s={job.status} /><Chip>{job.visibility}</Chip><span>{job.level} · {job.location} · {job.work_mode}</span>{job.team && <Chip>{job.team}</Chip>}{job.client_name && <Chip kind="gold">Client: {job.client_name}</Chip>}</span>}
        actions={<>
          {job.status !== "live" && job.can["jobs.edit"] && <Btn kind="primary" busy={busy} onClick={() => run(() => api.post(`/jobs/${id}/publish`)).then((r) => { toast(r.approval ? "Sent for approval (company policy)." : "Published.", "good"); reload(); })}>Publish</Btn>}
          {job.status === "live" && <Btn onClick={() => { navigator.clipboard?.writeText(link); toast("Invite link copied"); }}>Copy invite link</Btn>}
          {job.status === "live" && job.can["jobs.edit"] && <Btn kind="danger" onClick={() => run(() => api.post(`/jobs/${id}/close`), "Closed").then(reload)}>Close job</Btn>}
          <Btn onClick={() => run(() => api.post(`/jobs/${id}/duplicate`)).then((j) => nav(`/app/jobs/${j.id}`))}>Duplicate</Btn>
        </>} />
      <div className="grid g4">
        {[["Applied", "applied"], ["Shortlisted", "shortlisted"], ["In a round", "in_round"], ["To review", "awaiting_review"], ["Decision", "decision"], ["Offer", "offer"], ["Hired", "hired"], ["Rejected", "rejected"]].map(([l, k]) =>
          <div key={k} className="card stat"><div className="l">{l}</div><div className="v">{job.funnel[k] || 0}</div></div>)}
      </div>
      <Tabs value={tab} onChange={setTab} tabs={[["candidates", "Candidates"], ["pipeline", "Rounds and rules"], ["settings", "Job settings"], ["team", "Team"], ["about", "About the job"]]} />
      {tab === "candidates" && <Candidates job={job} onChange={reload} />}
      {tab === "pipeline" && <Pipeline job={job} onChange={reload} />}
      {tab === "settings" && <><AgentNote agent="hira">Settings here apply only to this job and override the team and company values, unless they are locked above. Round-level tweaks live under “Rounds and rules”.</AgentNote><SettingsEditor {...companySettings("job", job.id)} allowLock={false} /></>}
      {tab === "team" && <JobTeam job={job} onChange={reload} />}
      {tab === "about" && <div className="card pad col"><p style={{ whiteSpace: "pre-wrap" }}>{job.description}</p><div className="row wrap">{(job.skills || []).map((s, i) => <Chip key={i} kind={s.must ? "brand" : ""}>{s.name} L{s.level}</Chip>)}</div>
        {job.salary_max != null && <div>Salary band: {inr(job.salary_min)} – {inr(job.salary_max)} {job.salary_visible ? "(shown to candidates)" : "(hidden)"}</div>}
        <div className="small muted">Invite link: <span className="mono">{link}</span></div></div>}
    </>
  );
}

function Candidates({ job, onChange }) {
  const nav = useNavigate();
  const toast = useToast();
  const [ask, setAsk] = useState("");
  const [chips, setChips] = useState([]);
  const [rk, setRk] = useState(0);
  const [add, setAdd] = useState(false);
  const [inviteFor, setInviteFor] = useState(null);
  const [run, busy] = useAction();
  const params = {};
  chips.forEach((c) => {
    if (c.field === "match_score" && c.op === "gte") params.min_match = c.value;
    else if (c.field === "match_score" && c.op === "lte") params.max_match = c.value;
    else if (c.field === "stage") params.stage = params.stage ? params.stage + "," + c.value : c.value;
    else if (c.field === "q") params.q = c.value;
  });
  const askHira = async (e) => {
    e.preventDefault();
    if (!ask.trim()) return;
    try { const r = await api.post(`/jobs/${job.id}/ask`, { text: ask }); setChips(r.chips || []); if (!r.chips?.length) toast("Hira couldn't turn that into filters. Try “shortlisted above 70”."); }
    catch (x) { toast(x.message, "bad"); }
  };
  const bulk = (action, ids, done, extra = {}) => run(() => api.post(`/jobs/${job.id}/bulk`, { ids, action, ...extra })).then((r) => {
    toast(`${r.done} updated${r.failed.length ? `, ${r.failed.length} not: ${r.failed[0].error}` : ""}`, r.failed.length ? "bad" : "good"); done(); onChange();
  });
  return (
    <>
      <form className="agent hira" onSubmit={askHira} style={{ alignItems: "center" }}>
        <Hira size={40} />
        <input className="input grow" value={ask} onChange={(e) => setAsk(e.target.value)} placeholder="Ask Hira: “shortlisted with Python above 70”, “awaiting review”, “mentions AWS”…" aria-label="Ask Hira to filter" />
        <Btn kind="primary" type="submit">Ask Hira</Btn>
        {job.can["candidates.move"] && <Btn busy={busy} type="button" onClick={() => run(() => api.post(`/jobs/${job.id}/shortlist`, { threshold: 60 })).then((r) => { toast(`Hira scored ${r.scored} new applicants; 60%+ are shortlisted.`, "good"); setRk(rk + 1); onChange(); })}>Score new applicants</Btn>}
        {job.can["candidates.move"] && <Btn type="button" onClick={() => setAdd(true)}>Add candidates</Btn>}
      </form>
      <DataTable endpoint={`/jobs/${job.id}/applications`} defaultSort="match" reloadKey={rk + JSON.stringify(params)} params={params} chips={chips}
        onClearChip={(i) => setChips(chips.filter((_, j) => j !== i))} selectable={job.can["candidates.move"]} viewKey="applications"
        onRow={(r) => nav(`/app/applications/${r.id}`)} searchPlaceholder="Search name or email…"
        filters={[{ key: "stage", label: "Stage", options: [["applied", "Applied"], ["shortlisted", "Shortlisted"], ["in_round", "In a round"], ["awaiting_review", "To review"], ["decision", "Decision"], ["offer", "Offer"], ["hired", "Hired"], ["rejected", "Rejected"], ["on_hold", "On hold"]].map(([value, label]) => ({ value, label })) },
          { key: "source", label: "Source", options: ["applied", "invited", "bulk", "pool"] }]}
        bulk={(ids, done) => <>
          <Btn size="sm" onClick={() => bulk("shortlist", ids, done)}>Shortlist</Btn>
          {job.can["interviews.run"] && <Btn size="sm" kind="gold" onClick={() => setInviteFor({ ids, done })}>Invite to next round</Btn>}
          <Btn size="sm" onClick={() => bulk("hold", ids, done)}>Hold</Btn>
          <Btn size="sm" kind="danger" onClick={() => bulk("reject", ids, done)}>Reject</Btn>
        </>}
        columns={[
          { key: "name", label: "Candidate", sort: "name", render: (r) => <div><b>{r.candidate.name}</b><div className="tiny muted">{r.candidate.headline || r.candidate.email}</div></div> },
          { key: "match", label: "Match", sort: "match", render: (r) => <div style={{ minWidth: 130 }}><div className="row"><div className="grow"><Bar value={r.match_score} /></div><b className="small">{r.match_score ?? "—"}%</b></div>
            <div className="tiny muted ellipsis" style={{ maxWidth: 220 }}>{(r.match_reasons?.reasons || []).join(" · ") || (r.match_reasons?.missing?.length ? "Missing " + r.match_reasons.missing.join(", ") : "")}</div></div> },
          { key: "stage", label: "Stage", sort: "stage", render: (r) => <Status s={r.stage} /> },
          { key: "round", label: "Current round", render: (r) => r.round_name ? <span className="small">{r.round_name}{r.last_round && <> · <Status s={r.last_round.status} /></>}</span> : "—" },
          { key: "score", label: "Last score", render: (r) => r.last_round?.score != null ? <b>{r.last_round.type === "mcq" ? r.last_round.score + "%" : r.last_round.score + "/5"}</b> : "—" },
          { key: "warnings", label: "Integrity", render: (r) => r.last_round ? (r.last_round.warnings ? <Chip kind="warn">{r.last_round.warnings} warning{r.last_round.warnings > 1 ? "s" : ""}</Chip> : <Chip kind="good">Clean</Chip>) : "—" },
          { key: "skills", label: "Skills", render: (r) => <div className="row wrap" style={{ maxWidth: 260 }}>{r.candidate.skills.slice(0, 4).map((s, i) => <Chip key={i} kind={s.verified ? "good" : ""}>{s.name}{s.verified ? " ✓" : ""}</Chip>)}</div> },
          { key: "source", label: "Source", render: (r) => <span className="small">{r.source}</span> },
          { key: "applied", label: "Applied", sort: "applied", render: (r) => fmtDate(r.created_at) },
        ]} />
      {add && <AddCandidates job={job} onClose={() => setAdd(false)} onDone={() => { setRk(rk + 1); onChange(); }} />}
      {inviteFor && <InviteModal job={job} onClose={() => setInviteFor(null)} onInvite={(extra) => bulk("invite", inviteFor.ids, () => { inviteFor.done(); setInviteFor(null); }, extra)} />}
    </>
  );
}

export function InviteModal({ job, onClose, onInvite, nextIndex }) {
  const { data: ivs } = useAsync(() => api.get("/company/interviewers"), []);
  const [f, setF] = useState({ round_index: nextIndex ?? "", interviewer_id: "", scheduled_at: "" });
  const rt = f.round_index !== "" ? job.rounds[+f.round_index]?.type : null;
  const f2f = rt === "f2f_isha" || rt === "f2f_human";
  return (
    <Modal title="Invite to a round" onClose={onClose} footer={<><Btn onClick={onClose}>Cancel</Btn><Btn kind="primary" onClick={() => onInvite({ round_index: f.round_index === "" ? undefined : +f.round_index, interviewer_id: f.interviewer_id || undefined, scheduled_at: f.scheduled_at || undefined })}>Send invites</Btn></>}>
      <Field label="Round" hint="Leave as “next round” to move each candidate one step on."><Select value={String(f.round_index)} onChange={(v) => setF({ ...f, round_index: v })} options={[{ value: "", label: "Next round for each candidate" }, ...job.rounds.map((r, i) => ({ value: String(i), label: `${i + 1}. ${r.name || ROUND_LABEL[r.type]}` }))]} /></Field>
      {(f2f || f.round_index === "") && <Field label="Interviewer (for face-to-face rounds)"><Select value={String(f.interviewer_id)} onChange={(v) => setF({ ...f, interviewer_id: v })} options={[{ value: "", label: "Choose…" }, ...(ivs || []).map((u) => ({ value: String(u.id), label: `${u.name}${u.skills_meta?.skills ? " · " + u.skills_meta.skills.join(", ") : ""}` }))]} /></Field>}
      {(f2f || f.round_index === "") && <Field label="When"><Input type="datetime-local" value={f.scheduled_at} onChange={(e) => setF({ ...f, scheduled_at: e.target.value })} /></Field>}
      <p className="small muted">Candidates get an email and an inbox card with the deadline. Credits are used when an invite is sent.</p>
    </Modal>
  );
}

function AddCandidates({ job, onClose, onDone }) {
  const [rows, setRows] = useState([{ name: "", email: "", resume_text: "" }]);
  const [csv, setCsv] = useState("");
  const [run, busy] = useAction();
  const parse = () => {
    const out = csv.split("\n").map((l) => l.split(",").map((x) => x.trim())).filter((x) => x[1]?.includes("@")).map(([name, email, ...rest]) => ({ name, email, resume_text: rest.join(", ") }));
    if (out.length) setRows(out);
  };
  return (
    <Modal wide title="Add candidates" onClose={onClose} footer={<><Btn onClick={onClose}>Cancel</Btn><Btn kind="primary" busy={busy} onClick={() => run(() => api.post(`/jobs/${job.id}/applications`, { candidates: rows.filter((r) => r.email) })).then((r) => { onDone(); onClose(); alert(`${r.added.length} added${r.skipped.length ? `, ${r.skipped.length} already applied or not candidates` : ""}.`); })}>Add {rows.filter((r) => r.email).length}</Btn></>}>
      {rows.map((r, i) => (
        <div key={i} className="grid g3">
          <Input placeholder="Name" value={r.name} onChange={(e) => { const x = [...rows]; x[i] = { ...r, name: e.target.value }; setRows(x); }} />
          <Input placeholder="Email" value={r.email} onChange={(e) => { const x = [...rows]; x[i] = { ...r, email: e.target.value }; setRows(x); }} />
          <Input placeholder="Resume text or skills (optional)" value={r.resume_text} onChange={(e) => { const x = [...rows]; x[i] = { ...r, resume_text: e.target.value }; setRows(x); }} />
        </div>
      ))}
      <Btn size="sm" onClick={() => setRows([...rows, { name: "", email: "", resume_text: "" }])}>+ Another</Btn>
      <div className="divider" />
      <Field label="Or paste CSV: name, email, skills or resume text"><Textarea value={csv} onChange={(e) => setCsv(e.target.value)} placeholder={"Asha Rao, asha@example.com, Python Django SQL\nVikas, vikas@example.com, React"} /></Field>
      <Btn size="sm" onClick={parse}>Read CSV</Btn>
    </Modal>
  );
}

function Pipeline({ job, onChange }) {
  const [edit, setEdit] = useState(null);
  const [rounds, setRounds] = useState(job.rounds);
  const [run, busy] = useAction();
  useEffect(() => setRounds(job.rounds), [job.rounds]);
  const save = (r) => run(() => api.patch(`/jobs/${job.id}`, { rounds: r }), "Rounds saved").then(onChange);
  return (
    <div className="split">
      <div className="col">
        {job.rounds_resolved.map((r) => (
          <div key={r.index} className="card pad col">
            <div className="row"><span className="chip brand">{r.index + 1}</span><h3>{r.name}</h3><Chip>{ROUND_LABEL[r.type]}</Chip>
              {Object.keys(r.config || {}).length > 0 && <Chip kind="good">{Object.keys(r.config).length} round override{Object.keys(r.config).length > 1 ? "s" : ""}</Chip>}
              {job.can["jobs.edit"] && <Btn size="sm" className="right" onClick={() => setEdit(r)}>Configure round</Btn>}</div>
            <div className="row wrap small">
              {Object.entries(r.resolved).filter(([k]) => !k.startsWith("integrity.") && !k.startsWith("report.")).map(([k, v]) => <Chip key={k} kind={k in (r.config || {}) ? "good" : ""}>{k.split(".")[1].replace(/_/g, " ")}: {Array.isArray(v) ? v.length + " selected" : String(v)}</Chip>)}
            </div>
            <div className="row wrap small"><span className="faint">Integrity:</span>{Object.entries(r.resolved).filter(([k]) => k.startsWith("integrity.")).map(([k, v]) => <Chip key={k} kind={k in (r.config || {}) ? "good" : ""}>{k.split(".")[1].replace(/_/g, " ")}: {Array.isArray(v) ? v.join(", ") || "none" : String(v)}</Chip>)}</div>
          </div>
        ))}
      </div>
      <div className="card pad col">
        <h3>Change the rounds</h3>
        <p className="small muted">Candidates already in a round keep the settings they were invited with.</p>
        <RoundsEditor rounds={rounds} onChange={setRounds} />
        <Btn kind="primary" busy={busy} disabled={!job.can["jobs.edit"]} onClick={() => save(rounds)}>Save rounds</Btn>
      </div>
      {edit && <RoundConfig job={job} round={edit} onClose={() => setEdit(null)} onSave={(cfg) => { const r = job.rounds.map((x, i) => i === edit.index ? { ...x, config: cfg } : x); save(r).then(() => setEdit(null)); }} />}
    </div>
  );
}

function RoundConfig({ round, onClose, onSave }) {
  const [cfg, setCfg] = useState({ ...(round.config || {}) });
  const keys = Object.keys(round.resolved);
  const val = (k) => (k in cfg ? cfg[k] : round.resolved[k]);
  const setK = (k, v) => setCfg({ ...cfg, [k]: v });
  return (
    <Modal wide title={`Configure: ${round.name}`} onClose={onClose} footer={<><Btn onClick={() => setCfg({})}>Clear all overrides</Btn><Btn kind="primary" onClick={() => onSave(cfg)}>Save round</Btn></>}>
      <p className="small muted">Values in green are set for this round only. Everything else is inherited from the job, team, company or platform.</p>
      <div className="tbl-wrap"><table className="tbl"><tbody>
        {keys.map((k) => {
          const v = val(k);
          const over = k in cfg;
          let input;
          if (k === "voice.name") input = <VoiceSelect value={v} onChange={(x) => setK(k, x)} />;
          else if (k === "voice.allowed") input = <VoicesMulti value={v || []} onChange={(x) => setK(k, x)} />;
          else if (typeof v === "boolean") input = <Switch on={v} onChange={(x) => setK(k, x)} label={k} />;
          else if (typeof v === "number") input = <div style={{ width: 120 }}><Input type="number" value={v} onChange={(e) => setK(k, +e.target.value)} /></div>;
          else if (Array.isArray(v)) input = <Input value={v.join(", ")} onChange={(e) => setK(k, e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} />;
          else if (k === "interview.difficulty") input = <div style={{ width: 160 }}><Select value={v} onChange={(x) => setK(k, x)} options={["easy", "medium", "hard"]} /></div>;
          else if (k === "voice.rate") input = <div style={{ width: 160 }}><Select value={v} onChange={(x) => setK(k, x)} options={["-20%", "-10%", "0%", "10%", "20%"]} /></div>;
          else input = <Input value={v ?? ""} onChange={(e) => setK(k, e.target.value)} />;
          return <tr key={k} style={over ? { background: "var(--good-soft)" } : undefined}><td className="b small" style={{ width: 240 }}>{k}</td><td>{input}</td>
            <td style={{ width: 90 }}>{over && <Btn size="sm" kind="ghost" onClick={() => { const c = { ...cfg }; delete c[k]; setCfg(c); }}>Inherit</Btn>}</td></tr>;
        })}
      </tbody></table></div>
    </Modal>
  );
}

function JobTeam({ job, onChange }) {
  const { data: users } = useAsync(() => api.get("/company/users", { size: 100 }), []);
  const [rows, setRows] = useState(job.assignments.map((a) => ({ user_id: a.user_id, role: a.role })));
  const [run, busy] = useAction();
  if (!users) return <Loading />;
  return (
    <div className="card pad col" style={{ maxWidth: 760 }}>
      <AgentNote agent="hira">People added here get job-level access for their role, even if their company role is narrower. Use it to bring in a hiring manager or a panel interviewer for one job only.</AgentNote>
      {rows.map((r, i) => (
        <div key={i} className="row">
          <Select value={String(r.user_id)} onChange={(v) => { const x = [...rows]; x[i] = { ...r, user_id: +v }; setRows(x); }} options={users.items.map((u) => ({ value: String(u.id), label: `${u.name} (${u.email})` }))} />
          <div style={{ width: 200 }}><Select value={r.role} onChange={(v) => { const x = [...rows]; x[i] = { ...r, role: v }; setRows(x); }} options={["recruiter", "interviewer", "hiring_manager"]} /></div>
          <Btn kind="ghost" size="sm" onClick={() => setRows(rows.filter((_, j) => j !== i))}>✕</Btn>
        </div>
      ))}
      <div className="row"><Btn size="sm" onClick={() => setRows([...rows, { user_id: users.items[0]?.id, role: "interviewer" }])}>+ Add person</Btn>
        <Btn kind="primary" className="right" busy={busy} disabled={!job.can["jobs.edit"]} onClick={() => run(() => api.put(`/jobs/${job.id}/assignments`, { assignments: rows }), "Team saved").then(onChange)}>Save team</Btn></div>
    </div>
  );
}
