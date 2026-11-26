/** V02.01.08: Teams: how many interviews each person has taken. Company admins only.
 * The summary (tiles, top interviewers, interviews by week, upcoming, interviews by person) and one person's page. */
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, download } from "../../api";
import { PageHead } from "../../components/Shell";
import { Avatar, Btn, Chip, Empty, ErrorBox, Input, Loading, Select, useAsync, useToast } from "../../components/ui";

const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function presets() {
  const t = new Date();
  const m0 = new Date(t.getFullYear(), t.getMonth(), 1), m1 = new Date(t.getFullYear(), t.getMonth() + 1, 0);
  const l0 = new Date(t.getFullYear(), t.getMonth() - 1, 1), l1 = new Date(t.getFullYear(), t.getMonth(), 0);
  const q0 = new Date(t.getFullYear(), t.getMonth() - 2, 1);
  const lab = (a, b) => `${a.getDate()}–${b.getDate()} ${MONTHS[b.getMonth()]} ${b.getFullYear()}`;
  return {
    this: { label: `This month: ${lab(m0, m1)}`, from: iso(m0), to: iso(m1) },
    last: { label: `Last month: ${lab(l0, l1)}`, from: iso(l0), to: iso(l1) },
    q: { label: `Last 3 months: ${q0.getDate()} ${MONTHS[q0.getMonth()]} – ${m1.getDate()} ${MONTHS[m1.getMonth()]}`, from: iso(q0), to: iso(m1) },
  };
}

/** The period picker, kept in the address bar so Back and a shared link keep it. */
function usePeriod() {
  const P = useMemo(presets, []);
  const q = new URLSearchParams(window.location.search);
  const known = Object.keys(P).find((k) => P[k].from === q.get("from") && P[k].to === q.get("to"));
  const [key, setKey] = useState(q.get("from") ? (known || "custom") : "this");
  const [custom, setCustom] = useState({ from: q.get("from") || P.this.from, to: q.get("to") || P.this.to });
  const range = key === "custom" ? custom : P[key];
  const set = (k) => { setKey(k); if (k !== "custom") window.history.replaceState(null, "", `${window.location.pathname}?from=${P[k].from}&to=${P[k].to}`); };
  const setC = (c) => { setCustom(c); window.history.replaceState(null, "", `${window.location.pathname}?from=${c.from}&to=${c.to}`); };
  const picker = (
    <div className="row wrap" style={{ gap: 8 }}>
      <Select aria-label="Period" value={key} onChange={set} style={{ width: "auto", minWidth: 250 }}
        options={[{ value: "this", label: P.this.label }, { value: "last", label: P.last.label }, { value: "q", label: P.q.label }, { value: "custom", label: "Custom dates…" }]} />
      {key === "custom" && <>
        <Input type="date" aria-label="From" value={custom.from} onChange={(e) => setC({ ...custom, from: e.target.value })} style={{ width: 160 }} />
        <Input type="date" aria-label="To" value={custom.to} onChange={(e) => setC({ ...custom, to: e.target.value })} style={{ width: 160 }} />
      </>}
    </div>);
  return { range, picker, qs: `from=${range.from}&to=${range.to}` };
}

const Tile = ({ label, value, tone }) => (
  <div className="card tm-tile"><span className="tm-tile-l">{label}</span><b className={"tm-tile-v " + (tone || "")}>{value ?? "—"}</b></div>);
const mins = (m) => (m == null ? "—" : `${m} min`);
const RESULT_TONE = { Proceed: "good", Hold: "warn", Reject: "bad", "Feedback pending": "warn" };
const STATUS_TONE = { Upcoming: "info", Completed: "good", "Closed early": "warn", Cancelled: "bad", "In progress": "brand" };

