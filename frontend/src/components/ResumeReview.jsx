// CP-004 / PRF-09 (V02.00.10): read a resume, show what saving it changes, and save only after the person confirms.
// The old resume's skills are replaced by the new resume's; skills added by hand and verified skills stay.
// Used by the candidate (base "/me") and by the hiring team (base "/candidates/<id>").
import { useState } from "react";
import { api, download } from "../api";
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
    // CAN-002 (V02.00.11): some phone file managers hand over a name without an extension, so the server checks
    // the file's content instead. Only clearly wrong types are stopped here.
    if (/\.(jpe?g|png|gif|heic|webp|xlsx?|pptx?|zip|rar)$/i.test(file.name)) { toast("Use a PDF, Word (DOCX or DOC) or TXT file.", "bad"); return; }
    if (file.size > MAX_MB * 1024 * 1024) { toast(`That file is over ${MAX_MB} MB. Use a smaller file.`, "bad"); return; }
    const fd = new FormData(); fd.append("file", file); read(fd);
  };
  return (
    <div className="col" style={{ gap: 10 }}>
      <label className={"btn" + (busy ? " disabled" : "")} style={{ alignSelf: "flex-start" }}>{busy ? "Reading…" : "Upload PDF, Word or TXT"}
        <input type="file" accept=".pdf,.docx,.doc,.txt,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain" hidden disabled={busy} onChange={(e) => { pick(e.target.files[0]); e.target.value = ""; }} /></label>
      {!compact && <span className="tiny muted">PDF, DOCX, DOC or TXT, up to {MAX_MB} MB. The file is kept so you can download it later.</span>}
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
    text, fields, upload_id: preview.upload_id || null, add: [...add], remove: [...remove],
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

/** CAN-002 (V02.00.11): the resume file on file, with download and earlier versions. */
export function ResumeFileLine({ file, history, href, name }) {
  const toast = useToast();
  if (!file) return null;
  const kb = Math.max(1, Math.round((file.size || 0) / 1024));
  const get = (v) => download(v ? `${href}?version=${v.id}` : href, (v || file).filename).catch((e) => toast(e.message, "bad"));
  const older = (history || []).filter((h) => h.status === "old");
  return (
    <div className="col" style={{ gap: 4 }}>
      <div className="row wrap" style={{ gap: 8 }}><span aria-hidden="true">📄</span><b className="small">{file.filename}</b>
        <span className="tiny muted">{kb} KB · uploaded {new Date(file.uploaded_at).toLocaleDateString()}{file.by ? ` by ${file.by}` : ""}</span>
        <Btn size="sm" kind="ghost" onClick={() => get(null)} aria-label={`Download ${name ? name + "'s" : "the"} resume`}>Download</Btn></div>
      {older.length > 0 && href.includes("/candidates/") && <details className="tiny"><summary>Earlier versions ({older.length})</summary>
        {older.map((h) => <div key={h.id} className="row" style={{ gap: 6 }}><span>{h.filename} · {new Date(h.uploaded_at).toLocaleDateString()}</span><button type="button" className="linkbtn" onClick={() => get(h)}>Download</button></div>)}</details>}
    </div>
  );
}
