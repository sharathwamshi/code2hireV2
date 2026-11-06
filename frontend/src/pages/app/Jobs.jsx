import { useEffect, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import DataTable from "../../components/DataTable";
import { AgentNote, Hira } from "../../components/Mascot";
import SettingsEditor, { SettingInput, companySettings, settingError } from "../../components/Settings";
import { PageHead } from "../../components/Shell";
import { Bar, Btn, Chip, Field, Input, Integrity, Loading, Modal, ROUND_LABEL, Score, Select, Status, Switch, Tabs, Textarea, fmtDate, inr, isoToLocalInput, localInputToISO, useAction, useAsync, useToast } from "../../components/ui";
import { RoundsEditor } from "../admin/Admin";
import { intError } from "../../lib/validate";
import AddCandidate from "../../components/AddCandidate";

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

// ---------------------------------------------------------------- job rules (the server checks the same)
const todayISO = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
export function jobBasicsErrors(j) {
  const e = {};
  const t = (j.title || "").trim();
  if (!t) e.title = "This is required."; else if (t.length < 2) e.title = "Job title needs at least 2 characters."; else if (t.length > 120) e.title = "Job title can be at most 120 characters.";
  return e;
}
export function jobDetailsErrors(j) {
  const e = {};
  const hi = intError(j.hires_target, { lo: 1, hi: 1000, required: true, label: "Hires needed" }); if (hi) e.hires_target = hi;
  const a = intError(j.salary_min, { lo: 0, label: "Minimum salary" }); if (a) e.salary_min = a;
  const b = intError(j.salary_max, { lo: 0, label: "Maximum salary" }); if (b) e.salary_max = b;
  if (!a && !b && j.salary_min != null && j.salary_max != null && j.salary_min !== "" && j.salary_max !== "" && Number(j.salary_min) > Number(j.salary_max)) e.salary_min = "Minimum salary can't be more than the maximum.";
  if (j.deadline && j.deadline < todayISO()) e.deadline = "The deadline can't be in the past.";
  return e;
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
  const [errs, setErrs] = useState({});
  const { data: tpl } = useAsync(() => api.get("/templates"), []);
  const { data: comp } = useAsync(() => api.get("/company"), []);
  // a team-scoped recruiter can only create jobs in their own team: preselect it so the save never fails at the end
  useEffect(() => {
    if (comp && !comp.job_no_team && comp.job_teams?.length && !job.team_id) setJob((x) => ({ ...x, team_id: comp.job_teams[0] }));
  }, [comp]); // eslint-disable-line react-hooks/exhaustive-deps
  const teamOpts = comp ? [...(comp.job_no_team !== false ? [{ value: "", label: "No team" }] : []),
    ...(comp.teams || []).filter((t) => comp.job_no_team !== false || (comp.job_teams || []).includes(t.id)).map((t) => ({ value: String(t.id), label: t.name }))] : [{ value: "", label: "No team" }];
  const draft = async () => {
    setBusy(true);
    try { const d = await api.post("/jobs/draft", { text }); setJob({ ...job, ...d }); setStep(1); toast("Hira drafted the plan. Check each step.", "good"); }
    catch (e) { toast(e.message, "bad"); } finally { setBusy(false); }
  };
  const stepErrors = (i, j = job) => i === 1 ? jobBasicsErrors(j) : i === 2 ? (j.rounds.length ? {} : { rounds: "Add at least one round." }) : i === 3 ? jobDetailsErrors(j) : {};
  const goTo = (i) => {
    for (let k = 1; k < i; k++) { const e = stepErrors(k); if (Object.keys(e).length) { setErrs(e); setStep(k); toast("Fix the highlighted fields first.", "bad"); return; } }
    setErrs({}); setStep(i);
  };
  const create = async (publish) => {
    const all = { ...stepErrors(1), ...stepErrors(2), ...stepErrors(3) };
    if (Object.keys(all).length) { setErrs(all); setStep(all.title ? 1 : all.rounds ? 2 : 3); toast("Fix the highlighted fields first.", "bad"); return; }
    setBusy(true);
    try {
      const j = await api.post("/jobs", job);
      if (publish) { const p = await api.post(`/jobs/${j.id}/publish`); toast(p.approval ? "Sent for approval (company policy)." : "Published.", "good"); }
      nav(`/app/jobs/${j.id}`);
    } catch (e) {
      toast(e.message, "bad");
      if (e.fields) { setErrs(e.fields); setStep(e.fields.title || e.fields.skills ? 1 : e.fields.rounds ? 2 : 3); }
    } finally { setBusy(false); }
  };
  const set = (k, v) => { setJob({ ...job, [k]: v }); if (errs[k] || (k.startsWith("salary") && errs.salary_min)) { const e = { ...errs }; delete e[k]; if (k.startsWith("salary")) delete e.salary_min; setErrs(e); } };
  return (
    <>
      <PageHead back="/app/jobs" title="New job" sub="Paste anything about the role. Hira drafts the plan; you check every step." />
      <div className="card">
        <div className="stepper" style={{ borderBottom: "1px solid var(--line)" }}>
          {STEPS.map((s, i) => <span key={s} style={{ display: "contents" }}>{i > 0 && <span className="sep" />}
            <button className={"st " + (i === step ? "on" : i < step ? "done" : "")} onClick={() => (i <= step ? (setErrs({}), setStep(i)) : goTo(i))}><i>{i < step ? "✓" : i + 1}</i>{s}</button></span>)}
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
              <div className="grid g2"><Field label="Job title" required error={errs.title}><Input value={job.title} maxLength={120} placeholder="e.g. Senior Python Developer" onChange={(e) => set("title", e.target.value)} /></Field>
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
              {errs.rounds && <span className="field-err">{errs.rounds}</span>}
              {job.questions?.length > 0 && <div className="col"><b>First interview questions Hira drafted</b>{job.questions.map((q, i) => <div key={i} className="quote">{q}</div>)}</div>}
            </>
          )}
          {step === 3 && (
            <div className="grid g2">
              <Field label="Location" error={errs.location}><Input value={job.location} maxLength={120} placeholder="e.g. Bengaluru" onChange={(e) => set("location", e.target.value)} /></Field>
              <Field label="Work mode"><Select value={job.work_mode} onChange={(v) => set("work_mode", v)} options={["onsite", "hybrid", "remote"]} /></Field>
              <Field label="Team" error={errs.team_id} hint={comp && comp.job_no_team === false ? "You can create jobs in your own team." : undefined}><Select value={String(job.team_id || "")} onChange={(v) => set("team_id", v ? +v : null)} options={teamOpts} /></Field>
              <Field label="Visibility" hint="Public shows on the Code2Hire job board. Private is invite-link only. Internal is for employees."><Select value={job.visibility} onChange={(v) => set("visibility", v)} options={["private", "public", "internal"]} /></Field>
              <Field label="Salary from (₹ / year)" error={errs.salary_min}><Input type="number" min={0} step={1000} inputMode="numeric" placeholder="e.g. 1200000" value={job.salary_min ?? ""} onChange={(e) => set("salary_min", e.target.value === "" ? null : Number(e.target.value))} /></Field>
              <Field label="Salary to (₹ / year)" error={errs.salary_max}><Input type="number" min={0} step={1000} inputMode="numeric" placeholder="e.g. 1800000" value={job.salary_max ?? ""} onChange={(e) => set("salary_max", e.target.value === "" ? null : Number(e.target.value))} /></Field>
              <label className="check"><input type="checkbox" checked={!!job.salary_visible} onChange={(e) => set("salary_visible", e.target.checked)} />Show salary to candidates</label>
              <Field label="Hires needed" required error={errs.hires_target}><Input type="number" min={1} max={1000} step={1} inputMode="numeric" value={job.hires_target ?? ""} onChange={(e) => set("hires_target", e.target.value === "" ? "" : Number(e.target.value))} /></Field>
              <Field label="Deadline" error={errs.deadline}><Input type="date" min={todayISO()} value={job.deadline || ""} onChange={(e) => set("deadline", e.target.value)} /></Field>
              <Field label="Client name (agencies)" error={errs.client_name}><Input value={job.client_name || ""} maxLength={120} onChange={(e) => set("client_name", e.target.value)} /></Field>
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
          {step > 0 && step < 4 && <Btn kind="primary" onClick={() => { const e = stepErrors(step); if (Object.keys(e).length) { setErrs(e); return; } goTo(step + 1); }}>Next</Btn>}
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
          {job.can["jobs.create"] && <Btn busy={busy} onClick={() => run(() => api.post(`/jobs/${id}/duplicate`), "Duplicated as a draft").then((j) => nav(`/app/jobs/${j.id}`)).catch(() => {})}>Duplicate</Btn>}
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
  const loc = useLocation();
  const toast = useToast();
  const [ask, setAsk] = useState("");
  const [chips, setChips] = useState([]);
  const [rk, setRk] = useState(0);
  // "Ask Hira" suggested someone for this job: open Add candidate with them picked
  const [preset, setPreset] = useState(loc.state?.pick || null);
  const [add, setAdd] = useState(!!loc.state?.pick);
  useEffect(() => { if (loc.state?.pick) { setPreset(loc.state.pick); setAdd(true); } }, [loc.key]); // eslint-disable-line react-hooks/exhaustive-deps
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
        <Btn type="button" onClick={() => setAdd(true)}>+ Add candidate</Btn>
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
          { key: "round", label: "Current round", render: (r) => r.round_name ? <span className="small">{r.round_name}{r.last_round && <> · <Status s={r.last_round.status} /></>}
            {r.last_round?.setup && ["invited", "scheduled", "in_progress"].includes(r.last_round.status) && <> <Chip kind={r.last_round.setup === "tested" ? "good" : r.last_round.setup === "needs_help" ? "bad" : "warn"}>{r.last_round.setup === "tested" ? "Setup tested ✓" : r.last_round.setup === "needs_help" ? "Needs help" : "Setup check failed"}</Chip></>}</span> : "—" },
          { key: "score", label: "Last score", render: (r) => r.last_round?.score != null ? <Score value={r.last_round.score} type={r.last_round.type} scale={r.last_round.scale || 5} pct /> : "—" },
          { key: "warnings", label: "Integrity", render: (r) => r.last_round ? <Integrity count={r.last_round.warnings} /> : "—" },
          { key: "skills", label: "Skills", render: (r) => <div className="row wrap" style={{ maxWidth: 260 }}>{r.candidate.skills.slice(0, 4).map((s, i) => <Chip key={i} kind={s.verified ? "good" : ""}>{s.name}{s.verified ? " ✓" : ""}</Chip>)}</div> },
          { key: "source", label: "Source", render: (r) => <span className="small">{r.source}</span> },
          { key: "applied", label: "Applied", sort: "applied", render: (r) => fmtDate(r.created_at) },
        ]} />
      {add && <AddCandidate jobId={job.id} preset={preset} onClose={() => { setAdd(false); setPreset(null); if (loc.state?.pick) nav(loc.pathname, { replace: true, state: null }); }} onDone={() => { setRk(rk + 1); onChange(); }} />}
      {inviteFor && <InviteModal job={job} onClose={() => setInviteFor(null)} onInvite={(extra) => bulk("invite", inviteFor.ids, () => { inviteFor.done(); setInviteFor(null); }, extra)} />}
    </>
  );
}

