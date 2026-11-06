import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { speak, stopSpeaking } from "../lib/speech";
import { FolderPicker } from "./QuestionBank";
import { Btn, Chip, Input, ListEditor, Loading, Modal, Select, Switch, Textarea, useToast } from "./ui";

let voiceCache = null;
export function useVoices() {
  const [v, setV] = useState(voiceCache);
  useEffect(() => { if (!voiceCache) api.get("/speech/voices").then((d) => { voiceCache = d; setV(d); }).catch(() => {}); }, []);
  return v;
}

const SAMPLE = "Hello, I'm Hira. Take a moment, and tell me about a project you're proud of.";

export function VoicePreview({ voice, rate }) {
  const [on, setOn] = useState(false);
  return (
    <Btn size="sm" kind="ghost" aria-label={`Preview ${voice}`} onClick={async () => {
      if (on) { stopSpeaking(); setOn(false); return; }
      setOn(true); await speak(SAMPLE, { voice, rate }); setOn(false);
    }}>{on ? "■ Stop" : "▶ Hear"}</Btn>
  );
}

export function VoiceSelect({ value, onChange, disabled, only }) {
  const v = useVoices();
  if (!v) return <span className="spin" />;
  const rows = v.voices.filter((x) => !only || only.includes(x.name));
  return (
    <div className="row" style={{ minWidth: 300 }}>
      <Select disabled={disabled} value={value} onChange={onChange}
        options={rows.map((x) => ({ value: x.name, label: `${x.label} · ${x.gender || ""} · ${x.style || x.locale}` }))} />
      <VoicePreview voice={value} />
    </div>
  );
}

export function VoicesMulti({ value = [], onChange, disabled }) {
  const v = useVoices();
  if (!v) return <span className="spin" />;
  const byLocale = {};
  v.voices.forEach((x) => (byLocale[x.locale] ||= []).push(x));
  return (
    <div className="col" style={{ gap: 6 }}>
      {Object.entries(byLocale).map(([loc, list]) => (
        <div key={loc} className="row wrap" style={{ gap: 6 }}>
          <span className="tiny b muted" style={{ width: 48 }}>{loc}</span>
          {list.map((x) => {
            const on = value.includes(x.name);
            return (
              <span key={x.name} className={"chip " + (on ? "brand" : "")} style={{ cursor: disabled ? "default" : "pointer" }}>
                <label className="check" style={{ gap: 4 }}>
                  <input type="checkbox" disabled={disabled} checked={on} onChange={() => onChange(on ? value.filter((n) => n !== x.name) : [...value, x.name])} />
                  {x.label}
                </label>
                <VoicePreview voice={x.name} />
              </span>
            );
          })}
        </div>
      ))}
      {!v.azure && <span className="tiny muted">Azure Speech isn't connected yet, so previews use your browser's voice. Add the key in Platform settings.</span>}
    </div>
  );
}

/** Same limits as the server (services/settings.py RANGES etc.), so a bad value is caught while typing. */
export function settingError(m, v) {
  if (!m) return "";
  if (m.type === "int") {
    if (v === "" || v == null) return "Enter a number.";
    const n = Number(v);
    if (!Number.isInteger(n)) return "Use a whole number.";
    if (m.min != null && (n < m.min || n > m.max)) return `Use ${m.min} to ${m.max}${m.unit === "%" ? "%" : " " + m.unit}.`;
  }
  if (m.type === "list" && Array.isArray(v)) {
    if (m.max_items && v.length > m.max_items) return `At most ${m.max_items} items.`;
    if (m.max_length && v.some((x) => String(x).length > m.max_length)) return `Each item can be at most ${m.max_length} characters.`;
  }
  if (m.type === "text" && m.max_length && String(v || "").length > m.max_length) return `At most ${m.max_length} characters.`;
  return "";
}

export const rangeHint = (m) => (m?.min != null ? `${m.min} to ${m.max}${m.unit === "%" ? "%" : " " + m.unit}` : "");

