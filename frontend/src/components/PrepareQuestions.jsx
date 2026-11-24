import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { Btn, Chip, Input, Loading, Modal, Select, useToast } from "./ui";

/**
 * V02.00.13: Prepare questions. Before a live interview with Isha, the interviewer picks the questions.
 * Isha proposes them in sections (one per skill or topic from the job description and the resume), each mixing
 * question types (basics, hands-on, scenario, real situation, own experience, design). How much of each type
 * depends on the candidate's level; the "How Isha mixes questions" card explains it.
 */
const SOURCE = {
  claude: ["good", "Written by Claude"],
  builtin: ["warn", "Built-in · Claude was unavailable"],
  bank: ["info", "From the question bank · Claude was unavailable"],
  own: ["brand", "Yours"],
};
const KIND_TONE = { intro: "isha", core: "brand", gap: "warn", claim: "info", domain: "", behaviour: "", own: "brand" };
const MIX_TYPES = ["basics", "hands_on", "scenario", "real_world", "experience", "design"];
const LEVEL_ORDER = ["fresher", "mid", "senior", "lead"];
const ordered = (levels) => LEVEL_ORDER.filter((k) => levels[k]).map((k) => [k, levels[k]]);

export function MixTable({ levels, types, level, onPick }) {
  // the percentage table, drawn as bars so the mix reads at a glance
  return (
    <div className="mix-card" aria-label="How Isha mixes questions by level">
      <div className="mix-h">
        <b>How Isha mixes questions</b>
        <span className="small muted">Share of the skill questions for each level. The Introduction and Working style are always included.</span>
      </div>
      <div className="mix-table" role="table">
        <div className="mix-row mix-head" role="row">
          <span role="columnheader">Level</span>
          {MIX_TYPES.map((t) => <span key={t} role="columnheader" title={types[t]?.meaning}>{types[t]?.label}</span>)}
        </div>
        {ordered(levels).map(([k, L]) => (
          <button type="button" key={k} role="row" className={"mix-row" + (k === level ? " on" : "")} onClick={() => onPick?.(k)}
            aria-pressed={k === level} title={onPick ? `Use the ${L.label} mix` : undefined}>
            <span role="cell" className="mix-level"><b>{L.label}</b><span className="tiny muted">{L.years}</span></span>
            {MIX_TYPES.map((t) => {
              const v = L.mix[t] || 0;
              return (
                <span role="cell" key={t} className="mix-cell">
                  <span className="mix-bar" aria-hidden><i style={{ width: `${Math.max(v ? 6 : 0, v * 2.4)}%` }} /></span>
                  <span className={"mix-pct" + (v ? "" : " zero")}>{v ? `${v}%` : "–"}</span>
                </span>
              );
            })}
          </button>
        ))}
      </div>
      {levels[level] && <div className="small mix-note"><b>{levels[level].label}:</b> {levels[level].note}</div>}
      <div className="mix-legend">{MIX_TYPES.map((t) => <span key={t} className="tiny"><b>{types[t]?.label}</b>: {types[t]?.meaning}</span>)}</div>
    </div>
  );
}

