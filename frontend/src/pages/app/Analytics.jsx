import { useState } from "react";
import { api, download } from "../../api";
import { useAuth } from "../../auth";
import DataTable from "../../components/DataTable";
import { Hira } from "../../components/Mascot";
import { PageHead } from "../../components/Shell";
import { Btn, Chip, Field, Input, Loading, ROUND_LABEL, Select, Seg, Tabs, useAction, useAsync, useToast } from "../../components/ui";

export function Bars({ rows, fmt = (v) => v, max }) {
  const m = max || Math.max(1, ...rows.map((r) => r.value));
  return (
    <div className="col" style={{ gap: 8 }}>
      {rows.map((r) => (
        <div key={r.label} className="row" style={{ gap: 10 }}>
          <span className="small" style={{ width: 150, textAlign: "right" }} title={r.label}>{r.label.replace(/_/g, " ")}</span>
          <div className="grow" style={{ background: "var(--soft)", borderRadius: 6, height: 22, position: "relative" }}>
            <div style={{ width: `${(100 * r.value) / m}%`, height: "100%", background: "var(--brand)", borderRadius: 6, transition: "width .5s", minWidth: r.value ? 4 : 0 }} />
          </div>
          <b className="small" style={{ width: 60 }}>{fmt(r.value)}</b>
        </div>
      ))}
    </div>
  );
}

export function Line({ rows, height = 200 }) {
  if (!rows.length) return null;
  const w = 600, pad = 30, max = Math.max(1, ...rows.map((r) => r.value));
  const pts = rows.map((r, i) => [pad + (i * (w - 2 * pad)) / Math.max(1, rows.length - 1), height - pad - ((height - 2 * pad) * r.value) / max]);
  return (
    <svg viewBox={`0 0 ${w} ${height}`} width="100%" role="img" aria-label="Line chart">
      <line x1={pad} y1={height - pad} x2={w - pad} y2={height - pad} stroke="var(--line-2)" />
      <polyline fill="none" stroke="var(--brand)" strokeWidth="3" points={pts.map((p) => p.join(",")).join(" ")} />
      {pts.map((p, i) => <g key={i}><circle cx={p[0]} cy={p[1]} r="4" fill="var(--brand)" /><text x={p[0]} y={height - 10} fontSize="11" textAnchor="middle" fill="var(--muted)">{rows[i].label}</text><text x={p[0]} y={p[1] - 8} fontSize="11" textAnchor="middle" fill="var(--ink)">{rows[i].value}</text></g>)}
    </svg>
  );
}

export default function Analytics() {
  const { can } = useAuth();
  const [tab, setTab] = useState("overview");
  const [days, setDays] = useState("90");
  return (
    <>
      <PageHead title="Analytics" sub="How hiring is going, which interviewers are calibrated, which questions work."
        actions={<><Seg value={days} onChange={setDays} options={[["30", "30 days"], ["90", "90 days"], ["365", "1 year"]]} />
          {can("export") && <><Btn onClick={() => download("/export/applications", "applications.csv")}>Export applications</Btn><Btn onClick={() => download("/export/reports", "reports.csv")}>Export reports</Btn></>}</>} />
      <Tabs value={tab} onChange={setTab} tabs={[["overview", "Overview"], ["interviewers", "Interviewer calibration"], ["questions", "Question quality"], ["builder", "Report builder"]]} />
      {tab === "overview" && <Overview days={days} />}
      {tab === "interviewers" && <Interviewers days={days} />}
      {tab === "questions" && <QuestionsQ days={days} />}
      {tab === "builder" && <Builder days={days} />}
    </>
  );
}

function Overview({ days }) {
  const { data } = useAsync(() => api.get("/analytics/overview", { days }), [days]);
  if (!data) return <Loading />;
  const t = data.totals;
  return (
    <>
      <div className="grid g4">
        {[["Applications", t.applications], ["Rounds sent", t.rounds], ["Rounds completed", t.completed], ["Reports to review", t.reports_pending], ["Hired", t.hired], ["Rejected", t.rejected],
          ["Rounds with warnings", t.integrity_rate + "%"], ["Avg hours to complete", t.avg_hours_to_complete]].map(([l, v]) => <div key={l} className="card stat"><div className="l">{l}</div><div className="v">{v}</div></div>)}
      </div>
      <div className="grid g2">
        <div className="card pad col"><h3>Funnel</h3><Bars rows={data.funnel.map((f) => ({ label: f.stage, value: f.count }))} /></div>
        <div className="card pad col"><h3>Average score by round type</h3>
          {data.by_round.length ? <Bars rows={data.by_round.map((r) => ({ label: ROUND_LABEL[r.type] || r.type, value: r.avg_pct }))} max={100} fmt={(v) => v + "%"} /> : <span className="muted">No completed rounds yet.</span>}</div>
      </div>
    </>
  );
}

function Interviewers({ days }) {
  const { data } = useAsync(() => api.get("/analytics/interviewers", { days }), [days]);
  if (!data) return <Loading />;
  return (
    <DataTable rows={data} defaultSort="interviews" columns={[
      { key: "name", label: "Interviewer", sort: "name", render: (r) => <b>{r.name}</b> }, { key: "interviews", label: "Interviews", sort: "interviews" },
      { key: "avg_score", label: "Average score", sort: "avg_score" }, { key: "vs_team", label: "vs team", sort: "vs_team", render: (r) => <Chip kind={Math.abs(r.vs_team) > .6 ? "warn" : ""}>{r.vs_team > 0 ? "+" : ""}{r.vs_team}</Chip> },
      { key: "ai_diff", label: "Difference from Isha", sort: "ai_diff", render: (r) => r.ai_diff == null ? "—" : <Chip kind={r.ai_diff < .75 ? "good" : r.ai_diff < 1.5 ? "warn" : "bad"}>{r.ai_diff}</Chip> },
      { key: "proceed_rate", label: "Proceed rate", sort: "proceed_rate", render: (r) => r.proceed_rate + "%" },
      { key: "flag", label: "Flag", render: (r) => r.flag ? <Chip kind="warn">{r.flag}</Chip> : "" }]} />
  );
}

