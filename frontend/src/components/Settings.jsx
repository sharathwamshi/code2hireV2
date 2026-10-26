import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { speak, stopSpeaking } from "../lib/speech";
import { Btn, Chip, Input, ListEditor, Loading, Select, Switch, useToast } from "./ui";

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

function Editor({ row, onSave }) {
  const [val, setVal] = useState(row.value);
  useEffect(() => setVal(row.value), [row.value]);
  const dirty = JSON.stringify(val) !== JSON.stringify(row.value);
  const dis = !row.editable;
  const save = (v = val) => onSave(row.key, v);
  let input;
  if (row.type === "bool") input = <Switch on={!!val} disabled={dis} label={row.label} onChange={(v) => { setVal(v); save(v); }} />;
  else if (row.type === "select") input = <div style={{ width: 220 }}><Select disabled={dis} value={String(val)} onChange={(v) => { const x = typeof row.default === "number" ? +v : v; setVal(x); save(x); }} options={row.options.map(String)} /></div>;
  else if (row.type === "int") input = <div className="row"><div style={{ width: 110 }}><Input type="number" disabled={dis} value={val ?? ""} onChange={(e) => setVal(e.target.value === "" ? "" : +e.target.value)} /></div>{dirty && <Btn size="sm" kind="primary" onClick={() => save()}>Save</Btn>}</div>;
  else if (row.type === "voice") input = <VoiceSelect disabled={dis} value={val} onChange={(v) => { setVal(v); save(v); }} />;
  else if (row.type === "voices") input = <VoicesMulti disabled={dis} value={val || []} onChange={(v) => { setVal(v); save(v); }} />;
  else if (row.type === "list") input = <div className="row" style={{ alignItems: "flex-start" }}><div style={{ minWidth: 280 }}><ListEditor value={val || []} onChange={setVal} /></div>{dirty && <Btn size="sm" kind="primary" onClick={() => save()}>Save</Btn>}</div>;
  else if (row.type === "color") input = <div className="row"><input type="color" disabled={dis} value={val} onChange={(e) => setVal(e.target.value)} />{dirty && <Btn size="sm" kind="primary" onClick={() => save()}>Save</Btn>}</div>;
  else input = <div className="row"><div style={{ minWidth: 280 }}><Input disabled={dis} value={val ?? ""} onChange={(e) => setVal(e.target.value)} /></div>{dirty && <Btn size="sm" kind="primary" onClick={() => save()}>Save</Btn>}</div>;
  return input;
}

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
    } catch (e) { toast(e.message, "bad"); }
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
                <td style={{ maxWidth: 320 }}><div className="b">{r.label}</div><div className="tiny faint mono">{r.key}</div></td>
                <td><Editor row={r} onSave={(k, v) => doSave(k, v, { locked: r.locked_here })} /></td>
                <td>
                  <Chip kind={SOURCE[r.source]?.[1]}>{SOURCE[r.source]?.[0] || r.source}</Chip>
                  {r.locked_at && <div className="tiny" style={{ color: "var(--bad)", marginTop: 4 }}>🔒 Locked at {r.locked_at} level</div>}
                </td>
                {allowLock && <td>{r.editable && <label className="check small"><input type="checkbox" checked={r.locked_here} onChange={(e) => doSave(r.key, r.value, { locked: e.target.checked })} />Lock</label>}</td>}
                <td>{r.overridden_here && r.editable && <Btn size="sm" kind="ghost" onClick={() => doSave(r.key, null, { reset: true })}>Reset</Btn>}</td>
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
