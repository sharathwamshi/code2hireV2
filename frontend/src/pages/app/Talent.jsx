import { useState } from "react";
import { api } from "../../api";
import AddCandidate from "../../components/AddCandidate";
import DataTable from "../../components/DataTable";
import EditCandidate from "../../components/EditCandidate";
import { AccountState, NEW_LINK_TIP, NewLink } from "./AddedCandidates";
import { useAuth } from "../../auth";
import { PageHead } from "../../components/Shell";
import { Btn, Chip, Field, Modal, Select, Status, useAction, useAsync, useConfirm, useToast } from "../../components/ui";

export default function Talent() {
  const [add, setAdd] = useState(null);
  const [nw, setNw] = useState(false);
  const [link, setLink] = useState(null);
  const [rk, setRk] = useState(0);
  const { can } = useAuth();
  const [edit, setEdit] = useState(null);
  const [removed, setRemoved] = useState(false);  // V02.00.08 (A3)
  const [run] = useAction();
  const ask = useConfirm();
  const removeFromPool = async (ids, done, names) => {
    const ok = await ask({ title: ids.length === 1 ? `Remove ${names[0]} from your talent pool?` : `Remove ${ids.length} people from your talent pool?`, yes: "Remove", danger: true,
      text: "They leave your talent pool and your searches. Their Code2Hire account and any jobs they're in stay (use Remove from job for those). Adding them again by email brings them back, or restore them from Removed." });
    if (ok) run(() => api.post("/talent-pool/remove", { user_ids: ids }), "Removed from your talent pool").then(() => { done(); setRk(rk + 1); }).catch(() => {});
  };
  const restore = (ids, done) => run(() => api.post("/talent-pool/restore", { user_ids: ids }), "Back in your talent pool").then(() => { done(); setRk(rk + 1); }).catch(() => {});
  return (
    <>
      <PageHead title="Talent pool" sub="Everyone who applied to your company or was added by your team. Re-use strong people for new jobs."
        actions={can("candidates.add") && <Btn kind="primary" onClick={() => setNw(true)}>+ Add candidate</Btn>} />
      <DataTable endpoint="/talent-pool" defaultSort="created" selectable reloadKey={rk} onSelectionChange={(ids) => { if (!ids.length) setAdd(null); }}
        params={{ removed: removed ? "true" : "" }} rowLabel={(r) => r.name}
        toolbarStart={<div className="seg" role="group" aria-label="Which people"><button type="button" className={!removed ? "on" : ""} onClick={() => setRemoved(false)}>Talent pool</button><button type="button" className={removed ? "on" : ""} onClick={() => setRemoved(true)}>Removed</button></div>}
        bulk={(ids, done, names) => removed
          ? <Btn size="sm" kind="gold" onClick={() => restore(ids, done)}>Restore to pool</Btn>
          : <><Btn size="sm" kind="gold" onClick={() => setAdd({ ids, done, names })}>Add to a job</Btn>{can("candidates.move") && <Btn size="sm" kind="ghost" onClick={() => removeFromPool(ids, done, names)}>Remove from pool</Btn>}</>}
        columns={[{ key: "name", label: "Name", sort: "name", render: (r) => <div><b>{r.name}</b><div className="tiny muted">{r.headline || r.email}</div></div> },
          { key: "skills", label: "Skills", render: (r) => <div className="row wrap" style={{ maxWidth: 360 }}>{r.skills.map((s, i) => <Chip key={i} kind={s.verified ? "good" : ""}>{s.name} L{s.level}{s.verified ? " ✓" : ""}</Chip>)}</div> },
          { key: "applications", label: "Applications" }, { key: "best_stage", label: "Furthest stage", render: (r) => r.best_stage ? <Status s={r.best_stage} /> : <span className="small muted">Not applied yet</span> },
          { key: "account", label: "Account", render: (r) => <span className="state-cell"><AccountState state={r.account} />
            {r.account !== "active" && can("candidates.add") ? <Btn size="sm" kind="ghost" title={NEW_LINK_TIP} onClick={(e) => { e.stopPropagation(); setLink(r); }}>New link</Btn> : <span />}</span> },
          ...(can("candidates.edit") ? [{ key: "edit", label: "", render: (r) => <Btn size="sm" onClick={(e) => { e.stopPropagation(); setEdit(r.id); }} aria-label={`Edit ${r.name}`}>Edit</Btn> }] : [])]} />
      {edit && <EditCandidate id={edit} onClose={() => setEdit(null)} onSaved={() => setRk((x) => x + 1)} />}
      {nw && <AddCandidate onClose={() => { setNw(false); setRk(rk + 1); }} onDone={() => setRk((x) => x + 1)} />}
      {link && <NewLink user={link} onClose={() => { setLink(null); setRk(rk + 1); }} />}
      {add && <AddToJob ids={add.ids} names={add.names} onClose={() => setAdd(null)} onDone={add.done} />}
    </>
  );
}

function AddToJob({ ids, names = [], onClose, onDone }) {
  const { data } = useAsync(() => api.get("/jobs", { status: "live", size: 100 }), []);
  const [job, setJob] = useState("");
  const [run, busy] = useAction();
  const toast = useToast();
  return (
    <Modal title={`Add ${ids.length} ${ids.length === 1 ? "person" : "people"} to a job`} onClose={onClose} footer={<><Btn onClick={onClose}>Cancel</Btn><Btn kind="primary" busy={busy} disabled={!job} onClick={() => run(() => api.post("/talent-pool/add-to-job", { job_id: +job, user_ids: ids })).then((r) => { toast(`${r.added} added${r.skipped ? `, ${r.skipped} already on this job` : ""}.`, "good"); onDone(); onClose(); }).catch(() => {})}>Add</Btn></>}>
      {names.length > 0 && <div className="small muted">{names.slice(0, 6).join(", ")}{names.length > 6 ? ` and ${names.length - 6} more` : ""}</div>}
      <Field label="Live job"><Select value={job} onChange={setJob} options={[{ value: "", label: "Choose…" }, ...(data?.items || []).map((j) => ({ value: String(j.id), label: j.title }))]} /></Field>
    </Modal>
  );
}
