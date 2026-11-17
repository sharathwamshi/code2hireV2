// V02.00.10: recruiters, interviewers and admins edit a candidate's details and add or replace the resume from the
// Talent pool, a job's pipeline, the application page and Added candidates. The email (their sign-in) is not editable,
// and verified skills can't be removed or lowered.
import { useState } from "react";
import { api } from "../api";
import ResumeReview, { ResumeFileLine, ResumeInput } from "./ResumeReview";
import { Btn, Chip, Field, Input, Loading, Modal, Select, useAction, useAsync, useConfirm } from "./ui";

const LV = ["Beginner", "Working", "Independent", "Advanced", "Expert"];

export default function EditCandidate({ id, onClose, onSaved }) {
  const { data, reload, error } = useAsync(() => api.get(`/candidates/${id}/profile`), [id]);
  const [f, setF] = useState(null);
  const [fe, setFe] = useState({});
  const [skill, setSkill] = useState("");
  const [skErr, setSkErr] = useState("");
  const [preview, setPreview] = useState(null);
  const [tab, setTab] = useState("details");
  const [run, busy] = useAction();
  const ask = useConfirm();
  if (error && !data) return <Modal title="Edit candidate" onClose={onClose}><p role="alert">{String(error)}</p></Modal>;
  if (!data) return <Modal title="Edit candidate" onClose={onClose}><Loading /></Modal>;
  const p = f || { name: data.name, headline: data.headline, location: data.location, phone: data.phone, experience_years: data.experience_years ?? "", skills: data.skills, target_roles: data.target_roles };
  const set = (k, v) => setF({ ...p, [k]: v });
  const add = (e) => {
    e.preventDefault();
    const v = skill.trim();
    if (!v) return;
    if (p.skills.some((s) => s.name.toLowerCase() === v.toLowerCase())) { setSkErr(`${v} is already listed.`); return; }
    set("skills", [...p.skills, { name: v, level: 2 }]); setSkill(""); setSkErr("");
  };
  const save = () => { setFe({}); return run(() => api.patch(`/candidates/${id}/profile`, { ...p, experience_years: p.experience_years === "" ? null : Number(p.experience_years) }), "Candidate updated")
    .then((r) => { setF(null); reload(); onSaved?.(r); }).catch((e) => e.fields && setFe(e.fields)); };
  const close = async () => { if (f && !(await ask({ title: "Discard your changes?", yes: "Discard", danger: true }))) return; onClose(); };
  return (
    <>
      <Modal wide title={`Edit ${data.name}`} onClose={close} dirty={!!f}
        footer={tab === "details" ? <><Btn onClick={close}>Cancel</Btn><Btn kind="primary" busy={busy} disabled={!f} onClick={save}>Save changes</Btn></> : <Btn onClick={close}>Close</Btn>}>
        <div className="row wrap small" style={{ gap: 8 }}><span className="muted">{data.email}</span><Chip>Profile strength {data.strength}%</Chip>
          {data.has_resume ? <Chip kind="good">✓ Resume on file</Chip> : <Chip kind="warn">No resume</Chip>}
          {data.self_managed && <Chip kind="brand" title="The candidate has signed in and manages this profile too. They'll be told about changes.">Candidate manages this profile</Chip>}</div>
        <div className="seg" role="tablist"><button type="button" role="tab" aria-selected={tab === "details"} className={tab === "details" ? "on" : ""} onClick={() => setTab("details")}>Details and skills</button>
          <button type="button" role="tab" aria-selected={tab === "resume"} className={tab === "resume" ? "on" : ""} onClick={() => setTab("resume")}>{data.has_resume ? "Replace resume" : "Add resume"}</button></div>
        {tab === "details" ? <>
          <div className="grid g2">
            <Field label="Name" required error={fe.name}><Input value={p.name} maxLength={80} onChange={(e) => set("name", e.target.value)} /></Field>
            <Field label="Headline" error={fe.headline}><Input value={p.headline} maxLength={120} placeholder="e.g. Backend developer" onChange={(e) => set("headline", e.target.value)} /></Field>
            <Field label="City" error={fe.location}><Input value={p.location} maxLength={120} onChange={(e) => set("location", e.target.value)} /></Field>
            <Field label="Phone" error={fe.phone} hint="With country code"><Input type="tel" value={p.phone} maxLength={20} onChange={(e) => set("phone", e.target.value.replace(/[^\d+\s\-()]/g, ""))} /></Field>
            <Field label="Years of experience" error={fe.experience_years} hint="0 for a fresher"><Input type="number" min={0} max={60} value={p.experience_years ?? ""} onChange={(e) => set("experience_years", e.target.value === "" ? "" : Math.max(0, Math.min(60, Math.round(Number(e.target.value)))))} /></Field>
            <Field label="Target role"><Input value={p.target_roles?.[0] || ""} maxLength={120} onChange={(e) => set("target_roles", e.target.value ? [e.target.value] : [])} /></Field>
          </div>
          <div className="col" style={{ gap: 8 }}>
            <b className="small">Skills ({p.skills.length})</b>
            <form className="row" onSubmit={add}><Input value={skill} onChange={(e) => { setSkill(e.target.value); setSkErr(""); }} placeholder="Add a skill" maxLength={80} aria-label="Add a skill" /><Btn type="submit" disabled={!skill.trim()}>Add</Btn></form>
            {skErr && <span className="small" style={{ color: "var(--bad)" }} role="alert">{skErr}</span>}
            {fe.skills && <span className="small" style={{ color: "var(--bad)" }} role="alert">{fe.skills}</span>}
            <div className="skill-grid">{p.skills.map((s, i) => <div key={s.name + i} className="skill-cell"><span className="grow skill-name" title={s.name}>{s.name}</span>
              {s.verified ? <Chip kind="good">✓ L{s.level} verified</Chip> : <>
                <div style={{ width: 150 }}><Select value={String(s.level)} aria-label={`Level for ${s.name}`} onChange={(v) => set("skills", p.skills.map((x, j) => (j === i ? { ...x, level: +v } : x)))} options={LV.map((l, k) => ({ value: String(k + 1), label: `L${k + 1} · ${l}` }))} /></div>
                <button type="button" className="btn ghost icon-btn" aria-label={`Remove ${s.name}`} onClick={() => set("skills", p.skills.filter((_, j) => j !== i))}>✕</button></>}</div>)}</div>
          </div>
        </> : <div className="col" style={{ gap: 10 }}>
          <span className="small muted">Disha reads the resume and shows what changes before anything is saved. Skills from the old resume are replaced; skills added by hand and verified skills stay.</span>
          <ResumeFileLine file={data.resume_file} history={data.resume_history} href={`/candidates/${id}/resume/file`} name={data.name} />
          <ResumeInput base={`/candidates/${id}`} onRead={setPreview} compact />
        </div>}
      </Modal>
      {preview && <ResumeReview base={`/candidates/${id}`} preview={preview} who="their" onClose={() => setPreview(null)} onSaved={(r) => { setPreview(null); setF(null); reload(); onSaved?.(r); }} />}
    </>
  );
}
