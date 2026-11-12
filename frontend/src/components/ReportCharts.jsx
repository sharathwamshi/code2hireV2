// V02.00.08: the visual parts of every report (hiring team, hiring manager, client, candidate, shared link).
// Plain SVG, no chart library: the theme colours come from CSS variables, so they follow the app's look.
import { fmtDate, fmtScore, scorePct } from "./ui";

export const band = (pct) => (pct == null ? "none" : pct >= 70 ? "good" : pct >= 45 ? "warn" : "bad");
const COL = { good: "var(--good)", warn: "#E08A1E", bad: "var(--bad)", none: "var(--line-2)", brand: "var(--brand)", info: "var(--info)", isha: "var(--isha-gold)" };
const LEVEL = { Strong: "good", Meets: "info", Weak: "bad", Developing: "warn" };
export const levelOf = (score) => (score == null ? null : score >= 4 ? "Strong" : score >= 3 ? "Meets" : "Weak");

/** Half-circle gauge for a 0–100 value, coloured by band. */
export function Gauge({ pct, label, sub, size = 180, tone: forced }) {
  const r = 70, cx = 90, cy = 86, L = Math.PI * r;
  const v = Math.max(0, Math.min(100, pct ?? 0));
  const tone = forced || band(pct);
  return (
    <figure className="rc-gauge" style={{ width: size, margin: 0 }} role="img" aria-label={`Overall ${pct ?? "no"} percent`}>
      <svg viewBox="0 0 180 104" width="100%">
        <path d={`M${cx - r},${cy} A${r},${r} 0 0 1 ${cx + r},${cy}`} fill="none" stroke="var(--soft)" strokeWidth="16" strokeLinecap="round" />
        {pct != null && <path d={`M${cx - r},${cy} A${r},${r} 0 0 1 ${cx + r},${cy}`} fill="none" stroke={COL[tone]} strokeWidth="16" strokeLinecap="round"
          strokeDasharray={`${(v / 100) * L} ${L}`} />}
        <text x={cx} y={cy - 18} textAnchor="middle" className="rc-gauge-v">{label ?? (pct == null ? "—" : `${pct}%`)}</text>
        <text x={cx} y={cy + 2} textAnchor="middle" className="rc-gauge-s">{sub || ""}</text>
      </svg>
    </figure>
  );
}

/** Ring split into parts, with a number in the middle. parts: [{label, value, tone}] */
export function Donut({ parts, center, sub, size = 132, title }) {
  const total = parts.reduce((a, p) => a + (p.value || 0), 0);
  const r = 46, C = 2 * Math.PI * r;
  let acc = 0;
  return (
    <div className="rc-donut">
      <svg viewBox="0 0 120 120" width={size} height={size} role="img" aria-label={title || parts.map((p) => `${p.label} ${p.value}`).join(", ")}>
        <circle cx="60" cy="60" r={r} fill="none" stroke="var(--soft)" strokeWidth="16" />
        {total > 0 && parts.map((p, i) => {
          const len = (p.value / total) * C;
          const el = <circle key={i} cx="60" cy="60" r={r} fill="none" stroke={COL[p.tone] || p.tone} strokeWidth="16"
            strokeDasharray={`${Math.max(0, len - (parts.filter((x) => x.value).length > 1 ? 1.5 : 0))} ${C}`} strokeDashoffset={-acc} transform="rotate(-90 60 60)" />;
          acc += len;
          return el;
        })}
        <text x="60" y="58" textAnchor="middle" className="rc-donut-v">{center}</text>
        {sub && <text x="60" y="76" textAnchor="middle" className="rc-donut-s">{sub}</text>}
      </svg>
      <div className="rc-legend">{parts.map((p) => <span key={p.label}><i style={{ background: COL[p.tone] || p.tone }} />{p.label} <b>{p.value}</b></span>)}</div>
    </div>
  );
}

