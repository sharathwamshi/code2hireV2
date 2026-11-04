import { useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import DataTable from "../../components/DataTable";
import { AgentNote } from "../../components/Mascot";
import { ShareLink } from "../../components/AddCandidate";
import SettingsEditor, { companySettings } from "../../components/Settings";
import { PageHead } from "../../components/Shell";
import { Btn, Chip, Empty, Field, Input, Loading, Modal, Select, Switch, Tabs, fmtDate, useAction, useAsync, useToast, useConfirm } from "../../components/ui";

export default function CompanyAdmin({ initial = "people" }) {
  const [tab, setTab] = useState(initial);
  return (
    <>
      <PageHead title="Company admin" sub="People, roles, permissions, rules and settings. Everything here is logged." />
      <Tabs value={tab} onChange={setTab} tabs={[["people", "People and roles"], ["teams", "Teams"], ["roles", "Custom roles"], ["grants", "Grants and cover"], ["policies", "Policies"],
        ["settings", "Settings"], ["branding", "Company and branding"], ["review", "Access review"], ["audit", "Audit log"]]} />
      {tab === "people" && <People />}
      {tab === "teams" && <Teams />}
      {tab === "roles" && <CustomRoles />}
      {tab === "grants" && <Grants />}
      {tab === "policies" && <Policies />}
      {tab === "settings" && <ScopedSettings />}
      {tab === "branding" && <Branding />}
      {tab === "review" && <AccessReview />}
      {tab === "audit" && <DataTable endpoint="/company/audit" defaultSort="created" columns={[{ key: "created_at", label: "When", sort: "created", render: (r) => fmtDate(r.created_at, true) }, { key: "actor", label: "Who" },
        { key: "action", label: "Action", sort: "action", render: (r) => <span className="mono small">{r.action}</span> }, { key: "target", label: "Target", render: (r) => r.target_type ? `${r.target_type} #${r.target_id ?? ""}` : "—" },
        { key: "detail", label: "Detail", render: (r) => <span className="tiny muted mono">{JSON.stringify(r.detail).slice(0, 140)}</span> }]} />}
    </>
  );
}

function useCatalog() {
  const perms = useAsync(() => api.get("/company/permissions"), []);
  const comp = useAsync(() => api.get("/company"), []);
  const jobs = useAsync(() => api.get("/jobs", { size: 100 }), []);
  return { cat: perms.data, teams: comp.data?.teams || [], jobs: jobs.data?.items || [], reloadCat: perms.reload };
}

function RolesEditor({ roles, onChange, cat, teams, jobs }) {
  const roleOpts = [...Object.keys(cat.roles).map((r) => ({ value: r, label: cat.labels[r] })), ...cat.custom.map((c) => ({ value: "custom:" + c.id, label: c.name + " (custom)" }))];
  return (
    <div className="col">
      {roles.map((r, i) => (
        <div key={i} className="row">
          <div style={{ width: 230 }}><Select value={r.role} onChange={(v) => { const x = [...roles]; x[i] = { ...r, role: v }; onChange(x); }} options={roleOpts} /></div>
          <div style={{ width: 150 }}><Select value={r.scope_type} onChange={(v) => { const x = [...roles]; x[i] = { ...r, scope_type: v, scope_id: null }; onChange(x); }} options={[{ value: "company", label: "Whole company" }, { value: "team", label: "One team" }, { value: "job", label: "One job" }]} /></div>
          {r.scope_type === "team" && <Select value={String(r.scope_id || "")} onChange={(v) => { const x = [...roles]; x[i] = { ...r, scope_id: +v }; onChange(x); }} options={[{ value: "", label: "Choose team" }, ...teams.map((t) => ({ value: String(t.id), label: t.name }))]} />}
          {r.scope_type === "job" && <Select value={String(r.scope_id || "")} onChange={(v) => { const x = [...roles]; x[i] = { ...r, scope_id: +v }; onChange(x); }} options={[{ value: "", label: "Choose job" }, ...jobs.map((j) => ({ value: String(j.id), label: j.title }))]} />}
          <Btn size="sm" kind="ghost" onClick={() => onChange(roles.filter((_, j) => j !== i))}>✕</Btn>
        </div>
      ))}
      <Btn size="sm" onClick={() => onChange([...roles, { role: "interviewer", scope_type: "company" }])}>+ Add a role</Btn>
      <p className="small muted">Roles stack. One person can be a manager for the whole company, a recruiter on one team and an interviewer on one job.</p>
    </div>
  );
}

function People() {
  const { me } = useAuth();
  const { cat, teams, jobs } = useCatalog();
  const [rk, setRk] = useState(0);
  const [edit, setEdit] = useState(null);
  const [invite, setInvite] = useState(false);
  const [temp, setTemp] = useState(null);
  const [run, busy] = useAction();
  if (!cat) return <Loading />;
  return (
    <>
      <DataTable endpoint="/company/users" reloadKey={rk} defaultSort="name" onRow={(r) => setEdit({ ...r, roles: r.roles.map((x) => ({ role: x.role, scope_type: x.scope_type, scope_id: x.scope_id })) })}
        toolbar={<Btn size="sm" kind="primary" onClick={() => setInvite({ name: "", email: "", roles: [{ role: "recruiter", scope_type: "company" }] })}>Invite person</Btn>}
        filters={[{ key: "active", label: "Status", options: [{ value: "true", label: "Active" }, { value: "false", label: "Switched off" }] }]}
        columns={[{ key: "name", label: "Name", sort: "name", render: (r) => <div><b>{r.name}</b><div className="tiny muted">{r.email}</div></div> },
          { key: "roles", label: "Roles", render: (r) => <div className="row wrap">{r.roles.map((x) => <Chip key={x.id} kind="brand">{x.label} · {x.scope_name}</Chip>)}{!r.roles.length && <span className="faint small">Job assignments only</span>}</div> },
          { key: "grants", label: "Extra grants", render: (r) => r.grants.length ? <Chip kind="gold">{r.grants.length}</Chip> : "—" },
          { key: "active", label: "Active", render: (r) => r.active ? <Chip kind="good">Active</Chip> : <Chip>Off</Chip> },
          { key: "last_login", label: "Last sign-in", sort: "last_login", render: (r) => fmtDate(r.last_login_at, true) }]} />
      {invite && <Modal wide title="Invite a person" onClose={() => setInvite(null)} footer={<Btn kind="primary" busy={busy} onClick={() => run(() => api.post("/company/users", invite)).then((r) => { setInvite(null); setTemp(r); setRk(rk + 1); })}>Send invite</Btn>}>
        <div className="grid g2"><Field label="Name"><Input value={invite.name} onChange={(e) => setInvite({ ...invite, name: e.target.value })} /></Field><Field label="Email"><Input value={invite.email} onChange={(e) => setInvite({ ...invite, email: e.target.value })} /></Field></div>
        <Field label="Interviewer skills (helps match interviewers to jobs)"><Input placeholder="Python, System design" onChange={(e) => setInvite({ ...invite, skills_meta: { skills: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) } })} /></Field>
        <RolesEditor roles={invite.roles} onChange={(roles) => setInvite({ ...invite, roles })} cat={cat} teams={teams} jobs={jobs} />
      </Modal>}
      {temp && <Modal title={temp.link ? "Invite ready" : "New password"} onClose={() => setTemp(null)}>
        {temp.link ? <><p>Send {temp.user.name} this personal link. It opens their workspace straight away, and they choose their own password there.</p><ShareLink name={temp.user.name} link={temp.link} company={me?.company?.name} />
          <details><summary className="small">Or share a temporary password instead</summary><div className="card pad mono" style={{ marginTop: 8 }}>{temp.temporary_password}</div></details></>
          : <><p>Temporary password for {temp.user.email}. They'll be asked to change it.</p><div className="card pad mono">{temp.temporary_password}</div></>}
      </Modal>}
      {edit && <Modal wide title={edit.name} onClose={() => setEdit(null)} footer={<>
        <Btn onClick={() => run(() => api.post(`/company/users/${edit.id}/reset-password`)).then((r) => setTemp({ user: edit, temporary_password: r.temporary_password }))}>Reset password</Btn>
        <Btn kind={edit.active ? "danger" : ""} onClick={() => run(() => api.patch(`/company/users/${edit.id}`, { active: !edit.active }), edit.active ? "Switched off" : "Switched on").then(() => { setEdit(null); setRk(rk + 1); })}>{edit.active ? "Switch off" : "Switch on"}</Btn>
        <Btn kind="primary" busy={busy} onClick={() => run(() => api.put(`/company/users/${edit.id}/roles`, { roles: edit.roles }), "Roles saved").then(() => { setEdit(null); setRk(rk + 1); })}>Save roles</Btn></>}>
        <RolesEditor roles={edit.roles} onChange={(roles) => setEdit({ ...edit, roles })} cat={cat} teams={teams} jobs={jobs} />
        {edit.grants.length > 0 && <div className="col"><b>Extra grants</b>{edit.grants.map((g) => <div key={g.id} className="small">{cat.permissions[g.permission]} · {g.scope_type}{g.expires_at ? ` · until ${fmtDate(g.expires_at)}` : ""}</div>)}</div>}
      </Modal>}
    </>
  );
}

function Teams() {
  const { data, reload } = useAsync(() => api.get("/company/teams"), []);
  const [name, setName] = useState("");
  const [run] = useAction();
  const ask = useConfirm();
  if (!data) return <Loading />;
  return (
    <div className="grid g2">
      <div className="card">{data.map((t) => <div key={t.id} className="list-row"><b className="grow">{t.name}</b><Chip>{t.members} people</Chip><Chip>{t.jobs} jobs</Chip>
        <Btn size="sm" kind="ghost" onClick={async () => { const n = await ask({ title: "Rename team", input: { label: "Team name", value: t.name, required: true, max: 80 }, yes: "Rename" }); if (n && n !== t.name) run(() => api.patch(`/company/teams/${t.id}`, { name: n }), "Renamed").then(reload); }}>Rename</Btn></div>)}</div>
      <form className="card pad col" onSubmit={(e) => { e.preventDefault(); run(() => api.post("/company/teams", { name }), "Team created").then(() => { setName(""); reload(); }); }}>
        <h3>New team</h3><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Data, Sales, Campus" /><Btn kind="primary" type="submit">Create</Btn>
        <p className="small muted">Teams can override company settings (for example a different voice or pass mark) under Settings.</p>
      </form>
    </div>
  );
}

function CustomRoles() {
  const { cat, reloadCat } = useCatalog();
  const [edit, setEdit] = useState(null);
  const [run, busy] = useAction();
  if (!cat) return <Loading />;
  return (
    <>
      <div className="row"><Btn kind="primary" onClick={() => setEdit({ name: "", base_role: "recruiter", permissions: [...cat.roles.recruiter] })}>New custom role</Btn></div>
      <div className="card tbl-wrap"><table className="tbl"><thead><tr><th>Permission</th>{Object.keys(cat.roles).map((r) => <th key={r}>{cat.labels[r]}</th>)}{cat.custom.map((c) => <th key={c.id}><button className="btn ghost sm" onClick={() => setEdit(c)}>{c.name} ✎</button></th>)}</tr></thead>
        <tbody>{Object.entries(cat.permissions).map(([p, l]) => <tr key={p}><td><b className="small">{l}</b><div className="tiny faint mono">{p}</div></td>
          {Object.values(cat.roles).map((ps, i) => <td key={i}>{ps.includes(p) ? "✓" : ""}</td>)}{cat.custom.map((c) => <td key={c.id}>{c.permissions.includes(p) ? "✓" : ""}</td>)}</tr>)}</tbody></table></div>
      {edit && <Modal wide title={edit.id ? `Edit ${edit.name}` : "New custom role"} onClose={() => setEdit(null)} footer={<Btn kind="primary" busy={busy} onClick={() => run(() => edit.id ? api.patch(`/company/roles/${edit.id}`, edit) : api.post("/company/roles", edit), "Saved").then(() => { setEdit(null); reloadCat(); })}>Save</Btn>}>
        <Field label="Name"><Input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} placeholder="e.g. Panel lead" /></Field>
        <div className="grid g2">{Object.entries(cat.permissions).map(([p, l]) => <label key={p} className="check small"><input type="checkbox" checked={edit.permissions.includes(p)} onChange={(e) => setEdit({ ...edit, permissions: e.target.checked ? [...edit.permissions, p] : edit.permissions.filter((x) => x !== p) })} />{l}</label>)}</div>
      </Modal>}
    </>
  );
}