/** One input for one setting, drawn from its metadata. Used by the settings table and the round editor. */
export function SettingInput({ m, value, onChange, onCommit, disabled, error }) {
  const commit = (v) => { onChange(v); onCommit?.(v); };
  if (m.type === "bool") return <Switch on={!!value} disabled={disabled} label={m.label} onChange={commit} />;
  if (m.type === "select") return <div style={{ width: 220 }}><Select disabled={disabled} value={String(value)} onChange={(v) => commit(typeof m.default === "number" ? +v : v)} options={m.options.map(String)} /></div>;
  if (m.type === "voice") return <VoiceSelect disabled={disabled} value={value} onChange={commit} />;
  if (m.type === "folders") return <FolderPicker disabled={disabled} value={value || []} onChange={commit} />;
  if (m.type === "voices") return <VoicesMulti disabled={disabled} value={value || []} onChange={commit} />;
  if (m.key === "f2f.own_questions") return <QuestionList value={value || []} onChange={onChange} disabled={disabled} max={m.max_items} />;
  if (m.type === "list") return <div style={{ minWidth: 280 }}><ListEditor value={value || []} onChange={onChange} max={m.max_items} /></div>;
  if (m.type === "color") return <input type="color" disabled={disabled} value={value} onChange={(e) => onChange(e.target.value)} aria-label={m.label} />;
  if (m.type === "int") return (
    <div className="row" style={{ gap: 8 }}>
      <div style={{ width: 110 }}><Input type="number" inputMode="numeric" step={1} min={m.min} max={m.max} disabled={disabled} value={value ?? ""} aria-invalid={error ? true : undefined}
        aria-label={m.label} onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))} onKeyDown={(e) => { if (["e", "E", "+", "."].includes(e.key)) e.preventDefault(); }} /></div>
      {m.min != null && <span className="tiny muted">{rangeHint(m)}</span>}
    </div>
  );
  if (m.type === "text" && (m.max_length || 0) > 400) return (
    <div className="col" style={{ minWidth: 320, gap: 4 }}><Textarea disabled={disabled} maxLength={m.max_length} value={value ?? ""} onChange={(e) => onChange(e.target.value)} aria-label={m.label} style={{ minHeight: 90 }} />
      <span className="tiny muted">{String(value || "").length} of {m.max_length} characters</span></div>);
  return <div style={{ minWidth: 280 }}><Input disabled={disabled} maxLength={m.max_length} value={value ?? ""} onChange={(e) => onChange(e.target.value)} aria-label={m.label} /></div>;
}

/** An ordered list of the interviewer's own questions: type one, or pick from the question bank; move up/down; remove. */
export function QuestionList({ value = [], onChange, max = 30, disabled }) {
  const [t, setT] = useState("");
  const [note, setNote] = useState("");
  const [pick, setPick] = useState(false);
  const add = (raw) => {
    const q = String(raw || "").trim().replace(/\s+/g, " ");
    if (!q) return;
    if (q.length > 300) { setNote("A question can be at most 300 characters."); return; }
    if (value.some((v) => v.toLowerCase() === q.toLowerCase())) { setNote("That question is already in the list."); return; }
    if (value.length >= max) { setNote(`At most ${max} questions.`); return; }
    onChange([...value, q]); setT(""); setNote("");
  };
  const move = (i, d) => { const n = [...value]; const [x] = n.splice(i, 1); n.splice(i + d, 0, x); onChange(n); };
  return (
    <div className="col" style={{ gap: 6, minWidth: 300 }}>
      {value.length > 0 && <ol className="qlist">{value.map((q, i) => (
        <li key={q}><span className="grow">{q}</span>
          <span className="row" style={{ gap: 2 }}>
            <Btn size="sm" kind="ghost" disabled={disabled || i === 0} aria-label="Move up" onClick={() => move(i, -1)}>↑</Btn>
            <Btn size="sm" kind="ghost" disabled={disabled || i === value.length - 1} aria-label="Move down" onClick={() => move(i, 1)}>↓</Btn>
            <Btn size="sm" kind="ghost" disabled={disabled} aria-label={"Remove question " + (i + 1)} onClick={() => onChange(value.filter((_, j) => j !== i))}>×</Btn>
          </span></li>))}</ol>}
      {!disabled && <div className="row" style={{ alignItems: "flex-start" }}>
        <div className="grow"><Textarea rows={2} maxLength={300} value={t} placeholder="Type a question and press Enter" aria-label="New question"
          onChange={(e) => { setT(e.target.value); setNote(""); }} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); add(t); } }} /></div>
        <div className="col" style={{ gap: 4 }}><Btn size="sm" disabled={!t.trim()} onClick={() => add(t)}>Add</Btn><Btn size="sm" kind="ghost" onClick={() => setPick(true)}>From bank…</Btn></div>
      </div>}
      <span className="tiny muted">{note || `${value.length} of at most ${max}. Asked first, in this order.`}</span>
      {pick && <BankPicker onClose={() => setPick(false)} onPick={(qs) => { const n = [...value]; qs.forEach((q) => { if (n.length < max && !n.some((v) => v.toLowerCase() === q.toLowerCase())) n.push(q); }); onChange(n); setPick(false); }} />}
    </div>
  );
}

