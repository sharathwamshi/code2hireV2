import { useEffect, useMemo, useState } from "react";
import { api, download } from "../api";
import DataTable from "./DataTable";
import { AgentNote } from "./Mascot";
import { Btn, Chip, Confirm, Empty, Field, Input, ListEditor, Loading, Modal, Select, Status, Tabs, Textarea, ago, fmtDate, useAction, useAsync, useToast } from "./ui";

const L = "ABCDEF";

export function flatFolders(tree, depth = 0, path = []) {
  const out = [];
  (tree || []).forEach((f) => {
    const p = [...path, f.name];
    out.push({ id: f.id, label: p.join(" / "), depth, name: f.name, total: f.total });
    out.push(...flatFolders(f.children, depth + 1, p));
  });
  return out;
}

/** Folder multi-select used by rounds and settings: "draw MCQs from these folders". */
export function FolderPicker({ value = [], onChange, disabled }) {
  const { data: own } = useAsync(() => api.get("/qbank/folders"), []);
  const { data: glob } = useAsync(() => api.get("/qbank/folders", { scope: "global" }), []);
  if (!own || !glob) return <span className="spin" />;
  const groups = [["Our bank", flatFolders(own.tree)], ["Code2Hire bank", flatFolders(glob.tree)]];
  return (
    <div className="col" style={{ gap: 6, maxHeight: 240, overflow: "auto", minWidth: 300 }}>
      {groups.map(([g, list]) => list.length > 0 && (
        <div key={g} className="col" style={{ gap: 2 }}>
          <span className="tiny b muted">{g}</span>
          {list.map((f) => (
            <label key={f.id} className="check small" style={{ paddingLeft: f.depth * 16 }}>
              <input type="checkbox" disabled={disabled} checked={value.includes(f.id)} onChange={(e) => onChange(e.target.checked ? [...value, f.id] : value.filter((x) => x !== f.id))} />
              {f.name} <span className="faint">({f.total})</span>
            </label>
          ))}
        </div>
      ))}
      <span className="tiny muted">{value.length ? `${value.length} folder${value.length > 1 ? "s" : ""}: only approved questions in these folders (and their sub-folders) are used.` : "None chosen: questions are picked by the job's skills."}</span>
    </div>
  );
}

function FolderNode({ f, sel, onSel, open, toggle, onAct, writable, depth = 0 }) {
  const has = f.children?.length > 0;
  const on = sel === String(f.id);
  return (
    <>
      <div className={"qb-node" + (on ? " on" : "")} style={{ paddingLeft: 8 + depth * 14 }} onClick={() => onSel(String(f.id))}>
        <button className="qb-caret" onClick={(e) => { e.stopPropagation(); toggle(f.id); }} aria-label={open[f.id] ? "Collapse" : "Expand"} style={{ visibility: has ? "visible" : "hidden" }}>{open[f.id] ? "▾" : "▸"}</button>
        <span className="qb-ico">{on ? "📂" : "📁"}</span>
        <span className="grow ellipsis" title={f.description || f.name}>{f.name}</span>
        {f.pending > 0 && <span className="qb-dot" title={`${f.pending} waiting for approval`} />}
        <span className="qb-count">{f.total}</span>
        {writable && <button className="qb-more" onClick={(e) => { e.stopPropagation(); onAct(f, e.currentTarget); }} aria-label={`Folder actions for ${f.name}`}>⋯</button>}
      </div>
      {has && open[f.id] && f.children.map((c) => <FolderNode key={c.id} f={c} sel={sel} onSel={onSel} open={open} toggle={toggle} onAct={onAct} writable={writable} depth={depth + 1} />)}
    </>
  );
}

