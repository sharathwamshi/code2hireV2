import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, setCompanyOverride } from "../../api";
import DataTable from "../../components/DataTable";
import { Hira } from "../../components/Mascot";
import QuestionBank from "../../components/QuestionBank";
import SettingsEditor, { platformSettings } from "../../components/Settings";
import { PageHead } from "../../components/Shell";
import { Bar, Btn, Chip, Empty, Field, Input, Loading, Modal, ROUND_LABEL, Select, Status, Switch, Tabs, Textarea, fmtDate, useAction, useAsync, useToast } from "../../components/ui";

export function Overview() {
  const { data: d } = useAsync(() => api.get("/platform/overview"), []);
  const nav = useNavigate();
  if (!d) return <Loading />;
  const tiles = [["Active companies", d.companies.active], ["On trial", d.companies.trial], ["Suspended", d.companies.suspended], ["Hiring-team users", d.users],
    ["Candidates", d.candidates], ["Live jobs", d.jobs_live], ["MCQ rounds", d.assessments], ["AI interviews", d.ai_interviews], ["Isha sessions", d.isha_sessions],
    ["Reports", d.reports], ["Disputes open", d.disputes], ["AI–human agreement", d.ai_human_agreement != null ? d.ai_human_agreement + "%" : "—"]];
  return (
    <>
      <PageHead title="Platform overview" sub="Every company, credit and agent on Code2Hire." actions={<Btn kind="primary" onClick={() => nav("/admin/companies?new=1")}>Onboard a company</Btn>} />
      {(!d.ai_configured || !d.voice_configured) && (
        <div className="agent hira"><Hira size={44} /><div className="grow"><b>Finish the set-up</b>
          <div>{!d.ai_configured && "Add the Anthropic API key so Hira, Isha and Disha use Claude. "}{!d.voice_configured && "Add the Azure Speech key so interviews use natural voices. "}Until then every feature still works with built-in fallbacks.</div></div>
          <Btn kind="primary" onClick={() => nav("/admin/settings")}>Open integrations</Btn></div>
      )}
      <div className="grid g4">{tiles.map(([l, v]) => <div key={l} className="card stat"><div className="l">{l}</div><div className="v">{v ?? 0}</div></div>)}</div>
      <div className="grid g2">
        <div className="card"><div className="card-h"><h3>Credit burn</h3></div><div className="card-b col">
          {d.credit_burn.map((c) => <div key={c.id} className="row"><button className="btn ghost sm" onClick={() => nav(`/admin/companies/${c.id}`)} style={{ width: 180, justifyContent: "flex-start" }}>{c.name}</button><div className="grow"><Bar value={c.pct} tone={c.pct > 90 ? "bad" : c.pct > 75 ? "warn" : "good"} /></div><span className="small" style={{ width: 120, textAlign: "right" }}>{c.used} / {c.total}</span></div>)}
        </div></div>
        <div className="card"><div className="card-h"><h3>Waiting for you</h3></div>
          <div className="list-row"><span className="grow">AI-drafted global questions to review</span><Chip kind="warn">{d.pending_questions}</Chip><Btn size="sm" onClick={() => nav("/admin/questions")}>Review</Btn></div>
          <div className="list-row"><span className="grow">Certifications asking for “Code2Hire Verified”</span><Chip kind="warn">{d.certs_in_review}</Chip><Btn size="sm" onClick={() => nav("/admin/certifications")}>Review</Btn></div>
          <div className="list-row"><span className="grow">Candidate disputes</span><Chip kind={d.disputes ? "bad" : ""}>{d.disputes}</Chip></div>
        </div>
      </div>
    </>
  );
}

const PLAN_OPTS = ["trial", "employer", "agency", "enterprise"];

