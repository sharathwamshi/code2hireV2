// V02.00.08: remove a candidate from a job, and bring them back (Restore, or Start fresh from round 1).
import { useState } from "react";
import { api } from "../api";
import { Btn, Field, Modal, Textarea, useAction, useToast } from "./ui";

/** V02.00.08 (A1/A2): bring a removed candidate back, where they were or from round 1. */
export function RestoreModal({ appId, name, onClose, onDone }) {
  const [run, busy] = useAction();
  const go = (mode) => run(() => api.post(`/applications/${appId}/restore`, { mode }), mode === "fresh" ? "Started fresh from round 1" : "Restored").then((r) => onDone?.(r));
  return (
    <Modal title={`Bring back ${name}`} onClose={onClose} footer={<Btn onClick={onClose}>Cancel</Btn>}>
      <div className="col" style={{ gap: 10 }}>
        <button type="button" className="card pad stat-link" disabled={busy} onClick={() => go("continue")}><b>Restore</b><div className="small muted">Continue where they left off: same stage, same rounds and reports.</div></button>
        <button type="button" className="card pad stat-link" disabled={busy} onClick={() => go("fresh")}><b>Start fresh</b><div className="small muted">Begin again from round 1. Earlier rounds stay as history (voided), out of scores and decisions. Videos are kept.</div></button>
      </div>
    </Modal>
  );
}


/** V02.00.08 (A1): remove from the job. Open invites are cancelled and their credits come back; reports and videos stay. */
export function RemoveModal({ ids, names, onClose, onDone }) {
  const [note, setNote] = useState("");
  const [run, busy] = useAction();
  const toast = useToast();
  const go = () => run(() => api.post("/applications/bulk-remove", { ids, note })).then((r) => {
    if (r.skipped?.length) toast(r.skipped.map((x) => `${x.name}: ${x.reason}`).join(" "), "warn");
    else toast(ids.length === 1 ? "Removed from the job" : `${r.removed} removed from the job`, "good");
    onDone?.(r);
  });
  return (
    <Modal title={ids.length === 1 ? `Remove ${names[0]} from this job?` : `Remove ${ids.length} candidates from this job?`} onClose={onClose}
      footer={<><Btn onClick={onClose}>Cancel</Btn><Btn kind="danger" busy={busy} onClick={go}>Remove from job</Btn></>}>
      <p className="small" style={{ marginTop: 0 }}>They leave the pipeline. Open invites are cancelled and their credits come back. Reports and videos stay.
        To bring them back, use the Stage filter → <b>Removed</b>, or add the same email again: you can restore them or start fresh.</p>
      <Field label="Reason (optional, for the team)"><Textarea value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} /></Field>
    </Modal>
  );
}
