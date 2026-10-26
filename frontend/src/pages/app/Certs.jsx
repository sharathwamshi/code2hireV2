import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../../api";
import DataTable from "../../components/DataTable";
import { AgentNote } from "../../components/Mascot";
import { PageHead } from "../../components/Shell";
import { Btn, Chip, Field, Input, ListEditor, Loading, Select, Status, Switch, Tabs, fmtDate, useAction, useAsync, useToast } from "../../components/ui";

export function CertsList() {
  const nav = useNavigate();
  const [run] = useAction();
  return (
    <>
      <PageHead title="Certifications" sub="Design exams, set grading and validity, and issue verifiable certificates."
        actions={<Btn kind="primary" onClick={() => run(() => api.post("/certs", { name: "New certification", sections: [{ type: "mcq", name: "Knowledge", weight: 100, questions: 10, minutes: 20 }] })).then((c) => nav(`/app/certifications/${c.id}`))}>New certification</Btn>} />
      <DataTable endpoint="/certs" defaultSort="created" onRow={(r) => !r.global && nav(`/app/certifications/${r.id}`)}
        filters={[{ key: "status", label: "Status", options: ["draft", "review", "published", "retired"] }]}
        columns={[{ key: "name", label: "Certification", sort: "name", render: (r) => <div><b>{r.name}</b>{r.global && <Chip kind="brand">Code2Hire Verified</Chip>}<div className="tiny muted">{(r.skills || []).join(", ")} · L{r.level}</div></div> },
          { key: "sections", label: "Sections", render: (r) => (r.sections || []).map((s) => `${s.name || s.type} ${s.weight}%`).join(" · ") },
          { key: "pass", label: "Pass at", render: (r) => r.pass_rules?.cutoff + "%" }, { key: "attempts", label: "Attempts" }, { key: "holders", label: "Holders" },
          { key: "status", label: "Status", sort: "status", render: (r) => <span className="row"><Status s={r.status} />{r.problems?.length > 0 && <Chip kind="warn">{r.problems.length} to fix</Chip>}</span> }]} />
    </>
  );
}

const STEPS = ["Basics", "Sections", "Grading", "Proctoring", "Eligibility", "Attempts and fee", "Validity and output", "Review and publish"];