export function Companies() {
  const nav = useNavigate();
  const [open, setOpen] = useState(new URLSearchParams(location.search).get("new") === "1");
  const [rk, setRk] = useState(0);
  return (
    <>
      <PageHead title="Companies" sub="Onboard, set plans and limits, and give support access." actions={<Btn kind="primary" onClick={() => setOpen(true)}>Onboard a company</Btn>} />
      <DataTable endpoint="/platform/companies" reloadKey={rk} defaultSort="created" onRow={(r) => nav(`/admin/companies/${r.id}`)}
        filters={[{ key: "status", label: "Status", options: ["trial", "active", "suspended"] }, { key: "plan", label: "Plan", options: PLAN_OPTS }]}
        columns={[{ key: "name", label: "Company", sort: "name", render: (r) => <div><b>{r.name}</b><div className="tiny muted">{r.domain}</div></div> },
          { key: "plan", label: "Plan", sort: "plan", render: (r) => <Chip kind="brand">{r.plan}</Chip> }, { key: "status", label: "Status", sort: "status", render: (r) => <Status s={r.status} /> },
          { key: "credits", label: "Credits used", sort: "credits", render: (r) => <div style={{ minWidth: 140 }}><Bar value={r.credits_used} max={r.credits_total} tone="good" /><span className="tiny">{r.credits_used} / {r.credits_total}</span></div> },
          { key: "users", label: "Users" }, { key: "jobs", label: "Jobs" }, { key: "created_at", label: "Joined", sort: "created", render: (r) => fmtDate(r.created_at) }]} />
      {open && <Onboard onClose={() => setOpen(false)} onDone={() => setRk(rk + 1)} />}
    </>
  );
}

function Onboard({ onClose, onDone }) {
  const [f, setF] = useState({ name: "", domain: "", plan: "trial", admin_name: "", admin_email: "" });
  const [res, setRes] = useState(null);
  const [run, busy] = useAction();
  if (res) return (
    <Modal title="Company onboarded" onClose={onClose} footer={<Btn kind="primary" onClick={onClose}>Done</Btn>}>
      <p>Share these sign-in details with the Company Admin. They will be asked to choose a new password.</p>
      <div className="card pad mono">{res.admin.email}<br />{res.temporary_password}</div>
      <p className="small muted">Default team, policies and settings were created. The invite is valid for 7 days.</p>
    </Modal>
  );
  return (
    <Modal title="Onboard a company" onClose={onClose} footer={<><Btn onClick={onClose}>Cancel</Btn><Btn kind="primary" busy={busy} onClick={() => run(() => api.post("/platform/companies", f)).then((r) => { setRes(r); onDone(); })}>Create company</Btn></>}>
      <div className="grid g2"><Field label="Company name"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label="Domain"><Input value={f.domain} placeholder="acme.com" onChange={(e) => setF({ ...f, domain: e.target.value })} /></Field></div>
      <Field label="Plan"><Select value={f.plan} onChange={(v) => setF({ ...f, plan: v })} options={PLAN_OPTS} /></Field>
      <div className="grid g2"><Field label="Company Admin name"><Input value={f.admin_name} onChange={(e) => setF({ ...f, admin_name: e.target.value })} /></Field>
        <Field label="Company Admin email"><Input type="email" value={f.admin_email} onChange={(e) => setF({ ...f, admin_email: e.target.value })} /></Field></div>
    </Modal>
  );
}