export default function PrepareQuestions({ attemptId, candidateName, onClose, onSaved }) {
  const toast = useToast();
  const [d, setD] = useState(null);
  const [sel, setSel] = useState([]);
  const [busy, setBusy] = useState("");
  const [open, setOpen] = useState({});
  const [own, setOwn] = useState("");
  const [ownSec, setOwnSec] = useState("own");
  const [showMix, setShowMix] = useState(true);
  const [dirty, setDirty] = useState(false);

  const load = (out) => { setD(out); setSel(out.prep?.selected || []); };
  useEffect(() => { api.get(`/isha/${attemptId}/prepare`).then(load).catch((e) => toast(e.message, "bad")); }, [attemptId]); // eslint-disable-line react-hooks/exhaustive-deps

  const prep = d?.prep || {};
  const qs = prep.questions || [];
  const byId = useMemo(() => Object.fromEntries(qs.map((q) => [q.id, q])), [qs]);
  const sections = prep.sections || [];
  const chosen = sel.map((i) => byId[i]).filter(Boolean);
  const total = chosen.reduce((a, q) => a + (q.minutes || 0), 0);
  const minutes = d?.summary?.minutes || 45;

  const post = async (payload, msg, key = "save") => {
    setBusy(key);
    try { const out = await api.post(`/isha/${attemptId}/prepare`, payload); load(out); setDirty(false); if (msg) toast(msg, "good"); return out; }
    catch (e) { toast(e.message, "bad"); return null; }
    finally { setBusy(""); }
  };
  const toggle = (id) => { setDirty(true); setSel((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id])); };
  const move = (i, dlt) => { setDirty(true); setSel((s) => { const x = [...s]; const [v] = x.splice(i, 1); x.splice(i + dlt, 0, v); return x; }); };
  const save = async () => { const out = await post({ selected: sel }, "Questions saved. Isha will follow them in the interview."); if (out) onSaved?.(out); };

  if (!d) return <Modal size="xl" title="Prepare questions" onClose={onClose}><Loading text="Isha is writing questions for this candidate…" /></Modal>;
  const locked = d.locked;
  const level = prep.level || "mid";
  const typeLabel = (t) => (t === "own" ? "Your question" : d.types[t]?.label || t);

  return (
    <Modal size="xl" dirty={dirty} title={`Prepare questions · ${candidateName}`} onClose={onClose}
      footer={<>
        <span className="small muted grow">{locked ? "The interview has started: the questions are set. Add or skip questions from the room." : "Isha listens during the interview and marks each question as you ask it. You don't need to press anything."}</span>
        <Btn onClick={onClose}>{locked ? "Close" : "Cancel"}</Btn>
        {!locked && <Btn kind="primary" busy={busy === "save"} disabled={!sel.length} onClick={save}>Save {sel.length} question{sel.length === 1 ? "" : "s"}</Btn>}
      </>}>
      <div className="prep-top">
        <div className="col" style={{ gap: 4 }}>
          <span className="small muted">Isha proposes questions in sections, one per skill or topic from the job and {candidateName.split(" ")[0]}'s resume. Tick the ones you want; their order is the interview's order.</span>
          <div className="row wrap" style={{ gap: 6 }}>
            <span className="small b">Candidate level</span>
            <div className="seg" role="radiogroup" aria-label="Candidate level">
              {ordered(d.levels).map(([k, L]) => <button type="button" key={k} role="radio" aria-checked={k === level} className={k === level ? "on" : ""} disabled={locked || !!busy}
                onClick={() => k !== level && post({ level: k }, `Questions rewritten for a ${L.label.toLowerCase()} candidate.`, "level")}>{L.label}</button>)}
            </div>
            {busy === "level" && <span className="row small muted" style={{ gap: 6 }}><span className="spin" style={{ width: 12, height: 12 }} /> Rewriting…</span>}
            <Chip kind={d.ai?.configured && prep.ai ? "good" : "warn"}>{d.ai?.configured ? (prep.ai ? "● Claude wrote these" : "● Claude unavailable: built-in questions") : "Claude isn't set up: built-in questions"}</Chip>
            <button type="button" className="linkbtn small" onClick={() => setShowMix(!showMix)} aria-expanded={showMix}>{showMix ? "Hide" : "Show"} how Isha mixes questions</button>
          </div>
        </div>
        {!locked && <div className="row" style={{ gap: 6 }}>
          <Btn size="sm" busy={busy === "reset"} onClick={() => post({ reset: true }, "Isha's picks restored.", "reset")}>Use Isha's picks</Btn>
          <Btn size="sm" kind="ghost" busy={busy === "all"} onClick={() => post({ refresh: "all", selected: sel }, "Unticked questions rewritten.", "all")}>Rewrite unticked</Btn>
        </div>}
      </div>
      {showMix && <MixTable levels={d.levels} types={d.types} level={level} onPick={locked ? null : (k) => k !== level && post({ level: k }, `Questions rewritten for a ${d.levels[k].label.toLowerCase()} candidate.`, "level")} />}

      <div className="prep-grid">
        <section className="col" style={{ gap: 10, minWidth: 0 }} aria-label="Isha's proposals">
          {sections.map((s) => {
            const mine = qs.filter((q) => q.section === s.key);
            if (!mine.length) return null;
            const n = mine.filter((q) => sel.includes(q.id)).length;
            const collapsed = open[s.key] === false;
            const kind = d.kinds[s.kind] || {};
            return (
              <div key={s.key} className="prep-sec card">
                <div className="prep-sec-h">
                  <button type="button" className="linkbtn" aria-expanded={!collapsed} onClick={() => setOpen({ ...open, [s.key]: collapsed })}>{collapsed ? "▸" : "▾"}</button>
                  <b className="ell">{s.name}</b>
                  {s.kind !== "intro" && <Chip kind={KIND_TONE[s.kind]} title={kind.meaning}>{kind.label}</Chip>}
                  {s.must && <Chip kind="bad">Must-have</Chip>}
                  {s.years ? <Chip>{s.years} yrs on resume</Chip> : null}
                  {s.verified && <Chip kind="good" title="Proven in an earlier round or a verified skill: Isha skips the basics">Already proven</Chip>}
                  <span className="grow" />
                  <span className="small muted">{n} chosen</span>
                  {!locked && !["own", "intro"].includes(s.kind) && <Btn size="sm" kind="ghost" busy={busy === s.key} onClick={() => post({ refresh: s.key, selected: sel }, `${s.name}: unticked questions rewritten.`, s.key)}>Rewrite</Btn>}
                </div>
                {kind.meaning && !collapsed && <div className="tiny muted" style={{ padding: "0 14px 6px" }}>{kind.meaning}{(s.probe || []).length ? ` · Probe from earlier rounds: ${s.probe.join("; ")}` : ""}</div>}
                {!collapsed && mine.map((q) => {
                  const on = sel.includes(q.id);
                  const src = SOURCE[q.source] || SOURCE.builtin;
                  return (
                    <label key={q.id} className={"prep-q" + (on ? " on" : "")}>
                      <input type="checkbox" checked={on} disabled={locked} onChange={() => toggle(q.id)} />
                      <div className="col" style={{ gap: 4, minWidth: 0 }}>
                        <span className="row wrap" style={{ gap: 6 }}>
                          <Chip kind="brand" title={d.types[q.type]?.meaning}>{typeLabel(q.type)}</Chip>
                          <Chip>~{q.minutes || 5} min</Chip>
                          <Chip kind={src[0]}>{src[1]}</Chip>
                        </span>
                        <span className="prep-qt">“{q.q}”</span>
                        {(q.good || []).length > 0 && <span className="tiny muted">Good answer: {q.good.join(" · ")}</span>}
                        {(q.followups || []).length > 0 && <span className="tiny muted">{q.followups.length} prepared follow-ups, used if Claude goes down</span>}
                      </div>
                    </label>
                  );
                })}
              </div>
            );
          })}
          {!locked && <form className="card pad row wrap" style={{ gap: 8 }} onSubmit={(e) => { e.preventDefault(); if (own.trim()) post({ add: { q: own, section: ownSec }, selected: sel }, "Your question was added.", "add").then((o) => o && setOwn("")); }}>
            <Input style={{ flex: "1 1 320px" }} value={own} onChange={(e) => setOwn(e.target.value)} placeholder="Add your own question" aria-label="Your own question" maxLength={400} />
            <Select value={ownSec} onChange={setOwnSec} aria-label="Section for your question"
              options={[{ value: "own", label: "Your questions" }, ...sections.filter((s) => !["own", "intro"].includes(s.kind)).map((s) => ({ value: s.key, label: s.name }))]} />
            <Btn type="submit" busy={busy === "add"} disabled={own.trim().length < 8}>Add</Btn>
          </form>}
        </section>

        <aside className="prep-side card" aria-label="Your questions">
          <div className="prep-side-h">
            <div className="row"><b>Your questions · {chosen.length}</b><span className="grow" /><Chip kind={total <= minutes ? "good" : "bad"}>≈ {total} of {minutes} min</Chip></div>
            <div className={"bar " + (total <= minutes ? "good" : "bad")}><i style={{ width: `${Math.min(100, (100 * total) / Math.max(1, minutes))}%` }} /></div>
          </div>
          <div className="col" style={{ gap: 6, padding: 10, overflow: "auto", minHeight: 0, flex: 1 }}>
            {!chosen.length && <div className="empty small">Tick questions on the left. The Introduction opens the interview.</div>}
            {chosen.map((q, i) => {
              const s = sections.find((x) => x.key === q.section) || {};
              return (
                <div key={q.id} className="prep-chosen">
                  <span className="num">{i + 1}</span>
                  <div className="col grow" style={{ gap: 0, minWidth: 0 }}>
                    <b className="small ell" title={q.q}>{s.kind === "intro" ? "Introduction" : s.name}</b>
                    <span className="tiny muted">{typeLabel(q.type)} · {q.minutes || 5} min{q.source === "builtin" ? " · built-in" : ""}</span>
                  </div>
                  {!locked && <>
                    <Btn size="sm" kind="ghost" aria-label={`Move question ${i + 1} up`} disabled={i === 0} onClick={() => move(i, -1)}>↑</Btn>
                    <Btn size="sm" kind="ghost" aria-label={`Move question ${i + 1} down`} disabled={i === chosen.length - 1} onClick={() => move(i, 1)}>↓</Btn>
                    <Btn size="sm" kind="ghost" aria-label={`Remove question ${i + 1}`} onClick={() => toggle(q.id)}>✕</Btn>
                  </>}
                </div>
              );
            })}
            <div className="tiny muted" style={{ padding: "4px 2px" }}>A Wrap-up (“What questions do you have for us?”) is added at the end.</div>
          </div>
          <div className="prep-checks">
            <span className="tiny b muted">CHECKS</span>
            {(dirty ? [{ ok: total <= minutes, text: `About ${total} of ${minutes} minutes` }, { ok: true, text: "Save to re-run every check" }] : d.summary.checks).map((c, i) => (
              <span key={i} className="small row" style={{ gap: 6, alignItems: "flex-start" }}><span style={{ color: c.ok ? "var(--good)" : "var(--warn)" }} aria-hidden>{c.ok ? "✓" : "!"}</span>{c.text}</span>
            ))}
          </div>
        </aside>
      </div>
    </Modal>
  );
}
