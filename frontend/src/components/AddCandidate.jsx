import { useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { AgentNote } from "./Mascot";
import { Btn, Chip, Field, Input, ListEditor, Modal, Seg, Select, Textarea, fmtDate, useAction, useAsync, useToast } from "./ui";

export function fullLink(path) { return window.location.origin + path; }

/** Copy, email or WhatsApp a candidate's personal portal link. */
export function ShareLink({ name, link, job, company, expires }) {
  const toast = useToast();
  const url = fullLink(link);
  const first = (name || "").split(" ")[0] || "there";
  const msg = `Hi ${first}, ${company ? company + " has" : "we've"} added you on Code2Hire${job ? ` for the ${job} role` : ""}. Open your personal link to see your next steps, then set your own password: ${url}`;
  return (
    <div className="col" style={{ gap: 6 }}>
      <div className="linkbox"><code title={url}>{url}</code>
        <Btn size="sm" kind="primary" onClick={() => { navigator.clipboard?.writeText(url); toast("Link copied", "good"); }}>Copy</Btn></div>
      <div className="row wrap" style={{ gap: 6 }}>
        <a className="btn sm" href={`mailto:?subject=${encodeURIComponent(`Your Code2Hire link${job ? ` · ${job}` : ""}`)}&body=${encodeURIComponent(msg)}`}>✉ Email</a>
        <a className="btn sm" target="_blank" rel="noreferrer" href={`https://wa.me/?text=${encodeURIComponent(msg)}`}>WhatsApp</a>
        <Btn size="sm" kind="ghost" onClick={() => { navigator.clipboard?.writeText(msg); toast("Message copied", "good"); }}>Copy message</Btn>
        {expires && <span className="tiny muted right">Works until {fmtDate(expires)}, or until they set a password</span>}
      </div>
    </div>
  );
}

function parseRows(text) {
  return text.split("\n").map((l) => l.split(/[,\t]/).map((x) => x.trim())).filter((x) => x.some(Boolean) && (x[1] || "").includes("@"))
    .map(([name, email, phone, ...skills]) => ({ name, email, phone, skills: skills.join(" ").split(/[;|]/).map((s) => s.trim()).filter(Boolean) }));
}

export default function AddCandidate({ onClose, onDone, jobId }) {
  const { me } = useAuth();
  const { data: jobs } = useAsync(() => api.get("/jobs", { size: 100, status: "live" }).catch(() => ({ items: [] })), []);
  const [mode, setMode] = useState("one");
  const [f, setF] = useState({ name: "", email: "", phone: "", headline: "", location: "", skills: [], resume_text: "", job_id: jobId ? String(jobId) : "" });
  const [bulk, setBulk] = useState("");
  const [res, setRes] = useState(null);
  const [run, busy] = useAction();
  const rows = mode === "many" ? parseRows(bulk) : [];
  const job = (jobs?.items || []).find((j) => String(j.id) === String(f.job_id));
  const submit = () => run(() => api.post("/candidates", mode === "one" ? { ...f, job_id: f.job_id || undefined } : { candidates: rows, job_id: f.job_id || undefined }))
    .then((r) => { setRes(r); onDone?.(r); });

  if (res) {
    return (
      <Modal wide title={res.added ? `${res.added} candidate${res.added > 1 ? "s" : ""} added` : "Nothing was added"} onClose={onClose}
        footer={<><Btn onClick={() => { setRes(null); setF({ ...f, name: "", email: "", phone: "", headline: "", location: "", skills: [], resume_text: "" }); setBulk(""); }}>Add another</Btn><Btn kind="primary" onClick={onClose}>Done</Btn></>}>
        <AgentNote agent="disha" title="Send each person their link">The link opens their portal straight away, no password needed. There they see the job and their next steps, and set their own password. After that the link stops working and they sign in normally.</AgentNote>
        {res.results.map((r, i) => (
          <div key={i} className="card pad col" style={{ gap: 8 }}>
            <div className="row"><b>{r.name || r.email}</b><span className="small muted">{r.email}</span>
              {r.error ? <span className="right"><Chip kind="bad">{r.error}</Chip></span> : r.existing ? <Chip kind="info">Already on Code2Hire</Chip> : <Chip kind="good">New account</Chip>}
              {r.application_id && <Chip kind="brand">Added to {job?.title || "the job"}</Chip>}</div>
            {r.link && <ShareLink name={r.name} link={r.link} job={job?.title} company={me?.company?.name} expires={r.expires_at} />}
            {r.note && <div className="small muted">{r.note}</div>}
          </div>
        ))}
      </Modal>
    );
  }
  return (
    <Modal wide title="Add a candidate" onClose={onClose}
      footer={<><Btn onClick={onClose}>Cancel</Btn><Btn kind="primary" busy={busy} disabled={mode === "one" ? !f.email.includes("@") : !rows.length} onClick={submit}>{mode === "one" ? "Add and get link" : `Add ${rows.length} and get links`}</Btn></>}>
      <Seg value={mode} onChange={setMode} options={[["one", "One person"], ["many", "Paste a list"]]} />
      <Field label="Add to a job (optional)" hint="Leave empty to add them to your talent pool only. You can add them to a job later.">
        <Select value={f.job_id} onChange={(v) => setF({ ...f, job_id: v })} options={[{ value: "", label: "No job: talent pool only" }, ...(jobs?.items || []).map((j) => ({ value: String(j.id), label: `${j.title} · ${j.location || ""}` }))]} />
      </Field>
      {mode === "one" ? <>
        <div className="grid g2">
          <Field label="Full name"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} autoFocus /></Field>
          <Field label="Email"><Input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
          <Field label="Phone (for WhatsApp)"><Input value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} placeholder="+91 98450 00000" /></Field>
          <Field label="City"><Input value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} /></Field>
        </div>
        <Field label="Headline"><Input value={f.headline} onChange={(e) => setF({ ...f, headline: e.target.value })} placeholder="e.g. Backend developer, 4 years" /></Field>
        <Field label="Skills"><ListEditor value={f.skills} onChange={(v) => setF({ ...f, skills: v })} placeholder="Type a skill and press Enter" /></Field>
        <Field label="Resume text (optional)" hint="The candidate can upload their own resume from the portal too."><Textarea value={f.resume_text} onChange={(e) => setF({ ...f, resume_text: e.target.value })} data-allow-paste="1" /></Field>
      </> : <>
        <Field label="One person per line: name, email, phone, skills (skills separated by ;)">
          <Textarea value={bulk} onChange={(e) => setBulk(e.target.value)} style={{ minHeight: 170, fontFamily: "ui-monospace, monospace", fontSize: 12.5 }} data-allow-paste="1"
            placeholder={"Asha Rao, asha@example.com, 9845000001, Python; Django\nVikas Nair, vikas@example.com, , React"} />
        </Field>
        {bulk && <div className="small muted">{rows.length} valid row{rows.length === 1 ? "" : "s"} found.</div>}
      </>}
    </Modal>
  );
}