function QuestionForm({ init, folders, onSave, onCancel, busy, saveLabel = "Save" }) {
  const [f, setF] = useState(() => ({ text: "", code: "", options: ["", "", "", ""], answer: 0, explanation: "", skill: "", level: 3, tags: [], folder_id: "", time_seconds: "", note: "", ...init, options: [...(init?.options?.length ? init.options : ["", "", "", ""])] }));
  const set = (k, v) => setF({ ...f, [k]: v });
  return (
    <div className="col" style={{ gap: 12 }}>
      <Field label="Question"><Textarea value={f.text} onChange={(e) => set("text", e.target.value)} style={{ minHeight: 80 }} /></Field>
      <Field label="Code snippet (optional)"><Textarea className="textarea mono" value={f.code || ""} onChange={(e) => set("code", e.target.value)} style={{ minHeight: 60, fontFamily: "ui-monospace, monospace" }} /></Field>
      <div className="col" style={{ gap: 6 }}>
        <b className="small">Options <span className="muted" style={{ fontWeight: 500 }}>· pick the correct one</span></b>
        {f.options.map((o, i) => (
          <div key={i} className="row">
            <label className={"qb-opt-k" + (f.answer === i ? " on" : "")} title="Mark as correct"><input type="radio" name="ans" checked={f.answer === i} onChange={() => set("answer", i)} />{L[i]}</label>
            <Input value={o} onChange={(e) => { const x = [...f.options]; x[i] = e.target.value; set("options", x); }} placeholder={`Option ${L[i]}`} />
            <Btn size="sm" kind="ghost" disabled={f.options.length <= 2} onClick={() => { const x = f.options.filter((_, j) => j !== i); setF({ ...f, options: x, answer: f.answer === i ? 0 : f.answer > i ? f.answer - 1 : f.answer }); }} aria-label="Remove option">✕</Btn>
          </div>
        ))}
        {f.options.length < 6 && <Btn size="sm" onClick={() => set("options", [...f.options, ""])} style={{ alignSelf: "flex-start" }}>+ Add option</Btn>}
      </div>
      <Field label="Explanation (shown in reports and practice feedback)"><Textarea value={f.explanation || ""} onChange={(e) => set("explanation", e.target.value)} style={{ minHeight: 60 }} /></Field>
      <div className="grid g3">
        <Field label="Skill"><Input value={f.skill || ""} onChange={(e) => set("skill", e.target.value)} placeholder="e.g. Python" /></Field>
        <Field label="Level"><Select value={String(f.level)} onChange={(v) => set("level", +v)} options={"12345".split("").map((l) => ({ value: l, label: "L" + l }))} /></Field>
        <Field label="Suggested seconds"><Input type="number" value={f.time_seconds || ""} onChange={(e) => set("time_seconds", e.target.value)} placeholder="optional" /></Field>
      </div>
      <Field label="Folder"><Select value={String(f.folder_id || "")} onChange={(v) => set("folder_id", v ? +v : null)} options={[{ value: "", label: "No folder (unfiled)" }, ...folders.map((x) => ({ value: String(x.id), label: x.label }))]} /></Field>
      <Field label="Tags"><ListEditor value={f.tags || []} onChange={(v) => set("tags", v)} placeholder="Add a tag and press Enter" /></Field>
      {init?.id && <Field label="What changed? (saved with the new version)"><Input value={f.note} onChange={(e) => set("note", e.target.value)} placeholder="e.g. Clearer wording" /></Field>}
      <div className="row"><Btn onClick={onCancel}>Cancel</Btn><Btn kind="primary" className="right" busy={busy} onClick={() => onSave({ ...f, options: f.options.filter((o) => o.trim()) })}>{saveLabel}</Btn></div>
    </div>
  );
}

function Preview({ q }) {
  return (
    <div className="col" style={{ gap: 10 }}>
      <div className="qb-preview">
        <div className="row small muted"><span>As the candidate sees it</span><span className="right">{q.skill} · L{q.level}{q.time_seconds ? ` · ~${q.time_seconds}s` : ""}</span></div>
        <div style={{ fontWeight: 700, fontSize: 16, lineHeight: 1.45 }}>{q.text}</div>
        {q.code && <pre className="code">{q.code}</pre>}
        {(q.options || []).map((o, i) => (
          <div key={i} className={"qb-pv-opt" + (i === q.answer ? " ok" : "")}><span className="k">{L[i]}</span><span className="grow">{o}</span>{i === q.answer && <b style={{ color: "var(--good)" }}>✓ Correct</b>}</div>
        ))}
      </div>
      {q.explanation && <div className="tip-box"><b>Why: </b>{q.explanation}</div>}
    </div>
  );
}

function diffFields(a, b) {
  const keys = ["text", "code", "options", "answer", "explanation", "skill", "level", "tags"];
  return keys.filter((k) => JSON.stringify(a?.[k] ?? null) !== JSON.stringify(b?.[k] ?? null));
}

