import { useState } from "react";
import { api } from "../api";
import { AgentNote } from "./Mascot";
import { Bar, Btn, Chip, Integrity, ROUND_LABEL, Score, Status, Textarea, fmtDate, fmtScore, scorePct, useConfirm, useToast } from "./ui";
import { AnswerMap, CompetencyBars, Donut, Gauge, IntegrityTimeline, QuestionCoverage, Radar, SkillStack, Stat, band, coverageMode, levelOf } from "./ReportCharts";
import { seekRecording } from "./RecordingPlayer";

const REC = { proceed: ["Proceed", "good"], hold: ["Hold", "warn"], reject: ["Do not proceed", "bad"] };
const CLAIM = { confirmed: ["Confirmed", "good"], partly: ["Partly", "warn"], contradicted: ["Contradicted", "bad"], not_tested: ["Not tested", ""] };

/** Renders any report for any audience. The server already removed what this audience mustn't see. */
const toSecs = (t) => { const [m, sec] = String(t).split(":").map(Number); return (m || 0) * 60 + (sec || 0); };

export default function ReportView({ r, onEvidence, onChanged }) {
  const s = r.sections || {};
  const scale = r.scale || 5;
  const isIsha = s.kind === "f2f_isha";   // V02.01.07: no comparison with Isha's scores on these reports
  // R6 (V02.00.06): every question is open by default; closed ones are remembered per report view
  const [closedQ, setClosedQ] = useState(() => new Set());
  const isOpen = (i) => !closedQ.has(i);
  const toggleQ = (i) => setClosedQ((c) => { const n = new Set(c); if (n.has(i)) n.delete(i); else n.add(i); return n; });
  const candidate = r.audience === "candidate";
  const qProps = { r, s, scale, closedQ, setClosedQ, isOpen, toggleQ, onChanged };
  if (candidate) return <CandidateView r={r} s={s} scale={scale} qProps={qProps} />;
  const pct = scorePct(r.overall);
  const mcq = s.kind === "mcq";
  const comps = s.competencies || [];
  const levels = { Strong: 0, Meets: 0, Weak: 0 };
  comps.forEach((c) => { const l = c.not_covered || c.score == null ? null : (c.level || levelOf(c.score)); if (l && levels[l] != null) levels[l]++; });
  const qs = (s.questions || []).filter((q) => !q.skipped);   // V02.01.02: a skipped question is for the hiring team only
  const right = qs.filter((q) => q.correct).length;
  const skipped = qs.filter((q) => q.chosen == null || q.chosen === "").length;
  const pts = qs.reduce((a, q) => a + (q.good_answer || []).length, 0);
  const hit = qs.reduce((a, q) => a + (q.covered || []).filter(Boolean).length, 0);
  const rec = REC[r.recommendation];
  const live = r.type === "f2f_isha" || r.type === "f2f_human";
  return (
    <div className="col report-view" style={{ gap: 16 }}>
      <div className={"card rc-hero " + (rec ? rec[1] : "none")}>
        <div className="rc-hero-band" />
        <div className="row wrap" style={{ gap: 20, alignItems: "center", padding: "18px 20px 8px" }}>
          <Gauge pct={pct} label={pct == null ? "—" : `${pct}%`} sub={pct == null ? "" : fmtScore(r.overall, scale, { pct: false })} />
          <div className="grow col" style={{ gap: 6, minWidth: 260 }}>
            <div className="row wrap" style={{ gap: 8 }}>
              <h2 style={{ margin: 0 }}>{r.candidate?.name}</h2>
              <Chip kind="brand">{r.round || ROUND_LABEL[r.type]}</Chip>
              <Status s={r.status} />
            </div>
            <div className="muted small">{r.job?.title}{!r.taken && r.completed_at ? ` · completed ${fmtDate(r.completed_at, true)}` : ""}{r.interviewer ? ` · interviewer ${r.interviewer}` : ""}{r.version ? ` · version ${r.version}` : ""}</div>
            {r.taken && <div className="rc-taken" aria-label="When the interview was taken">
              <span><i className="tiny muted">Taken on</i><b>{r.taken.date}</b></span>
              <span><i className="tiny muted">Time</i><b>{r.taken.time}</b></span>
              <span><i className="tiny muted">Length</i><b>{r.taken.length}</b></span>
            </div>}
            {rec && <div className={"rc-verdict " + rec[1]}><span className="rc-verdict-k">{live ? "Interviewer" : "Hira"} recommends</span><b>{rec[0]}</b>{r.confidence && <span className="rc-verdict-c">confidence {r.confidence}</span>}</div>}
            {!rec && isIsha && <div className="rc-verdict"><span className="rc-verdict-k">Recommendation</span><b>Awaiting the hiring team</b></div>}
            {r.verdict && <div className="small"><Chip kind="dark">Decision: {r.verdict}</Chip></div>}
          </div>
        </div>
        {s.summary && <p className="rc-summary">{s.summary}</p>}
        {s.finished_reason && s.finished_reason !== "completed" && s.finished_reason !== "submitted" && <div style={{ padding: "0 20px 12px" }}><Chip kind="warn">Ended: {String(s.finished_reason).replace(/_/g, " ")}</Chip></div>}
        <div className="rc-stats">
          <Stat label="Overall" icon="◎" value={pct == null ? "—" : `${pct}%`} sub={fmtScore(r.overall, scale, { pct: false })} tone={band(pct)} />
          {mcq && qs.length > 0 && <Stat label="Correct" icon="✓" value={`${right} / ${qs.length}`} sub={skipped ? `${skipped} skipped` : "none skipped"} tone={band(Math.round((100 * right) / qs.length))} />}
          {!mcq && comps.length > 0 && <Stat label="Competencies" icon="▤" value={`${levels.Strong} strong`} sub={`${levels.Meets} meets · ${levels.Weak} weak`} tone={levels.Weak > levels.Strong ? "warn" : "good"} />}
          {!mcq && pts > 0 && <Stat label="Answer coverage" icon="◔" value={`${Math.round((100 * hit) / pts)}%`} sub={`${hit} of ${pts} expected points`} tone={band(Math.round((100 * hit) / pts))} />}
          {s.integrity && <Stat label="Integrity" icon="⛨" value={s.integrity.warnings ? `${s.integrity.warnings} warning${s.integrity.warnings > 1 ? "s" : ""}` : "Clean"} sub={`${(s.integrity.events || []).length} event${(s.integrity.events || []).length === 1 ? "" : "s"} logged`} tone={s.integrity.warnings ? (s.integrity.warnings > 2 ? "bad" : "warn") : "good"} />}
          {rec && <Stat label="Recommendation" icon="➜" value={rec[0]} sub={r.verdict ? `Decision: ${r.verdict}` : "Awaiting a decision"} tone={rec[1]} />}
        </div>
      </div>

      {s.isha && <IshaAssessment s={s} />}
      {s.isha_summary && <IshaSummary r={r} s={s} />}

      {mcq && qs.length > 0 && (
        <div className="card">
          <div className="card-h"><h3>Results at a glance</h3><span className="small muted">Click a square to jump to that question</span></div>
          <div className="rc-grid2 pad">
            <Donut title="Answers" center={`${Math.round((100 * right) / qs.length)}%`} sub="correct"
              parts={[{ label: "Correct", value: right, tone: "good" }, { label: "Wrong", value: qs.length - right - skipped, tone: "bad" }, { label: "Skipped", value: skipped, tone: "none" }]} />
            <div className="col" style={{ gap: 14, minWidth: 0 }}>
              <div><div className="rc-k">Every question</div><AnswerMap questions={qs} /></div>
              <div><div className="rc-k">By skill</div><SkillStack questions={qs} /></div>
            </div>
          </div>
        </div>
      )}

      {!mcq && comps.length > 0 && (
        <div className="card">
          <div className="card-h"><h3>Scores by competency</h3><span className="small muted">Click a bar for the evidence behind the score</span></div>
          <div className="rc-grid2 pad">
            <CompetencyBars comps={comps} scale={scale} onPick={onEvidence} />
            <div className="col" style={{ alignItems: "center", gap: 6 }}>
              <Radar comps={comps} />
              {comps.filter((c) => c.score != null).length >= 3 && <div className="rc-legend small"><span><i style={{ background: "var(--brand)" }} />Score</span>{!isIsha && comps.some((c) => c.ai_score != null) && <span><i style={{ background: "var(--isha-gold)" }} />Isha live</span>}<span><i className="rc-dash" />Meets bar (3)</span></div>}
              {comps.filter((c) => c.score != null).length < 3 && <Donut title="Levels" center={comps.length} sub="competencies"
                parts={[{ label: "Strong", value: levels.Strong, tone: "good" }, { label: "Meets", value: levels.Meets, tone: "info" }, { label: "Weak", value: levels.Weak, tone: "bad" }]} />}
            </div>
          </div>
        </div>
      )}

      {comps.length > 0 && (
        <div className="card">
          <div className="card-h"><h3>{mcq ? "Score by skill" : "Competency details"}</h3><span className="small muted">Click a row to see the evidence</span></div>
          <div className="tbl-wrap"><table className="tbl rc-table">
            <thead><tr><th>{mcq ? "Skill" : "Competency"}</th><th style={{ width: 200 }}>Score</th><th>Level</th><th>Evidence</th>{!isIsha && comps.some((c) => c.ai_score != null) && <th>Isha's live score</th>}</tr></thead>
            <tbody>{comps.map((c, i) => {
              const lvl = c.level || levelOf(c.score);
              return (
              <tr key={i} className={"clickable lvl-" + (c.not_covered || c.score == null ? "none" : (lvl || "").toLowerCase())} onClick={() => onEvidence?.(c)}>
                <td className="b">{c.name}{c.weight > 1 && <span className="tiny faint"> ×{c.weight}</span>}{c.not_covered && <> <Chip kind="warn">Not covered</Chip></>}
                  {c.skipped && <div className="tiny muted" style={{ fontWeight: 400 }}>Skipped by the interviewer: not counted{c.skip_reason ? ` · “${c.skip_reason}”` : ""}</div>}</td>
                <td><div className="row"><div className="grow"><Bar value={c.score} max={5} tone={{ Strong: "good", Meets: "info", Weak: "bad" }[lvl]} /></div><Score value={c.score} scale={scale} /></div></td>
                <td>{c.skipped ? <span className="rc-pill none">Skipped</span> : lvl && !c.not_covered ? <span className={"rc-pill " + ({ Strong: "good", Meets: "info", Weak: "bad" }[lvl] || "none")}>{lvl}</span> : "—"}</td>
                <td style={{ maxWidth: 420 }}>{c.evidence ? <div className="quote small">“{c.evidence}”{c.time ? <span className="faint"> · {c.time}</span> : null}</div> : <span className="faint">{c.reason || "—"}</span>}{c.note && <div className="small muted">{c.note}</div>}</td>
                {!isIsha && comps.some((x) => x.ai_score != null) && <td><Score value={c.ai_score} scale={scale} /></td>}
              </tr>);
            })}</tbody>
          </table></div>
        </div>
      )}

      {(s.strengths?.length > 0 || s.gaps?.length > 0) && (
        <div className="rc-grid2 tight">
          <div className="card pad rc-list good"><h3><span aria-hidden="true">▲</span> Strengths <span className="rc-count">{(s.strengths || []).length}</span></h3>
            {(s.strengths || []).length ? <ul>{s.strengths.map((x, i) => <li key={i}>{x}</li>)}</ul> : <span className="muted small">None recorded.</span>}</div>
          <div className="card pad rc-list bad"><h3><span aria-hidden="true">▼</span> Gaps <span className="rc-count">{(s.gaps || []).length}</span></h3>
            {(s.gaps || []).length ? <ul>{s.gaps.map((x, i) => <li key={i}>{x}</li>)}</ul> : <span className="muted small">None recorded.</span>}
            {s.handoff?.length > 0 && <><div className="divider" /><b className="small">Next round should probe</b><ul style={{ margin: 0 }}>{s.handoff.map((x, i) => <li key={i}>{x}</li>)}</ul></>}</div>
        </div>
      )}

      <div className="grid g2">
        {s.resume_vs_reality?.length > 0 && (
          <div className="card col">
            <div className="card-h"><h3>Resume vs reality</h3>
              <span className="right row" style={{ gap: 4 }}>{Object.entries(CLAIM).map(([k, [l, t]]) => { const n = s.resume_vs_reality.filter((c) => c.status === k).length; return n ? <Chip key={k} kind={t}>{n} {l.toLowerCase()}</Chip> : null; })}</span></div>
            <div className="tbl-wrap"><table className="tbl"><thead><tr><th>Claim on the resume</th><th style={{ width: 130 }}>In the interview</th></tr></thead>
              <tbody>{s.resume_vs_reality.map((c, i) => <tr key={i}><td>{c.claim}</td><td><Chip kind={CLAIM[c.status]?.[1]}>{CLAIM[c.status]?.[0] || c.status}</Chip></td></tr>)}</tbody></table></div>
          </div>
        )}
        {s.coverage && (s.coverage.planned || []).length > 0 && (
          <div className="card pad col">
            <h3>Coverage of the plan</h3>
            <div className="row wrap" style={{ gap: 16, alignItems: "center" }}>
              <Donut size={110} title="Plan coverage" center={`${Math.round((100 * (s.coverage.tested || []).length) / s.coverage.planned.length)}%`} sub="tested"
                parts={[{ label: "Tested", value: (s.coverage.planned || []).filter((p) => (s.coverage.tested || []).includes(p)).length, tone: "good" }, { label: "Not tested", value: (s.coverage.planned || []).filter((p) => !(s.coverage.tested || []).includes(p)).length, tone: "warn" }]} />
              <div className="row wrap grow" style={{ gap: 6 }}>{(s.coverage.planned || []).map((p, i) => <Chip key={i} kind={(s.coverage.tested || []).includes(p) ? "good" : "warn"}>{(s.coverage.tested || []).includes(p) ? "✓" : "○"} {p}</Chip>)}</div>
            </div>
          </div>
        )}
        {s.ai_agreement && !isIsha && (
          <div className="card pad col">
            <h3>Interviewer vs Isha</h3>
            <div className="rc-agree"><div className={"rc-agree-meter " + (s.ai_agreement.level === "high" ? "good" : s.ai_agreement.level === "medium" ? "warn" : "bad")}><i style={{ width: `${Math.max(6, 100 - (Number(s.ai_agreement.avg_diff) || 0) * 25)}%` }} /></div>
              <span>Agreement <b>{s.ai_agreement.level}</b>: they differ by <b>{s.ai_agreement.avg_diff}</b> points on average across {s.ai_agreement.pairs} competencies.</span></div>
          </div>
        )}
        {s.integrity && (
          <div className="card pad col">
            <div className="row"><h3>Integrity</h3><Integrity count={s.integrity.warnings} /></div>
            {!s.integrity.events?.length ? <div className="rc-clean"><span aria-hidden="true">✓</span> No events recorded.</div> : <IntegrityTimeline events={s.integrity.events} />}
            {s.integrity.events?.length > 0 && <div className="tbl-wrap"><table className="tbl"><thead><tr><th>Event</th><th>When</th><th>Counted</th></tr></thead><tbody>
              {s.integrity.events.map((e, i) => <tr key={i}><td><span className="dot" style={{ color: e.counted ? (e.severity === "high" ? "var(--bad)" : "#E08A1E") : "var(--faint)" }} /> {e.label}{e.q != null ? ` · question ${e.q + 1}` : ""}</td><td className="small">{fmtDate(e.at, true)}</td><td>{e.counted ? <Chip kind={e.severity === "high" ? "bad" : "warn"}>Counted</Chip> : <span className="faint small">Notice</span>}</td></tr>)}</tbody></table></div>}
            {s.integrity.snapshots?.length > 0 && <>
              <b className="small">Camera at the moment of each face warning</b>
              <div className="row wrap" style={{ gap: 8 }}>{s.integrity.snapshots.map((x, i) => (
                <figure key={i} style={{ margin: 0, width: 150 }}><img src={x.image} alt={`${x.label} at ${fmtDate(x.at, true)}`} style={{ width: "100%", borderRadius: 8, display: "block" }} />
                  <figcaption className="tiny muted">{x.label} · {fmtDate(x.at, true)}</figcaption></figure>))}</div>
            </>}
          </div>
        )}
      </div>

      {!mcq && qs.length > 0 && coverageMode(qs) && (
        <div className="card">
          <div className="card-h"><h3>Answer quality by question</h3><span className="small muted">{coverageMode(qs) === "coverage" ? "Share of a good answer's points the candidate covered." : "Score for each answer, as a percentage."} Click a bar to read the answer.</span></div>
          <div className="pad"><QuestionCoverage questions={qs} scale={scale} /></div>
        </div>
      )}

      <QuestionList {...qProps} />
      {r.history?.length > 0 && (
        <div className="card pad col"><h3>Version history</h3>
          {r.history.map((h, i) => <div key={i} className="small"><b>v{h.version}</b> · {h.by} · {fmtDate(h.at, true)}{h.verdict ? ` · verdict ${h.verdict}` : ""}{h.note ? ` · “${h.note}”` : ""}
            {(h.changes || []).map((c, j) => <div key={j} className="muted" style={{ paddingLeft: 16 }}>{c.name}: {c.from} → {c.to} ({c.reason})</div>)}</div>)}
        </div>
      )}
    </div>
  );
}

function QuestionList({ r, s, scale, setClosedQ, isOpen, toggleQ, onChanged }) {
  if (!s.questions?.length) return null;
  return (
    <>
        <div className="card">
          <div className="card-h"><h3>{s.kind === "mcq" ? "Questions and answers" : "Question by question"}</h3>
            <span className="small muted">{s.questions.length} question{s.questions.length === 1 ? "" : "s"}
              {/* V02.01.01: how the answers were filed */}
              {s.review && !s.review.undone && (s.review.turns || s.review.source) && " · filed by Isha reading the whole transcript"}
              {s.review?.undone && " · filed as during the interview"}
</span>
            <span className="right row" style={{ gap: 4 }}>
              <Btn size="sm" kind="ghost" onClick={() => setClosedQ(new Set())}>Expand all</Btn>
              <Btn size="sm" kind="ghost" onClick={() => setClosedQ(new Set(s.questions.map((_, i) => i)))}>Collapse all</Btn></span></div>
          {s.questions.map((q, i) => {
            const mcq = s.kind === "mcq";
            const letter = (k) => (typeof k === "number" && k >= 0 ? String.fromCharCode(65 + k) : "");
            const chosen = q.chosen == null || q.chosen === "" ? null : Number(q.chosen);
            return (
              <div key={i} id={`q${i + 1}`} className="list-row qa-row" style={{ alignItems: "flex-start", flexDirection: "column", gap: 8 }}>
                <button className="row" aria-expanded={isOpen(i)} style={{ width: "100%", border: 0, background: "none", cursor: "pointer", textAlign: "left", padding: 0, color: "inherit" }} onClick={() => toggleQ(i)}>
                  <span className="chip">{i + 1}</span><b className="grow">{q.q}</b>
                  {q.kind === "followup" && <Chip kind="gold">Follow-up</Chip>}
                  {q.extra && <Chip kind="info">Not in the plan</Chip>}
                  {q.added && <Chip kind="brand">{q.added_from === "resume" ? "From the resume" : "From the job description"}</Chip>}
                  {q.skipped && <Chip>Skipped by the interviewer: not counted</Chip>}
                  {q.followups?.length > 0 && <Chip kind="gold">{q.followups.length} follow-up{q.followups.length === 1 ? "" : "s"}</Chip>}
                  {q.topic && <Chip>{q.topic}</Chip>}
                  {mcq ? <Chip kind={q.correct ? "good" : chosen == null ? "" : "bad"}>{q.correct ? "Correct" : chosen == null ? "Skipped" : "Wrong"}</Chip> : q.score != null && <Score value={q.score} scale={scale} />}
                  {q.time && (r.video?.parts?.length && r.audience !== "candidate" && r.audience !== "client"
                    ? <span role="button" tabIndex={0} className="linkbtn tiny" title="Play the video from here" onKeyDown={(e) => { if (e.key === "Enter") { e.stopPropagation(); seekRecording(toSecs(q.time)); } }} onClick={(e) => { e.stopPropagation(); seekRecording(toSecs(q.time)); }}>▶ {q.time}</span>
                    : <span className="tiny faint">{q.time}</span>)}
                  <span className="tiny faint" aria-hidden="true">{isOpen(i) ? "▾" : "▸"}</span>
                </button>
                {/* V02.01.04: a reviewer files this answer under another question of the report, or takes it off */}
                {isOpen(i) && !mcq && onChanged && r.can?.review && r.audience !== "candidate" && r.audience !== "client" && s.questions.length > 1 &&
                  <RefileAnswer r={r} i={i} qs={s.questions} onChanged={onChanged} />}
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
                ) : q.skipped ? (
                  <div className="small muted">Not asked: the interviewer skipped this question{q.skip_reason ? `: “${q.skip_reason}”` : "."} It isn't scored.</div>
                ) : (<>
                  {q.summary && <div className="qa-brief"><span className="qa-l">In brief</span> {q.summary}</div>}
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
                  {/* V02.01.02: follow-ups are part of their question */}
                  {q.followups?.length > 0 && q.a !== undefined && <div className="qa-fus">
                    <div className="qa-l">Follow-ups</div>
                    {q.followups.map((f, j) => <div key={j} className="qa-fu"><b className="small">“{f.q}”</b>{f.time && <span className="tiny faint"> {f.time}</span>}
                      <div className="small">{f.a || <span className="muted">(no answer)</span>}</div></div>)}
                  </div>}
                </>))}
              </div>
            );
          })}
        </div>
    </>
  );
}