export function CompanyDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const { data, reload } = useAsync(() => api.get(`/platform/companies/${id}`), [id]);
  const [credit, setCredit] = useState({ delta: 500, reason: "" });
  const [run, busy] = useAction();
  if (!data) return <Loading />;
  const c = data.company;
  const patch = (p) => run(() => api.patch(`/platform/companies/${id}`, p), "Saved").then(reload);
  return (
    <>
      <PageHead back="/admin/companies" title={c.name} sub={`${c.domain || "No domain"} · ${c.country} · joined ${fmtDate(c.created_at)}`}
        actions={<Btn kind="primary" onClick={async () => { await api.post(`/platform/companies/${id}/support-access`, { minutes: 30 }); setCompanyOverride(id); toast("Support access on. The company admin was told.", "good"); nav("/app/today"); window.location.reload(); }}>Open support access</Btn>} />
      <div className="grid g4">
        <div className="card stat"><div className="l">Users</div><div className="v">{data.counts.users}</div></div>
        <div className="card stat"><div className="l">Jobs</div><div className="v">{data.counts.jobs}</div></div>
        <div className="card stat"><div className="l">Applications</div><div className="v">{data.counts.applications}</div></div>
        <div className="card stat"><div className="l">Credits</div><div className="v">{c.credits_used} / {c.credits_total}</div></div>
      </div>
      <div className="grid g2">
        <div className="card pad col">
          <h3>Plan and status</h3>
          <div className="grid g2"><Field label="Plan"><Select value={c.plan} onChange={(v) => patch({ plan: v })} options={PLAN_OPTS} /></Field>
            <Field label="Status"><Select value={c.status} onChange={(v) => patch({ status: v })} options={["trial", "active", "suspended"]} /></Field></div>
          <h4>Limits</h4>
          <div className="grid g2">{Object.entries(c.limits || {}).map(([k, v]) => <Field key={k} label={k.replace(/_/g, " ")}><Input type="number" defaultValue={v} onBlur={(e) => +e.target.value !== v && patch({ limits: { [k]: +e.target.value } })} /></Field>)}</div>
        </div>
        <div className="card pad col">
          <h3>Features</h3>
          {Object.entries(c.flags || {}).map(([k, v]) => <div key={k} className="row between"><span>{k.replace(/_/g, " ")}</span><Switch on={v} label={k} onChange={(x) => patch({ flags: { [k]: x } })} /></div>)}
          <div className="divider" />
          <h3>Adjust credits</h3>
          <div className="row"><Input type="number" value={credit.delta} onChange={(e) => setCredit({ ...credit, delta: +e.target.value })} style={{ width: 120 }} />
            <Input placeholder="Reason (logged)" value={credit.reason} onChange={(e) => setCredit({ ...credit, reason: e.target.value })} />
            <Btn kind="primary" busy={busy} onClick={() => run(() => api.post(`/platform/companies/${id}/credits`, credit), "Credits updated").then(reload)}>Apply</Btn></div>
        </div>
      </div>
      <div className="card"><div className="card-h"><h3>Company Admins</h3></div>{data.admins.map((a) => <div key={a.id} className="list-row"><b>{a.name}</b><span className="muted">{a.email}</span></div>)}</div>
      <DataTable endpoint="/platform/audit" params={{ company_id: id }} defaultSort="created" columns={auditCols} />
    </>
  );
}

const auditCols = [{ key: "created_at", label: "When", sort: "created", render: (r) => fmtDate(r.created_at, true) }, { key: "actor", label: "Who" },
  { key: "action", label: "Action", sort: "action", render: (r) => <span className="mono small">{r.action}</span> },
  { key: "target", label: "Target", render: (r) => r.target_type ? `${r.target_type} #${r.target_id ?? ""}` : "—" },
  { key: "detail", label: "Detail", render: (r) => <span className="tiny muted mono ellipsis" style={{ display: "inline-block", maxWidth: 360 }}>{JSON.stringify(r.detail)}</span> }];

export function PlatformSettings() {
  const [tab, setTab] = useState("integrations");
  return (
    <>
      <PageHead title="AI, voice and defaults" sub="Platform defaults every company inherits. Lock a setting to stop companies changing it." />
      <Tabs value={tab} onChange={setTab} tabs={[["integrations", "Integrations"], ["voice", "Voices"], ["all", "All defaults"]]} />
      {tab === "integrations" && <Integrations />}
      {tab === "voice" && <SettingsEditor {...platformSettings} groups={["Voice", "AI"]} />}
      {tab === "all" && <SettingsEditor {...platformSettings} />}
    </>
  );
}

