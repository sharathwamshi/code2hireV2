import { useEffect, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import AddCandidate, { ShareLink } from "../../components/AddCandidate";
import DataTable from "../../components/DataTable";
import { fmtPhone } from "../../lib/validate";
import { AgentNote } from "../../components/Mascot";
import { PageHead } from "../../components/Shell";
import { Btn, Chip, Modal, ago, fmtDate, useAction } from "../../components/ui";

/** Account states, with what each one means (shown as a tooltip). */
export const ACCOUNT = {
  not_sent: ["Not sent", "", "A link was created but nobody has copied or sent it yet."],
  invited: ["Not sent", "", "A link was created but nobody has copied or sent it yet."],
  sent: ["Link sent", "info", "The link was copied or sent. They haven't opened it yet."],
  opened: ["Opened link", "gold", "They opened their link and are in, but haven't set a password yet."],
  active: ["Active", "good", "They sign in with their own password. No link is needed."],
  expired: ["Link expired", "bad", "The link expired before they set a password. Create a new one."],
  no_link: ["No link yet", "", "They were added or applied without a personal link. Create one to invite them to their portal."],
};
export function AccountState({ state }) {
  const a = ACCOUNT[state] || [state, ""];
  return <Chip kind={a[1]} title={a[2]}>{a[0]}</Chip>;
}
export const NEW_LINK_TIP = "Creates a new personal link. Any earlier link stops working.";

/** Asks first (the old link stops working), then creates the link and shows the ways to send it. */
export function NewLink({ user, onClose }) {
  const { me } = useAuth();
  const [res, setRes] = useState(null);
  const [run, busy] = useAction();
  const hadLink = ["not_sent", "invited", "sent", "opened"].includes(user.state || user.account);
  const create = () => run(() => api.post(`/candidates/${user.id}/link`)).then(setRes).catch(() => {});
  useEffect(() => { if (!hadLink) create(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  if (!res && hadLink) {
    return <Modal title={`New link for ${user.name}?`} onClose={onClose} footer={<><Btn onClick={onClose}>Cancel</Btn><Btn kind="primary" busy={busy} onClick={create}>Create new link</Btn></>}>
      <p style={{ margin: 0 }}>{user.name} already has a link{(user.state || user.account) === "opened" ? " and has opened it" : ""}. A new link cancels the earlier one, so only send the new one.</p>
    </Modal>;
  }
  return <Modal title={`Link for ${user.name}`} onClose={onClose} footer={<Btn kind="primary" onClick={onClose}>Close</Btn>}>
    {!res ? <span className="spin" /> : <>{hadLink && <p className="small" style={{ margin: 0 }}>The earlier link no longer works. Send this one instead.</p>}
      <ShareLink userId={user.id} name={user.name} email={user.email} link={res.link} company={me?.company?.name} expires={res.expires_at} /></>}
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
      <AgentNote agent="disha">“Not sent” means the link exists but nobody has copied or sent it yet. “Link sent” means it went out but they haven't opened it. “Opened link” means they're in, but haven't set a password. “Active” means they sign in with their own password; no link is needed. Hover a status to see what it means.</AgentNote>
      <DataTable endpoint="/candidates" reloadKey={rk} defaultSort="added" searchPlaceholder="Search name or email…"
        columns={[{ key: "name", label: "Candidate", sort: "name", render: (r) => <div><b>{r.name}</b><div className="tiny muted">{r.email}{r.phone ? ` · ${fmtPhone(r.phone)}` : ""}</div></div> },
          { key: "jobs", label: "Jobs", render: (r) => r.jobs.length ? <div className="row wrap">{r.jobs.map((j, i) => <Chip key={i}>{j}</Chip>)}</div> : <span className="small muted">Talent pool</span> },
          { key: "state", label: "Account", render: (r) => <AccountState state={r.state} /> },
          { key: "added_by", label: "Added by" }, { key: "added", label: "Added", sort: "added", render: (r) => <span className="small">{fmtDate(r.added_at)}</span> },
          { key: "seen", label: "Last seen", render: (r) => <span className="small">{r.last_login_at ? ago(r.last_login_at) : "—"}</span> },
          { key: "act", label: "", render: (r) => r.state !== "active" ? <Btn size="sm" title={NEW_LINK_TIP} onClick={(e) => { e.stopPropagation(); setLink(r); }}>New link</Btn> : null }]}
        filters={[{ key: "state", label: "Account", options: ["not_sent", "sent", "opened", "active", "expired", "no_link"].map((v) => ({ value: v, label: ACCOUNT[v][0] })) }]} />
      {add && <AddCandidate onClose={() => { setAdd(false); setRk(rk + 1); }} />}
      {link && <NewLink user={link} onClose={() => { setLink(null); setRk(rk + 1); }} />}
    </>
  );
}