export function CertBuilder() {
  const { id } = useParams();
  const toast = useToast();
  const { data: c, setData } = useAsync(() => api.get(`/certs/${id}`), [id]);
  const [step, setStep] = useState(0);
  const [tab, setTab] = useState("config");
  const [run, busy] = useAction();
  if (!c) return <Loading />;
  const locked = c.status === "published";
  const set = (k, v) => setData({ ...c, [k]: v });
  const save = async (extra = {}) => { const r = await run(() => api.patch(`/certs/${id}`, { ...pick(c), ...extra })); setData({ ...c, ...r }); return r; };
  const sections = c.sections || [];
  const total = sections.reduce((a, s) => a + +(s.weight || 0), 0);
  return (
    <>
      <PageHead back="/app/certifications" title={c.name} sub={<span className="row"><Status s={c.status} /><span>{(c.skills || []).join(", ")} · Level {c.level}</span></span>}
        actions={<>{!locked && <Btn busy={busy} onClick={() => save().then(() => toast("Saved", "good"))}>Save draft</Btn>}{locked && <Btn kind="danger" onClick={() => run(() => api.post(`/certs/${id}/retire`), "Retired").then(setData)}>Retire</Btn>}</>} />
      <Tabs value={tab} onChange={setTab} tabs={[["config", "Configuration"], ["attempts", "Attempts and holders"]]} />
      {tab === "attempts" ? <Attempts id={id} /> : (
        <div className="card">
          <div className="stepper" style={{ borderBottom: "1px solid var(--line)" }}>
            {STEPS.map((s, i) => <span key={s} style={{ display: "contents" }}>{i > 0 && <span className="sep" />}<button className={"st " + (i === step ? "on" : i < step ? "done" : "")} onClick={() => setStep(i)}><i>{i + 1}</i>{s}</button></span>)}
          </div>
          <div className="card-b col" style={{ gap: 14, minHeight: 320 }}>
            {locked && step < 7 && <AgentNote agent="hira">This certification is published. Sections and grading are locked once people take it; duplicate it to make a new version.</AgentNote>}
            {step === 0 && <div className="grid g2">
              <Field label="Name"><Input value={c.name} onChange={(e) => set("name", e.target.value)} /></Field>
              <Field label="Issued by (shown on the certificate)"><Input value={c.issuer || ""} onChange={(e) => set("issuer", e.target.value)} /></Field>
              <Field label="Skills certified"><ListEditor value={c.skills || []} onChange={(v) => set("skills", v)} /></Field>
              <Field label="Level"><Select value={String(c.level)} onChange={(v) => set("level", +v)} options={"12345".split("").map((l) => ({ value: l, label: "Level " + l }))} /></Field>
            </div>}
            {step === 1 && <>
              <div className="row"><b>Sections</b><Chip kind={Math.abs(total - 100) < .5 ? "good" : "bad"}>Weights total {total}%</Chip></div>
              {sections.map((s, i) => (
                <div key={i} className="card pad grid g4" style={{ alignItems: "end" }}>
                  <Field label="Type"><Select disabled={locked} value={s.type} onChange={(v) => upd(i, { type: v })} options={[{ value: "mcq", label: "MCQ" }, { value: "ai_interview", label: "AI interview (voice)" }]} /></Field>
                  <Field label="Name"><Input disabled={locked} value={s.name || ""} onChange={(e) => upd(i, { name: e.target.value })} /></Field>
                  <Field label="Weight %"><Input disabled={locked} type="number" value={s.weight} onChange={(e) => upd(i, { weight: +e.target.value })} /></Field>
                  <Field label="Questions"><Input disabled={locked} type="number" value={s.questions} onChange={(e) => upd(i, { questions: +e.target.value })} /></Field>
                  <Field label="Minutes"><Input disabled={locked} type="number" value={s.minutes} onChange={(e) => upd(i, { minutes: +e.target.value })} /></Field>
                  <Field label="Minimum % in this section"><Input disabled={locked} type="number" value={s.minimum || ""} onChange={(e) => upd(i, { minimum: +e.target.value || null })} /></Field>
                  {s.type === "mcq" ? <label className="check"><input type="checkbox" disabled={locked} checked={!!s.negative_marking} onChange={(e) => upd(i, { negative_marking: e.target.checked })} />Negative marking</label>
                    : <Field label="Difficulty"><Select disabled={locked} value={s.difficulty || "medium"} onChange={(v) => upd(i, { difficulty: v })} options={["easy", "medium", "hard"]} /></Field>}
                  <Btn kind="ghost" disabled={locked} onClick={() => set("sections", sections.filter((_, j) => j !== i))}>Remove</Btn>
                </div>
              ))}
              <Btn disabled={locked} onClick={() => set("sections", [...sections, { type: "ai_interview", name: "Spoken interview", weight: 0, questions: 3, minutes: 15 }])}>+ Add section</Btn>
            </>}
            {step === 2 && <div className="grid g3">
              {[["cutoff", "Pass at (%)"], ["merit", "Merit at (%)"], ["distinction", "Distinction at (%)"]].map(([k, l]) => <Field key={k} label={l}><Input disabled={locked} type="number" value={c.pass_rules?.[k] ?? ""} onChange={(e) => set("pass_rules", { ...c.pass_rules, [k]: +e.target.value })} /></Field>)}
              <p className="small muted" style={{ gridColumn: "1/-1" }}>Final score = weighted average of sections. A section minimum fails the exam even if the total passes.</p>
            </div>}
            {step === 3 && <div className="col">
              <Field label="Proctoring"><Select value={c.proctoring} onChange={(v) => set("proctoring", v)} options={[{ value: "none", label: "None (practice-style)" }, { value: "ai", label: "AI proctoring (fullscreen, tab, face, paste)" }, { value: "ai_human", label: "AI proctoring + human review of flags" }]} /></Field>
              <label className="check"><input type="checkbox" checked={!!c.id_check} onChange={(e) => set("id_check", e.target.checked)} />Ask for a photo ID before the exam</label>
              <p className="small muted">Warnings allowed and instant-pause events come from your company integrity settings.</p>
            </div>}
            {step === 4 && <div className="grid g3">
              <Field label="Prerequisite skill (verified)"><Input value={c.eligibility?.prerequisite_skill || ""} onChange={(e) => set("eligibility", { ...c.eligibility, prerequisite_skill: e.target.value })} /></Field>
              <Field label="At least level"><Input type="number" value={c.eligibility?.prerequisite_level || ""} onChange={(e) => set("eligibility", { ...c.eligibility, prerequisite_level: +e.target.value })} /></Field>
              <Field label="Who can take it"><Select value={c.eligibility?.audience || "everyone"} onChange={(v) => set("eligibility", { ...c.eligibility, audience: v })} options={["everyone", "applicants", "invite_only"]} /></Field>
            </div>}
            {step === 5 && <div className="grid g3">
              <Field label="Attempts allowed"><Input type="number" value={c.attempts_allowed} onChange={(e) => set("attempts_allowed", +e.target.value)} /></Field>
              <Field label="Days between attempts"><Input type="number" value={c.cooldown_days} onChange={(e) => set("cooldown_days", +e.target.value)} /></Field>
              <Field label="Fee (₹, 0 = free)"><Input type="number" value={c.fee} onChange={(e) => set("fee", +e.target.value)} /></Field>
            </div>}
            {step === 6 && <div className="col">
              <Field label="Valid for (months)"><Input type="number" value={c.validity_months} onChange={(e) => set("validity_months", +e.target.value)} style={{ width: 140 }} /></Field>
              {[["verification_page", "Public verification page"], ["linkedin", "Add-to-LinkedIn button"], ["badge", "Also update the candidate's skill badge"], ["revoke_on_integrity", "Hold for review if integrity warnings exceed the limit"]].map(([k, l]) =>
                <div key={k} className="row"><Switch on={!!c.output?.[k]} label={l} onChange={(v) => set("output", { ...c.output, [k]: v })} /><span>{l}</span></div>)}
            </div>}
            {step === 7 && <div className="col">
              {c.problems?.length ? <AgentNote agent="hira" title="Fix these before publishing">{c.problems.map((p, i) => <div key={i}>• {p}</div>)}</AgentNote> : <AgentNote agent="hira" title="Ready to publish">Everything checks out. Save first if you changed anything.</AgentNote>}
              <div className="grid g3"><div className="card pad"><div className="small muted">Sections</div><b>{sections.length} · {total}%</b></div><div className="card pad"><div className="small muted">Pass / merit / distinction</div><b>{c.pass_rules?.cutoff} / {c.pass_rules?.merit} / {c.pass_rules?.distinction}</b></div><div className="card pad"><div className="small muted">Valid</div><b>{c.validity_months} months</b></div></div>
              {!locked && <div className="row"><Btn busy={busy} onClick={() => save().then(() => run(() => api.post(`/certs/${id}/publish`), "Published").then(setData))} kind="primary">Save and publish</Btn>
                <Btn busy={busy} onClick={() => save().then(() => run(() => api.post(`/certs/${id}/publish`, { request_verified: true }), "Sent to Code2Hire for the Verified mark").then(setData))}>Ask for “Code2Hire Verified”</Btn></div>}
            </div>}
          </div>
          <div className="modal-f">{step > 0 && <Btn onClick={() => setStep(step - 1)}>Back</Btn>}{step < 7 && <Btn kind="primary" onClick={() => { if (!locked) save(); setStep(step + 1); }}>Next</Btn>}</div>
        </div>
      )}
    </>
  );
  function upd(i, p) { set("sections", sections.map((s, j) => (j === i ? { ...s, ...p } : s))); }
}