function QuestionsQ({ days }) {
  const { data } = useAsync(() => api.get("/analytics/questions", { days }), [days]);
  if (!data) return <Loading />;
  return (
    <DataTable rows={data} defaultSort="asked" columns={[
      { key: "question", label: "Question", render: (r) => <span style={{ maxWidth: 560, display: "inline-block" }}>{r.question}</span> }, { key: "skill", label: "Skill" },
      { key: "asked", label: "Times asked", sort: "asked" }, { key: "correct_pct", label: "Answered correctly", sort: "correct_pct", render: (r) => r.correct_pct + "%" },
      { key: "flag", label: "Flag", render: (r) => r.flag ? <Chip kind="warn">{r.flag}</Chip> : "" }]} />
  );
}

function Builder({ days }) {
  const toast = useToast();
  const { data: sources } = useAsync(() => api.get("/analytics/sources"), []);
  const { data: saved, reload } = useAsync(() => api.get("/analytics/saved"), []);
  const [text, setText] = useState("");
  const [spec, setSpec] = useState({ source: "applications", group_by: "stage", measure: "count", chart: "bar" });
  const [res, setRes] = useState(null);
  const [name, setName] = useState("");
  const [run, busy] = useAction();
  const go = (s = spec) => run(() => api.post(`/analytics/run?days=${days}`, { spec: s })).then((r) => { setRes(r); setSpec({ ...s, ...r.spec }); });
  if (!sources) return <Loading />;
  const src = sources[spec.source];
  return (
    <div className="split">
      <div className="col" style={{ gap: 16 }}>
        <form className="agent hira" style={{ alignItems: "center" }} onSubmit={(e) => { e.preventDefault(); run(() => api.post(`/analytics/ask?days=${days}`, { text })).then((r) => { setRes(r); setSpec({ chart: "bar", ...r.spec }); }); }}>
          <Hira size={40} /><input className="input grow" value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask Hira: “average interview score by interviewer”, “applications by month”…" /><Btn kind="primary" type="submit" busy={busy}>Build</Btn>
        </form>
        <div className="card pad">
          {!res ? <div className="empty">Pick a source, a grouping and a measure, or ask Hira in plain words.</div> : !res.rows.length ? <div className="empty">No data for this report yet.</div> : (
            <>
              <div className="row" style={{ marginBottom: 12 }}><h3>{res.spec.name || `${res.spec.measure.replace(/_/g, " ")} by ${res.spec.group_by}`}</h3><span className="small muted right">{res.spec.source}</span></div>
              {spec.chart === "line" ? <Line rows={res.rows} /> : spec.chart === "table" ? (
                <table className="tbl"><thead><tr><th>{res.spec.group_by}</th><th>{res.spec.measure}</th><th>n</th></tr></thead><tbody>{res.rows.map((r) => <tr key={r.label}><td>{r.label}</td><td>{r.value}</td><td>{r.n}</td></tr>)}</tbody></table>
              ) : <Bars rows={res.rows} />}
            </>
          )}
        </div>
      </div>
      <div className="col" style={{ gap: 16 }}>
        <div className="card pad col">
          <h3>Build it yourself</h3>
          <Field label="Data"><Select value={spec.source} onChange={(v) => setSpec({ ...spec, source: v, group_by: sources[v].group_by[0], measure: "count" })} options={Object.keys(sources)} /></Field>
          <Field label="Group by"><Select value={spec.group_by} onChange={(v) => setSpec({ ...spec, group_by: v })} options={src.group_by} /></Field>
          <Field label="Measure"><Select value={spec.measure} onChange={(v) => setSpec({ ...spec, measure: v })} options={src.measures} /></Field>
          <Field label="Show as"><Seg value={spec.chart} onChange={(v) => setSpec({ ...spec, chart: v })} options={[["bar", "Bars"], ["line", "Line"], ["table", "Table"]]} /></Field>
          <Btn kind="primary" busy={busy} onClick={() => go()}>Run report</Btn>
          {res && <div className="row"><Input placeholder="Name this report" value={name} onChange={(e) => setName(e.target.value)} /><Btn onClick={() => run(() => api.post("/analytics/saved", { name: name || "Report", spec }), "Saved").then(() => { reload(); setName(""); })}>Save</Btn></div>}
        </div>
        <div className="card"><div className="card-h"><h3>Saved reports</h3></div>
          {(saved || []).map((s) => <div key={s.id} className="list-row"><button className="btn ghost sm grow" style={{ justifyContent: "flex-start" }} onClick={() => go(s.spec)}>{s.name}</button>
            <Btn size="sm" kind="ghost" onClick={() => api.del(`/analytics/saved/${s.id}`).then(() => { reload(); toast("Deleted"); })}>✕</Btn></div>)}
          {!saved?.length && <div className="empty small">None yet.</div>}
        </div>
      </div>
    </div>
  );
}