function BankPicker({ onClose, onPick }) {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState(null);
  const [sel, setSel] = useState([]);
  useEffect(() => { const t = setTimeout(() => api.get("/qbank/questions", { q, size: 30, status: "approved" }).then((d) => setRows(d.rows || d)).catch(() => setRows([])), 250); return () => clearTimeout(t); }, [q]);
  return (
    <Modal title="Pick from the question bank" onClose={onClose} footer={<><Btn onClick={onClose}>Cancel</Btn><Btn kind="primary" disabled={!sel.length} onClick={() => onPick(sel)}>Add {sel.length || ""} question{sel.length === 1 ? "" : "s"}</Btn></>}>
      <Input placeholder="Search questions or skills…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search questions" />
      {!rows ? <Loading /> : rows.length === 0 ? <p className="small muted">No questions found.</p> : (
        <div className="col" style={{ gap: 4, maxHeight: 360, overflow: "auto" }}>{rows.map((r) => (
          <label key={r.id} className="check small" style={{ alignItems: "flex-start" }}><input type="checkbox" checked={sel.includes(r.text)} onChange={(e) => setSel(e.target.checked ? [...sel, r.text] : sel.filter((x) => x !== r.text))} />
            <span><span className="chip">{r.skill || "General"}</span> {r.text}</span></label>))}</div>)}
    </Modal>
  );
}

const INSTANT = ["bool", "select", "voice", "folders", "voices"];

function Editor({ row, onSave }) {
  const [val, setVal] = useState(row.value);
  const [srvErr, setSrvErr] = useState("");
  useEffect(() => { setVal(row.value); setSrvErr(""); }, [row.value]);
  const dirty = JSON.stringify(val) !== JSON.stringify(row.value);
  const localErr = dirty ? settingError(row, val) : "";
  const error = localErr || srvErr;
  const save = async (v = val) => { if (settingError(row, v)) return; const e = await onSave(row.key, v); setSrvErr(e || ""); };
  return (
    <div className="col" style={{ gap: 4 }}>
      <div className="row" style={{ alignItems: "flex-start" }}>
        <SettingInput m={row} value={val} disabled={!row.editable} error={error} onChange={(v) => { setVal(v); setSrvErr(""); }} onCommit={INSTANT.includes(row.type) ? save : undefined} />
        {dirty && !INSTANT.includes(row.type) && <><Btn size="sm" kind="primary" disabled={!!localErr} onClick={() => save()}>Save</Btn><Btn size="sm" kind="ghost" onClick={() => setVal(row.value)}>Cancel</Btn></>}
      </div>
      {error && <span className="tiny" role="alert" style={{ color: "var(--bad)" }}>{error}</span>}
    </div>
  );
}