function History({ d, onRestore, writable }) {
  const [cmp, setCmp] = useState(null);
  const cur = d.question;
  return (
    <div className="col" style={{ gap: 0 }}>
      {d.versions.map((v, i) => {
        const prev = d.versions[i + 1];
        const changed = prev ? diffFields(prev.snapshot, v.snapshot) : [];
        const isCur = v.version === cur.version;
        return (
          <div key={v.version} className="qb-ver">
            <div className="qb-ver-dot" style={{ background: isCur ? "var(--brand)" : "var(--line-2)" }} />
            <div className="grow col" style={{ gap: 4 }}>
              <div className="row"><b>Version {v.version}</b>{isCur && <Chip kind="brand">Current</Chip>}<span className="tiny faint right">{fmtDate(v.at, true)}</span></div>
              <div className="small muted">{v.by} · {v.note || "—"}</div>
              {changed.length > 0 && <div className="row wrap">{changed.map((c) => <Chip key={c}>{c === "answer" ? "correct option" : c} changed</Chip>)}</div>}
              <div className="row">
                <Btn size="sm" kind="ghost" onClick={() => setCmp(cmp === v.version ? null : v.version)}>{cmp === v.version ? "Hide" : isCur ? "View" : "Compare with current"}</Btn>
                {!isCur && writable && <Btn size="sm" onClick={() => onRestore(v.version)}>Restore this version</Btn>}
              </div>
              {cmp === v.version && (
                <div className="qb-cmp">
                  {(isCur ? ["text", "options", "answer", "explanation"] : diffFields(v.snapshot, cur)).map((k) => (
                    <div key={k} className="col" style={{ gap: 2 }}>
                      <span className="tiny b muted">{k === "answer" ? "Correct option" : k}</span>
                      {!isCur && <div className="qb-old">{fmtVal(k, v.snapshot)}</div>}
                      <div className={isCur ? "" : "qb-new"}>{fmtVal(k, isCur ? v.snapshot : cur)}</div>
                    </div>
                  ))}
                  {!isCur && !diffFields(v.snapshot, cur).length && <span className="small muted">Same content as the current version.</span>}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
const fmtVal = (k, s) => k === "options" ? (s.options || []).map((o, i) => `${L[i]}. ${o}`).join("  ·  ") : k === "answer" ? L[s.answer] + ". " + (s.options || [])[s.answer] : k === "tags" ? (s.tags || []).join(", ") : String(s[k] ?? "—");

function Performance({ s, q }) {
  if (!s.asked) return <Empty title="Not used yet" text="Stats appear once candidates answer this question in a round." />;
  const total = Object.values(s.spread).reduce((a, b) => a + b, 0) || 1;
  return (
    <div className="col" style={{ gap: 14 }}>
      <div className="grid g3">
        <div className="card stat"><div className="l">Times asked</div><div className="v">{s.asked}</div></div>
        <div className="card stat"><div className="l">Answered correctly</div><div className="v">{s.correct_pct}%</div></div>
        <div className="card stat"><div className="l">Signal</div><div className="v" style={{ fontSize: 16 }}>{s.flag ? <Chip kind="warn">{s.flag}</Chip> : <Chip kind="good">Healthy</Chip>}</div></div>
      </div>
      <div className="col" style={{ gap: 6 }}>
        <b className="small">How candidates answered</b>
        {(q.options || []).map((o, i) => {
          const n = s.spread[String(i)] || 0;
          return <div key={i} className="row small"><span style={{ width: 18 }} className="b">{L[i]}</span><div className="grow bar" style={{ height: 14 }}><i style={{ width: `${(100 * n) / total}%`, background: i === q.answer ? "var(--good)" : "#B8C0D0" }} /></div><span style={{ width: 70, textAlign: "right" }}>{n} · {Math.round((100 * n) / total)}%</span></div>;
        })}
        {s.spread.skipped > 0 && <div className="small muted">Skipped {s.spread.skipped}</div>}
      </div>
      {s.by_version.length > 1 && <div className="col" style={{ gap: 4 }}><b className="small">By version</b>{s.by_version.map((v) => <div key={v.version} className="row small"><span className="grow">Version {v.version}</span><span>{v.asked} asked · {v.correct_pct}% correct</span></div>)}</div>}
      {s.jobs.length > 0 && <div className="col" style={{ gap: 4 }}><b className="small">Used in</b><div className="row wrap">{s.jobs.map((j) => <Chip key={j.id}>{j.title}</Chip>)}</div></div>}
    </div>
  );
}

function Drawer({ id, scope, folders, onClose, onChanged, canCopy }) {
  const [tab, setTab] = useState("preview");
  const { data: d, reload, setData } = useAsync(() => api.get(`/qbank/questions/${id}`, { scope }), [id, scope]);
  const [run, busy] = useAction();
  const toast = useToast();
  useEffect(() => setTab("preview"), [id]);
  if (!d) return <aside className="qb-drawer"><Loading /></aside>;
  const q = d.question;
  const patch = (p, msg) => run(() => api.patch(`/qbank/questions/${id}?scope=${scope}`, p), msg).then((x) => { setData(x); onChanged(); });
  return (
    <aside className="qb-drawer" aria-label="Question details">
      <div className="row" style={{ padding: "12px 16px", borderBottom: "1px solid var(--line)" }}>
        <Status s={q.status} /><Chip kind="brand">v{q.version}</Chip>{q.source === "ai" && <Chip kind="info">Drafted by Hira</Chip>}{q.source === "import" && <Chip>Imported</Chip>}
        <button className="btn ghost icon-btn right" onClick={onClose} aria-label="Close">✕</button>
      </div>
      <div style={{ padding: "0 16px" }}><Tabs value={tab} onChange={setTab} tabs={[["preview", "Preview"], ...(d.writable ? [["edit", "Edit"]] : []), ["history", `History (${d.versions.length})`], ["perf", "Performance"]]} /></div>
      <div className="qb-drawer-b">
        {tab === "preview" && (
          <div className="col" style={{ gap: 14 }}>
            <Preview q={q} />
            <div className="grid g2 small">
              <div><span className="muted">Folder</span><div className="b">{q.folder || "Unfiled"}</div></div>
              <div><span className="muted">Last change</span><div className="b">{ago(q.updated_at || q.created_at)}</div></div>
            </div>
            {q.tags?.length > 0 && <div className="row wrap">{q.tags.map((t) => <Chip key={t}>#{t}</Chip>)}</div>}
            <div className="row wrap">
              {d.writable && q.status === "pending" && <><Btn kind="primary" busy={busy} onClick={() => patch({ status: "approved" }, "Approved: now usable in rounds")}>Approve</Btn><Btn kind="danger" onClick={() => patch({ status: "rejected" }, "Rejected")}>Reject</Btn></>}
              {d.writable && <Btn onClick={() => setTab("edit")}>Edit</Btn>}
              {d.writable && <Btn onClick={() => run(() => api.post(`/qbank/questions/${id}/duplicate?scope=${scope}`), "Duplicated (as pending)").then(onChanged)}>Duplicate</Btn>}
              {d.writable && (q.status === "archived" ? <Btn onClick={() => patch({ status: "approved" }, "Restored")}>Unarchive</Btn> : <Btn kind="ghost" onClick={() => patch({ status: "archived" }, "Archived: hidden from rounds")}>Archive</Btn>)}
              {canCopy && <Btn kind="primary" onClick={() => run(() => api.post(`/qbank/questions/${id}/duplicate?scope=global`, { to_company: true }), "Copied to your bank, where you can edit it").then(onChanged)}>Copy to our bank</Btn>}
            </div>
            {q.status === "pending" && <AgentNote agent="hira">Pending questions are never shown to candidates. Check the correct option and the explanation, then approve.</AgentNote>}
          </div>
        )}
        {tab === "edit" && <QuestionForm key={q.version} init={q} folders={folders} busy={busy} saveLabel={`Save as version ${q.version + 1}`} onCancel={() => setTab("preview")}
          onSave={(f) => { const { note, ...rest } = f; run(() => api.patch(`/qbank/questions/${id}?scope=${scope}`, { ...rest, note }), "Saved").then((x) => { setData(x); setTab("preview"); onChanged(); }); }} />}
        {tab === "history" && <History d={d} writable={d.writable} onRestore={(v) => run(() => api.post(`/qbank/questions/${id}/restore?scope=${scope}`, { version: v }), `Restored version ${v} as a new version`).then((x) => { setData(x); onChanged(); })} />}
        {tab === "perf" && <Performance s={d.stats} q={q} />}
      </div>
    </aside>
  );
}

export default function QuestionBank({ allowGlobalBrowse = true, globalOnly = false }) {
  const [selKey] = useState(0); // eslint-disable-line no-unused-vars
  const toast = useToast();
  const [scope, setScope] = useState(globalOnly ? "global" : "company");
  const [sel, setSel] = useState("");
  const [open, setOpen] = useState({});
  const [rk, setRk] = useState(0);
  const [qid, setQid] = useState(null);
  const [skill, setSkill] = useState("");
  const [tag, setTag] = useState("");
  const [modal, setModal] = useState(null);
  const [menu, setMenu] = useState(null);
  const [run, busy] = useAction();
  const { data: tree, reload: reloadTree } = useAsync(() => api.get("/qbank/folders", { scope }), [scope, rk]);
  const { data: facets } = useAsync(() => api.get("/qbank/facets", { scope }), [scope, rk]);
  const folders = useMemo(() => flatFolders(tree?.tree), [tree]);
  useEffect(() => { setSel(""); setQid(null); setSkill(""); setTag(""); }, [scope]);
  useEffect(() => { if (tree) setOpen((o) => Object.keys(o).length ? o : Object.fromEntries((tree.tree || []).map((f) => [f.id, true]))); }, [tree]);
  const refresh = () => setRk((x) => x + 1);
  if (!tree) return <Loading />;
  const COLS = [
              { key: "text", label: "Question", render: (r) => <div style={{ maxWidth: 520 }}><div className="qb-clamp b">{r.text}</div>
                <div className="row wrap" style={{ gap: 4, marginTop: 4 }}>{r.code && <Chip kind="dark">code</Chip>}{(r.tags || []).slice(0, 4).map((t) => <span key={t} className="tiny muted">#{t}</span>)}{!sel && !qid && r.folder && <span className="tiny faint">📁 {r.folder}</span>}</div></div> },
              { key: "skill", label: "Skill", sort: "skill", render: (r) => <Chip>{r.skill}</Chip> },
              { key: "level", label: "Level", sort: "level", render: (r) => <span className="qb-lvl" title={`Level ${r.level}`}>{[1, 2, 3, 4, 5].map((n) => <i key={n} className={n <= r.level ? "on" : ""} />)}</span> },
              { key: "version", label: "Ver.", sort: "version", render: (r) => <Chip kind={r.version > 1 ? "brand" : ""}>v{r.version}</Chip> },
              { key: "status", label: "Status", sort: "status", render: (r) => <Status s={r.status} /> },
              { key: "source", label: "Source", render: (r) => <span className="small">{r.source === "ai" ? "✨ Hira" : r.source === "import" ? "CSV" : "Manual"}</span> },
              { key: "updated", label: "Updated", sort: "updated", render: (r) => <span className="small">{ago(r.updated_at || r.created_at)}</span> },
            ];
  const writable = tree.writable;
  const selName = sel === "" ? "All questions" : sel === "unfiled" ? "Unfiled" : sel === "pending" ? "Waiting for approval" : sel === "archived" ? "Archive" : folders.find((f) => String(f.id) === sel)?.label;
  const params = { scope, skill, tag, ...(sel && !["pending", "archived"].includes(sel) ? { folder_id: sel } : {}), ...(sel === "pending" ? { status: "pending" } : sel === "archived" ? { status: "archived" } : {}) };
  const folderAct = async (kind, f) => {
    setMenu(null);
    if (kind === "sub") setModal({ kind: "folder", parent_id: f.id });
    if (kind === "rename") setModal({ kind: "folder", id: f.id, name: f.name, description: f.description });
    if (kind === "move") setModal({ kind: "move-folder", f });
    if (kind === "delete") setModal({ kind: "delete-folder", f });
    if (kind === "export") download(`/qbank/questions/export?scope=${scope}&folder_id=${f.id}`, `${f.name}.csv`);
  };
  return (
    <div className="qb">
      <div className="qb-bar">
        {!globalOnly && allowGlobalBrowse && <div className="seg"><button className={scope === "company" ? "on" : ""} onClick={() => setScope("company")}>Our bank</button><button className={scope === "global" ? "on" : ""} onClick={() => setScope("global")}>Code2Hire bank</button></div>}
        <span className="small muted">{tree.total} questions{tree.pending ? ` · ${tree.pending} waiting for approval` : ""}{!writable ? " · read only" : ""}</span>
        <div className="right row wrap">
          {writable && <Btn kind="primary" onClick={() => setModal({ kind: "new" })}>+ New question</Btn>}
          {writable && <Btn onClick={() => setModal({ kind: "hira" })}>✨ Ask Hira to draft</Btn>}
          {writable && <Btn onClick={() => setModal({ kind: "import" })}>Import CSV</Btn>}
          <Btn onClick={() => download(`/qbank/questions/export?scope=${scope}${sel && /^\d+$/.test(sel) ? `&folder_id=${sel}` : ""}`, "questions.csv")}>Export</Btn>
        </div>
      </div>
      <div className={"qb-body" + (qid ? " with-drawer" : "")}>
        <nav className="qb-tree" aria-label="Question folders">
          {[["", "All questions", tree.total, "🗂"], ["pending", "Waiting for approval", tree.pending, "⏳"], ["unfiled", "Unfiled", tree.unfiled, "📄"], ["archived", "Archive", facets?.archived ?? "", "🗄"]].map(([k, l, n, ico]) => (
            <div key={k} className={"qb-node" + (sel === k ? " on" : "")} onClick={() => setSel(k)}><span className="qb-caret" /><span className="qb-ico">{ico}</span><span className="grow">{l}</span><span className="qb-count">{n}</span></div>
          ))}
          <div className="row" style={{ padding: "12px 8px 4px" }}><span className="tiny b muted" style={{ letterSpacing: ".06em" }}>FOLDERS</span>
            {writable && <button className="btn ghost sm right" style={{ height: 24 }} onClick={() => setModal({ kind: "folder", parent_id: null })}>+ New</button>}</div>
          {!tree.tree.length && <div className="small muted" style={{ padding: 8 }}>No folders yet. {writable ? "Create one to organise questions by role, skill or hiring drive." : ""}</div>}
          {tree.tree.map((f) => <FolderNode key={f.id} f={f} sel={sel} onSel={setSel} open={open} toggle={(id) => setOpen({ ...open, [id]: !open[id] })} writable={writable}
            onAct={(f2, el) => { const r = el.getBoundingClientRect(); setMenu({ f: f2, x: r.right, y: r.bottom }); }} />)}
        </nav>
        <section className="qb-list">
          <div className="row wrap" style={{ marginBottom: 10 }}>
            <h3 style={{ marginRight: 8 }}>{selName}</h3>
            {(facets?.skills || []).slice(0, 8).map(([s, n]) => <button key={s} className={"chip" + (skill === s ? " brand" : "")} style={{ border: 0, cursor: "pointer" }} onClick={() => setSkill(skill === s ? "" : s)}>{s} <span className="faint">{n}</span></button>)}
            {facets?.tags?.length > 0 && <div style={{ width: 160 }}><Select value={tag} onChange={setTag} options={[{ value: "", label: "Any tag" }, ...facets.tags.map(([t, n]) => ({ value: t, label: `#${t} (${n})` }))]} /></div>}
          </div>
          <DataTable endpoint="/qbank/questions" params={params} reloadKey={rk} defaultSort="updated" viewKey={"qbank-" + scope} selectable={writable || scope === "global"}
            onRow={(r) => setQid(r.id)} searchPlaceholder="Search question text, skill or explanation…"
            filters={[{ key: "level", label: "Level", width: 120, options: "12345".split("").map((l) => ({ value: l, label: "L" + l })) },
              ...(sel === "pending" || sel === "archived" ? [] : [{ key: "status", label: "Status", width: 150, options: ["approved", "pending", "rejected"] }]),
              { key: "source", label: "Source", width: 140, options: [{ value: "manual", label: "Manual" }, { value: "ai", label: "Hira" }, { value: "import", label: "Imported" }] }]}
            bulk={(ids, done) => scope === "global" && !writable
              ? <Btn size="sm" kind="gold" onClick={() => run(async () => { for (const i of ids) await api.post(`/qbank/questions/${i}/duplicate?scope=global`, { to_company: true }); }, `${ids.length} copied to your bank`).then(done)}>Copy to our bank</Btn>
              : <>
                <Btn size="sm" onClick={() => setModal({ kind: "move", ids, done })}>Move to folder</Btn>
                <Btn size="sm" kind="gold" onClick={() => run(() => api.post(`/qbank/questions/bulk?scope=${scope}`, { ids, action: "approved" }), "Approved").then(() => { done(); refresh(); })}>Approve</Btn>
                <Btn size="sm" onClick={() => { const t = prompt("Tag to add"); if (t) run(() => api.post(`/qbank/questions/bulk?scope=${scope}`, { ids, action: "tag", tag: t }), "Tagged").then(() => { done(); refresh(); }); }}>Add tag</Btn>
                <Btn size="sm" onClick={() => { const l = prompt("Set level (1–5)"); if (l) run(() => api.post(`/qbank/questions/bulk?scope=${scope}`, { ids, action: "level", level: +l }), "Level updated").then(() => { done(); refresh(); }); }}>Set level</Btn>
                <Btn size="sm" kind="danger" onClick={() => run(() => api.post(`/qbank/questions/bulk?scope=${scope}`, { ids, action: sel === "archived" ? "approved" : "archived" }), sel === "archived" ? "Restored" : "Archived").then(() => { done(); refresh(); })}>{sel === "archived" ? "Unarchive" : "Archive"}</Btn>
              </>}
            empty={<Empty title={sel === "pending" ? "Nothing waiting for approval" : "No questions here yet"} text={writable ? "Add one, ask Hira to draft some, or import a CSV." : ""} />}
            columns={qid ? COLS.filter((c) => ["text", "version", "status"].includes(c.key)) : COLS} />
        </section>
        {qid && <Drawer id={qid} scope={scope} folders={folders} onClose={() => setQid(null)} onChanged={refresh} canCopy={scope === "global" && !globalOnly} />}
      </div>

      {menu && <div className="modal-bg" style={{ background: "transparent" }} onMouseDown={() => setMenu(null)}>
        <div className="pop-menu" style={{ position: "fixed", left: Math.min(menu.x, window.innerWidth - 230), top: menu.y + 4, minWidth: 210, padding: 6 }} onMouseDown={(e) => e.stopPropagation()}>
          {[["sub", "New sub-folder"], ["rename", "Rename or describe"], ["move", "Move folder"], ["export", "Export as CSV"], ["delete", "Delete folder"]].map(([k, l]) =>
            <button key={k} className="btn ghost sm" style={{ width: "100%", justifyContent: "flex-start", color: k === "delete" ? "var(--bad)" : undefined }} onClick={() => folderAct(k, menu.f)}>{l}</button>)}
        </div></div>}

      {modal?.kind === "new" && <Modal wide title="New question" onClose={() => setModal(null)}>
        <QuestionForm init={{ folder_id: /^\d+$/.test(sel) ? +sel : "" }} folders={folders} busy={busy} saveLabel="Create question" onCancel={() => setModal(null)}
          onSave={(f) => run(() => api.post(`/qbank/questions?scope=${scope}`, f), "Question created").then((q) => { setModal(null); refresh(); setQid(q.id); })} />
      </Modal>}
      {modal?.kind === "hira" && <HiraDraft scope={scope} folders={folders} sel={sel} onClose={() => setModal(null)} onDone={(n, fid) => { setModal(null); refresh(); setSel("pending"); toast(`Hira drafted ${n} questions. They're waiting for your approval.`, "good"); }} />}
      {modal?.kind === "import" && <ImportCsv scope={scope} onClose={() => setModal(null)} onDone={() => refresh()} />}
      {modal?.kind === "folder" && <FolderModal scope={scope} m={modal} folders={folders} onClose={() => setModal(null)} onDone={() => { setModal(null); refresh(); }} />}
      {modal?.kind === "move" && <MoveModal folders={folders} title={`Move ${modal.ids.length} question${modal.ids.length > 1 ? "s" : ""}`} onClose={() => setModal(null)}
        onPick={(fid) => run(() => api.post(`/qbank/questions/bulk?scope=${scope}`, { ids: modal.ids, action: "move", folder_id: fid }), "Moved").then(() => { modal.done(); setModal(null); refresh(); })} />}
      {modal?.kind === "move-folder" && <MoveModal folders={folders.filter((f) => { const me = folders.find((x) => x.id === modal.f.id)?.label; return f.label !== me && !f.label.startsWith(me + " / "); })} title={`Move “${modal.f.name}” into…`} rootLabel="Top level" onClose={() => setModal(null)}
        onPick={(fid) => run(() => api.patch(`/qbank/folders/${modal.f.id}?scope=${scope}`, { parent_id: fid }), "Folder moved").then(() => { setModal(null); refresh(); })} />}
      {modal?.kind === "delete-folder" && <Confirm title={`Delete “${modal.f.name}”?`} danger yes="Delete folder" onClose={() => setModal(null)}
        text={`Its ${modal.f.total} question${modal.f.total === 1 ? "" : "s"} and any sub-folders move up one level. No questions are deleted.`}
        onYes={() => run(() => api.del(`/qbank/folders/${modal.f.id}?scope=${scope}`), "Folder deleted").then(() => { if (sel === String(modal.f.id)) setSel(""); refresh(); })} />}
    </div>
  );
}

function FolderModal({ scope, m, folders, onClose, onDone }) {
  const [name, setName] = useState(m.name || "");
  const [desc, setDesc] = useState(m.description || "");
  const [run, busy] = useAction();
  const parent = folders.find((f) => f.id === m.parent_id);
  return <Modal title={m.id ? "Rename folder" : parent ? `New folder inside “${parent.name}”` : "New folder"} onClose={onClose}
    footer={<Btn kind="primary" busy={busy} disabled={!name.trim()} onClick={() => run(() => m.id ? api.patch(`/qbank/folders/${m.id}?scope=${scope}`, { name, description: desc }) : api.post(`/qbank/folders?scope=${scope}`, { name, description: desc, parent_id: m.parent_id }), "Saved").then(onDone)}>Save</Btn>}>
    <Field label="Folder name"><Input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Senior Java screen, Campus 2026, Sales role-play" /></Field>
    <Field label="Description (optional)"><Input value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="Who uses it and when" /></Field>
  </Modal>;
}

function MoveModal({ folders, title, onPick, onClose, rootLabel = "No folder (unfiled)" }) {
  const [v, setV] = useState("");
  return <Modal title={title} onClose={onClose} footer={<Btn kind="primary" onClick={() => onPick(v ? +v : null)}>Move</Btn>}>
    <div className="col" style={{ gap: 2, maxHeight: 360, overflow: "auto" }}>
      <label className="check"><input type="radio" name="mv" checked={v === ""} onChange={() => setV("")} />{rootLabel}</label>
      {folders.map((f) => <label key={f.id} className="check" style={{ paddingLeft: f.depth * 18 }}><input type="radio" name="mv" checked={v === String(f.id)} onChange={() => setV(String(f.id))} />📁 {f.name}</label>)}
    </div>
  </Modal>;
}

function HiraDraft({ scope, folders, sel, onClose, onDone }) {
  const [g, setG] = useState({ skills: "", level: 3, n: 5, folder_id: /^\d+$/.test(sel) ? sel : "", tags: [] });
  const [run, busy] = useAction();
  return <Modal title="Ask Hira to draft questions" onClose={onClose} footer={<Btn kind="primary" busy={busy} disabled={!g.skills.trim()} onClick={() => run(() => api.post(`/qbank/questions/generate?scope=${scope}`, { ...g, skills: g.skills.split(",").map((s) => s.trim()).filter(Boolean), folder_id: g.folder_id || null })).then((r) => onDone(r.created, g.folder_id))}>Draft</Btn>}>
    <AgentNote agent="hira">Tell me the skills and level. I'll draft clear, single-answer questions with explanations. They wait as “pending” until someone approves them.</AgentNote>
    <Field label="Skills (comma separated)"><Input value={g.skills} onChange={(e) => setG({ ...g, skills: e.target.value })} placeholder="e.g. Kafka, Spring Boot" /></Field>
    <div className="grid g2"><Field label="Level"><Select value={String(g.level)} onChange={(v) => setG({ ...g, level: +v })} options={"12345".split("").map((l) => ({ value: l, label: "L" + l }))} /></Field>
      <Field label="How many (max 20)"><Input type="number" value={g.n} onChange={(e) => setG({ ...g, n: +e.target.value })} /></Field></div>
    <Field label="Put them in"><Select value={String(g.folder_id)} onChange={(v) => setG({ ...g, folder_id: v })} options={[{ value: "", label: "Unfiled" }, ...folders.map((f) => ({ value: String(f.id), label: f.label }))]} /></Field>
    <Field label="Tags (optional)"><ListEditor value={g.tags} onChange={(v) => setG({ ...g, tags: v })} /></Field>
  </Modal>;
}

function ImportCsv({ scope, onClose, onDone }) {
  const [text, setText] = useState("");
  const [res, setRes] = useState(null);
  const [run, busy] = useAction();
  return <Modal wide title="Import questions from CSV" onClose={onClose} footer={res ? <Btn kind="primary" onClick={onClose}>Done</Btn> : <Btn kind="primary" busy={busy} disabled={!text.trim()} onClick={() => run(() => api.post(`/qbank/questions/import?scope=${scope}`, { csv: text })).then((r) => { setRes(r); onDone(); })}>Import</Btn>}>
    {!res ? <>
      <p className="small">Columns: <span className="mono">folder, skill, level, question, code, A–F, answer, explanation, tags, status</span>. The folder can be a path like <span className="mono">Engineering / Backend / Java</span>; missing folders are created. Answer is a letter. Tags are separated by <span className="mono">;</span>. Rows without “approved” arrive as pending.</p>
      <div className="row"><Btn size="sm" onClick={() => download("/qbank/csv-template", "question-template.csv")}>Download template</Btn>
        <label className="btn sm">Choose file<input type="file" accept=".csv" hidden onChange={async (e) => { const f = e.target.files[0]; if (f) setText(await f.text()); }} /></label></div>
      <Textarea value={text} onChange={(e) => setText(e.target.value)} style={{ minHeight: 200, fontFamily: "ui-monospace, monospace", fontSize: 12 }} placeholder="…or paste the CSV here" data-allow-paste="1" />
    </> : <>
      <AgentNote agent="hira" title={`${res.created} question${res.created === 1 ? "" : "s"} imported`}>{res.problems.length ? "Some rows were skipped:" : "Every row was imported."}</AgentNote>
      {res.problems.map((p, i) => <div key={i} className="small" style={{ color: "var(--bad)" }}>• {p}</div>)}
    </>}
  </Modal>;
}
