import { useState } from "react";
import { api } from "../../api";
import DataTable from "../../components/DataTable";
import { PageHead } from "../../components/Shell";
import { Btn, Chip, Field, Modal, Select, Status, useAction, useAsync } from "../../components/ui";

export default function Talent() {
  const [add, setAdd] = useState(null);
  return (
    <>
      <PageHead title="Talent pool" sub="Everyone who has applied to your company. Re-use strong people for new jobs." />
      <DataTable endpoint="/talent-pool" defaultSort="created" selectable bulk={(ids, done) => <Btn size="sm" kind="gold" onClick={() => setAdd({ ids, done })}>Add to a job</Btn>}
        columns={[{ key: "name", label: "Name", sort: "name", render: (r) => <div><b>{r.name}</b><div className="tiny muted">{r.headline || r.email}</div></div> },
          { key: "skills", label: "Skills", render: (r) => <div className="row wrap" style={{ maxWidth: 360 }}>{r.skills.map((s, i) => <Chip key={i} kind={s.verified ? "good" : ""}>{s.name} L{s.level}{s.verified ? " ✓" : ""}</Chip>)}</div> },
          { key: "applications", label: "Applications" }, { key: "best_stage", label: "Furthest stage", render: (r) => <Status s={r.best_stage} /> }]} />
      {add && <AddToJob ids={add.ids} onClose={() => setAdd(null)} onDone={add.done} />}
    </>
  );
}

function AddToJob({ ids, onClose, onDone }) {
  const { data } = useAsync(() => api.get("/jobs", { status: "live", size: 100 }), []);
  const [job, setJob] = useState("");
  const [run, busy] = useAction();
  return (
    <Modal title={`Add ${ids.length} people to a job`} onClose={onClose} footer={<Btn kind="primary" busy={busy} disabled={!job} onClick={() => run(() => api.post("/talent-pool/add-to-job", { job_id: +job, user_ids: ids })).then((r) => { alert(`${r.added} added.`); onDone(); onClose(); })}>Add</Btn>}>
      <Field label="Live job"><Select value={job} onChange={setJob} options={[{ value: "", label: "Choose…" }, ...(data?.items || []).map((j) => ({ value: String(j.id), label: j.title }))]} /></Field>
    </Modal>
  );
}