function Integrations() {
  const { data, reload } = useAsync(() => api.get("/platform/integrations"), []);
  const [f, setF] = useState({ anthropic_api_key: "", azure_speech_key: "", azure_speech_region: "" });
  const [run, busy] = useAction();
  const [test, setTest] = useState({});
  if (!data) return <Loading />;
  const doTest = async (which) => { try { const r = await api.post("/platform/integrations/test", { which }); setTest({ ...test, [which]: { ok: true, r } }); } catch (e) { setTest({ ...test, [which]: { ok: false, r: e.message } }); } };
  return (
    <div className="grid g2">
      <div className="card pad col">
        <div className="row"><h3>Anthropic (all AI work)</h3>{data.anthropic_ok ? <Chip kind="good">Connected</Chip> : <Chip kind="warn">Not set</Chip>}</div>
        <p className="small muted">Hira, Isha and Disha use Claude for drafting jobs, scoring, interviews, live analysis, reports and learning paths. Choose the model under Voices → AI.</p>
        <Field label="API key" hint={data.anthropic_api_key ? `Current: ${data.anthropic_api_key}` : "Starts with sk-ant-"}><Input type="password" value={f.anthropic_api_key} onChange={(e) => setF({ ...f, anthropic_api_key: e.target.value })} /></Field>
        <div className="row"><Btn kind="primary" busy={busy} onClick={() => run(() => api.put("/platform/integrations", f), "Saved").then(reload)}>Save</Btn><Btn onClick={() => doTest("anthropic")}>Test</Btn></div>
        {test.anthropic && <div className={"chip " + (test.anthropic.ok ? "good" : "bad")} style={{ height: "auto", padding: 8 }}>{test.anthropic.ok ? JSON.stringify(test.anthropic.r) : test.anthropic.r}</div>}
      </div>
      <div className="card pad col">
        <div className="row"><h3>Azure Speech (all voice)</h3>{data.azure_ok ? <Chip kind="good">Connected</Chip> : <Chip kind="warn">Not set</Chip>}</div>
        <p className="small muted">Text-to-speech for Hira's voice and speech-to-text for candidate answers and Isha's live transcript.</p>
        <Field label="Speech key" hint={data.azure_speech_key ? `Current: ${data.azure_speech_key}` : ""}><Input type="password" value={f.azure_speech_key} onChange={(e) => setF({ ...f, azure_speech_key: e.target.value })} /></Field>
        <Field label="Region" hint={`Current: ${data.azure_speech_region}`}><Input placeholder="centralindia" value={f.azure_speech_region} onChange={(e) => setF({ ...f, azure_speech_region: e.target.value })} /></Field>
        <div className="row"><Btn kind="primary" busy={busy} onClick={() => run(() => api.put("/platform/integrations", f), "Saved").then(reload)}>Save</Btn><Btn onClick={() => doTest("azure")}>Test</Btn></div>
        {test.azure && <div className={"chip " + (test.azure.ok ? "good" : "bad")} style={{ height: "auto", padding: 8 }}>{test.azure.ok ? `Token OK · region ${test.azure.r.region} · ${test.azure.r.voices} voices` : test.azure.r}</div>}
      </div>
    </div>
  );
}

export function QuestionTable({ endpoint, save, generatePath, scopeToggle }) {
  const [rk, setRk] = useState(0);
  const [gen, setGen] = useState(false);
  const [edit, setEdit] = useState(null);
  const [scope, setScope] = useState("company");
  const [run, busy] = useAction();
  const [g, setG] = useState({ skills: "Python", level: 3, n: 5 });
  return (
    <>
      <DataTable endpoint={endpoint} reloadKey={rk} defaultSort="created" params={scopeToggle ? { scope } : {}}
        toolbar={<>{scopeToggle && <div className="seg"><button className={scope === "company" ? "on" : ""} onClick={() => setScope("company")}>Ours</button><button className={scope === "global" ? "on" : ""} onClick={() => setScope("global")}>Global (read-only)</button></div>}
          {generatePath && <Btn size="sm" kind="primary" onClick={() => setGen(true)}>Ask Hira to draft</Btn>}</>}
        filters={[{ key: "status", label: "Status", options: ["approved", "pending", "rejected"] }]}
        onRow={(r) => (scope === "company" || !scopeToggle) && setEdit(r)}
        columns={[{ key: "text", label: "Question", render: (r) => <div style={{ maxWidth: 560 }}><b>{r.text}</b><div className="tiny muted">{(r.options || []).length} options · answer {String.fromCharCode(65 + r.answer)}</div></div> },
          { key: "skill", label: "Skill", sort: "skill", render: (r) => <Chip>{r.skill}</Chip> }, { key: "level", label: "Level", sort: "level", render: (r) => "L" + r.level },
          { key: "source", label: "Source", render: (r) => <Chip kind={r.source === "ai" ? "brand" : ""}>{r.source === "ai" ? "Hira" : "Manual"}</Chip> },
          { key: "status", label: "Status", render: (r) => <Status s={r.status} /> }]} />
      {gen && <Modal title="Ask Hira to draft questions" onClose={() => setGen(false)} footer={<Btn kind="primary" busy={busy} onClick={() => run(() => api.post(generatePath, { ...g, skills: g.skills.split(",").map((s) => s.trim()) }), "Drafted. Review them before use.").then(() => { setGen(false); setRk(rk + 1); })}>Draft</Btn>}>
        <Field label="Skills (comma separated)"><Input value={g.skills} onChange={(e) => setG({ ...g, skills: e.target.value })} /></Field>
        <div className="grid g2"><Field label="Level"><Select value={String(g.level)} onChange={(v) => setG({ ...g, level: +v })} options={["1", "2", "3", "4", "5"]} /></Field>
          <Field label="How many"><Input type="number" value={g.n} onChange={(e) => setG({ ...g, n: +e.target.value })} /></Field></div>
        <p className="small muted">Drafts arrive as “pending”. Only approved questions are used in rounds.</p>
      </Modal>}
      {edit && <QuestionEdit q={edit} onClose={() => setEdit(null)} onSave={(p) => run(() => save(edit.id, p), "Saved").then(() => { setEdit(null); setRk(rk + 1); })} />}
    </>
  );
}