function Grants() {
  const { cat } = useCatalog();
  const { data, reload } = useAsync(() => api.get("/company/grants"), []);
  const { data: users } = useAsync(() => api.get("/company/users", { size: 100 }), []);
  const [g, setG] = useState({ user_id: "", permission: "analytics.view", expires_at: "", reason: "" });
  const [cover, setCover] = useState({ from_user_id: "", to_user_id: "", until: "" });
  const [run, busy] = useAction();
  const toast = useToast();
  if (!cat || !data || !users) return <Loading />;
  const uopts = [{ value: "", label: "Choose person" }, ...users.items.map((u) => ({ value: String(u.id), label: u.name }))];
  return (
    <div className="split">
      <div className="card">
        <div className="card-h"><h3>Grants</h3><span className="small muted">Extra permissions on top of roles, with an expiry</span></div>
        {!data.length && <Empty title="No grants yet" />}
        {data.map((x) => <div key={x.id} className="list-row"><div className="grow"><b>{x.user}</b> · {cat.permissions[x.permission]}<div className="small muted">{x.scope_type}{x.scope_id ? " #" + x.scope_id : ""} · {x.expires_at ? "until " + fmtDate(x.expires_at) : "no expiry"}{x.reason ? ` · ${x.reason}` : ""}</div></div>
          <Chip kind={x.status === "active" && !x.expired ? "good" : x.status === "pending" ? "warn" : ""}>{x.expired ? "expired" : x.status}</Chip>
          {x.status !== "revoked" && <Btn size="sm" kind="danger" onClick={() => run(() => api.del(`/company/grants/${x.id}`), "Revoked").then(reload)}>Revoke</Btn>}</div>)}
      </div>
      <div className="col" style={{ gap: 16 }}>
        <div className="card pad col"><h3>Give a permission</h3>
          <Field label="Person"><Select value={g.user_id} onChange={(v) => setG({ ...g, user_id: v })} options={uopts} /></Field>
          <Field label="Permission"><Select value={g.permission} onChange={(v) => setG({ ...g, permission: v })} options={Object.entries(cat.permissions).map(([value, label]) => ({ value, label }))} /></Field>
          <Field label="Expires"><Input type="date" value={g.expires_at} onChange={(e) => setG({ ...g, expires_at: e.target.value })} /></Field>
          <Field label="Reason"><Input value={g.reason} onChange={(e) => setG({ ...g, reason: e.target.value })} /></Field>
          <Btn kind="primary" busy={busy} disabled={!g.user_id} onClick={() => run(() => api.post("/company/grants", g)).then((r) => { toast(r.status === "pending" ? "Sent for approval (sensitive permission)" : "Granted", "good"); reload(); })}>Grant</Btn>
        </div>
        <div className="card pad col"><h3>Temporary cover</h3><p className="small muted">“Rahul covers Anita's jobs while she's away.” Access ends automatically.</p>
          <Field label="Cover for"><Select value={cover.from_user_id} onChange={(v) => setCover({ ...cover, from_user_id: v })} options={uopts} /></Field>
          <Field label="Covered by"><Select value={cover.to_user_id} onChange={(v) => setCover({ ...cover, to_user_id: v })} options={uopts} /></Field>
          <Field label="Until"><Input type="date" value={cover.until} onChange={(e) => setCover({ ...cover, until: e.target.value })} /></Field>
          <Btn busy={busy} disabled={!cover.from_user_id || !cover.to_user_id} onClick={() => run(() => api.post("/company/cover", cover)).then((r) => { toast(`Cover set for ${r.jobs} jobs`, "good"); reload(); })}>Set cover</Btn>
        </div>
      </div>
    </div>
  );
}

