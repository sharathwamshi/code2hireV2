import { useState } from "react";
import { AgentNote } from "./Mascot";
import { Bar, Btn, Chip, Integrity, ROUND_LABEL, Ring, Score, Status, fmtDate, fmtScore, scorePct } from "./ui";
import { seekRecording } from "./RecordingPlayer";

const REC = { proceed: ["Proceed", "good"], hold: ["Hold", "warn"], reject: ["Do not proceed", "bad"] };
const CLAIM = { confirmed: ["Confirmed", "good"], partly: ["Partly", "warn"], contradicted: ["Contradicted", "bad"], not_tested: ["Not tested", ""] };

/** Renders any report for any audience. The server already removed what this audience mustn't see. */
const toSecs = (t) => { const [m, sec] = String(t).split(":").map(Number); return (m || 0) * 60 + (sec || 0); };

export default function ReportView({ r, onEvidence }) {
  const s = r.sections || {};
  const scale = r.scale || 5;
  // R6 (V02.00.06): every question is open by default; closed ones are remembered per report view
  const [closedQ, setClosedQ] = useState(() => new Set());
  const isOpen = (i) => !closedQ.has(i);
  const toggleQ = (i) => setClosedQ((c) => { const n = new Set(c); if (n.has(i)) n.delete(i); else n.add(i); return n; });
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
          <div className="card-h"><h3>{s.kind === "mcq" ? "Questions and answers" : "Question by question"}</h3>
            <span className="small muted">{s.questions.length} question{s.questions.length === 1 ? "" : "s"}</span>
            <span className="right row" style={{ gap: 4 }}>
              <Btn size="sm" kind="ghost" onClick={() => setClosedQ(new Set())}>Expand all</Btn>
              <Btn size="sm" kind="ghost" onClick={() => setClosedQ(new Set(s.questions.map((_, i) => i)))}>Collapse all</Btn></span></div>
          {s.questions.map((q, i) => {
            const mcq = s.kind === "mcq";
            const letter = (k) => (typeof k === "number" && k >= 0 ? String.fromCharCode(65 + k) : "");
            const chosen = q.chosen == null || q.chosen === "" ? null : Number(q.chosen);
            return (
              <div key={i} className="list-row qa-row" style={{ alignItems: "flex-start", flexDirection: "column", gap: 8 }}>
                <button className="row" aria-expanded={isOpen(i)} style={{ width: "100%", border: 0, background: "none", cursor: "pointer", textAlign: "left", padding: 0, color: "inherit" }} onClick={() => toggleQ(i)}>
                  <span className="chip">{i + 1}</span><b className="grow">{q.q}</b>
                  {q.kind === "followup" && <Chip kind="gold">Follow-up</Chip>}
                  {q.topic && <Chip>{q.topic}</Chip>}
                  {mcq ? <Chip kind={q.correct ? "good" : chosen == null ? "" : "bad"}>{q.correct ? "Correct" : chosen == null ? "Skipped" : "Wrong"}</Chip> : q.score != null && <Score value={q.score} scale={scale} />}
                  {q.time && (r.video?.parts?.length && r.audience !== "candidate" && r.audience !== "client"
                    ? <span role="button" tabIndex={0} className="linkbtn tiny" title="Play the video from here" onKeyDown={(e) => { if (e.key === "Enter") { e.stopPropagation(); seekRecording(toSecs(q.time)); } }} onClick={(e) => { e.stopPropagation(); seekRecording(toSecs(q.time)); }}>▶ {q.time}</span>
                    : <span className="tiny faint">{q.time}</span>)}
                  <span className="tiny faint" aria-hidden="true">{isOpen(i) ? "▾" : "▸"}</span>
                </button>
                {isOpen(i) && (mcq ? (
                  <div className="qa-grid">
                    <div className="qa-box expected"><div className="qa-l">Correct answer</div>{typeof q.answer === "number" ? <>{letter(q.answer)}. {(q.options || [])[q.answer]}</> : "—"}
                      {q.explanation && <div className="small muted" style={{ marginTop: 4 }}>{q.explanation}</div>}</div>
                    <div className={"qa-box response " + (q.correct ? "ok" : chosen == null ? "" : "no")}><div className="qa-l">{r.audience === "candidate" ? "Your answer" : "Candidate chose"}</div>
                      {chosen == null ? <span className="muted">Skipped</span> : <>{letter(chosen)}. {(q.options || [])[chosen]} {q.correct ? "✓" : "✗"}</>}</div>
                    <div className="qa-opts">{(q.options || []).map((o, j) => (
                      <div key={j} className="small" style={{ color: j === q.answer ? "var(--good)" : j === chosen ? "var(--bad)" : undefined }}>
                        {j === q.answer ? "✓" : j === chosen ? "✗" : "·"} {letter(j)}. {o}</div>))}</div>
                  </div>
                ) : (
                  <div className="qa-grid">
                    <div className="qa-box expected"><div className="qa-l">A good answer covers</div>
                      {(q.good_answer || []).length ? <ul className="qa-points">{q.good_answer.map((g, j) => (
                        <li key={j} className={q.covered?.[j] ? "hit" : q.covered_level?.[j] === "partial" ? "part" : ""}>
                          <span aria-hidden="true">{q.covered?.[j] ? "✓" : q.covered_level?.[j] === "partial" ? "◐" : "○"}</span> {g}
                          <span className="sr-only">{q.covered?.[j] ? " (covered)" : " (not covered)"}</span></li>))}</ul>
                        : <span className="muted small">No expected points were set for this question.</span>}
                      {(q.good_answer || []).length > 0 && <div className="tiny muted" style={{ marginTop: 4 }}>{(q.covered || []).filter(Boolean).length} of {q.good_answer.length} covered</div>}</div>
                    <div className="qa-box response"><div className="qa-l">{r.audience === "candidate" ? "Your answer" : "Candidate's answer"}</div>
                      {q.a !== undefined ? (q.a ? <div className="quote" style={{ margin: 0 }}>{q.a}</div> : <span className="muted">(no answer)</span>) : <span className="muted small">Hidden in this version of the report.</span>}
                      {q.tags?.length > 0 && <div className="row wrap" style={{ marginTop: 6 }}>{q.tags.map((t, j) => <Chip key={j} kind={t.type === "good" ? "good" : t.type === "flag" ? "bad" : t.type === "vague" ? "warn" : "info"}>{t.label}</Chip>)}</div>}
                      {q.interviewer_said?.length > 0 && <div className="small muted" style={{ marginTop: 6 }}><b>Interviewer also said:</b> {q.interviewer_said.join(" / ")}</div>}
                      {q.auto && <div className="tiny faint" style={{ marginTop: 4 }}>Isha matched this question when the interviewer asked it.</div>}</div>
                  </div>
                ))}
              </div>
            );
          })}
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