export function QuestionEdit({ q, onClose, onSave }) {
  const [f, setF] = useState({ ...q, options: [...(q.options || ["", "", "", ""])] });
  return (
    <Modal wide title={q.id ? "Review question" : "New question"} onClose={onClose} footer={<>
      {q.id && <Btn kind="danger" onClick={() => onSave({ ...f, status: "rejected" })}>Reject</Btn>}
      <Btn kind="primary" onClick={() => onSave({ ...f, status: "approved" })}>Approve and save</Btn></>}>
      <Field label="Question"><Textarea value={f.text} onChange={(e) => setF({ ...f, text: e.target.value })} /></Field>
      <Field label="Code (optional)"><Textarea className="textarea mono" value={f.code || ""} onChange={(e) => setF({ ...f, code: e.target.value })} /></Field>
      {f.options.map((o, i) => <div key={i} className="row"><label className="check"><input type="radio" name="ans" checked={f.answer === i} onChange={() => setF({ ...f, answer: i })} />{String.fromCharCode(65 + i)}</label><Input value={o} onChange={(e) => { const op = [...f.options]; op[i] = e.target.value; setF({ ...f, options: op }); }} /></div>)}
      <div className="grid g2"><Field label="Skill"><Input value={f.skill} onChange={(e) => setF({ ...f, skill: e.target.value })} /></Field><Field label="Level"><Select value={String(f.level)} onChange={(v) => setF({ ...f, level: +v })} options={["1", "2", "3", "4", "5"]} /></Field></div>
      <Field label="Explanation"><Textarea value={f.explanation || ""} onChange={(e) => setF({ ...f, explanation: e.target.value })} /></Field>
    </Modal>
  );
}

export function GlobalQuestions() {
  return <><PageHead title="Global question bank" sub="Shared with every company. Folders, versions and approvals. Companies can copy any question into their own bank." />
    <QuestionBank globalOnly /></>;
}

export function Templates() {
  const { data, reload } = useAsync(() => api.get("/platform/templates"), []);
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ name: "", description: "", rounds: [{ type: "mcq", name: "Skill screen" }] });
  const [run] = useAction();
  return (
    <>
      <PageHead title="Hiring templates" sub="Global starting points: rounds and rubrics companies can copy." actions={<Btn kind="primary" onClick={() => setOpen(true)}>New template</Btn>} />
      {!data ? <Loading /> : !data.length ? <Empty title="No templates yet" /> : (
        <div className="grid g3">{data.map((t) => <div key={t.id} className="card pad col"><h3>{t.name}</h3><p className="muted small">{t.description}</p>
          <div className="row wrap">{t.rounds.map((r, i) => <Chip key={i} kind="brand">{i + 1}. {r.name || ROUND_LABEL[r.type]}</Chip>)}</div></div>)}</div>
      )}
      {open && <Modal title="New template" onClose={() => setOpen(false)} footer={<Btn kind="primary" onClick={() => run(() => api.post("/platform/templates", f), "Created").then(() => { setOpen(false); reload(); })}>Create</Btn>}>
        <Field label="Name"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label="Description"><Textarea value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
        <RoundsEditor rounds={f.rounds} onChange={(rounds) => setF({ ...f, rounds })} />
      </Modal>}
    </>
  );
}

