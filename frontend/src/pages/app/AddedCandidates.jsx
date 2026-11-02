import { useEffect, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import AddCandidate, { ShareLink } from "../../components/AddCandidate";
import DataTable from "../../components/DataTable";
import { AgentNote } from "../../components/Mascot";
import { PageHead } from "../../components/Shell";
import { Btn, Chip, Modal, ago, fmtDate, useAction } from "../../components/ui";

export const ACCOUNT = { invited: ["Link sent", "info"], opened: ["Opened link", "gold"], active: ["Active", "good"], expired: ["Link expired", "bad"], no_link: ["No link", ""] };

export function NewLink({ user, onClose }) {
  const { me } = useAuth();
  const [res, setRes] = useState(null);
  const [run, busy] = useAction();
  useEffect(() => { run(() => api.post(`/candidates/${user.id}/link`)).then(setRes).catch(onClose); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return <Modal title={`New link for ${user.name}`} onClose={onClose} footer={<Btn kind="primary" onClick={onClose}>Done</Btn>}>
    {busy || !res ? <span className="spin" /> : <><p className="small">The earlier link no longer works. Send this one instead.</p><ShareLink name={user.name} link={res.link} company={me?.company?.name} expires={res.expires_at} /></>}
  </Modal>;
}

export default function AddedCandidates() {
  const [add, setAdd] = useState(false);
  const [link, setLink] = useState(null);
  const [rk, setRk] = useState(0);
  useEffect(() => { const f = () => setRk((x) => x + 1); window.addEventListener("c2h:candidates", f); return () => window.removeEventListener("c2h:candidates", f); }, []);
  return (
    <>
      <PageHead title="Added candidates" sub="People your team added. Each gets a personal link that opens their portal, where they set their own password."
        actions={<Btn kind="primary" onClick={() => setAdd(true)}>+ Add candidate</Btn>} />
      <AgentNote agent="disha">“Link sent” means they haven't opened it yet. “Opened link” means they're in, but haven't set a password. “Active” means they sign in with their own password; no new link is needed.</AgentNote>
      <DataTable endpoint="/candidates" reloadKey={rk} defaultSort="added" searchPlaceholder="Search name or email…"
        columns={[{ key: "name", label: "Candidate", sort: "name", render: (r) => <div><b>{r.name}</b><div className="tiny muted">{r.email}{r.phone ? ` · ${r.phone}` : ""}</div></div> },
          { key: "jobs", label: "Jobs", render: (r) => r.jobs.length ? <div className="row wrap">{r.jobs.map((j, i) => <Chip key={i}>{j}</Chip>)}</div> : <span className="small muted">Talent pool</span> },
          { key: "state", label: "Account", render: (r) => <Chip kind={ACCOUNT[r.state]?.[1]}>{ACCOUNT[r.state]?.[0] || r.state}</Chip> },
          { key: "added_by", label: "Added by" }, { key: "added", label: "Added", sort: "added", render: (r) => <span className="small">{fmtDate(r.added_at)}</span> },
          { key: "seen", label: "Last seen", render: (r) => <span className="small">{r.last_login_at ? ago(r.last_login_at) : "—"}</span> },
          { key: "act", label: "", render: (r) => r.state !== "active" && <Btn size="sm" onClick={(e) => { e.stopPropagation(); setLink(r); }}>{r.state === "expired" ? "Send new link" : "Get link again"}</Btn> }]} />
      {add && <AddCandidate onClose={() => { setAdd(false); setRk(rk + 1); }} />}
      {link && <NewLink user={link} onClose={() => { setLink(null); setRk(rk + 1); }} />}
    </>
  );
}