export function InviteModal({ job, onClose, onInvite, nextIndex }) {
  const { data: ivs } = useAsync(() => api.get("/company/interviewers"), []);
  const [f, setF] = useState({ round_index: nextIndex ?? "", interviewer_id: "", scheduled_at: "" });
  const [busy, setBusy] = useState(false);
  const rt = f.round_index !== "" ? job.rounds[+f.round_index]?.type : null;
  const f2f = rt === "f2f_isha" || rt === "f2f_human";
  const iso = localInputToISO(f.scheduled_at);
  const timeErr = f.scheduled_at && !iso ? "Enter a valid date and time." : iso && new Date(iso).getTime() < Date.now() - 60000 ? "Pick a time in the future." : "";
  const ivErr = f2f && !f.interviewer_id ? "Choose who runs this interview." : "";
  const send = async () => {
    if (timeErr || ivErr) return;
    setBusy(true);
    try { await onInvite({ round_index: f.round_index === "" ? undefined : +f.round_index, interviewer_id: f.interviewer_id || undefined, scheduled_at: iso || undefined }); }
    finally { setBusy(false); }
  };
  return (
    <Modal title="Invite to a round" onClose={onClose} footer={<>{(timeErr || ivErr) && <span className="missing-note">{ivErr || timeErr}</span>}<Btn onClick={onClose}>Cancel</Btn><Btn kind="primary" busy={busy} disabled={!!(timeErr || ivErr)} onClick={send}>Send invites</Btn></>}>
      <Field label="Round" hint="Leave as “next round” to move each candidate one step on."><Select value={String(f.round_index)} onChange={(v) => setF({ ...f, round_index: v })} options={[{ value: "", label: "Next round for each candidate" }, ...job.rounds.map((r, i) => ({ value: String(i), label: `${i + 1}. ${r.name || ROUND_LABEL[r.type]}` }))]} /></Field>
      {(f2f || f.round_index === "") && <Field label="Interviewer (for face-to-face rounds)" required={f2f} error={f.interviewer_id ? "" : ivErr && "This is required."}><Select value={String(f.interviewer_id)} onChange={(v) => setF({ ...f, interviewer_id: v })} options={[{ value: "", label: "Choose…" }, ...(ivs || []).map((u) => ({ value: String(u.id), label: `${u.name}${u.skills_meta?.skills ? " · " + u.skills_meta.skills.join(", ") : ""}` }))]} /></Field>}
      {(f2f || f.round_index === "") && <Field label="When" error={timeErr} hint={`Your local time (${Intl.DateTimeFormat().resolvedOptions().timeZone}). The candidate sees it in theirs.`}><Input type="datetime-local" min={isoToLocalInput(new Date().toISOString())} value={f.scheduled_at} onChange={(e) => setF({ ...f, scheduled_at: e.target.value })} /></Field>}
      <p className="small muted">Candidates get an email and an inbox card with the deadline. Credits are used when an invite is sent.</p>
    </Modal>
  );
}