/** The candidate's feedback: what went well, what to work on, what to do next; and their own answers when shared. */
function CandidateView({ r, s, scale, qProps }) {
  const res = r.result || {};
  const pct = res.score != null ? scorePct(res.score) : null;
  const cards = [["good", "✓", "What went well", s.strengths], ["warn", "↗", "What to work on", s.gaps], ["info", "➜", "Next steps", s.next_steps]];
  const qs = (s.questions || []).filter((q) => !q.skipped);   // V02.01.02: a skipped question is for the hiring team only
  return (
    <div className="col report-view" style={{ gap: 16 }}>
      <AgentNote agent="disha" title="Your feedback">Here's what the team saw, in plain words. Use it to get even better.</AgentNote>
      {(pct != null || res.cleared != null) && (
        <div className="card rc-hero good"><div className="rc-hero-band" />
          <div className="row wrap" style={{ gap: 20, alignItems: "center", padding: "16px 20px" }}>
            {pct != null && <Gauge pct={pct} sub="your score" tone={res.cleared ? "good" : undefined} />}
            <div className="col grow" style={{ gap: 4 }}>
              <h3 style={{ margin: 0 }}>{r.round}</h3>
              {res.cleared && <div className="rc-verdict good"><b>You cleared this round</b></div>}
              {res.next_step && <span className="small">{res.next_step}</span>}
            </div>
          </div>
        </div>
      )}
      <div className="grid g3">
        {cards.map(([tone, icon, title, items]) => (
          <div key={title} className={"card pad rc-list " + tone}>
            <h3><span aria-hidden="true">{icon}</span> {title} <span className="rc-count">{(items || []).length}</span></h3>
            {(items || []).length ? <ul>{items.map((x, i) => <li key={i}>{typeof x === "string" ? x : x.title || x.name}</li>)}</ul> : <span className="muted small">Nothing here this time.</span>}
          </div>
        ))}
      </div>
      {(s.shared_summary || s.shared_parts?.length > 0) && (
        <div className="card pad col" style={{ gap: 8 }}>
          <h3 style={{ margin: 0 }}>Summary of your interview</h3>
          {s.shared_summary && <p style={{ margin: 0 }}>{s.shared_summary}</p>}
          {s.shared_parts?.length > 0 && <ol className="col" style={{ gap: 8, margin: 0, paddingLeft: 18 }}>{s.shared_parts.map((p, i) => <li key={i}><b className="small">{p.q}</b><div className="small">{p.summary}</div></li>)}</ol>}
        </div>
      )}
      {s.kind === "mcq" && qs.length > 0 && (
        <div className="card"><div className="card-h"><h3>Your answers at a glance</h3></div>
          <div className="rc-grid2 pad">
            <Donut title="Your answers" center={`${qs.filter((q) => q.correct).length}/${qs.length}`} sub="correct"
              parts={[{ label: "Correct", value: qs.filter((q) => q.correct).length, tone: "good" }, { label: "Wrong", value: qs.filter((q) => !q.correct && q.chosen != null && q.chosen !== "").length, tone: "bad" }, { label: "Skipped", value: qs.filter((q) => q.chosen == null || q.chosen === "").length, tone: "none" }]} />
            <div className="col" style={{ gap: 14 }}><div><div className="rc-k">Every question</div><AnswerMap questions={qs} /></div><div><div className="rc-k">By skill</div><SkillStack questions={qs} /></div></div>
          </div></div>
      )}
      {s.kind !== "mcq" && coverageMode(qs) && (
        <div className="card"><div className="card-h"><h3>How much of a good answer you covered</h3></div><div className="pad"><QuestionCoverage questions={qs} scale={scale} /></div></div>
      )}
      <QuestionList {...qProps} />
    </div>
  );
}