export function Teams() {
  const { range, picker, qs } = usePeriod();
  const { data, error, reload, loading } = useAsync(() => api.get(`/teams?${qs}`), [qs]);
  const toast = useToast();
  const nav = useNavigate();
  const exportCsv = () => download(`/teams/export.csv?${qs}`, `interviews-${range.from}-to-${range.to}.csv`).catch((e) => toast(e.message, "bad"));
  const head = <PageHead title="Teams" sub="See how many interviews each person has taken."
    actions={<div className="row wrap" style={{ gap: 8 }}>{picker}<Btn kind="primary" onClick={exportCsv}>Export CSV</Btn></div>} />;
  if (error) return <>{head}<ErrorBox error={error} onRetry={reload} /></>;
  if (!data || loading) return <>{head}<Loading /></>;
  const t = data.tiles;
  const maxTop = Math.max(1, ...data.top.map((x) => x.completed));
  const maxWeek = Math.max(1, ...data.weeks.map((w) => w.count));
  const any = data.people.some((p) => p.total);
  return (
    <>
      {head}
      <div className="tm-tiles">
        <Tile label="Interviewers" value={t.interviewers} /><Tile label="Interviews taken" value={t.taken} /><Tile label="Upcoming" value={t.upcoming} />
        <Tile label="Cancelled" value={t.cancelled} /><Tile label="Feedback pending" value={t.pending} tone={t.pending ? "warn" : ""} />
      </div>
      {!any ? <div className="card pad"><Empty title="No interviews in this period" text="When interviewers take live interviews, they'll show here: who took how many, what's coming up, and whose feedback is pending." /></div> : <>
        <div className="tm-panels">
          <section className="card pad col" style={{ gap: 14 }} aria-label="Top interviewers">
            <div className="row"><h3 className="grow" style={{ margin: 0 }}>Top interviewers</h3><span className="tiny muted">Completed</span></div>
            {data.top.length ? data.top.map((x, i) => (
              <button key={x.id} type="button" className="tm-top" onClick={() => nav(`/app/teams/${x.id}?${qs}`)}>
                <span className="tm-rank">{i + 1}</span><Avatar name={x.name} />
                <span className="col grow" style={{ gap: 6, minWidth: 0 }}>
                  <span className="row"><b className="grow ell">{x.name}</b><b>{x.completed}</b></span>
                  <span className="tm-bar"><i style={{ width: `${(100 * x.completed) / maxTop}%` }} /></span>
                </span>
              </button>)) : <span className="small muted">No completed interviews yet.</span>}
          </section>
          <section className="card pad col" style={{ gap: 10 }} aria-label="Interviews taken by week">
            <div className="row"><h3 className="grow" style={{ margin: 0 }}>Interviews taken by week</h3><span className="tiny muted">Completed</span></div>
            <div className="tm-weeks" role="list">
              {data.weeks.map((w) => (
                <div key={w.label} className="tm-week" role="listitem" aria-label={`${w.label}: ${w.count} completed`}>
                  <b>{w.count}</b><i style={{ height: `${Math.max(4, (100 * w.count) / maxWeek)}%` }} /><span className="tiny muted">{w.label}</span>
                </div>))}
            </div>
          </section>
          <section className="card pad col" style={{ gap: 4 }} aria-label="Upcoming interviews">
            <div className="row"><h3 className="grow" style={{ margin: 0 }}>Upcoming interviews</h3><span className="tiny muted">{data.upcoming.of ? `Next ${data.upcoming.items.length} of ${data.upcoming.of}` : ""}</span></div>
            {data.upcoming.items.length ? data.upcoming.items.map((u, i) => (
              <div key={i} className="tm-up">
                <div className="col grow" style={{ gap: 2 }}>
                  {u.application_id ? <Link to={`/app/applications/${u.application_id}`} className="b">{u.candidate}</Link> : <b>{u.candidate}</b>}
                  <span className="tiny muted">with {u.with}</span>
                </div>
                <div className="col" style={{ gap: 2, alignItems: "flex-end" }}><b className="tm-date">{u.date}</b>{u.time && <span className="tiny muted">{u.time} {data.period.zone}</span>}</div>
              </div>)) : <span className="small muted">Nothing scheduled in this period.</span>}
          </section>
        </div>
      </>}
      <section className="card" style={{ marginTop: 16, overflow: "hidden" }} aria-label="Interviews by person">
        <div className="tm-head"><h3 style={{ margin: 0 }}>Interviews by person</h3></div>
        <div className="tm-scroll"><table className="tm-table">
          <thead><tr><th>Interviewer</th><th>Total</th><th>Completed</th><th>Upcoming</th><th>Cancelled</th><th>Feedback pending</th><th>Avg. duration</th><th>Last interview</th><th>View</th></tr></thead>
          <tbody>{data.people.map((p) => (
            <tr key={p.id}>
              <td><span className="row" style={{ gap: 10 }}><Avatar name={p.name} /><b>{p.name}</b></span></td>
              <td><b>{p.total}</b></td><td>{p.completed}</td><td>{p.upcoming}</td><td>{p.cancelled}</td>
              <td className={p.pending ? "tm-warn b" : "b"}>{p.pending}</td><td>{mins(p.avg_minutes)}</td><td>{p.last || "—"}</td>
              <td><Btn size="sm" onClick={() => nav(`/app/teams/${p.id}?${qs}`)} aria-label={`View ${p.name}`}>View</Btn></td>
            </tr>))}
            {!data.people.length && <tr><td colSpan={9} className="muted small">Nobody has the interviewer role yet. Give it to people in Company admin › People.</td></tr>}
          </tbody>
        </table></div>
      </section>
      <p className="tiny muted" style={{ marginTop: 10 }}>Live interviews with an interviewer assigned (F2F with Isha and live interviews). Times in {data.period.zone}. Feedback pending: the interview ended and no scorecard was submitted yet.</p>
    </>
  );
}