function Pipeline({ job, onChange }) {
  const [edit, setEdit] = useState(null);
  const toast = useToast();
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
      {edit && <RoundConfig job={job} round={edit} onClose={() => setEdit(null)} onSave={async (cfg) => { const r = job.rounds.map((x, i) => i === edit.index ? { ...x, config: cfg } : x); await api.patch(`/jobs/${job.id}`, { rounds: r }); toast("Round saved", "good"); setEdit(null); onChange(); }} />}
    </div>
  );
}

function RoundConfig({ job, round, onClose, onSave }) {
  const [cfg, setCfg] = useState({ ...(round.config || {}) });
  const [busy, setBusy] = useState(false);
  const [srv, setSrv] = useState("");
  const keys = Object.keys(round.resolved);
  const val = (k) => (k in cfg ? cfg[k] : round.resolved[k]);
  const setK = (k, v) => { setSrv(""); setCfg({ ...cfg, [k]: v }); };
  const errs = {};
  keys.forEach((k) => { if (k in cfg) { const e = settingError(round.meta?.[k], cfg[k]); if (e) errs[k] = e; } });
  const own = val("f2f.own_questions") || [], total = val("f2f.questions");
  if (Array.isArray(own) && Number.isInteger(total) && own.length > total) errs["f2f.own_questions"] = `You listed ${own.length} questions but the plan has ${total}.`;
  if (Number.isInteger(val("pass.reject")) && val("pass.reject") > val("pass.advance")) errs["pass.reject"] = "Auto-reject must not be above auto-advance.";
  if (Number.isInteger(val("mcq.questions")) && val("mcq.minutes") * 2 < val("mcq.questions")) errs["mcq.minutes"] = `Allow at least ${Math.ceil(val("mcq.questions") / 2)} minutes.`;
  const bad = Object.keys(errs).length > 0;
  const groups = {};
  keys.forEach((k) => (groups[round.meta?.[k]?.group || "Other"] ||= []).push(k));
  return (
    <Modal wide title={`Configure: ${round.name}`} onClose={onClose} dirty={JSON.stringify(cfg) !== JSON.stringify(round.config || {})}
      footer={<>{(bad || srv) && <span className="missing-note">{srv || "Fix the highlighted values first."}</span>}<Btn onClick={() => setCfg({})}>Clear all overrides</Btn>
        <Btn kind="primary" busy={busy} disabled={bad} onClick={async () => { setBusy(true); try { await onSave(cfg); } catch (e) { setSrv(e.message); } finally { setBusy(false); } }}>Save round</Btn></>}>
      <RoundPreview job={job} round={round} val={val} />
      <p className="small muted">Values in green are set for this round only. Everything else is inherited from the job, team, company or platform.</p>
      {Object.entries(groups).map(([g, ks]) => (
        <div key={g} className="col" style={{ gap: 4 }}><h4 style={{ margin: "8px 0 0" }}>{g}</h4>
          <div className="tbl-wrap"><table className="tbl"><tbody>
            {ks.map((k) => {
              const m = round.meta?.[k] || { key: k, label: k, type: typeof val(k) === "boolean" ? "bool" : typeof val(k) === "number" ? "int" : Array.isArray(val(k)) ? "list" : "text" };
              const over = k in cfg;
              return <tr key={k} style={over ? { background: "var(--good-soft)" } : undefined}>
                <td className="small" style={{ width: 260 }}><div className="b">{m.label}</div></td>
                <td><SettingInput m={m} value={val(k)} error={errs[k]} onChange={(x) => setK(k, x)} />{errs[k] && <div className="tiny" role="alert" style={{ color: "var(--bad)" }}>{errs[k]}</div>}</td>
                <td style={{ width: 90 }}>{over && <Btn size="sm" kind="ghost" onClick={() => { const c = { ...cfg }; delete c[k]; setCfg(c); }}>Inherit</Btn>}</td></tr>;
            })}
          </tbody></table></div></div>))}
    </Modal>
  );
}