/** V02.01.01: Isha's brief summary of the whole interview, written when the scorecard (or the AI interview) was
 * submitted, and the choice to share the summaries with the candidate (off by default). */
function IshaSummary({ r, s }) {
  const toast = useToast();
  const sum = s.isha_summary;
  const [share, setShare] = useState(s.share || {});
  const [text, setText] = useState((s.share || {}).overall_text || sum.text || "");
  const [busy, setBusy] = useState(false);
  const [edit, setEdit] = useState(false);
  const canShare = r.can?.share || r.can?.review;
  const parts = (s.questions || []).filter((q) => q.summary).length;
  const save = async (patch, msg) => {
    const before = share;
    setBusy(true); setShare({ ...share, ...patch });
    try { const out = await api.post(`/reports/${r.id}/share-summaries`, patch); setShare(out.share || { ...before, ...patch }); toast(msg, "good"); setEdit(false); }
    catch (e) { setShare(before); toast(e.message, "bad"); }
    finally { setBusy(false); }
  };
  return (
    <div className="card pad col isha-summary" style={{ gap: 8 }}>
      <div className="row wrap" style={{ gap: 8 }}>
        <h3 className="grow" style={{ margin: 0 }}>Isha's summary</h3>
      </div>
      <p style={{ margin: 0 }}>{(share.overall && share.overall_text) || sum.text}</p>
      <div className="grid g3 small">
        {sum.strengths?.length > 0 && <div><b>Strengths</b><ul>{sum.strengths.map((x, i) => <li key={i}>{x}</li>)}</ul></div>}
        {sum.gaps?.length > 0 && <div><b>Gaps</b><ul>{sum.gaps.map((x, i) => <li key={i}>{x}</li>)}</ul></div>}
        {sum.claims?.length > 0 && <div><b>Claims to check</b><ul>{sum.claims.map((x, i) => <li key={i}>{x}</li>)}</ul></div>}
      </div>
      {parts > 0 && <span className="tiny muted">Each question below has a short “In brief” summary too.</span>}
      {canShare && <div className="share-sum col" style={{ gap: 6 }}>
        <b className="small">Share with the candidate</b>
        <label className="check small"><input type="checkbox" checked={!!share.overall} disabled={busy}
          onChange={(e) => save({ overall: e.target.checked }, e.target.checked ? "The candidate will see the overall summary." : "The overall summary is no longer shared.")} />Overall summary</label>
        {parts > 0 && <label className="check small"><input type="checkbox" checked={!!share.topics} disabled={busy}
          onChange={(e) => save({ topics: e.target.checked }, e.target.checked ? "The candidate will see the summary of each question." : "Question summaries are no longer shared.")} />Summary of each question ({parts})</label>}
        {share.overall && (edit
          ? <div className="col" style={{ gap: 6 }}><Textarea value={text} onChange={(e) => setText(e.target.value)} aria-label="Summary the candidate sees" />
            <div className="row" style={{ gap: 6 }}><Btn size="sm" kind="primary" busy={busy} onClick={() => save({ overall_text: text }, "Saved the summary the candidate sees.")}>Save</Btn><Btn size="sm" kind="ghost" onClick={() => setEdit(false)}>Cancel</Btn></div></div>
          : <button type="button" className="linkbtn tiny" onClick={() => setEdit(true)}>Edit what the candidate sees</button>)}
        <span className="tiny muted">Off by default. The candidate sees it with their feedback, never the scores, quotes or notes. The Ask Isha chat is never in the report.</span>
      </div>}
    </div>
  );
}

