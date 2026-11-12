import { useState } from "react";
import { useNavigate } from "react-router-dom";
import DataTable from "../../components/DataTable";
import { AgentNote } from "../../components/Mascot";
import RetakeModal from "../../components/Retake";
import { PageHead } from "../../components/Shell";
import { Btn, ROUND_LABEL, Status, fmtDate } from "../../components/ui";

const RETAKEABLE = ["in_progress", "paused", "completed", "reviewed", "not_finished", "expired"];

export default function Interviews() {
  const nav = useNavigate();
  const [retake, setRetake] = useState(null);  // V02.00.08: retake after a technical problem
  const [rk, setRk] = useState(0);
  return (
    <>
      <PageHead title="My interviews" sub="Face-to-face rounds where you are the interviewer." />
      <AgentNote agent="isha" title="You don't need to be an expert">Open the live room a few minutes early. I'll have a plan from the JD, the resume and earlier rounds, and I'll suggest the next question after every sentence.</AgentNote>
      <DataTable endpoint="/interviews" defaultSort="scheduled" reloadKey={rk} onRow={(r) => r.status === "voided" ? null : nav(r.report ? `/app/reports/${r.id}` : `/app/isha/${r.id}`)}
        filters={[{ key: "status", label: "Status", options: [{ value: "invited,scheduled", label: "Upcoming" }, { value: "in_progress", label: "In progress" }, { value: "completed,reviewed", label: "Done" }, { value: "voided", label: "Voided (retaken)" }] }]}
        columns={[{ key: "candidate", label: "Candidate", render: (r) => <b>{r.candidate}</b> }, { key: "job", label: "Job" },
          { key: "name", label: "Round", render: (r) => <span>{r.name} <span className="tiny muted">{ROUND_LABEL[r.round_type]}</span></span> },
          { key: "scheduled_at", label: "When", sort: "scheduled", render: (r) => r.scheduled_at ? fmtDate(r.scheduled_at, true) : "Not scheduled" },
          { key: "status", label: "Status", sort: "status", render: (r) => <Status s={r.status} /> },
          { key: "go", label: "", render: (r) => <span className="row" style={{ gap: 6, justifyContent: "flex-end" }}>
            {RETAKEABLE.includes(r.status) && <Btn size="sm" kind="ghost" title="It went wrong for a technical reason: void it and send a new invite" onClick={(e) => { e.stopPropagation(); setRetake(r); }}>Retake</Btn>}
            {r.status === "voided" ? null : r.report ? <Btn size="sm">Report</Btn> : <Btn size="sm" kind="primary">Open live room</Btn>}</span> }]} />
      {retake && <RetakeModal attemptId={retake.id} live={["in_progress", "paused"].includes(retake.status)} onClose={() => setRetake(null)} onDone={() => { setRetake(null); setRk(rk + 1); }} />}
    </>
  );
}