export function TeamPerson() {
  const { uid } = useParams();
  const { range, picker, qs } = usePeriod();
  const { data, error, reload, loading } = useAsync(() => api.get(`/teams/${uid}?${qs}`), [uid, qs]);
  const toast = useToast();
  const nav = useNavigate();
  const exportCsv = () => download(`/teams/export.csv?${qs}&person=${uid}`, `interviews-${range.from}-to-${range.to}-${uid}.csv`).catch((e) => toast(e.message, "bad"));
  const back = <button type="button" className="linkbtn small" onClick={() => nav(`/app/teams?${qs}`)}>← Back to Teams</button>;
  if (error) return <>{back}<ErrorBox error={error} onRetry={reload} /></>;
  if (!data || loading) return <>{back}<Loading /></>;
  const p = data.person, t = data.tiles;
  return (
    <>
      <div className="row wrap" style={{ marginBottom: 12, gap: 8 }}>{back}<span className="grow" />{picker}<Btn onClick={exportCsv}>Export CSV</Btn></div>
      <section className="card pad col" style={{ gap: 14 }}>
        <div className="row" style={{ gap: 12 }}>
          <Avatar name={p.name} />
          <div className="col" style={{ gap: 6 }}><h2 style={{ margin: 0 }}>{p.name}</h2>
            <span className="row wrap" style={{ gap: 6 }}>{p.roles.map((r) => <Chip key={r} kind="brand">{r}</Chip>)}</span></div>
        </div>
        <div className="tm-facts">
          <div><span className="tiny muted">Email</span><b>{p.email}</b></div>
          <div><span className="tiny muted">Account status</span><b>{p.active ? "Active" : "Inactive"}</b></div>
          <div><span className="tiny muted">Last interview</span><b>{p.last || "—"}</b></div>
          <div><span className="tiny muted">Next interview</span><b>{p.next ? `${p.next} ${data.period.zone}` : "—"}</b></div>
        </div>
      </section>
      <div className="tm-tiles seven">
        <Tile label="Total" value={t.total} /><Tile label="Completed" value={t.completed} /><Tile label="Upcoming" value={t.upcoming} /><Tile label="Cancelled" value={t.cancelled} />
        <Tile label="Feedback pending" value={t.pending} tone={t.pending ? "warn" : ""} /><Tile label="Avg. duration" value={mins(t.avg_minutes)} /><Tile label="Time spent" value={t.time_spent} />
      </div>
      <section className="card" style={{ overflow: "hidden" }} aria-label="All interviews">
        <div className="tm-head row"><h3 className="grow" style={{ margin: 0 }}>All interviews</h3>
          <span className="tiny muted">{data.period.from} to {data.period.to} · {data.interviews.length} record{data.interviews.length === 1 ? "" : "s"}</span></div>
        <div className="tm-scroll"><table className="tm-table">
          <thead><tr><th>Date</th><th>Time ({data.period.zone})</th><th>Duration</th><th>Candidate</th><th>Job role</th><th>Round</th><th>Status</th><th>Result</th></tr></thead>
          <tbody>{data.interviews.map((r) => (
            <tr key={r.id}>
              <td className="nw"><b>{r.date}</b></td><td className="nw">{r.time}</td><td className="nw">{r.duration}</td>
              <td>{r.report_id ? <Link to={`/app/reports/${r.attempt_id}`}>{r.candidate}</Link> : r.application_id ? <Link to={`/app/applications/${r.application_id}`}>{r.candidate}</Link> : r.candidate}</td>
              <td>{r.job}</td><td>{r.round}</td>
              <td><Chip kind={STATUS_TONE[r.status] || ""}>{r.status}</Chip></td>
              <td className={"b tm-res " + (RESULT_TONE[r.result] || "")}>{r.result || "—"}</td>
            </tr>))}
            {!data.interviews.length && <tr><td colSpan={8} className="muted small">No interviews in this period.</td></tr>}
          </tbody>
        </table></div>
      </section>
    </>
  );
}
