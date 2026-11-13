// V02.00.08: retake a round after a technical problem. Anyone on the hiring team can do it; the failed round is voided
// (kept, with its video, but left out of scores and decisions) and a new invite goes out for the same round.
import { useState } from "react";
import { api } from "../api";
import { Btn, Chip, Field, Loading, Modal, Select, Textarea, localInputToISO, useAction, useAsync } from "./ui";

export function Evidence({ ev }) {
  if (!ev) return null;
  const c = ev.connection;
  const rows = [
    ["Round status", ev.status?.replace(/_/g, " ")],
    ["Time in the round", ev.minutes ? `${ev.minutes} min` : "Didn't start"],
    c && ["Video call", !c.connected ? "Never connected" : c.used_relay ? "Connected through the relay" : "Connected directly"],
    c && c.retries > 0 && ["Automatic reconnects", c.retries],
    ev.started_without_video && ["Started", ev.started_without_video === "not_connected" ? "Before the video connected" : "Before the candidate joined"],
    ev.setup_candidate && ["Candidate's system check", ev.setup_candidate.text],
    ev.setup_interviewer && ["Interviewer's system check", ev.setup_interviewer.text],
    ev.warnings > 0 && ["Integrity warnings", ev.warnings],
    ["Video recorded", ev.videos ? "Yes, it's kept" : "No"],
  ].filter(Boolean);
  return (
    <div className="card pad col" style={{ gap: 4, background: "var(--bg-soft, #F6F7FB)" }}>
      <b className="small">What Code2Hire recorded about this round</b>
      <dl className="kv small">{rows.map(([k, v]) => <div key={k} style={{ display: "contents" }}><dt>{k}</dt><dd>{String(v)}</dd></div>)}</dl>
    </div>
  );
}

export default function RetakeModal({ attemptId, live, onClose, onDone }) {
  const { data, error } = useAsync(() => api.get(`/attempts/${attemptId}/retake`), [attemptId]);
  const [f, setF] = useState({ reason: "", note: "", scheduled_at: "" });
  const [run, busy] = useAction();
  const save = () => run(() => api.post(`/attempts/${attemptId}/retake`, { reason: f.reason, note: f.note, scheduled_at: f.scheduled_at ? localInputToISO(f.scheduled_at) : undefined }),
    "Retake sent. The candidate has a new invite.").then((r) => onDone?.(r));
  return (
    <Modal wide title="Retake: technical problem" onClose={onClose}
      footer={<><Btn onClick={onClose}>Cancel</Btn><Btn kind="primary" busy={busy} disabled={!data || !data.allowed || !data.left || !f.reason || (f.reason === "other" && !f.note.trim())} onClick={save}>Void this round and send a retake</Btn></>}>
      {error ? <div className="sc-note bad">{String(error)}</div> : !data ? <Loading /> : (
        <div className="col" style={{ gap: 12 }}>
          <p className="small" style={{ margin: 0 }}>
            <b>{data.round}</b> goes to <b>Voided</b>: it's kept for the record{data.evidence?.videos ? " with its video" : ""}, but left out of scores, comparisons and decisions.
            The candidate gets a new invite for the same round{live ? ", and anyone still in the room is told the session ended" : ""}.
          </p>
          <div className="row wrap" style={{ gap: 8 }}>
            <Chip kind={data.left ? "info" : "bad"}>{data.left ? `${data.left} of ${data.limit} retakes left for this round` : `No retakes left (limit ${data.limit})`}</Chip>
            <Chip>{data.credits ? `Uses ${data.credits} credit${data.credits > 1 ? "s" : ""}, like a re-interview` : "No credits"}</Chip>
          </div>
          {!data.allowed && <div className="sc-note warn">{data.status === "invited" || data.status === "scheduled" ? "This round hasn't started yet. Reschedule it instead." : "This round can't be retaken."}</div>}
          {!data.left && data.allowed && <div className="sc-note bad">The limit is set by Code2Hire. Ask support if this candidate needs another retake.</div>}
          <Field label="What went wrong?">
            <Select value={f.reason} onChange={(v) => setF({ ...f, reason: v })} options={[{ value: "", label: "Choose…" }, ...data.reasons]} />
          </Field>
          <Field label={f.reason === "other" ? "Details (required)" : "Details (optional)"}>
            <Textarea value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} placeholder="For example: the candidate's video froze after 10 minutes and didn't come back." maxLength={1000} />
          </Field>
          {(data.evidence?.connection || ["f2f_isha", "f2f_human"].includes(data.type)) && (
            <Field label="New time (optional)" hint="Leave empty to let the candidate join when you're both ready.">
              <input className="input" type="datetime-local" value={f.scheduled_at} onChange={(e) => setF({ ...f, scheduled_at: e.target.value })} />
            </Field>
          )}
          <Evidence ev={data.evidence} />
        </div>
      )}
    </Modal>
  );
}