export function RoundsEditor({ rounds, onChange }) {
  return (
    <div className="col">
      <b>Rounds, in order</b>
      {rounds.map((r, i) => (
        <div key={i} className="row">
          <span className="chip">{i + 1}</span>
          <div style={{ width: 200 }}><Select value={r.type} onChange={(v) => { const x = [...rounds]; x[i] = { ...r, type: v, name: r.name || ROUND_LABEL[v] }; onChange(x); }} options={Object.entries(ROUND_LABEL).map(([value, label]) => ({ value, label }))} /></div>
          <Input value={r.name || ""} placeholder="Round name" onChange={(e) => { const x = [...rounds]; x[i] = { ...r, name: e.target.value }; onChange(x); }} />
          <Btn size="sm" kind="ghost" disabled={i === 0} onClick={() => { const x = [...rounds]; [x[i - 1], x[i]] = [x[i], x[i - 1]]; onChange(x); }} aria-label="Move up">↑</Btn>
          <Btn size="sm" kind="ghost" onClick={() => onChange(rounds.filter((_, j) => j !== i))} aria-label="Remove round">✕</Btn>
        </div>
      ))}
      <Btn size="sm" onClick={() => onChange([...rounds, { type: "ai_interview", name: ROUND_LABEL.ai_interview, config: {} }])}>+ Add round</Btn>
    </div>
  );
}

export function CertReview() {
  const { data, reload } = useAsync(() => api.get("/platform/certifications/review"), []);
  const [run] = useAction();
  return (
    <>
      <PageHead title="Certification review" sub="Company certifications asking to carry the “Code2Hire Verified” mark." />
      {!data ? <Loading /> : !data.length ? <Empty title="Nothing to review" mascot={<Hira size={70} />} /> : data.map((c) => (
        <div key={c.id} className="card pad row wrap">
          <div className="grow"><h3>{c.name}</h3><div className="small muted">{(c.skills || []).join(", ")} · L{c.level} · {(c.sections || []).length} sections · pass {c.pass_rules?.cutoff}%</div></div>
          <Btn kind="danger" onClick={() => run(() => api.post(`/platform/certifications/${c.id}/decide`, { approve: false }), "Sent back").then(reload)}>Send back</Btn>
          <Btn kind="primary" onClick={() => run(() => api.post(`/platform/certifications/${c.id}/decide`, { approve: true }), "Published as verified").then(reload)}>Approve</Btn>
        </div>
      ))}
    </>
  );
}

export function Users() {
  return <><PageHead title="All users" sub="Everyone on the platform." />
    <DataTable endpoint="/platform/users" defaultSort="created" filters={[{ key: "kind", label: "Type", options: ["staff", "candidate"] }]}
      columns={[{ key: "name", label: "Name", sort: "name", render: (r) => <b>{r.name}</b> }, { key: "email", label: "Email" },
        { key: "kind", label: "Type", render: (r) => <Chip kind={r.is_superadmin ? "dark" : r.kind === "staff" ? "brand" : "disha"}>{r.is_superadmin ? "Superadmin" : r.kind}</Chip> },
        { key: "company_id", label: "Company", render: (r) => r.company_id ? "#" + r.company_id : "—" }, { key: "active", label: "Active", render: (r) => r.active ? "Yes" : "No" }]} /></>;
}

export function Audit() {
  return <><PageHead title="Audit log" sub="Every action across the platform, searchable." /><DataTable endpoint="/platform/audit" defaultSort="created" columns={auditCols} /></>;
}
