import { useState } from "react";
import { useNavigate } from "react-router-dom";
import DataTable from "../../components/DataTable";
import { AgentNote } from "../../components/Mascot";
import InterviewAgain from "../../components/InterviewAgain";
import CloseInterview from "../../components/CloseInterview";
import { PageHead } from "../../components/Shell";
import { Btn, ROUND_LABEL, Status, fmtDate, useToast } from "../../components/ui";

const OPEN = ["in_progress", "paused", "not_finished"];

export default function Interviews() {
  const nav = useNavigate();
  const [again, setAgain] = useState(null);  // N6 (V02.00.09): one "Interview again" action
  const [closing, setClosing] = useState(null);  // N4 (V02.00.09)
  const [rk, setRk] = useState(0);
  const toast = useToast();
  return (
    <>
      <PageHead title="My interviews" sub="Face-to-face rounds where you are the interviewer." />
      <AgentNote agent="isha" title="You don't need to be an expert">Open the live room a few minutes early. I'll have a plan from the JD, the resume and earlier rounds, and I'll suggest the next question after every sentence.</AgentNote>
      <DataTable endpoint="/interviews" defaultSort="scheduled" reloadKey={rk} onRow={(r) => ["voided", "cancelled", "expired"].includes(r.status) ? null : nav(r.report ? `/app/reports/${r.id}` : `/app/isha/${r.id}`)}
        filters={[{ key: "status", label: "Status", options: [{ value: "invited,scheduled", label: "Upcoming" }, { value: "in_progress", label: "In progress" }, { value: "not_finished", label: "Not finished" }, { value: "completed,reviewed", label: "Done" }, { value: "expired", label: "Missed" }, { value: "voided", label: "Voided (retaken)" }] }]}
        columns={[{ key: "candidate", label: "Candidate", render: (r) => <b>{r.candidate}</b> }, { key: "job", label: "Job" },
          { key: "name", label: "Round", render: (r) => <span>{r.name} <span className="tiny muted">{ROUND_LABEL[r.round_type]}</span></span> },
          { key: "scheduled_at", label: "When", sort: "scheduled", render: (r) => r.scheduled_at ? fmtDate(r.scheduled_at, true) : "Not scheduled" },
          { key: "status", label: "Status", sort: "status", render: (r) => <Status s={r.status} /> },
          { key: "go", label: "Actions", render: (r) => <span className="row" style={{ gap: 6, justifyContent: "flex-end" }}>
            {OPEN.includes(r.status) && <Btn size="sm" kind="ghost" title="Submit the scorecard from what was captured, or close it without one" onClick={(e) => { e.stopPropagation(); setClosing(r); }}>Close</Btn>}
            {!["voided", "cancelled"].includes(r.status) && <Btn size="sm" kind="ghost" title="Change the time, re-send, retake or re-interview" onClick={(e) => { e.stopPropagation(); setAgain(r); }}>Interview again</Btn>}
            {["voided", "cancelled", "expired"].includes(r.status) ? null : r.report ? <Btn size="sm">Report</Btn> : <Btn size="sm" kind="primary">{r.status === "not_finished" ? "Open" : "Open live room"}</Btn>}</span> }]} />
      {again && <InterviewAgain attemptId={again.id} onClose={() => setAgain(null)} onDone={(r) => { setAgain(null); toast(r?.message || "Done"); setRk(rk + 1); }} />}
      {closing && <CloseInterview attemptId={closing.id} onClose={() => setClosing(null)} onAgain={() => { setAgain(closing); setClosing(null); }} onDone={() => { setClosing(null); setRk(rk + 1); }} />}
    </>
  );
}