function RefileAnswer({ r, i, qs, onChanged }) {
  const toast = useToast();
  const ask = useConfirm();
  const go = async (v) => {
    if (!v) return;
    const target = v === "remove" ? "off the report" : `under “${qs[+v].topic || qs[+v].q}”`;
    const reason = await ask({ title: `File this answer ${target}?`, text: "It joins that question's answer and is scored again. The change is kept in the report's history.",
      input: { label: "Why? (kept with the change)", required: true, max: 300 }, yes: "File it" });
    if (!reason) return;
    try { const out = await api.post(`/reports/${r.id}/refile`, { index: i, to: v === "remove" ? "remove" : +v, reason }); onChanged(out); toast("Filed. The report was updated as a new version.", "good"); }
    catch (e) { toast(e.message, "bad"); }
  };
  return (
    <div className="row small" style={{ gap: 8 }}>
      <span className="tiny muted">Wrong question?</span>
      <select className="select file-under" value="" onChange={(e) => go(e.target.value)} aria-label="File this answer under another question">
        <option value="">File under…</option>
        <optgroup label="Questions in this report">{qs.map((q, k) => k !== i && !q.skipped && <option key={k} value={k}>{k + 1}. {(q.topic || q.q || "").slice(0, 60)}</option>)}</optgroup>
        <optgroup label="Other"><option value="remove">Remove it from the report</option></optgroup>
      </select>
    </div>
  );
}


