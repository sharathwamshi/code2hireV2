import { useState } from "react";
import { AgentNote } from "./Mascot";
import { Bar, Chip, Integrity, ROUND_LABEL, Ring, Score, Status, fmtDate, fmtScore, scorePct } from "./ui";

const REC = { proceed: ["Proceed", "good"], hold: ["Hold", "warn"], reject: ["Do not proceed", "bad"] };
const CLAIM = { confirmed: ["Confirmed", "good"], partly: ["Partly", "warn"], contradicted: ["Contradicted", "bad"], not_tested: ["Not tested", ""] };

/** Renders any report for any audience. The server already removed what this audience mustn't see. */
export default function ReportView({ r, onEvidence }) {
  const s = r.sections || {};
  const scale = r.scale || 5;
  const [openQ, setOpenQ] = useState(null);
  const candidate = r.audience === "candidate";
  if (candidate) {
    return (
      <div className="col" style={{ gap: 16 }}>
        <AgentNote agent="disha" title="Your feedback">Here's what the team saw, in plain words. Use it to get even better.</AgentNote>
        <div className="grid g3">
          <div className="card pad"><h3>What went well</h3><ul>{(s.strengths || []).map((x, i) => <li key={i}>{x}</li>)}</ul></div>
          <div className="card pad"><h3>What to work on</h3><ul>{(s.gaps || []).map((x, i) => <li key={i}>{x}</li>)}</ul></div>
          <div className="card pad"><h3>Next steps</h3><ul>{(s.next_steps || []).map((x, i) => <li key={i}>{x}</li>)}</ul></div>
        </div>
      </div>
    );
  }
  const pct = scorePct(r.overall);
  return (
    <div className="col" style={{ gap: 16 }}>
      <div className="card pad">
        <div className="row wrap" style={{ gap: 16, alignItems: "flex-start" }}>
          {pct != null && <div className="col" style={{ alignItems: "center", gap: 4 }}><Ring value={pct} label={fmtScore(r.overall, scale, { pct: false }).split(" / ")[0]} /><span className="tiny muted">out of {scale} · {pct}%</span></div>}
          <div className="grow col" style={{ gap: 6 }}>
            <div className="row wrap">
              <h2>{r.candidate?.name}</h2>
              <Chip kind="brand">{r.round || ROUND_LABEL[r.type]}</Chip>
              {r.recommendation && <Chip kind={REC[r.recommendation]?.[1]}>{r.type === "f2f_isha" || r.type === "f2f_human" ? "Interviewer" : "Hira"} recommends: {REC[r.recommendation]?.[0] || r.recommendation}</Chip>}
              {r.confidence && <Chip>Confidence: {r.confidence}</Chip>}
              {r.verdict && <Chip kind="dark">Decision: {r.verdict}</Chip>}
              <Status s={r.status} />
            </div>
            <div className="muted small">{r.job?.title} · completed {fmtDate(r.completed_at, true)}{r.interviewer ? ` · interviewer ${r.interviewer}` : ""} · version {r.version}</div>
            {s.summary && <p style={{ fontSize: 15 }}>{s.summary}</p>}
            {s.finished_reason && s.finished_reason !== "completed" && s.finished_reason !== "submitted" && <Chip kind="warn">Ended: {String(s.finished_reason).replace(/_/g, " ")}</Chip>}
          </div>
        </div>
      </div>

      {s.competencies?.length > 0 && (
        <div className="card">
          <div className="card-h"><h3>Competencies</h3><span className="small muted">Click a row to see the evidence behind the score</span></div>
          <div className="tbl-wrap"><table className="tbl">
            <thead><tr><th>Competency</th><th style={{ width: 180 }}>Score</th><th>Level</th><th>Evidence</th>{s.competencies.some((c) => c.ai_score != null) && <th>Isha's live score</th>}</tr></thead>
            <tbody>{s.competencies.map((c, i) => (
              <tr key={i} className="clickable" onClick={() => onEvidence?.(c)}>
                <td className="b">{c.name}{c.weight > 1 && <span className="tiny faint"> ×{c.weight}</span>}{c.not_covered && <Chip kind="warn">Not covered</Chip>}</td>
                <td><div className="row"><div className="grow"><Bar value={c.score} max={5} /></div><Score value={c.score} scale={scale} /></div></td>
                <td><Chip kind={c.level === "Strong" ? "good" : c.level === "Meets" ? "info" : "bad"}>{c.level}</Chip></td>
                <td style={{ maxWidth: 420 }}>{c.evidence ? <div className="quote small">“{c.evidence}”{c.time ? <span className="faint"> · {c.time}</span> : null}</div> : <span className="faint">—</span>}{c.note && <div className="small muted">{c.note}</div>}</td>
                {s.competencies.some((x) => x.ai_score != null) && <td><Score value={c.ai_score} scale={scale} /></td>}
              </tr>
            ))}</tbody>
          </table></div>
        </div>
      )}

      <div className="grid g2">
        {(s.strengths?.length > 0 || s.gaps?.length > 0) && (
          <div className="card pad col">
            <h3>Strengths and gaps</h3>
            <div className="row wrap">{(s.strengths || []).map((x, i) => <Chip key={i} kind="good">✓ {x}</Chip>)}</div>
            <div className="row wrap">{(s.gaps || []).map((x, i) => <Chip key={i} kind="bad">△ {x}</Chip>)}</div>
            {s.handoff?.length > 0 && <><div className="divider" /><b className="small">Next round should probe</b><ul style={{ margin: 0 }}>{s.handoff.map((x, i) => <li key={i}>{x}</li>)}</ul></>}
          </div>
        )}
        {s.resume_vs_reality?.length > 0 && (
          <div className="card pad col">
            <h3>Resume vs reality</h3>
            {s.resume_vs_reality.map((c, i) => <div key={i} className="row between"><span>{c.claim}</span><Chip kind={CLAIM[c.status]?.[1]}>{CLAIM[c.status]?.[0] || c.status}</Chip></div>)}
          </div>
        )}
        {s.coverage && (
          <div className="card pad col">
            <h3>Coverage</h3>
            <div className="row wrap">{(s.coverage.planned || []).map((p, i) => <Chip key={i} kind={(s.coverage.tested || []).includes(p) ? "good" : "warn"}>{(s.coverage.tested || []).includes(p) ? "✓" : "○"} {p}</Chip>)}</div>
          </div>
        )}
        {s.ai_agreement && (
          <div className="card pad col">
            <h3>Interviewer vs Isha</h3>
            <div>Average difference <b>{s.ai_agreement.avg_diff}</b> points across {s.ai_agreement.pairs} competencies.</div>
            <Chip kind={s.ai_agreement.level === "high" ? "good" : s.ai_agreement.level === "medium" ? "warn" : "bad"}>Agreement: {s.ai_agreement.level}</Chip>
          </div>
        )}
        {s.integrity && (
          <div className="card pad col">
            <div className="row"><h3>Integrity</h3><Integrity count={s.integrity.warnings} /></div>
            {!s.integrity.events?.length && <span className="muted small">No events recorded.</span>}
            {s.integrity.events?.map((e, i) => (
              <div key={i} className="row small"><span className="dot" style={{ color: e.counted ? (e.severity === "high" ? "var(--bad)" : "#E08A1E") : "var(--faint)" }} />
                <span className="grow">{e.label}{e.q != null ? ` · question ${e.q + 1}` : ""}</span><span className="faint">{e.counted ? "counted" : "notice"} · {fmtDate(e.at, true)}</span></div>
            ))}
            {s.integrity.snapshots?.length > 0 && <>
              <b className="small">Camera at the moment of each face warning</b>
              <div className="row wrap" style={{ gap: 8 }}>{s.integrity.snapshots.map((x, i) => (
                <figure key={i} style={{ margin: 0, width: 150 }}><img src={x.image} alt={`${x.label} at ${fmtDate(x.at, true)}`} style={{ width: "100%", borderRadius: 8, display: "block" }} />
                  <figcaption className="tiny muted">{x.label} · {fmtDate(x.at, true)}</figcaption></figure>))}</div>
            </>}
          </div>
        )}
      </div>

      {s.questions?.length > 0 && (
        <div className="card">
          <div className="card-h"><h3>{s.kind === "mcq" ? "Questions and answers" : "Question by question"}</h3></div>
          {s.questions.map((q, i) => (
            <div key={i} className="list-row" style={{ alignItems: "flex-start", flexDirection: "column", gap: 6 }}>
              <button className="row" style={{ width: "100%", border: 0, background: "none", cursor: "pointer", textAlign: "left", padding: 0 }} onClick={() => setOpenQ(openQ === i ? null : i)}>
                <span className="chip">{i + 1}</span><b className="grow">{q.q}</b>
                {q.topic && <Chip>{q.topic}</Chip>}
                {s.kind === "mcq" ? <Chip kind={q.correct ? "good" : q.chosen == null ? "" : "bad"}>{q.correct ? "Correct" : q.chosen == null ? "Skipped" : "Wrong"}</Chip> : <Score value={q.score} scale={scale} />}
                {q.time && <span className="tiny faint">{q.time}</span>}
              </button>
              {openQ === i && (
                <div className="col" style={{ paddingLeft: 34, width: "100%" }}>
                  {s.kind === "mcq" ? (
                    <div className="col" style={{ gap: 4 }}>{(q.options || []).map((o, j) => (
                      <div key={j} className="small" style={{ color: j === q.answer ? "var(--good)" : j === q.chosen ? "var(--bad)" : undefined }}>
                        {j === q.answer ? "✓" : j === q.chosen ? "✗" : "·"} {o}</div>))}
                      {q.explanation && <div className="small muted">{q.explanation}</div>}</div>
                  ) : (
                    <>
                      {q.a !== undefined && <div className="quote">{q.a || "(no answer)"}</div>}
                      {q.good_answer && <div className="small"><b>A good answer covers:</b> {q.good_answer.map((g, j) => <span key={j} style={{ color: q.covered?.[j] ? "var(--good)" : "var(--faint)" }}>{q.covered?.[j] ? "✓" : "○"} {g}{j < q.good_answer.length - 1 ? " · " : ""}</span>)}</div>}
                      {q.tags?.length > 0 && <div className="row wrap">{q.tags.map((t, j) => <Chip key={j} kind={t.type === "good" ? "good" : t.type === "flag" ? "bad" : t.type === "vague" ? "warn" : "info"}>{t.label}</Chip>)}</div>}
                    </>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      {r.history?.length > 0 && (
        <div className="card pad col"><h3>Version history</h3>
          {r.history.map((h, i) => <div key={i} className="small"><b>v{h.version}</b> · {h.by} · {fmtDate(h.at, true)}{h.verdict ? ` · verdict ${h.verdict}` : ""}{h.note ? ` · “${h.note}”` : ""}
            {(h.changes || []).map((c, j) => <div key={j} className="muted" style={{ paddingLeft: 16 }}>{c.name}: {c.from} → {c.to} ({c.reason})</div>)}</div>)}
        </div>
      )}
    </div>
  );
}
