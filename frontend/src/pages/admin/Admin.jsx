import { Fragment, useEffect, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { api, setCompanyOverride } from "../../api";
import DataTable from "../../components/DataTable";
import { Hira } from "../../components/Mascot";
import QuestionBank from "../../components/QuestionBank";
import SettingsEditor, { platformSettings } from "../../components/Settings";
import { PageHead } from "../../components/Shell";
import { Bar, Btn, Chip, Empty, Field, Input, Loading, Modal, ROUND_LABEL, Seg, Select, Status, Switch, Tabs, Textarea, fmtDate, useAction, useAsync, useConfirm, useToast } from "../../components/ui";
import ReportView from "../../components/ReportView";
import InterviewAgain from "../../components/InterviewAgain";
import CloseInterview from "../../components/CloseInterview";
import { probeConnection } from "../../components/SystemCheck";
import { emailError, nameError } from "../../lib/validate";

export function Overview() {
  const { data: d } = useAsync(() => api.get("/platform/overview"), []);
  const nav = useNavigate();
  if (!d) return <Loading />;
  // SA-008 (V02.00.08): every card opens its list, already filtered
  const tiles = [["Active companies", d.companies.active, "/admin/companies?status=active"], ["On trial", d.companies.trial, "/admin/companies?status=trial"],
    ["Suspended", d.companies.suspended, "/admin/companies?status=suspended"], ["Hiring-team users", d.users, "/admin/users?kind=staff"],
    ["Candidates", d.candidates, "/admin/users?kind=candidate"], ["Live jobs", d.jobs_live, "/admin/jobs?status=live"],
    ["MCQ rounds", d.assessments, "/admin/rounds?type=mcq"], ["AI interviews", d.ai_interviews, "/admin/rounds?type=ai_interview"],
    ["Isha sessions", d.isha_sessions, "/admin/rounds?type=f2f_isha"], ["Reports", d.reports, "/admin/reports"],
    ["Disputes open", d.disputes, "/admin/disputes"], ["AI–human agreement", d.ai_human_agreement != null ? d.ai_human_agreement + "%" : "—", "/admin/reports?reviewed=disagree"]];
  const waiting = [["AI-drafted global questions to review", d.pending_questions, "/admin/questions", "warn"],
    ["Certifications asking for “Code2Hire Verified”", d.certs_in_review, "/admin/certifications", "warn"], ["Candidate disputes", d.disputes, "/admin/disputes", "bad"]];
  const busy = waiting.filter((w) => w[1] > 0);
  return (
    <>
      <PageHead title="Platform overview" sub="Every company, credit and agent on Code2Hire." actions={<Btn kind="primary" onClick={() => nav("/admin/companies?new=1")}>Onboard a company</Btn>} />
      {(!d.ai_configured || !d.voice_configured) && (
        <div className="agent hira"><Hira size={44} /><div className="grow"><b>Finish the set-up</b>
          <div>{!d.ai_configured && "Add the Anthropic API key so Hira, Isha and Disha use Claude. "}{!d.voice_configured && "Add the Azure Speech key so interviews use natural voices. "}Until then every feature still works with built-in fallbacks.</div></div>
          <Btn kind="primary" onClick={() => nav("/admin/settings")}>Open integrations</Btn></div>
      )}
      {(d.ai_status?.recent_error || d.voice_status?.recent_error) && (
        <div className="warnbar w2" role="alert" style={{ position: "static" }}><b>!</b><span className="grow">
          {d.ai_status?.recent_error && <>Claude's key is saved but the last call failed: {d.ai_status.error}. Hira, Isha and Disha are using built-in fallbacks. </>}
          {d.voice_status?.recent_error && <>Azure Speech is saved but the last call failed: {d.voice_status.error}. Captions and voices fall back to the browser.</>}</span>
          <Btn size="sm" onClick={() => nav("/admin/settings")}>Check the keys</Btn></div>
      )}
      <div className="grid g4">{tiles.map(([l, v, to]) => <button key={l} type="button" className="card stat stat-link" onClick={() => nav(to)} aria-label={`${l}: ${v ?? 0}. Open the list`}><div className="l">{l}</div><div className="v">{v ?? 0}</div><span className="tiny muted">Open list →</span></button>)}</div>
      <div className="grid g2">
        <div className="card"><div className="card-h"><h3>Credit burn</h3></div><div className="card-b col">
          {d.credit_burn.map((c) => <div key={c.id} className="row"><button className="btn ghost sm" onClick={() => nav(`/admin/companies/${c.id}`)} style={{ width: 180, justifyContent: "flex-start" }}>{c.name}</button><div className="grow"><Bar value={c.pct} tone={c.pct > 90 ? "bad" : c.pct > 75 ? "warn" : "good"} /></div><span className="small" style={{ width: 120, textAlign: "right" }}>{c.used} / {c.total}</span></div>)}
        </div></div>
        <div className="card"><div className="card-h"><h3>Waiting for you</h3></div>
          {/* SA-009 (V02.00.08): a count shows only when something is waiting */}
          {!busy.length && <div className="list-row"><span className="grow muted">All clear. Nothing is waiting for you.</span></div>}
          {waiting.map(([label, n, to, kind]) => <div key={to} className="list-row"><span className="grow">{label}</span>{n > 0 && <Chip kind={kind}>{n} waiting</Chip>}<Btn size="sm" onClick={() => nav(to)}>{n > 0 ? "Review" : "Open"}</Btn></div>)}
        </div>
      </div>
    </>
  );
}

const PLAN_OPTS = ["trial", "employer", "agency", "enterprise"];

/** SA-008 (V02.00.08): the overview cards open lists with filters in the address, e.g. ?status=active */
function urlFilters(loc, keys) {
  const q = new URLSearchParams(loc.search);
  return Object.fromEntries(keys.filter((k) => q.get(k)).map((k) => [k, q.get(k)]));
}

export function Companies() {
  const nav = useNavigate();
  const loc = useLocation();
  const [open, setOpen] = useState(new URLSearchParams(loc.search).get("new") === "1");
  const [rk, setRk] = useState(0);
  // "?new=1" only opens the dialog once: it's removed from the address so a refresh or Back doesn't reopen it
  useEffect(() => { if (new URLSearchParams(loc.search).get("new") === "1") nav(loc.pathname, { replace: true }); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <>
      <PageHead title="Companies" sub="Onboard, set plans and limits, and give support access." actions={<Btn kind="primary" onClick={() => setOpen(true)}>Onboard a company</Btn>} />
      <DataTable key={loc.search} defaultFilters={urlFilters(loc, ["status", "plan"])} endpoint="/platform/companies" reloadKey={rk} defaultSort="created" onRow={(r) => nav(`/admin/companies/${r.id}`)}
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
  const EMPTY_CO = { name: "", domain: "", plan: "trial", admin_name: "", admin_email: "" };
  const [f, setF] = useState(EMPTY_CO);
  const [res, setRes] = useState(null);
  const [touched, setTouched] = useState({});
  const [tried, setTried] = useState(false);
  const [server, setServer] = useState({});
  const [run, busy] = useAction();
  const dom = f.domain.trim().toLowerCase();
  const errs = {
    name: !f.name.trim() ? "This is required." : f.name.trim().length < 2 ? "Company name needs at least 2 characters." : "",
    domain: dom && !/^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$/.test(dom) ? "Enter a domain like acme.com (no https:// or slashes)." : "",
    admin_name: nameError(f.admin_name), admin_email: emailError(f.admin_email),
  };
  const show = (k) => server[k] || ((touched[k] || tried) && errs[k]) || "";
  const bad = Object.keys(errs).filter((k) => errs[k]);
  const set = (k, v) => { setF({ ...f, [k]: v }); if (server[k]) { const n = { ...server }; delete n[k]; setServer(n); } };
  const create = () => {
    setTried(true);
    if (bad.length) return;
    run(() => api.post("/platform/companies", { ...f, name: f.name.trim(), domain: dom, admin_name: f.admin_name.trim(), admin_email: f.admin_email.trim() }))
      .then((r) => { setRes(r); onDone(); }).catch((e) => e.fields && setServer(e.fields));
  };
  if (res) return (
    <Modal title="Company onboarded" onClose={onClose} footer={<Btn kind="primary" onClick={onClose}>Done</Btn>}>
      <p>Share these sign-in details with the Company Admin. They will be asked to choose a new password.</p>
      <div className="card pad mono">{res.admin.email}<br />{res.temporary_password}</div>
      <p className="small muted">Default team, policies and settings were created. The invite is valid for 7 days.</p>
    </Modal>
  );
  return (
    <Modal title="Onboard a company" dirty={JSON.stringify(f) !== JSON.stringify(EMPTY_CO)} onClose={onClose} footer={(close) => <>
      {tried && bad.length > 0 && <span className="missing-note">Fix the highlighted fields.</span>}
      <Btn onClick={close}>Cancel</Btn><Btn kind="primary" busy={busy} disabled={tried && bad.length > 0} onClick={create}>Create company</Btn></>}>
      <form autoComplete="off" className="col" style={{ gap: 14 }} onSubmit={(e) => { e.preventDefault(); create(); }}>
        <div className="grid g2"><Field label="Company name" required error={show("name")}><Input value={f.name} maxLength={160} placeholder="e.g. Acme Technologies" onChange={(e) => set("name", e.target.value)} onBlur={() => setTouched({ ...touched, name: true })} autoFocus /></Field>
          <Field label="Domain" error={show("domain")} hint="Optional. Their email domain, e.g. acme.com"><Input value={f.domain} maxLength={120} placeholder="acme.com" onChange={(e) => set("domain", e.target.value)} onBlur={() => setTouched({ ...touched, domain: true })} /></Field></div>
        <Field label="Plan" required error={server.plan}><Select value={f.plan} onChange={(v) => set("plan", v)} options={PLAN_OPTS} /></Field>
        <div className="grid g2"><Field label="Company Admin name" required error={show("admin_name")}><Input value={f.admin_name} maxLength={80} placeholder="e.g. Neha Kapoor" onChange={(e) => set("admin_name", e.target.value)} onBlur={() => setTouched({ ...touched, admin_name: true })} /></Field>
          <Field label="Company Admin email" required error={show("admin_email")}><Input type="email" value={f.admin_email} maxLength={254} placeholder="name@company.com" onChange={(e) => set("admin_email", e.target.value)} onBlur={() => setTouched({ ...touched, admin_email: true })} /></Field></div>
      </form>
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
  { key: "company", label: "Company", render: (r) => r.company || "—" },
  { key: "action", label: "Action", sort: "action", render: (r) => r.action_label || r.action },
  { key: "target", label: "Target", render: (r) => r.target_label || (r.target_type ? `${r.target_type} #${r.target_id ?? ""}` : "—") },
  { key: "detail", label: "Details", render: (r) => (r.detail_items || []).length ? <span className="small ellipsis" style={{ display: "inline-block", maxWidth: 380 }} title={(r.detail_items || []).map((x) => `${x.label}: ${x.value}`).join(" · ")}>{(r.detail_items || []).map((x) => <span key={x.label}><span className="muted">{x.label}:</span> {x.value}{"  "}</span>)}</span> : "—" }];

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
  const [testing, setTesting] = useState("");
  if (!data) return <Loading />;
  const edit = (k, v, which) => { setF({ ...f, [k]: v }); if (test[which]) setTest({ ...test, [which]: null }); };
  // Tests what is typed in the box (without saving it); with nothing typed, tests the saved key.
  const doTest = async (which) => {
    if (testing) return;
    setTesting(which);
    const payload = which === "anthropic" ? { which, key: f.anthropic_api_key } : { which, key: f.azure_speech_key, region: f.azure_speech_region };
    try { const r = await api.post("/platform/integrations/test", payload); setTest((t) => ({ ...t, [which]: { ok: true, msg: `${r.message} (tested the ${r.source} key ${r.key})` } })); }
    catch (e) { setTest((t) => ({ ...t, [which]: { ok: false, msg: e.message } })); }
    finally { setTesting(""); }
  };
  const save = (keys, which) => {
    const payload = {}; keys.forEach((k) => { if (f[k].trim()) payload[k] = f[k].trim(); });
    return run(() => api.put("/platform/integrations", payload), "Saved").then(() => { const n = { ...f }; keys.forEach((k) => { n[k] = ""; }); setF(n); setTest({ ...test, [which]: null }); reload(); });
  };
  const Result = ({ t }) => t ? <div className={"chip " + (t.ok ? "good" : "bad")} role="status" style={{ height: "auto", padding: 8, whiteSpace: "normal" }}>{t.msg}</div> : null;
  return (
    <div className="grid g2">
      <div className="card pad col">
        <div className="row"><h3>Anthropic (all AI work)</h3>{data.anthropic_ok ? <Chip kind="good">Key saved</Chip> : <Chip kind="warn">Not set</Chip>}</div>
        <p className="small muted">Hira, Isha and Disha use Claude for drafting jobs, scoring, interviews, live analysis, reports and learning paths. Choose the model under Voices → AI.</p>
        <Field label="API key" hint={data.anthropic_api_key ? `Saved key: ${data.anthropic_api_key}. Paste a new one to replace it.` : "Starts with sk-ant-"}><Input type="password" autoComplete="off" value={f.anthropic_api_key} placeholder={data.anthropic_api_key ? "Paste a new key to replace the saved one" : "sk-ant-…"} onChange={(e) => edit("anthropic_api_key", e.target.value, "anthropic")} /></Field>
        <div className="row"><Btn kind="primary" busy={busy} disabled={!f.anthropic_api_key.trim()} onClick={() => save(["anthropic_api_key"], "anthropic")}>Save</Btn>
          <Btn busy={testing === "anthropic"} disabled={!f.anthropic_api_key.trim() && !data.anthropic_ok} onClick={() => doTest("anthropic")}>{f.anthropic_api_key.trim() ? "Test this key" : "Test saved key"}</Btn></div>
        <Result t={test.anthropic} />
        {data.ai_status?.recent_error && <div className="sc-note bad">Last call to Claude failed: {data.ai_status.error}. Hira, Isha and Disha are using built-in fallbacks until it works again.</div>}
        {data.ai_status?.working && <div className="tiny muted">Working · last call used {data.ai_status.model}.</div>}
      </div>
      <div className="card pad col">
        <div className="row"><h3>Azure Speech (all voice)</h3>{data.azure_ok ? <Chip kind="good">Key saved</Chip> : <Chip kind="warn">Not set</Chip>}</div>
        <p className="small muted">Text-to-speech for Hira's voice and speech-to-text for candidate answers and Isha's live transcript.</p>
        <Field label="Speech key" hint={data.azure_speech_key ? `Saved key: ${data.azure_speech_key}. Paste a new one to replace it.` : ""}><Input type="password" autoComplete="off" value={f.azure_speech_key} placeholder={data.azure_speech_key ? "Paste a new key to replace the saved one" : ""} onChange={(e) => edit("azure_speech_key", e.target.value, "azure")} /></Field>
        <Field label="Region" hint={`Saved region: ${data.azure_speech_region || "none"}`}><Input placeholder={data.azure_speech_region || "centralindia"} value={f.azure_speech_region} onChange={(e) => edit("azure_speech_region", e.target.value.trim().toLowerCase(), "azure")} /></Field>
        <div className="row"><Btn kind="primary" busy={busy} disabled={!f.azure_speech_key.trim() && !f.azure_speech_region.trim()} onClick={() => save(["azure_speech_key", "azure_speech_region"], "azure")}>Save</Btn>
          <Btn busy={testing === "azure"} disabled={!f.azure_speech_key.trim() && !data.azure_ok} onClick={() => doTest("azure")}>{f.azure_speech_key.trim() || f.azure_speech_region.trim() ? "Test what's typed" : "Test saved key"}</Btn></div>
        <Result t={test.azure} />
        {data.voice_status?.recent_error && <div className="sc-note bad">Last call to Azure failed: {data.voice_status.error}.</div>}
      </div>
      <TurnCard data={data} reload={reload} />
    </div>
  );
}

/** V02.00.08: the platform's video relay. Companies without their own TURN server use this one. */
function TurnCard({ data, reload }) {
  const [f, setF] = useState({ turn_urls: data.turn_urls || "", turn_username: data.turn_username || "", turn_credential: "", turn_secret: "" });
  const [run, busy] = useAction();
  const [probe, setProbe] = useState(null);
  const save = () => run(() => api.put("/platform/integrations", { turn_urls: f.turn_urls, turn_username: f.turn_username,
    ...(f.turn_credential ? { turn_credential: f.turn_credential } : {}), ...(f.turn_secret ? { turn_secret: f.turn_secret } : {}) }), "Relay saved")
    .then(() => { setF({ ...f, turn_credential: "", turn_secret: "" }); reload(); });
  const test = async () => {
    setProbe({ busy: true });
    try {
      const r = await api.get("/platform/integrations/turn-test");
      const x = await probeConnection(r.ice_servers, 9000);
      setProbe(x.relay ? { ok: true, msg: `Relay works: ${x.relay} relay route${x.relay > 1 ? "s" : ""} found${x.relayTcp ? " (including TCP/TLS)" : ""}.` }
        : { ok: false, msg: "No relay route came back. Check the addresses, the login or shared secret, and that the relay's ports are open in the server's firewall." });
    } catch (e) { setProbe({ ok: false, msg: e.message }); }
  };
  return (
    <div className="card pad col">
      <div className="row"><h3>Video relay (TURN)</h3>{data.turn_ok ? <Chip kind="good">Set</Chip> : <Chip kind="warn">Not set</Chip>}</div>
      <p className="small muted">Live interviews use it when a network blocks direct video, for example office Wi-Fi, mobile networks or VPNs. A company's own relay (Video call settings) takes priority.</p>
      <Field label="Relay addresses" hint="One or more, separated by spaces. Example: turn:beta.code2hire.ai:3478 turn:beta.code2hire.ai:3478?transport=tcp turns:beta.code2hire.ai:5349?transport=tcp">
        <Textarea value={f.turn_urls} onChange={(e) => setF({ ...f, turn_urls: e.target.value })} style={{ minHeight: 60 }} /></Field>
      <Field label="Shared secret (recommended)" hint={data.turn_secret ? `Saved: ${data.turn_secret}. Each call gets its own login that expires, so no password reaches a browser. Matches static-auth-secret in coturn.` : "Matches static-auth-secret in coturn (use-auth-secret). Each call then gets its own login that expires."}>
        <Input type="password" autoComplete="off" value={f.turn_secret} placeholder={data.turn_secret ? "Paste a new secret to replace it" : ""} onChange={(e) => setF({ ...f, turn_secret: e.target.value })} /></Field>
      <div className="grid g2">
        <Field label="Username (without a secret)"><Input value={f.turn_username} onChange={(e) => setF({ ...f, turn_username: e.target.value })} /></Field>
        <Field label="Password (without a secret)" hint={data.turn_credential ? `Saved: ${data.turn_credential}` : ""}><Input type="password" autoComplete="off" value={f.turn_credential} onChange={(e) => setF({ ...f, turn_credential: e.target.value })} /></Field>
      </div>
      <div className="row"><Btn kind="primary" busy={busy} onClick={save}>Save</Btn><Btn busy={probe?.busy} disabled={!data.turn_ok} onClick={test}>Test saved relay from this browser</Btn></div>
      {probe && !probe.busy && <div className={"chip " + (probe.ok ? "good" : "bad")} role="status" style={{ height: "auto", padding: 8, whiteSpace: "normal" }}>{probe.msg}</div>}
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
  const [showArchived, setShowArchived] = useState(false);
  const { data, reload } = useAsync(() => api.get("/platform/templates", { archived: showArchived ? "true" : "" }), [showArchived]);
  const [edit, setEdit] = useState(null); // {} for new, or the template
  const [run] = useAction();
  const ask = useConfirm();
  // SA-001 (V02.00.08): Delete moves a template to Archived; only an archived one can be deleted for good
  const remove = async (t) => {
    if (!t.archived) {
      const ok = await ask({ title: `Delete “${t.name}”?`, text: "It moves to Archived: companies won't see it when they start a job, and you can restore it from Show archived. Jobs already made from it keep their rounds.", yes: "Delete", danger: true });
      if (ok) run(() => api.del(`/platform/templates/${t.id}`), "Moved to Archived. Tick Show archived to see it.").then(reload).catch(() => {});
      return;
    }
    const ok = await ask({ title: `Delete “${t.name}” for good?`, text: "It's removed permanently and can't be restored. Jobs already made from it keep their rounds.", yes: "Delete permanently", danger: true });
    if (ok) run(() => api.del(`/platform/templates/${t.id}?permanent=1`), "Template deleted").then(reload).catch(() => {});
  };
  return (
    <>
      <PageHead title="Hiring templates" sub="Global starting points: rounds and rubrics companies can copy." actions={<>
        <label className="check small"><input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />Show archived{data && showArchived ? ` (${data.length})` : ""}</label>
        <Btn kind="primary" onClick={() => setEdit({})}>New template</Btn></>} />
      {showArchived && <p className="small muted" style={{ marginTop: 0 }}>Archived templates. Restore one to offer it to companies again, or delete it for good.</p>}
      {!data ? <Loading /> : !data.length ? (showArchived ? <Empty title="Nothing archived" text="Templates you delete or archive appear here." /> : <Empty title="No templates yet" text="Create one so companies can start a job from it." />) : (
        <div className="grid g3">{data.map((t) => (
          <div key={t.id} className="card pad col" style={{ opacity: t.archived ? .7 : 1 }}>
            <div className="row"><h3 className="grow">{t.name}</h3>{t.archived && <Chip>Archived</Chip>}</div>
            <p className="muted small" style={{ margin: 0 }}>{t.description || "No description."}</p>
            <div className="row wrap">{(t.rounds || []).map((r, i) => <Chip key={i} kind="brand">{i + 1}. {r.name || ROUND_LABEL[r.type]}</Chip>)}</div>
            {t.updated_at && <span className="tiny muted">Updated {fmtDate(t.updated_at, true)}</span>}
            <div className="row wrap" style={{ marginTop: "auto" }}>
              <Btn size="sm" onClick={() => setEdit(t)}>Edit</Btn>
              <Btn size="sm" kind="ghost" onClick={() => run(() => api.post(`/platform/templates/${t.id}/duplicate`), "Duplicated").then(reload).catch(() => {})}>Duplicate</Btn>
              <Btn size="sm" kind="ghost" onClick={() => run(() => api.patch(`/platform/templates/${t.id}`, { archived: !t.archived }), t.archived ? "Restored" : "Archived").then(reload).catch(() => {})}>{t.archived ? "Restore" : "Archive"}</Btn>
              <Btn size="sm" kind="ghost" className="right" style={{ color: "var(--bad)" }} onClick={() => remove(t)}>{t.archived ? "Delete permanently" : "Delete"}</Btn>
            </div>
          </div>))}</div>
      )}
      {edit && <TemplateEditor t={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload(); }} />}
    </>
  );
}

function TemplateEditor({ t, onClose, onSaved }) {
  const isNew = !t.id;
  const start = { name: t.name || "", description: t.description || "", rounds: t.rounds?.length ? t.rounds : [{ type: "mcq", name: "Skill screen" }] };
  const [f, setF] = useState(start);
  const [tried, setTried] = useState(false);
  const [server, setServer] = useState({});
  const [run, busy] = useAction();
  const errs = { name: !f.name.trim() ? "This is required." : f.name.trim().length < 2 ? "Name needs at least 2 characters." : "", rounds: f.rounds.length ? "" : "Add at least one round." };
  const show = (k) => server[k] || (tried && errs[k]) || "";
  const save = () => {
    setTried(true);
    if (errs.name || errs.rounds) return;
    run(() => (isNew ? api.post("/platform/templates", f) : api.patch(`/platform/templates/${t.id}`, f)), isNew ? "Template created" : "Template saved")
      .then(onSaved).catch((e) => e.fields && setServer(e.fields));
  };
  return (
    <Modal wide title={isNew ? "New template" : `Edit “${t.name}”`} dirty={JSON.stringify(f) !== JSON.stringify(start)} onClose={onClose}
      footer={(close) => <><Btn onClick={close}>Cancel</Btn><Btn kind="primary" busy={busy} onClick={save}>{isNew ? "Create template" : "Save changes"}</Btn></>}>
      <Field label="Name" required error={show("name")}><Input value={f.name} maxLength={160} placeholder="e.g. Standard tech hire" onChange={(e) => { setF({ ...f, name: e.target.value }); setServer({ ...server, name: "" }); }} autoFocus /></Field>
      <Field label="Description" hint="Shown to companies when they pick a template."><Textarea value={f.description} maxLength={2000} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
      <RoundsEditor rounds={f.rounds} onChange={(rounds) => setF({ ...f, rounds })} />
      {show("rounds") && <span className="field-err">{show("rounds")}</span>}
      {!isNew && <span className="small muted">Changes apply to new jobs only. Jobs already made from this template keep their rounds.</span>}
    </Modal>
  );
}

export function Disputes() {
  const [status, setStatus] = useState("open");
  const { data, reload } = useAsync(() => api.get("/platform/disputes", { status }), [status]);
  const [open, setOpen] = useState(null);
  return (
    <>
      <PageHead title="Candidate disputes" sub="Candidates who think a round was unfair. Look at the evidence, then grant a re-interview, change the outcome, or dismiss it with a reason. The candidate sees your answer." />
      <Seg value={status} onChange={setStatus} options={[["open", "Open"], ["resolved", "Resolved"], ["all", "All"]]} />
      {!data ? <Loading /> : !data.items.length ? <Empty title={status === "open" ? "No open disputes" : "Nothing here"} mascot={<Hira size={70} />} text="When a candidate raises a concern about a round, it shows up here." /> : (
        <div className="card"><div className="tbl-wrap"><table className="tbl">
          <thead><tr><th>Candidate</th><th>Company · job</th><th>Round</th><th>Their concern</th><th>Raised</th><th>Status</th><th /></tr></thead>
          <tbody>{data.items.map((r) => (
            <tr key={r.id} className="clickable" onClick={() => setOpen(r)}>
              <td><b>{r.candidate}</b><div className="tiny muted">{r.candidate_email}</div></td>
              <td>{r.company}<div className="tiny muted">{r.job}</div></td>
              <td className="small">{r.round}</td>
              <td style={{ maxWidth: 320 }}><div className="small qb-clamp">“{r.note}”</div></td>
              <td className="small">{fmtDate(r.disputed_at, true)}</td>
              <td>{r.status === "open" ? <Chip kind="bad">Open</Chip> : <Chip kind="good">{DISPUTE_LABEL[r.status] || r.status}</Chip>}</td>
              <td><Btn size="sm" onClick={(e) => { e.stopPropagation(); setOpen(r); }}>{r.status === "open" ? "Review" : "View"}</Btn></td>
            </tr>))}</tbody>
        </table></div></div>
      )}
      {open && <DisputeReview row={open} platform onClose={() => setOpen(null)} onDone={() => { setOpen(null); reload(); }} />}
    </>
  );
}

export const DISPUTE_LABEL = { reinterview: "Re-interview granted", changed: "Outcome changed", dismissed: "Dismissed", open: "Open" };

/** Evidence on the left, decision on the right. Used by the platform team and by the company's reviewers. */
export function DisputeReview({ row, platform, onClose, onDone }) {
  const { data } = useAsync(() => (platform ? api.get(`/platform/disputes/${row.id}`) : api.get(`/reports/${row.id}`)), [row.id]);
  const [action, setAction] = useState("");
  const [note, setNote] = useState("");
  const [run, busy] = useAction();
  const isOpen = (data?.dispute_status || row.status) === "open";
  const send = () => run(() => api.post(platform ? `/platform/disputes/${row.id}/resolve` : `/reports/${row.id}/resolve-dispute`, { action, note: note.trim() }), "Resolved. The candidate has been told.").then(onDone).catch(() => {});
  return (
    <Modal size="lg" title={`Dispute: ${row.candidate || data?.candidate?.name || ""}`} dirty={!!note.trim()} onClose={onClose} footer={(close) => isOpen ? <>
      {(!action || note.trim().length < 10) && <span className="missing-note">{!action ? "Choose an outcome." : "Write at least a sentence for the candidate."}</span>}
      <Btn onClick={close}>Cancel</Btn><Btn kind="primary" busy={busy} disabled={!action || note.trim().length < 10} onClick={send}>Send decision</Btn></> : <Btn kind="primary" onClick={close}>Close</Btn>}>
      {!data ? <Loading /> : <>
        <div className="agent disha"><div className="grow"><b>The candidate says</b><div style={{ whiteSpace: "pre-wrap" }}>“{data.dispute_note || row.note}”</div><div className="tiny muted">{data.company ? data.company + " · " : ""}{data.job?.title} · {data.round} · raised {fmtDate(data.disputed_at || row.disputed_at, true)}</div></div></div>
        {!isOpen && <div className="card pad"><b>{DISPUTE_LABEL[data.dispute_status] || "Resolved"}</b><div className="small">{data.dispute_resolution}</div><div className="tiny muted">{fmtDate(data.dispute_resolved_at, true)}</div></div>}
        {isOpen && <div className="card pad col">
          <b>Your decision</b>
          <div className="col" style={{ gap: 6 }}>
            {[["reinterview", "Grant a re-interview", "The candidate gets a fresh attempt at this round, free of charge."], ["changed", "Change the outcome", "You've corrected the scores or decision in the report. Say what changed."], ["dismissed", "Dismiss: the result stands", "Explain what you checked and why the result is fair."]].map(([k, l, h]) => (
              <label key={k} className="opt" style={{ alignItems: "flex-start" }}><input type="radio" name="dispute-action" checked={action === k} onChange={() => setAction(k)} /><div><b>{l}</b><div className="small muted">{h}</div></div></label>))}
          </div>
          <Field label="Message to the candidate" required hint={`${note.trim().length < 10 ? "At least 10 characters. " : ""}They will see this.`}><Textarea value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} /></Field>
        </div>}
        <ReportView r={data} />
      </>}
    </Modal>
  );
}

export function RoundsEditor({ rounds, onChange }) {
  return (
    <div className="col">
      <b>Rounds, in order</b>
      {rounds.map((r, i) => (
        <div key={i} className="row">
          <span className="chip">{i + 1}</span>
          <div style={{ flex: "0 0 auto", minWidth: 230 }}><Select aria-label={`Round ${i + 1} type`} title={ROUND_LABEL[r.type]} value={r.type} onChange={(v) => { const x = [...rounds]; x[i] = { ...r, type: v, name: !r.name || Object.values(ROUND_LABEL).includes(r.name) ? ROUND_LABEL[v] : r.name }; onChange(x); }} options={Object.entries(ROUND_LABEL).map(([value, label]) => ({ value, label }))} /></div>
          <Input aria-label={`Round ${i + 1} name`} value={r.name || ""} maxLength={120} placeholder="Round name" onChange={(e) => { const x = [...rounds]; x[i] = { ...r, name: e.target.value }; onChange(x); }} />
          <Btn size="sm" kind="ghost" disabled={i === 0} onClick={() => { const x = [...rounds]; [x[i - 1], x[i]] = [x[i], x[i - 1]]; onChange(x); }} aria-label="Move up">↑</Btn>
          <Btn size="sm" kind="ghost" onClick={() => onChange(rounds.filter((_, j) => j !== i))} aria-label="Remove round">✕</Btn>
        </div>
      ))}
      <Btn size="sm" disabled={rounds.length >= 10} onClick={() => onChange([...rounds, { type: "ai_interview", name: ROUND_LABEL.ai_interview, config: {} }])}>+ Add round</Btn>
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

/** SA-002/003 (V02.00.08): select users and delete them (they're archived, so their history stays); Archived shows them
 *  with Restore. */
export function Users() {
  const loc = useLocation();
  const [archived, setArchived] = useState(false);
  const [rk, setRk] = useState(0);
  const [run] = useAction();
  const ask = useConfirm();
  const del = async (ids, done, names) => {
    const ok = await ask({ title: `Delete ${ids.length === 1 ? names[0] : `${ids.length} users`}?`, danger: true, yes: "Delete",
      text: "They can't sign in any more and disappear from lists. Their jobs, interviews and reports stay. You can restore them from Archived." });
    if (ok) run(() => api.post("/platform/users/archive", { ids }), ids.length === 1 ? "User deleted" : `${ids.length} users deleted`).then(done).catch(() => {});
  };
  const restore = (ids, done) => run(() => api.post("/platform/users/restore", { ids }), "Restored").then(done).catch(() => {});
  // A5 (V02.00.08): erasure requests. Name, email, phone, resume and interview videos go; reports stay without personal data
  const erase = async (ids, done, names) => {
    const ok = await ask({ title: `Delete ${ids.length === 1 ? names[0] : `${ids.length} users`} permanently?`, danger: true, yes: "Delete permanently",
      text: "Their name, email, phone and resume are removed and their interview videos deleted. Reports stay for employers' records without personal data. This can't be undone, and they can't be restored." });
    if (ok) run(() => api.post("/platform/users/erase", { ids, confirm: "DELETE" }), "Deleted permanently").then(done).catch(() => {});
  };
  return <><PageHead title="All users" sub={archived ? "Deleted users. Restore them to let them sign in again." : "Everyone on the platform."} />
    <DataTable key={loc.search} endpoint="/platform/users" defaultSort="created" reloadKey={rk} params={{ archived: archived ? "true" : "" }}
      defaultFilters={urlFilters(loc, ["kind", "company_id"])} selectable rowLabel={(r) => r.name}
      toolbarStart={<div className="seg" role="group" aria-label="Which users"><button type="button" className={!archived ? "on" : ""} onClick={() => setArchived(false)}>Current</button><button type="button" className={archived ? "on" : ""} onClick={() => setArchived(true)}>Archived</button></div>}
      filters={[{ key: "kind", label: "Type", options: [{ value: "staff", label: "Hiring team" }, { value: "candidate", label: "Candidate" }, { value: "superadmin", label: "Superadmin" }] }]}
      bulk={(ids, done, names) => archived
        ? <><Btn size="sm" kind="gold" onClick={() => restore(ids, () => { done(); setRk(rk + 1); })}>Restore</Btn>
          <Btn size="sm" kind="danger" onClick={() => erase(ids, () => { done(); setRk(rk + 1); }, names)}>Delete permanently</Btn></>
        : <Btn size="sm" kind="danger" onClick={() => del(ids, () => { done(); setRk(rk + 1); }, names)}>Delete</Btn>}
      columns={[{ key: "name", label: "Name", sort: "name", render: (r) => <b>{r.name}{r.is_me && <span className="tiny muted"> (you)</span>}</b> }, { key: "email", label: "Email", sort: "email" },
        { key: "kind", label: "Type", render: (r) => <Chip kind={r.is_superadmin ? "dark" : r.kind === "staff" ? "brand" : "disha"}>{r.is_superadmin ? "Superadmin" : r.kind === "staff" ? "Hiring team" : "Candidate"}</Chip> },
        { key: "company", label: "Company", render: (r) => r.company || "—" },
        { key: "last_login_at", label: "Last sign-in", render: (r) => r.last_login_at ? fmtDate(r.last_login_at, true) : "Never" },
        archived ? { key: "archived_at", label: "Deleted", render: (r) => fmtDate(r.archived_at, true) } : { key: "active", label: "Active", render: (r) => r.active ? "Yes" : "No" }]} /></>;
}

/** SA-005/006 (V02.00.08): plain words instead of JSON, and a search across everything in a row. */
export function Audit() {
  const [open, setOpen] = useState(null);
  const { data: groups } = useAsync(() => api.get("/platform/audit/actions").catch(() => []), []);
  const { data: cos } = useAsync(() => api.get("/platform/companies", { size: 100 }).catch(() => ({ items: [] })), []);
  return <><PageHead title="Audit log" sub="Every action across the platform. Search by person, company, action, name, number or detail." />
    <DataTable endpoint="/platform/audit" defaultSort="created" columns={auditCols} onRow={setOpen} searchPlaceholder="Search people, actions, names, numbers…"
      filters={[{ key: "action", label: "Action", options: groups || [] }, { key: "company_id", label: "Company", width: 200, options: (cos?.items || []).map((c) => ({ value: String(c.id), label: c.name })) }]} />
    {open && <Modal title={open.action_label} onClose={() => setOpen(null)}>
      <dl className="kv">
        <dt>When</dt><dd>{fmtDate(open.created_at, true)}</dd>
        <dt>Who</dt><dd>{open.actor}</dd>
        {open.company && <><dt>Company</dt><dd>{open.company}</dd></>}
        <dt>Target</dt><dd>{open.target_label}</dd>
        {(open.detail_items || []).map((x, i) => <Fragment key={i}><dt>{x.label}</dt><dd>{x.value}</dd></Fragment>)}
        <dt>Action code</dt><dd className="mono tiny">{open.action}</dd>
      </dl>
    </Modal>}</>;
}

/** SA-008 (V02.00.08): platform-wide lists the overview cards open. */
export function PlatformJobs() {
  const loc = useLocation();
  return <><PageHead title="Jobs" sub="Every company's jobs. Open support access from the company to work on one." />
    <DataTable key={loc.search} endpoint="/platform/jobs" defaultSort="created" defaultFilters={urlFilters(loc, ["status", "company_id"])}
      filters={[{ key: "status", label: "Status", options: [{ value: "live", label: "Live" }, { value: "draft", label: "Draft" }, { value: "pending_approval", label: "Awaiting approval" }, { value: "closed", label: "Closed" }] }]}
      columns={[{ key: "title", label: "Job", sort: "title", render: (r) => <b>{r.title}</b> }, { key: "company", label: "Company" }, { key: "status", label: "Status", sort: "status", render: (r) => <Status s={r.status} /> },
        { key: "applications", label: "Candidates" }, { key: "location", label: "Location", render: (r) => r.location || "—" }, { key: "created_at", label: "Created", sort: "created", render: (r) => fmtDate(r.created_at) }]} /></>;
}

const RTYPE = [{ value: "mcq", label: "MCQ round" }, { value: "ai_interview", label: "AI interview" }, { value: "f2f_isha", label: "Live interview with Isha" }, { value: "f2f_human", label: "Live interview" }];
export function PlatformRounds() {
  const loc = useLocation();
  const t = new URLSearchParams(loc.search).get("type");
  const label = RTYPE.find((x) => x.value === t)?.label;
  const [again, setAgain] = useState(null);  // N6 (V02.00.09)
  const [closing, setClosing] = useState(null);  // N4 (V02.00.09)
  const [rk, setRk] = useState(0);
  const toast = useToast();
  return <><PageHead title={label ? label + "s" : "Rounds"} sub="Every round across companies, including practice and certifications." />
    <DataTable key={loc.search} endpoint="/platform/rounds" reloadKey={rk} defaultSort="created" defaultFilters={urlFilters(loc, ["type", "status"])}
      filters={[{ key: "type", label: "Type", width: 220, options: RTYPE }, { key: "status", label: "Status", options: ["invited", "scheduled", "in_progress", "completed", "reviewed", "expired", "not_finished"] },
        { key: "practice", label: "Kind", options: [{ value: "false", label: "Hiring rounds" }, { value: "true", label: "Practice" }] }]}
      columns={[{ key: "candidate", label: "Candidate", render: (r) => <b>{r.candidate || "—"}</b> }, { key: "type", label: "Type", render: (r) => RTYPE.find((x) => x.value === r.type)?.label || r.type },
        { key: "job", label: "Job", render: (r) => r.job || "—" }, { key: "company", label: "Company", render: (r) => r.company || "—" }, { key: "status", label: "Status", sort: "status", render: (r) => <Status s={r.status} /> },
        { key: "score", label: "Score", render: (r) => r.score != null ? r.score : "—" }, { key: "created_at", label: "Created", sort: "created", render: (r) => fmtDate(r.created_at) },
        { key: "actions", label: "Actions", render: (r) => r.hiring && <span className="row" style={{ gap: 6 }}>
          {["f2f_isha", "f2f_human"].includes(r.type) && ["in_progress", "paused", "not_finished"].includes(r.status) && <Btn size="sm" kind="ghost" onClick={() => setClosing(r.id)}>Close</Btn>}
          {!["voided", "cancelled"].includes(r.status) && <Btn size="sm" kind="ghost" onClick={() => setAgain(r.id)}>Interview again</Btn>}</span> }]} />
    {again && <InterviewAgain attemptId={again} onClose={() => setAgain(null)} onDone={(r) => { setAgain(null); toast(r?.message || "Done"); setRk(rk + 1); }} />}
    {closing && <CloseInterview attemptId={closing} onClose={() => setClosing(null)} onAgain={() => { setAgain(closing); setClosing(null); }} onDone={() => { setClosing(null); setRk(rk + 1); }} />}</>;
}

export function PlatformReports() {
  const loc = useLocation();
  return <><PageHead title="Reports" sub="Every report. “Reviewed” compares the AI's recommendation with the person's decision." />
    <DataTable key={loc.search} endpoint="/platform/reports" defaultSort="created" defaultFilters={urlFilters(loc, ["reviewed", "recommendation"])}
      filters={[{ key: "reviewed", label: "Reviewed", width: 220, options: [{ value: "any", label: "Reviewed by a person" }, { value: "agree", label: "AI and person agree" }, { value: "disagree", label: "AI and person disagree" }] },
        { key: "recommendation", label: "AI recommends", options: [{ value: "proceed", label: "Proceed" }, { value: "hold", label: "Hold" }, { value: "reject", label: "Do not proceed" }] }]}
      columns={[{ key: "candidate", label: "Candidate", render: (r) => <b>{r.candidate || "—"}</b> }, { key: "job", label: "Job", render: (r) => r.job || "—" }, { key: "company", label: "Company", render: (r) => r.company || "—" },
        { key: "type", label: "Round", render: (r) => RTYPE.find((x) => x.value === r.type)?.label || r.type }, { key: "overall", label: "Score", sort: "overall", render: (r) => r.overall ?? "—" },
        { key: "recommendation", label: "AI", render: (r) => r.recommendation || "—" }, { key: "verdict", label: "Person", render: (r) => r.verdict ? <>{r.verdict} {r.agree === false && <Chip kind="warn">Differs</Chip>}</> : "—" },
        { key: "created_at", label: "Created", sort: "created", render: (r) => fmtDate(r.created_at) }]} /></>;
}