/** What this round will actually do, in one line: question count and where the questions come from. */
function RoundPreview({ job, round, val }) {
  const mcq = round.type === "mcq";
  const n = mcq ? val("mcq.questions") : val("f2f.questions");
  const folders = JSON.stringify(val("mcq.folder_ids") || []);
  const [cov, setCov] = useState(null);
  useEffect(() => {
    if (!mcq || !Number.isInteger(n)) return undefined;
    const t = setTimeout(() => api.get(`/jobs/${job.id}/rounds/${round.index}/coverage`, { questions: n, folders }).then(setCov).catch(() => setCov(null)), 300);
    return () => clearTimeout(t);
  }, [mcq, n, folders]); // eslint-disable-line react-hooks/exhaustive-deps
  if (round.type === "f2f_isha" || round.type === "f2f_human") {
    const own = (val("f2f.own_questions") || []).length;
    const rest = Math.max(0, (n || 0) - own);
    return <div className="note">{n} questions in the plan: {own ? `your ${own}` : "none of your own yet"}{rest ? `, plus ${rest} ${round.type === "f2f_isha" ? "from Isha" : "suggested from the job's skills"}` : ""}.</div>;
  }
  if (mcq && cov) return <div className={"note" + (cov.short ? " warn" : "")}>{cov.message}</div>;
  if (round.type === "ai_interview") return <div className="note">{val("interview.questions")} main questions in {val("interview.minutes")} minutes, up to {val("interview.followup_depth")} follow-up{val("interview.followup_depth") === 1 ? "" : "s"} each.</div>;
  return null;
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
