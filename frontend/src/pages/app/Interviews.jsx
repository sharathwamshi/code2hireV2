import { useNavigate } from "react-router-dom";
import DataTable from "../../components/DataTable";
import { AgentNote } from "../../components/Mascot";
import { PageHead } from "../../components/Shell";
import { Btn, ROUND_LABEL, Status, fmtDate } from "../../components/ui";

export default function Interviews() {
  const nav = useNavigate();
  return (
    <>
      <PageHead title="My interviews" sub="Face-to-face rounds where you are the interviewer." />
      <AgentNote agent="isha" title="You don't need to be an expert">Open the live room a few minutes early. I'll have a plan from the JD, the resume and earlier rounds, and I'll suggest the next question after every sentence.</AgentNote>
      <DataTable endpoint="/interviews" defaultSort="scheduled" onRow={(r) => nav(r.report ? `/app/reports/${r.id}` : `/app/isha/${r.id}`)}
        filters={[{ key: "status", label: "Status", options: [{ value: "invited,scheduled", label: "Upcoming" }, { value: "in_progress", label: "In progress" }, { value: "completed,reviewed", label: "Done" }] }]}
        columns={[{ key: "candidate", label: "Candidate", render: (r) => <b>{r.candidate}</b> }, { key: "job", label: "Job" },
          { key: "name", label: "Round", render: (r) => <span>{r.name} <span className="tiny muted">{ROUND_LABEL[r.round_type]}</span></span> },
          { key: "scheduled_at", label: "When", sort: "scheduled", render: (r) => r.scheduled_at ? fmtDate(r.scheduled_at, true) : "Not scheduled" },
          { key: "status", label: "Status", sort: "status", render: (r) => <Status s={r.status} /> },
          { key: "go", label: "", render: (r) => r.report ? <Btn size="sm">Report</Btn> : <Btn size="sm" kind="primary">Open live room</Btn> }]} />
    </>
  );
}