const fmtDefault = (r) => (Array.isArray(r.default) ? (r.default.length ? r.default.join(", ") : "none") : typeof r.default === "boolean" ? (r.default ? "On" : "Off") : `${r.default ?? "—"}${r.unit === "%" ? "%" : ""}`);

const SOURCE = { default: ["Default", ""], platform: ["Platform", "info"], company: ["Company", "brand"], team: ["Team", "gold"], job: ["Job", "good"], round: ["Round", "good"] };

/**
 * The inheritance editor. load() returns rows from the API; save(key, value, {locked, reset}) persists.
 * Every row shows where its value comes from and whether a level above locked it.
 */
export default function SettingsEditor({ load, save, level, allowLock = true, groups }) {
  const [rows, setRows] = useState(null);
  const [q, setQ] = useState("");
  const [group, setGroup] = useState("All");
  const toast = useToast();
  useEffect(() => { load().then(setRows).catch((e) => toast(e.message, "bad")); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const allGroups = useMemo(() => ["All", ...new Set((rows || []).map((r) => r.group))].filter((g) => !groups || g === "All" || groups.includes(g)), [rows, groups]);
  if (!rows) return <Loading />;
  const doSave = async (key, value, extra = {}) => {
    try {
      const r = await save(key, value, extra);
      setRows(r); toast(extra.reset ? "Reset to inherited value" : "Saved", "good");
      return "";
    } catch (e) { toast(e.message, "bad"); return e.message; }
  };
  const shown = rows.filter((r) => (!groups || groups.includes(r.group)) && (group === "All" || r.group === group) &&
    (!q || (r.label + r.key).toLowerCase().includes(q.toLowerCase())));
  return (
    <div className="card">
      <div className="tbl-bar">
        <label className="search" style={{ flex: "1 1 240px", maxWidth: 360 }}><input placeholder="Find a setting…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Find a setting" /></label>
        <div className="seg" style={{ flexWrap: "wrap" }}>{allGroups.map((g) => <button key={g} className={g === group ? "on" : ""} onClick={() => setGroup(g)}>{g}</button>)}</div>
      </div>
      <div className="tbl-wrap">
        <table className="tbl">
          <thead><tr><th>Setting</th><th>Value at this level</th><th>Comes from</th>{allowLock && <th>Lock below</th>}<th /></tr></thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.key}>
                <td style={{ maxWidth: 320 }}><div className="b">{r.label}</div><div className="tiny faint">Default: {fmtDefault(r)}</div></td>
                <td><Editor row={r} onSave={(k, v) => doSave(k, v, { locked: r.locked_here })} /></td>
                <td>
                  <Chip kind={SOURCE[r.source]?.[1]}>{r.overridden_here ? "Set here" : (SOURCE[r.source]?.[0] || r.source)}</Chip>
                  {r.locked_at && <div className="tiny" style={{ color: "var(--bad)", marginTop: 4 }}>🔒 Locked at {r.locked_at} level</div>}
                </td>
                {allowLock && <td>{r.editable && <label className="check small"><input type="checkbox" checked={r.locked_here} onChange={(e) => doSave(r.key, r.value, { locked: e.target.checked })} />Lock</label>}</td>}
                <td>{r.overridden_here && r.editable && <Btn size="sm" kind="ghost" title="Remove the value set here and use the one from the level above" onClick={() => doSave(r.key, null, { reset: true })}>Reset to inherited</Btn>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function companySettings(scope, id) {
  return {
    load: () => api.get("/company/settings", { scope, id }),
    save: (key, value, extra) => api.put("/company/settings", { scope, id, key, value, ...extra }),
    level: scope,
  };
}
export const platformSettings = {
  load: () => api.get("/platform/settings"),
  save: (key, value, extra) => api.put("/platform/settings", { key, value, ...extra }),
  level: "platform",
};