function Policies() {
  const { data, reload } = useAsync(() => api.get("/company/policies"), []);
  const [edit, setEdit] = useState(null);
  const [run, busy] = useAction();
  if (!data) return <Loading />;
  return (
    <>
      <AgentNote agent="hira" title="When something happens, if it matches, then require approval, block or notify">Policies run automatically on every matching action and every hit is logged.</AgentNote>
      <div className="row"><Btn kind="primary" onClick={() => setEdit({ name: "", event: "job.publish", conditions: [], action: "require_approval", params: { approvals: 1, roles: ["manager"] }, enabled: true })}>New policy</Btn></div>
      <div className="card">{data.policies.map((p) => (
        <div key={p.id} className="list-row">
          <Switch on={p.enabled} label={p.name} onChange={(v) => run(() => api.patch(`/company/policies/${p.id}`, { enabled: v })).then(reload)} />
          <div className="grow"><b>{p.name}</b><div className="small muted">When <b>{data.events[p.event]?.label.toLowerCase()}</b>{p.conditions.map((c, i) => <span key={i}> {i ? "and" : "if"} {c.field} {c.op} {JSON.stringify(c.value)}</span>)} → <b>{data.actions[p.action]}</b>{p.params?.approvals ? ` (${p.params.approvals})` : ""}</div></div>
          <Btn size="sm" onClick={() => setEdit(p)}>Edit</Btn><Btn size="sm" kind="ghost" onClick={() => run(() => api.del(`/company/policies/${p.id}`), "Deleted").then(reload)}>✕</Btn>
        </div>))}</div>
      {edit && <Modal wide title={edit.id ? "Edit policy" : "New policy"} onClose={() => setEdit(null)} footer={<Btn kind="primary" busy={busy} onClick={() => run(() => edit.id ? api.patch(`/company/policies/${edit.id}`, edit) : api.post("/company/policies", edit), "Saved").then(() => { setEdit(null); reload(); })}>Save</Btn>}>
        <Field label="Name"><Input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></Field>
        <Field label="When"><Select value={edit.event} onChange={(v) => setEdit({ ...edit, event: v, conditions: [] })} options={Object.entries(data.events).map(([value, e]) => ({ value, label: e.label }))} /></Field>
        <b className="small">If (all must match)</b>
        {edit.conditions.map((c, i) => <div key={i} className="row">
          <Select value={c.field} onChange={(v) => upd(i, { field: v })} options={data.events[edit.event].fields} />
          <div style={{ width: 110 }}><Select value={c.op} onChange={(v) => upd(i, { op: v })} options={data.ops} /></div>
          <Input value={typeof c.value === "string" ? c.value : JSON.stringify(c.value)} onChange={(e) => { let v = e.target.value; try { v = JSON.parse(v); } catch { /* keep string */ } upd(i, { value: v }); }} />
          <Btn size="sm" kind="ghost" onClick={() => setEdit({ ...edit, conditions: edit.conditions.filter((_, j) => j !== i) })}>✕</Btn></div>)}
        <Btn size="sm" onClick={() => setEdit({ ...edit, conditions: [...edit.conditions, { field: data.events[edit.event].fields[0], op: "eq", value: "" }] })}>+ Condition</Btn>
        <div className="grid g2">
          <Field label="Then"><Select value={edit.action} onChange={(v) => setEdit({ ...edit, action: v })} options={Object.entries(data.actions).map(([value, label]) => ({ value, label }))} /></Field>
          {edit.action === "require_approval" && <Field label="Approvals needed"><Input type="number" value={edit.params?.approvals || 1} onChange={(e) => setEdit({ ...edit, params: { ...edit.params, approvals: +e.target.value } })} /></Field>}
          {edit.action === "block" && <Field label="Message shown"><Input value={edit.params?.message || ""} onChange={(e) => setEdit({ ...edit, params: { ...edit.params, message: e.target.value } })} /></Field>}
          {edit.action !== "block" && <Field label="Who (roles)"><Input value={(edit.params?.roles || []).join(", ")} onChange={(e) => setEdit({ ...edit, params: { ...edit.params, roles: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) } })} /></Field>}
        </div>
      </Modal>}
    </>
  );
  function upd(i, p) { setEdit({ ...edit, conditions: edit.conditions.map((c, j) => (j === i ? { ...c, ...p } : c)) }); }
}

