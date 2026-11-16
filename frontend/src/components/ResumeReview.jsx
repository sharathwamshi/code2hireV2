// CP-004 / PRF-09 (V02.00.10): read a resume, show what saving it changes, and save only after the person confirms.
// The old resume's skills are replaced by the new resume's; skills added by hand and verified skills stay.
// Used by the candidate (base "/me") and by the hiring team (base "/candidates/<id>").
import { useState } from "react";
import { api } from "../api";
import { Btn, Chip, Field, Modal, Textarea, useAction, useToast } from "./ui";

const FIELD_LABEL = { headline: "Headline", location: "City", phone: "Phone", experience_years: "Years of experience" };
const MAX_MB = 5;

export function ResumeInput({ base, onRead, compact }) {
  const toast = useToast();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const read = async (payload) => {
    setBusy(true);
    try { onRead(await api.post(`${base}/resume/read`, payload)); setText(""); }
    catch (e) { toast(e.message, "bad"); } finally { setBusy(false); }
  };
  const pick = (file) => {
    if (!file) return;
    if (!/\.(pdf|docx|txt)$/i.test(file.name)) { toast("Use a PDF, DOCX or TXT file.", "bad"); return; }
    if (file.size > MAX_MB * 1024 * 1024) { toast(`That file is over ${MAX_MB} MB. Use a smaller file.`, "bad"); return; }
    const fd = new FormData(); fd.append("file", file); read(fd);
  };
  return (
    <div className="col" style={{ gap: 10 }}>
      <label className={"btn" + (busy ? " disabled" : "")} style={{ alignSelf: "flex-start" }}>{busy ? "Reading…" : "Upload PDF, DOCX or TXT"}
        <input type="file" accept=".pdf,.docx,.txt" hidden disabled={busy} onChange={(e) => { pick(e.target.files[0]); e.target.value = ""; }} /></label>
      {!compact && <span className="tiny muted">Up to {MAX_MB} MB.</span>}
      <Field label="Or paste it"><Textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste the resume text here" style={{ minHeight: compact ? 70 : 100 }} /></Field>
      <Btn disabled={text.trim().length < 20 || busy} busy={busy} onClick={() => read({ text })}>Read pasted resume</Btn>
    </div>
  );
}

export default function ResumeReview({ base, preview, onClose, onSaved, who = "your" }) {
  const toast = useToast();
  const { plan, fields, text } = preview;
  const [add, setAdd] = useState(new Set(plan.add));
  const [remove, setRemove] = useState(new Set(plan.remove));
  const [fill, setFill] = useState(new Set(Object.keys(plan.fill || {})));
  const [run, busy] = useAction();
  const flip = (set, setter, v) => { const n = new Set(set); n.has(v) ? n.delete(v) : n.add(v); setter(n); };
  const save = () => run(() => api.post(`${base}/resume`, {
    text, fields, add: [...add], remove: [...remove],
    fill: Object.fromEntries(Object.entries(plan.fill || {}).filter(([k]) => fill.has(k))),
  })).then((r) => { toast(`Resume saved. ${r.added.length} skill${r.added.length === 1 ? "" : "s"} added, ${r.removed.length} removed.`, "good"); onSaved?.(r); });
  const none = !plan.add.length && !plan.remove.length && !Object.keys(plan.fill || {}).length;
  return (
    <Modal wide title="Check what the resume changes" onClose={onClose}
      footer={<><Btn onClick={onClose}>Cancel</Btn><Btn kind="primary" busy={busy} onClick={save}>Save resume</Btn></>}>
      <p className="small muted" style={{ margin: 0 }}>Disha read the resume. Untick anything you don't want. Skills added by hand and verified skills always stay.</p>
      {none && <div className="sc-note calm">No changes to {who} skills or details. Saving replaces the stored resume text only.</div>}
      {plan.add.length > 0 && <div className="col" style={{ gap: 6 }}><b className="small">Skills to add ({add.size})</b>
        <div className="row wrap" style={{ gap: 6 }}>{plan.add.map((s) => <button type="button" key={s} className={"chip " + (add.has(s) ? "good" : "")} aria-pressed={add.has(s)} onClick={() => flip(add, setAdd, s)}>{add.has(s) ? "✓ " : "+ "}{s}</button>)}</div></div>}
      {plan.remove.length > 0 && <div className="col" style={{ gap: 6 }}><b className="small">Skills from the old resume to remove ({remove.size})</b>
        <span className="tiny muted">These came from the previous resume and aren't in this one.</span>
        <div className="row wrap" style={{ gap: 6 }}>{plan.remove.map((s) => <button type="button" key={s} className={"chip " + (remove.has(s) ? "bad" : "")} aria-pressed={remove.has(s)} onClick={() => flip(remove, setRemove, s)}>{remove.has(s) ? "✕ " : "keep "}{s}</button>)}</div></div>}
      {Object.keys(plan.fill || {}).length > 0 && <div className="col" style={{ gap: 6 }}><b className="small">Empty details to fill in</b>
        {Object.entries(plan.fill).map(([k, v]) => <label key={k} className="row small" style={{ gap: 8 }}><input type="checkbox" checked={fill.has(k)} onChange={() => flip(fill, setFill, k)} />{FIELD_LABEL[k] || k}: <b>{String(v)}</b></label>)}</div>}
      {plan.keep.length > 0 && <div className="col" style={{ gap: 6 }}><b className="small">Staying</b><div className="row wrap" style={{ gap: 6 }}>{plan.keep.map((s) => <Chip key={s}>{s}</Chip>)}</div></div>}
    </Modal>
  );
}