/** Isha's assessment on the report (V02.01.07: no hiring recommendation and no record of what the interviewer changed:
 * the scores above are the final ones). */
function IshaAssessment({ s }) {
  const i = s.isha || {};
  const v = s.interviewer || {};
  const [open, setOpen] = useState(false);
  return (
    <div className="card pad col" style={{ gap: 10 }}>
      <div className="row wrap" style={{ gap: 8 }}>
        <h3 className="grow" style={{ margin: 0 }}>Isha's assessment</h3>
        {i.insufficient ? <Chip kind="warn">Not enough evidence</Chip> : <>
          {i.confidence && <Chip kind={i.confidence === "high" ? "good" : i.confidence === "low" ? "warn" : ""}>Confidence: {i.confidence}</Chip>}
          {i.rank && <Chip kind="info">{i.rank.place} of {i.rank.of} for this job{i.rank.same_set ? " · same questions" : ""}</Chip>}
        </>}
      </div>
      {i.reason && <p className="small" style={{ margin: 0 }}>{String(i.reason).replace(/^(Proceed|Hold|Do not proceed): /, "").replace(/ Confidence is low, so Isha says Hold rather than Do not proceed\./, "")}</p>}
      {!i.insufficient && <div className="grid g3 small">
        <div><span className="tiny b muted">STRENGTHS</span>{(i.strengths || []).length ? <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{i.strengths.map((x) => <li key={x}>{x}</li>)}</ul> : <div className="muted">None stood out</div>}</div>
        <div><span className="tiny b muted">CONCERNS</span>{(i.concerns || []).length ? <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{i.concerns.map((x) => <li key={x}>{x}</li>)}</ul> : <div className="muted">None</div>}</div>
        <div><span className="tiny b muted">RED FLAGS</span>{(i.flags || []).length ? <ul style={{ margin: "4px 0 0", paddingLeft: 18, color: "var(--bad)" }}>{i.flags.map((x) => <li key={x}>{x}</li>)}</ul> : <div className="muted">None</div>}</div>
      </div>}
      {(i.topics || []).length > 0 && <>
        <button type="button" className="linkbtn small" style={{ alignSelf: "flex-start" }} onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? "Hide" : "Show"} everything discussed ({i.topics.length} topic{i.topics.length > 1 ? "s" : ""})</button>
        {open && <div className="col" style={{ gap: 6 }}>{i.topics.map((t) => (
          <div key={t.topic} className="sentence col" style={{ gap: 2 }}>
            <div className="row" style={{ gap: 6 }}><b className="small grow">{t.topic}</b>{!t.planned && <Chip>Not in the plan</Chip>}<Chip>{t.score}/5</Chip></div>
            {t.evidence && <span className="small">“{t.evidence}”</span>}
            {(t.showed || t.missing) && <span className="tiny muted">{t.showed}{t.missing ? ` · Missing: ${t.missing}` : ""}</span>}
          </div>))}</div>}
      </>}
      {v.confirmed === false && <div className="sc-note warn" role="note"><b>Not yet confirmed by the interviewer.</b> No scorecard was submitted within 24 hours, so these are Isha's scores. The recommendation is for the hiring team.</div>}
    </div>
  );
}