const pick = (c) => Object.fromEntries(["name", "skills", "level", "issuer", "sections", "pass_rules", "proctoring", "id_check", "eligibility", "fee", "attempts_allowed", "cooldown_days", "validity_months", "output"]
  .filter((k) => k in c).filter((k) => !(c.status === "published" && (k === "sections" || k === "pass_rules"))).map((k) => [k, c[k]]));

function Attempts({ id }) {
  const [rk, setRk] = useState(0);
  const [run] = useAction();
  return (
    <DataTable endpoint={`/certs/${id}/attempts`} defaultSort="created" reloadKey={rk} filters={[{ key: "status", label: "Status", options: ["in_progress", "review", "completed"] }]}
      columns={[{ key: "name", label: "Candidate", render: (r) => <div><b>{r.name}</b><div className="tiny muted">{r.email}</div></div> },
        { key: "score", label: "Score", sort: "score", render: (r) => r.score != null ? r.score + "%" : "—" }, { key: "grade", label: "Grade", render: (r) => r.grade || "—" },
        { key: "passed", label: "Result", render: (r) => r.passed == null ? "—" : r.passed ? <Chip kind="good">Certified</Chip> : <Chip kind="bad">Not passed</Chip> },
        { key: "status", label: "Status", render: (r) => <Status s={r.status} /> }, { key: "created_at", label: "Started", sort: "created", render: (r) => fmtDate(r.created_at) },
        { key: "act", label: "", render: (r) => r.status === "review" && <span className="row"><Btn size="sm" kind="primary" onClick={() => run(() => api.post(`/cert-attempts/${r.id}/decide`, { approve: true }), "Certified").then(() => setRk(rk + 1))}>Certify</Btn><Btn size="sm" kind="danger" onClick={() => run(() => api.post(`/cert-attempts/${r.id}/decide`, { approve: false }), "Not certified").then(() => setRk(rk + 1))}>Decline</Btn></span> }]} />
  );
}
