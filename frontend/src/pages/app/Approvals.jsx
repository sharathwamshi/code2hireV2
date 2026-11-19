import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { Hira } from "../../components/Mascot";
import { PageHead } from "../../components/Shell";
import PaperReview from "../../components/PaperReview";
import { Btn, Chip, Empty, Loading, Seg, Status, Tabs, ago, useAction, useAsync, useConfirm, useToast } from "../../components/ui";

export default function Approvals() {
  const { can } = useAuth();
  const decider = can("approvals.decide");
  const [tab, setTab] = useState(() => (!decider || new URLSearchParams(window.location.search).get("tab") === "papers" ? "papers" : "requests"));
  const { data: waiting, reload: reloadPapers } = useAsync(() => api.get("/papers/waiting").catch(() => []), []);
  return (
    <>
      <PageHead title="Approvals" sub="Requests your company policies send for a second pair of eyes, and MCQ questions to check before candidates start." />
      <Tabs value={tab} onChange={setTab} tabs={[...(decider ? [["requests", "Requests"]] : []), ["papers", `MCQ papers${waiting?.length ? ` (${waiting.length})` : ""}`]]} />
      {tab === "requests" ? <Requests /> : <Papers list={waiting} reload={reloadPapers} />}
    </>
  );
}

/** A1 (V02.00.12): MCQ papers waiting for review, grouped by job, with Approve all. */
function Papers({ list, reload }) {
  const toast = useToast();
  const ask = useConfirm();
  const nav = useNavigate();
  const [open, setOpen] = useState(null);
  if (!list) return <Loading />;
  if (!list.length) return <Empty title="No questions to check" mascot={<Hira size={80} mood="happy" />} text="When you invite someone to an MCQ round, their questions wait here until someone checks them. The candidate can start once they're approved." />;
  const jobs = [...new Map(list.map((w) => [w.job_id, w.job])).entries()];
  return jobs.map(([jid, title]) => {
    const rows = list.filter((w) => w.job_id === jid);
    return (
      <div key={jid} className="card">
        <div className="card-h"><h3 className="grow">{title}</h3><Chip kind="warn">{rows.length} waiting</Chip>
          <Btn size="sm" kind="primary" onClick={async () => (await ask({ title: `Approve all ${rows.length} papers for ${title}?`, text: "Every candidate waiting on this job can start straight away. Open a paper first if you want to check its questions.", yes: "Approve all" })) &&
            api.post(`/jobs/${jid}/papers/approve-all`).then((r) => { toast(`${r.approved} approved${r.skipped ? `, ${r.skipped} skipped (no questions yet)` : ""}`, "good"); reload(); }).catch((e) => toast(e.message, "bad"))}>Approve all</Btn></div>
        {rows.map((w) => <div key={w.attempt_id} className="list-row"><div className="grow"><b>{w.candidate}</b><div className="small muted">{w.questions} of {w.wanted} questions · invited {ago(w.invited_at)}</div></div>
          {w.questions < w.wanted && <Chip kind="warn">Short by {w.wanted - w.questions}</Chip>}
          <Btn size="sm" onClick={() => nav(`/app/applications/${w.application_id}`)}>Application</Btn>
          <Btn size="sm" kind="primary" onClick={() => setOpen(w)}>Review questions</Btn></div>)}
        {open && rows.some((w) => w.attempt_id === open.attempt_id) && <PaperReview attemptId={open.attempt_id} name={open.candidate} onClose={() => { setOpen(null); reload(); }} onChanged={reload} />}
      </div>
    );
  });
}

function Requests() {
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
      <div className="row"><Seg value={status} onChange={setStatus} options={[["pending", "Waiting"], ["approved", "Approved"], ["rejected", "Rejected"], ["all", "All"]]} /></div>
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