/** Horizontal bars, one per competency, on a 1–5 scale; a diamond marks Isha's live score. */
export function CompetencyBars({ comps, scale = 5, onPick }) {
  const hasAi = comps.some((c) => c.ai_score != null);
  return (
    <div className="rc-bars" role="table" aria-label="Scores by competency">
      <div className="rc-bar-row rc-axis-row" aria-hidden="true"><span /><span className="rc-axis-track">{[0, 1, 2, 3, 4, 5].map((n) => <span key={n} style={{ left: `${(n / 5) * 100}%` }}>{(n * scale) / 5}</span>)}</span><span /></div>
      {comps.map((c, i) => {
        const lvl = c.level || levelOf(c.score);
        const tone = c.not_covered || c.score == null ? "none" : LEVEL[lvl] || band(scorePct(c.score));
        const w = c.score == null ? 0 : Math.max(2, ((Number(c.score) - 0) / 5) * 100);
        return (
          <button type="button" key={i} className="rc-bar-row" role="row" onClick={() => onPick?.(c)} title={c.evidence ? `“${c.evidence}”` : ""}>
            <span className="rc-bar-name" role="cell">{c.name}{c.weight > 1 && <em> ×{c.weight}</em>}</span>
            <span className="rc-bar-track" role="cell">
              {[1, 2, 3, 4].map((n) => <i key={n} className="rc-grid" style={{ left: `${(n / 5) * 100}%` }} />)}
              <span className="rc-bar-fill" style={{ width: `${w}%`, background: COL[tone] }} />
              {c.ai_score != null && <span className="rc-ai" style={{ left: `${(Number(c.ai_score) / 5) * 100}%` }} title={`Isha's live score ${c.ai_score}`} />}
            </span>
            <span className="rc-bar-val" role="cell">{c.not_covered || c.score == null ? <span className="faint">Not covered</span> : <><b>{fmtScore(c.score, scale, { pct: false }).split(" / ")[0]}</b><span className={"rc-pill " + tone}>{lvl}</span></>}</span>
          </button>
        );
      })}
      <div className="rc-legend small">
        <span><i style={{ background: COL.good }} />Strong (4–5)</span><span><i style={{ background: COL.info }} />Meets (3)</span><span><i style={{ background: COL.bad }} />Weak (below 3)</span>
        {hasAi && <span><i className="rc-ai-key" />Isha's live score</span>}
      </div>
    </div>
  );
}

/** Spider chart of the competency profile (needs 3 or more). */
export function Radar({ comps, size = 340 }) {
  const items = comps.filter((c) => c.score != null).slice(0, 10);
  if (items.length < 3) return null;
  const cx = 170, cy = 130, R = 88, n = items.length;
  const pt = (i, v) => { const a = -Math.PI / 2 + (2 * Math.PI * i) / n; return [cx + Math.cos(a) * R * v, cy + Math.sin(a) * R * v]; };
  const poly = (f) => items.map((c, i) => pt(i, f(c)).join(",")).join(" ");
  const hasAi = items.some((c) => c.ai_score != null);
  return (
    <svg viewBox="0 0 340 262" width={size} style={{ maxWidth: "100%" }} role="img" aria-label="Competency profile">
      {[0.2, 0.4, 0.6, 0.8, 1].map((k) => <polygon key={k} points={items.map((_, i) => pt(i, k).join(",")).join(" ")} fill={k === 1 ? "var(--soft)" : "none"} stroke="var(--line)" strokeWidth="1" />)}
      {items.map((_, i) => <line key={i} x1={cx} y1={cy} x2={pt(i, 1)[0]} y2={pt(i, 1)[1]} stroke="var(--line)" />)}
      <polygon points={poly(() => 0.6)} fill="none" stroke="var(--faint)" strokeDasharray="3 3" />
      {hasAi && <polygon points={poly((c) => (c.ai_score ?? c.score) / 5)} fill="var(--isha-gold)" fillOpacity=".12" stroke="var(--isha-gold)" strokeWidth="1.5" />}
      <polygon points={poly((c) => c.score / 5)} fill="var(--brand)" fillOpacity=".22" stroke="var(--brand)" strokeWidth="2" />
      {items.map((c, i) => { const [x, y] = pt(i, c.score / 5); return <circle key={i} cx={x} cy={y} r="3.5" fill="var(--brand)" />; })}
      {items.map((c, i) => {
        const [x, y] = pt(i, 1.16);
        const anchor = Math.abs(x - cx) < 8 ? "middle" : x > cx ? "start" : "end";
        return <text key={i} x={x} y={y + 3} textAnchor={anchor} className="rc-radar-l">{c.name.length > 20 ? c.name.slice(0, 19) + "…" : c.name}<tspan className="rc-radar-v" dx="4">{Number(c.score).toFixed(1)}</tspan></text>;
      })}
    </svg>
  );
}

/** One square per MCQ question: green right, red wrong, grey skipped. */
export function AnswerMap({ questions }) {
  return (
    <div className="rc-map" role="list" aria-label="Answer for each question">
      {questions.map((q, i) => {
        const skipped = q.chosen == null || q.chosen === "";
        const t = q.correct ? "good" : skipped ? "none" : "bad";
        return <a key={i} role="listitem" href={`#q${i + 1}`} className={"rc-sq " + t} title={`Question ${i + 1}: ${q.correct ? "correct" : skipped ? "skipped" : "wrong"}${q.skill ? " · " + q.skill : ""}`}>{i + 1}</a>;
      })}
    </div>
  );
}

/** Correct vs wrong per skill (MCQ), as stacked bars. */
export function SkillStack({ questions }) {
  const by = {};
  for (const q of questions) {
    const k = q.skill || "General";
    by[k] = by[k] || { right: 0, wrong: 0, skip: 0 };
    if (q.correct) by[k].right++; else if (q.chosen == null || q.chosen === "") by[k].skip++; else by[k].wrong++;
  }
  const rows = Object.entries(by).sort((a, b) => (b[1].right / (b[1].right + b[1].wrong + b[1].skip)) - (a[1].right / (a[1].right + a[1].wrong + a[1].skip)));
  return (
    <div className="col" style={{ gap: 8 }}>
      {rows.map(([k, v]) => {
        const n = v.right + v.wrong + v.skip;
        const p = Math.round((100 * v.right) / n);
        return (
          <div key={k} className="rc-stack-row">
            <span className="rc-bar-name">{k}</span>
            <span className="rc-stack" title={`${v.right} right, ${v.wrong} wrong, ${v.skip} skipped`}>
              <i style={{ width: `${(100 * v.right) / n}%`, background: COL.good }} /><i style={{ width: `${(100 * v.wrong) / n}%`, background: COL.bad }} /><i style={{ width: `${(100 * v.skip) / n}%`, background: COL.none }} />
            </span>
            <span className="rc-bar-val"><b>{p}%</b><span className="faint small"> {v.right}/{n}</span></span>
          </div>
        );
      })}
    </div>
  );
}

/** Interview questions: how much of a good answer each one covered (and its score when there is one). */
export const coverageMode = (questions) => (questions.some((q) => (q.covered || []).some(Boolean)) ? "coverage" : questions.some((q) => q.score != null) ? "score" : null);

export function QuestionCoverage({ questions, scale = 5, mode }) {
  const m = mode || coverageMode(questions);
  const rows = questions.map((q, i) => {
    const pts = (q.good_answer || []).length;
    const hit = (q.covered || []).filter(Boolean).length;
    const cov = m === "coverage" && pts ? Math.round((100 * hit) / pts) : null;
    return { i, q, pts, hit, cov, score: q.score };
  });
  if (!rows.some((r) => r.cov != null || r.score != null)) return null;
  const H = 120, w = Math.max(18, Math.min(42, 560 / rows.length));
  return (
    <div className="rc-cols-wrap">
      <svg viewBox={`0 0 ${rows.length * (w + 8) + 34} ${H + 34}`} width="100%" style={{ maxWidth: rows.length * (w + 8) + 34 }} role="img" aria-label="Points covered in each answer">
        {[0, 50, 100].map((g) => <g key={g}><line x1="30" x2={rows.length * (w + 8) + 34} y1={8 + H - (g / 100) * H} y2={8 + H - (g / 100) * H} stroke="var(--line)" strokeDasharray={g ? "3 3" : ""} />
          <text x="26" y={12 + H - (g / 100) * H} textAnchor="end" className="rc-axis">{g}%</text></g>)}
        {rows.map((r, k) => {
          const v = r.cov ?? (r.score != null ? scorePct(r.score) : 0);
          const h = Math.max(2, (v / 100) * H);
          const x = 34 + k * (w + 8);
          return (
            <g key={k}>
              <a href={`#q${r.i + 1}`}><rect x={x} y={8 + H - h} width={w} height={h} rx="4" fill={COL[band(v)]}>
                <title>{`Question ${r.i + 1}: ${r.cov != null ? `${r.hit} of ${r.pts} points covered` : ""}${r.score != null ? ` · score ${fmtScore(r.score, scale)}` : ""}`}</title></rect></a>
              <text x={x + w / 2} y={H + 24} textAnchor="middle" className="rc-axis">Q{r.i + 1}</text>
              {w >= 26 && <text x={x + w / 2} y={4 + H - h} textAnchor="middle" className="rc-axis b">{v}%</text>}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

/** Integrity events on a time line. */
export function IntegrityTimeline({ events }) {
  const ev = (events || []).filter((e) => e.at).map((e) => ({ ...e, t: new Date(e.at).getTime() })).filter((e) => !Number.isNaN(e.t));
  if (ev.length < 1) return null;
  const t0 = Math.min(...ev.map((e) => e.t)), t1 = Math.max(...ev.map((e) => e.t));
  const span = Math.max(1, t1 - t0);
  return (
    <div className="rc-timeline" aria-label="Integrity events over time">
      <div className="rc-tl-line" />
      {ev.map((e, i) => <span key={i} className={"rc-tl-dot " + (e.counted ? (e.severity === "high" ? "bad" : "warn") : "none")} style={{ left: `${ev.length === 1 ? 50 : 3 + ((e.t - t0) / span) * 94}%` }} title={`${e.label} · ${fmtDate(e.at, true)}${e.counted ? " · counted" : " · notice only"}`} />)}
      <div className="rc-tl-ends small faint"><span>{fmtDate(new Date(t0).toISOString(), true)}</span><span>{ev.length > 1 ? fmtDate(new Date(t1).toISOString(), true) : ""}</span></div>
    </div>
  );
}

/** A coloured key-figure tile. */
export function Stat({ label, value, sub, tone = "brand", icon }) {
  return (
    <div className={"rc-stat " + tone}>
      <div className="rc-stat-l">{icon && <span aria-hidden="true">{icon}</span>}{label}</div>
      <div className="rc-stat-v">{value}</div>
      {sub && <div className="rc-stat-s">{sub}</div>}
    </div>
  );
}
