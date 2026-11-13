// N6 (V02.00.09): one "Interview again" window, the same on every page and for every role. It shows the round's
// state and only the options that make sense for it: change the time or interviewer, re-send a missed invite,
// retake after a technical problem, a second assessment (re-interview), or (superadmin) grant one after a dispute.
import { useEffect, useState } from "react";
import { api } from "../api";
import { Evidence } from "./Retake";
import { Btn, Chip, Field, Loading, Modal, Select, Status, Textarea, fmtDate, localInputToISO, useAction, useAsync } from "./ui";

const F2F = ["f2f_isha", "f2f_human"];

export default function InterviewAgain({ attemptId, preset, onClose, onDone }) {
  const { data, error } = useAsync(() => api.get(`/attempts/${attemptId}/again`), [attemptId]);
  const { data: ivs } = useAsync(() => api.get("/company/interviewers").catch(() => []), []);
  const [action, setAction] = useState(preset || "");
  const [f, setF] = useState({ reason: "", note: "", scheduled_at: "", interviewer_id: "" });
  const [run, busy] = useAction();
  useEffect(() => {
    if (!data) return;
    const ok = data.options.filter((o) => o.allowed);
    if (!action || !ok.find((o) => o.key === action)) setAction(ok.length === 1 ? ok[0].key : (preset && ok.find((o) => o.key === preset) ? preset : ok[0]?.key || ""));
  }, [data]); // eslint-disable-line react-hooks/exhaustive-deps
  const opt = data?.options.find((o) => o.key === action);
  const f2f = data && F2F.includes(data.type);
  const need = action === "retake" ? (!f.reason || (f.reason === "other" && !f.note.trim()))
    : action === "reschedule" ? (!f.scheduled_at && !f.interviewer_id) : action === "dispute" ? !f.note.trim() : false;
  const save = () => run(() => api.post(`/attempts/${attemptId}/again`, {
    action, reason: f.reason || undefined, note: f.note || undefined, interviewer_id: f.interviewer_id || undefined,
    scheduled_at: f.scheduled_at ? localInputToISO(f.scheduled_at) : undefined,
  })).then((r) => onDone?.(r));
  const label = { reschedule: "Save changes", resend: "Send new invite", retake: "Void this round and send a retake", reinterview: "Send re-interview", dispute: "Grant re-interview" }[action] || "Continue";
  return (
    <Modal wide title="Interview again" onClose={onClose}
      footer={<><Btn onClick={onClose}>Cancel</Btn><Btn kind={action === "retake" ? "danger" : "primary"} busy={busy} disabled={!opt?.allowed || need} onClick={save}>{label}</Btn></>}>
      {error ? <div className="sc-note bad">{String(error)}</div> : !data ? <Loading /> : (
        <div className="col" style={{ gap: 14 }}>
          <div className="row wrap" style={{ gap: 8 }}>
            <b>{data.candidate}</b><span className="muted">·</span><span>{data.round}</span><span className="muted">·</span><span className="muted">{data.job}</span><Status s={data.status} />
            {data.interviewer && <Chip>Interviewer: {data.interviewer}</Chip>}{data.scheduled_at && <Chip>{fmtDate(data.scheduled_at, true)}</Chip>}
          </div>
          <div className="col" style={{ gap: 8 }} role="radiogroup" aria-label="What do you need?">
            <b className="small">What do you need?</b>
            {data.options.map((o) => (
              <label key={o.key} className={"again-opt" + (action === o.key ? " on" : "") + (o.allowed ? "" : " off")}>
                <input type="radio" name="again" disabled={!o.allowed} checked={action === o.key} onChange={() => setAction(o.key)} />
                <div className="grow">
                  <div className="row wrap" style={{ gap: 6 }}><b>{o.label}</b>
                    {o.allowed && <Chip kind={o.credits ? "warn" : "good"}>{o.credits ? `${o.credits} credit${o.credits > 1 ? "s" : ""}` : "Free"}</Chip>}
                    {o.counts && <Chip kind={o.counts.used >= o.counts.limit ? "bad" : "info"}>{o.counts.used} of {o.counts.limit} used</Chip>}
                  </div>
                  <div className="small muted">{o.allowed ? o.help : o.why}</div>
                </div>
              </label>))}
            {!data.options.some((o) => o.allowed) && <div className="sc-note warn">Nothing can be done for this round right now. The reasons are under each option.</div>}
          </div>
          {action === "retake" && <Field label="What went wrong?"><Select value={f.reason} onChange={(v) => setF({ ...f, reason: v })} options={[{ value: "", label: "Choose…" }, ...data.reasons]} /></Field>}
          {action && <Field label={action === "retake" && f.reason === "other" ? "Details (required)" : action === "dispute" ? "Note for the candidate (required)" : "Note (optional)"}>
            <Textarea value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} maxLength={1000}
              placeholder={action === "retake" ? "For example: the candidate's video froze after 10 minutes and didn't come back." : action === "reinterview" ? "Why a second assessment?" : action === "resend" ? "For example: the candidate was unwell that day." : ""} /></Field>}
          {action && action !== "dispute" && (f2f || action === "reschedule") && <div className="grid g2">
            <Field label="Interviewer" hint={action === "reschedule" ? "Leave as is to keep the same person." : "Leave empty to keep the same person."}>
              <Select value={String(f.interviewer_id)} onChange={(v) => setF({ ...f, interviewer_id: v })} options={[{ value: "", label: data.interviewer ? `Keep ${data.interviewer}` : "Keep as is" }, ...(ivs || []).map((u) => ({ value: String(u.id), label: u.name }))]} /></Field>
            <Field label="New time (optional)" hint="Leave empty to let the candidate join when you're both ready.">
              <input className="input" type="datetime-local" value={f.scheduled_at} onChange={(e) => setF({ ...f, scheduled_at: e.target.value })} /></Field>
          </div>}
          {action === "retake" && <Evidence ev={data.evidence} />}
        </div>
      )}
    </Modal>
  );
}
