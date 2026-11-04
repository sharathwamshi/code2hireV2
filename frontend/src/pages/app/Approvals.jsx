import { useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { Hira } from "../../components/Mascot";
import { PageHead } from "../../components/Shell";
import { Btn, Chip, Empty, Loading, Seg, Status, ago, useAction, useAsync, useConfirm } from "../../components/ui";

export default function Approvals() {
  const { me } = useAuth();
  const [status, setStatus] = useState("pending");
  const { data, reload } = useAsync(() => api.get("/company/approvals", { status }), [status]);
  const [run] = useAction();
  const ask = useConfirm();
  const decide = async (a, approve) => {
    const note = approve ? "" : await ask({ title: "Reject this request", input: { label: "Why are you rejecting it?", hint: "Shared with the requester.", required: true, multiline: true }, yes: "Reject", danger: true });
    if (!approve && note == null) return;
    run(() => api.post(`/company/approvals/${a.id}/decide`, { approve, note }), approve ? "Approved" : "Rejected").then(reload);
  };
  return (
    <>
      <PageHead title="Approvals" sub="Requests your company policies send for a second pair of eyes." actions={<Seg value={status} onChange={setStatus} options={[["pending", "Waiting"], ["approved", "Approved"], ["rejected", "Rejected"], ["all", "All"]]} />} />
      {!data ? <Loading /> : !data.length ? <Empty title="Nothing waiting" mascot={<Hira size={80} mood="happy" />} text="Publishing public jobs, offers above band and sensitive grants show up here when a policy asks for approval." /> : (
        <div className="card">{data.map((a) => (
          <div key={a.id} className="list-row">
            <div className="grow"><b>{a.title}</b><div className="small muted">{a.note} · requested by {a.requested_by_name} · {ago(a.created_at)}</div>
              <div className="row small">{(a.approvers || []).length} of {a.approvals_needed} approvals{a.payload?.salary && <Chip>Salary ₹{Number(a.payload.salary).toLocaleString("en-IN")}</Chip>}</div></div>
            <Chip kind="brand">{a.kind}</Chip><Status s={a.status} />
            {a.status === "pending" && a.requested_by !== me.user.id && !(a.approvers || []).includes(me.user.id) && <><Btn kind="danger" size="sm" onClick={() => decide(a, false)}>Reject</Btn><Btn kind="primary" size="sm" onClick={() => decide(a, true)}>Approve</Btn></>}
            {a.status === "pending" && a.requested_by === me.user.id && <span className="small muted">Your request</span>}
          </div>
        ))}</div>
      )}
    </>
  );
}