function ScopedSettings() {
  const { me } = useAuth();
  const { data } = useAsync(() => api.get("/company/teams"), []);
  const [scope, setScope] = useState("company");
  if (!data) return <Loading />;
  const sid = scope === "company" ? me.user.company_id : +scope;
  return (
    <>
      <div className="row"><span className="b">Editing settings for</span><div style={{ width: 260 }}><Select value={scope} onChange={setScope} options={[{ value: "company", label: "Whole company" }, ...data.map((t) => ({ value: String(t.id), label: "Team: " + t.name }))]} /></div>
        <span className="small muted">Job and round settings live on each job.</span></div>
      <AgentNote agent="hira">Values flow down: platform → company → team → job → round. Lock a value to stop lower levels changing it. Voices: pick Hira's default voice and the voices candidates can choose from; press ▶ to hear each one.</AgentNote>
      <SettingsEditor key={scope} {...companySettings(scope === "company" ? "company" : "team", sid)} />
    </>
  );
}

function Branding() {
  const { data, reload } = useAsync(() => api.get("/company"), []);
  const [run, busy] = useAction();
  const [f, setF] = useState(null);
  if (!data) return <Loading />;
  const c = f || { name: data.company.name, domain: data.company.domain || "", timezone: data.company.timezone, gst: data.company.gst || "", branding: data.company.branding || {} };
  return (
    <div className="grid g2">
      <div className="card pad col"><h3>Company</h3>
        <Field label="Name"><Input value={c.name} onChange={(e) => setF({ ...c, name: e.target.value })} /></Field>
        <Field label="Domain"><Input value={c.domain} onChange={(e) => setF({ ...c, domain: e.target.value })} /></Field>
        <Field label="GST number"><Input value={c.gst} onChange={(e) => setF({ ...c, gst: e.target.value })} /></Field>
        <Field label="Logo URL"><Input value={c.branding.logo_url || ""} onChange={(e) => setF({ ...c, branding: { ...c.branding, logo_url: e.target.value } })} /></Field>
        <Field label="Brand colour"><input type="color" value={c.branding.color || "#5B3FFF"} onChange={(e) => setF({ ...c, branding: { ...c.branding, color: e.target.value } })} /></Field>
        <Btn kind="primary" busy={busy} onClick={() => run(() => api.patch("/company", c), "Saved").then(reload)}>Save</Btn>
      </div>
      <div className="card pad col"><h3>Plan and usage</h3>
        <div>Plan <Chip kind="brand">{data.company.plan}</Chip></div>
        <div>Credits {data.usage.credits_used} / {data.usage.credits_total}</div>
        <div>Seats {data.usage.seats_used} / {data.company.limits?.seats}</div>
        <div>Live jobs {data.usage.active_jobs} / {data.company.limits?.active_jobs}</div>
        <p className="small muted">Contact Code2Hire to change your plan or add credits.</p>
      </div>
    </div>
  );
}

function AccessReview() {
  const { data, reload } = useAsync(() => api.get("/company/access-review"), []);
  const [run] = useAction();
  if (!data) return <Loading />;
  if (!data.length) return <Empty title="Nothing to tidy up" text="No stale accounts or old grants found." />;
  return (
    <div className="card">{data.map((x, i) => <div key={i} className="list-row"><Chip kind="warn">{x.type.replace("_", " ")}</Chip><div className="grow"><b>{x.user}</b><div className="small muted">{x.suggestion}</div></div>
      {x.grant_id && <Btn size="sm" kind="danger" onClick={() => run(() => api.del(`/company/grants/${x.grant_id}`), "Revoked").then(reload)}>Revoke</Btn>}
      {x.user_id && <Btn size="sm" kind="danger" onClick={() => run(() => api.patch(`/company/users/${x.user_id}`, { active: false }), "Switched off").then(reload)}>Switch off</Btn>}</div>)}</div>
  );
}
