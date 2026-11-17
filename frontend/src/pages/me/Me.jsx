// Candidate portal (V02.00.10): Home, Jobs, Applications, Practice, Skill checks, Learning paths, Certifications,
// Feedback and Profile, rebuilt from the review of the live site and the PDF design. Item ids (HOM-01, JOB-07 ...)
// refer to Code2Hire_Portal_Review_2.xlsx; CP-xxx to the candidate QA tracker.
import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, download } from "../../api";
import { useAuth } from "../../auth";
import { Disha } from "../../components/Mascot";
import ReportView from "../../components/ReportView";
import ResumeReview, { ResumeFileLine, ResumeInput } from "../../components/ResumeReview";
import { PageHead } from "../../components/Shell";
import { PasswordForm } from "../../components/SetPassword";
import SystemCheck from "../../components/SystemCheck";
import { Bar, Btn, Chip, Empty, Field, Input, Loading, Modal, ROUND_LABEL, Ring, Score, Select, Seg, Status, Textarea, displayName, fmtDate, fmtTime, inr, useAction, useAsync, useConfirm, useToast } from "../../components/ui";

export const LEVELS = { 1: ["Beginner", "Knows the basics and the words."], 2: ["Working", "Can build features with some guidance."],
  3: ["Independent", "Works without help on everyday tasks."], 4: ["Advanced", "Designs solutions and reviews others' work."], 5: ["Expert", "Leads, teaches and solves the hardest problems."] };
export const levelName = (l) => `Level ${l} · ${LEVELS[l]?.[0] || ""}`;
const askDisha = (q) => window.dispatchEvent(new CustomEvent("c2h:disha", { detail: { q } }));

/** GLB-10: a page that can't load says so and offers Retry. */
function Failed({ error, retry }) {
  return <div className="card pad col" role="alert" style={{ gap: 8 }}><b>This page didn't load</b><span className="small muted">{String(error)}</span><div><Btn onClick={retry}>Retry</Btn></div></div>;
}

/** Tile that opens a page (CP-001 / HOM-03). */
function StatTile({ to, label, value, help, action, children }) {
  const nav = useNavigate();
  return (
    <button type="button" className="card stat stat-link" onClick={() => nav(to)} aria-label={`${label}: ${value}. ${action}`}>
      {children || <><div className="l">{label}</div><div className="v">{value}</div></>}
      {help && <div className="tiny muted">{help}</div>}
      <span className="small stat-go">{action} →</span>
    </button>
  );
}

// ---------------------------------------------------------------------------------------------------------- Home

export function Home() {
  const nav = useNavigate();
  const { data: d, reload, error } = useAsync(() => api.get("/me"), []);
  const [path, setPath] = useState(null);
  const [goal, setGoal] = useState("");
  const [chat, setChat] = useState("");
  const [run, busy] = useAction();
  // bug 8 / gap 9 (V02.00.07): the home page updates by itself when an invite, a schedule or a change arrives
  useEffect(() => {
    const again = () => reload();
    window.addEventListener("c2h:news", again);
    const t = setInterval(again, 60000);
    return () => { window.removeEventListener("c2h:news", again); clearInterval(t); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const loc = useLocation();
  useEffect(() => { if (d && loc.hash) document.getElementById(loc.hash.slice(1))?.scrollIntoView({ behavior: "smooth", block: "start" }); }, [!!d, loc.key]); // eslint-disable-line react-hooks/exhaustive-deps
  if (error && !d) return <Failed error={error} retry={reload} />;
  if (!d) return <Loading />;
  const upcoming = d.invites.filter((i) => i.scheduled_at && ["scheduled", "invited", "in_progress"].includes(i.status))
    .sort((a, b) => new Date(a.scheduled_at) - new Date(b.scheduled_at));
  const st = d.completeness;
  const ns = d.next_steps;
  const first = displayName(d.user.name).split(" ")[0];
  const showPath = (g) => run(() => api.post("/me/path", { goal: g })).then((p) => { setPath(p); setGoal(""); reload(); });
  return (
    <>
      <PageHead title={`Hi ${first}`} sub="Learn, prove your skills and get matched. Disha keeps track." />
      {upcoming.length > 0 && <div id="upcoming" className="col" style={{ gap: 12 }}>
        {upcoming.map((i) => <Upcoming key={i.attempt_id} item={i} setupOk={i.setup_ok || d.setup_tested} onJoin={() => nav(`/room/${i.attempt_id}`)} onSetup={() => nav("/me/setup")} />)}
      </div>}
      {d.invites.length > 0 && (
        <div className="card">
          <div className="card-h"><h3>Waiting for you</h3><Chip kind="brand">{d.invites.length}</Chip><Btn size="sm" className="right" onClick={() => nav("/me/setup")}>Test my setup</Btn></div>
          {d.invites.map((i) => <div key={i.attempt_id} className="list-row"><div className="grow"><b>{i.name}</b><div className="small muted">{i.job} · {ROUND_LABEL[i.type]}{i.deadline_at ? ` · complete by ${fmtDate(i.deadline_at, true)}` : ""}</div>
            {i.instructions?.length > 0 && <div className="tiny muted" style={{ marginTop: 2 }}>{i.instructions.slice(0, 2).join(" ")} {i.setup_ok || d.setup_tested ? <Chip kind="good">✓ Setup tested</Chip> : <button type="button" className="linkbtn" onClick={() => nav("/me/setup")}>Test my setup</button>}</div>}</div>
            <Status s={i.status} />{i.paper_pending ? <Chip kind="warn" title="The hiring team checks your questions first. We'll tell you when you can start.">Being prepared</Chip> : i.type !== "f2f_isha" && i.type !== "f2f_human" ? <Btn kind="primary" onClick={() => nav(`/room/${i.attempt_id}`)}>{i.status === "in_progress" || i.status === "paused" ? "Continue" : "Start"}</Btn> : <><span className="small muted">{i.scheduled_at ? "Live · " + fmtDate(i.scheduled_at, true) : "Live video interview"}</span><JoinButton item={i} onJoin={() => nav(`/room/${i.attempt_id}`)} /></>}</div>)}
        </div>
      )}
      <div className="grid g4">
        <StatTile to="/me/profile" label="Profile strength" value={`${st.pct}%`} action={st.pct >= 100 ? "View profile" : "Complete profile"}>
          <div className="row"><Ring value={st.pct} label={st.pct + "%"} neutral /><div><div className="l">Profile strength</div><div className="small">{st.missing.length ? "Add " + st.missing.slice(0, 2).join(", ").toLowerCase() + (st.missing.length > 2 ? ` +${st.missing.length - 2}` : "") : "Complete"}</div></div></div>
        </StatTile>
        <StatTile to="/me/skills" label="Verified skills" value={d.stats.verified_skills} help="Skills you proved with a check." action="Take a skill check" />
        <StatTile to="/me/skills" label="Badges and certificates" value={d.stats.badges} help="Earned from checks and exams." action="See skill checks" />
        <StatTile to="/me/applications" label="Applications" value={d.stats.applications} help="Active hiring processes." action="View applications" />
      </div>
      {ns.done < ns.total && (
        <div className="card pad col next-steps">
          <div className="row"><h3 className="grow">Your next steps</h3><span className="small b">{ns.done} of {ns.total} done</span></div>
          <Bar value={ns.done} max={ns.total} tone="good" />
          {ns.steps.map((s) => <div key={s.key} className={"list-row ns-row" + (s.done ? " done" : "")}>
            <span className={"ns-dot" + (s.done ? " done" : "")} aria-hidden="true">{s.done ? "✓" : ""}</span>
            <span className="grow">{s.label}</span>{s.done ? <Chip kind="good">Done</Chip> : <Btn size="sm" onClick={() => nav(s.link)}>{s.action}</Btn>}</div>)}
        </div>
      )}
      <div className="split">
        <div className="col" style={{ gap: 16 }}>
          <div className="card pad col disha-panel" aria-label="Disha">
            <div className="row"><Disha size={54} mood="happy" /><div><h3 style={{ margin: 0 }}>Disha, your career coach</h3><div className="tiny">Disha guides you. Hira runs your voice interviews.</div></div></div>
            <div className="disha-tip">{d.tip}</div>
            <div className="row wrap" style={{ gap: 6 }}>{[["Suggest a role", "Which roles suit my skills?"], ["Improve my profile", "How can I improve my profile?"], ["Verify a skill", "Which skill should I verify first?"], ["Practice interview", "Help me prepare for my next interview."]].map(([l, q]) => (
              <button key={l} type="button" className="chip disha-short" onClick={() => askDisha(q)}>{l}</button>))}</div>
            <form className="row" onSubmit={(e) => { e.preventDefault(); if (chat.trim()) { askDisha(chat.trim()); setChat(""); } }}>
              <Input value={chat} onChange={(e) => setChat(e.target.value)} placeholder="Ask Disha anything" aria-label="Ask Disha anything" maxLength={500} /><Btn type="submit" disabled={!chat.trim()}>Ask</Btn></form>
          </div>
          <div className="card pad col" id="path">
            <div><h3 style={{ margin: 0 }}>Disha's path for you</h3><div className="small muted">{d.goal ? `Goal: ${d.goal}` : "Tell me the role you're aiming for and I'll lay out the steps."}</div></div>
            <form className="col" style={{ gap: 8 }} onSubmit={(e) => { e.preventDefault(); if (goal.trim().length >= 2) showPath(goal.trim()); }}>
              <Field label="Target role" hint="For example Senior Python Developer. Pick one below or type your own."><div className="row">
                <Input value={goal} onChange={(e) => setGoal(e.target.value)} placeholder={d.goal || "e.g. Senior Python Developer"} maxLength={120} />
                <Btn kind="primary" type="submit" busy={busy} disabled={goal.trim().length < 2} title={goal.trim().length < 2 ? "Type or pick a role first" : ""}>Show my path</Btn></div></Field>
              {d.role_chips?.length > 0 && <div className="row wrap" style={{ gap: 6 }}><span className="tiny muted">Roles for you:</span>{d.role_chips.map((r) => <button type="button" key={r} className="chip" onClick={() => setGoal(r)}>{r}</button>)}</div>}
            </form>
            {path && path.steps.map((s, i) => <div key={i} className="agent disha" style={{ padding: 12 }}><span className="chip disha">Step {i + 1}</span><div><b>{s.t}</b><div className="small">{s.d}</div></div></div>)}
            <div className="row wrap"><Btn onClick={() => nav("/me/skills")}>Take a skill check</Btn><Btn onClick={() => nav("/me/practice")}>Practise an interview</Btn><Btn onClick={() => nav("/me/jobs")}>See matching jobs</Btn></div>
          </div>
        </div>
        <div className="col" style={{ gap: 16 }}>
          <div className="card pad col">
            <div className="row"><h3 className="grow">Your skills</h3><span className="tiny muted"><span className="lg-dot self" /> Self-reported <span className="lg-dot ver" /> Verified</span></div>
            {d.top_skills.length ? <div className="row wrap" style={{ gap: 6 }}>{d.top_skills.map((s) => <Chip key={s.name} kind={s.verified ? "good" : ""} title={levelName(s.level)}>{s.verified ? "✓ " : ""}{s.name} · L{s.level}</Chip>)}</div>
              : <span className="muted small">Add your resume and Disha will find your skills.</span>}
            <div className="row wrap">{d.skills_total > d.top_skills.length && <Link className="small" to="/me/profile#skills">View all {d.skills_total} skills</Link>}
              <Link className="small" to="/me/profile#skills">Edit skills</Link><Btn size="sm" kind="primary" className="right" onClick={() => nav("/me/skills")}>Verify my skills</Btn></div>
          </div>
          <div className="card pad col">
            <div className="row"><h3 className="grow">Jobs for you</h3><Link className="small" to="/me/jobs">View all jobs</Link></div>
            {!d.jobs_preview.length ? <span className="small muted">No open jobs yet. New jobs are added every week.</span> : d.jobs_preview.map((j) => (
              <div key={j.id} className="list-row" style={{ gap: 10 }}><Ring value={j.match} label={j.match + "%"} neutral />
                <div className="grow"><b className="small">{j.title}</b><div className="tiny muted">{j.company || "Confidential"} · {j.location}</div>
                  {j.matched.length > 0 && <div className="tiny" style={{ color: "var(--good)" }}>✓ {j.matched.slice(0, 3).map((m) => m.split(" L")[0]).join(", ")}</div>}</div>
                <Btn size="sm" onClick={() => nav(`/me/jobs/${j.id}`)}>View job</Btn></div>))}
          </div>
          <div className="card pad col">
            <h3 style={{ margin: 0 }}>Recent activity</h3>
            {!d.activity.length ? <span className="small muted">Nothing here yet. Practise an interview and your scores will show up here.</span> : d.activity.map((a, i) => (
              <Link key={i} to={a.link} className="list-row linkless" style={{ gap: 8 }}><span aria-hidden="true">{a.kind === "badge" ? "🏅" : a.kind === "application" ? "📄" : a.kind === "skill_check" ? "✅" : "🎤"}</span>
                <span className="grow small">{a.title}{a.score != null && a.kind !== "application" ? <> · <Score value={a.score} type={a.type} pct /></> : null}</span><span className="tiny muted">{fmtDate(a.at)}</span></Link>))}
          </div>
        </div>
      </div>
    </>
  );
}

/** "Test my setup" (V02.00.05): the full system check, any time, without starting a round. Nothing is recorded. */
export function SetupTest() {
  const nav = useNavigate();
  return (
    <>
      <PageHead title="Test my setup" sub="Run the same check your interview uses: device, browser, camera, microphone, speaker, recording and internet. Nothing is recorded or shared." />
      <div className="card" style={{ background: "#0B1026", color: "#fff" }}>
        <SystemCheck dark role="candidate" final={() => (
          <div className="sc-block"><div className="sc-big">✅</div><h2>Your setup works</h2>
            <p>Use this same computer and browser for your interview. Before the round starts you'll run a short check again.</p>
            <Btn kind="gold" onClick={() => nav("/me")}>Back to home</Btn></div>)} />
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------------------------------------- Jobs

function SkillChips({ have, learn, onLearn, max = 4 }) {
  return (
    <div className="job-chips">
      <div className="col" style={{ gap: 4 }}><span className="tiny b muted">YOU HAVE</span>
        <div className="row wrap" style={{ gap: 6 }}>{have.length ? have.slice(0, max).map((m, i) => <span key={i} className="chip good wrap-chip" title={m}>✓ {m}</span>) : <span className="tiny muted">None yet</span>}</div></div>
      {learn.length > 0 && <div className="col" style={{ gap: 4 }}><span className="tiny b muted">TO LEARN</span>
        <div className="row wrap" style={{ gap: 6 }}>{learn.slice(0, max).map((m, i) => <button type="button" key={i} className="chip warn wrap-chip" title={`${m}: build a learning path`} onClick={(e) => { e.stopPropagation(); onLearn?.(m); }}>↗ {m}</button>)}
          {learn.length > max && <span className="tiny muted">+{learn.length - max} more</span>}</div></div>}
    </div>
  );
}

export function Jobs() {
  const nav = useNavigate();
  const toast = useToast();
  const [sp, setSp] = useSearchParams();
  const [q, setQ] = useState(sp.get("q") || "");
  const [f, setF] = useState({ sort: "match", location: "", mode: "", level: "", verified: false, saved: false });
  const [page, setPage] = useState(1);
  const params = { q, ...f, verified: f.verified ? 1 : "", saved: f.saved ? 1 : "", page };
  const { data, reload, error } = useAsync(() => api.get("/me/jobs", params), [q, JSON.stringify(f), page]);
  useEffect(() => { if (sp.get("q") && sp.get("q") !== q) setQ(sp.get("q")); }, [sp]); // eslint-disable-line react-hooks/exhaustive-deps
  const set = (k, v) => { setF({ ...f, [k]: v }); setPage(1); };
  const active = [["location", f.location], ["mode", f.mode], ["level", f.level], ["verified", f.verified && "Verified skills only"], ["saved", f.saved && "Saved jobs"]].filter(([, v]) => v);
  const reset = () => { setF({ ...f, location: "", mode: "", level: "", verified: false, saved: false }); setQ(""); setSp({}); setPage(1); };
  const learn = (skill, goal) => api.post("/me/learning", { skill, goal }).then(() => nav("/me/learning")).catch((e) => toast(e.message, "bad"));
  const save = (j) => api.post(`/me/jobs/${j.id}/save`, { on: !j.saved }).then(() => { toast(j.saved ? "Removed from saved jobs" : "Job saved", "good"); reload(); }).catch((e) => toast(e.message, "bad"));
  return (
    <>
      <PageHead title="Jobs for you" sub="Ranked by how well your skills match. Verified skills count more." actions={<Seg value={f.sort} onChange={(v) => set("sort", v)} options={[["match", "Best match"], ["posted", "Newest"]]} />} />
      <div className="card pad col job-filters">
        <Input placeholder="Search title, company, skill or city…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} aria-label="Search jobs" />
        <div className="row wrap" style={{ gap: 10 }}>
          <div style={{ minWidth: 160 }}><Select value={f.location} onChange={(v) => set("location", v)} options={[{ value: "", label: "Any location" }, ...(data?.filters.locations || []).map((x) => ({ value: x, label: x }))]} aria-label="Location" /></div>
          <Seg value={f.mode} onChange={(v) => set("mode", v)} options={[["", "Any mode"], ...(data?.filters.modes || []).map((m) => [m, m])]} />
          <div style={{ minWidth: 150 }}><Select value={f.level} onChange={(v) => set("level", v)} options={[{ value: "", label: "Any experience" }, ...(data?.filters.levels || []).map((x) => ({ value: x, label: x }))]} aria-label="Experience" /></div>
          <label className="row small" style={{ gap: 6 }} title={data && !data.verified_skills ? "You have no verified skills yet. Take a skill check first." : ""}><input type="checkbox" checked={f.verified} disabled={data && !data.verified_skills && !f.verified} onChange={(e) => set("verified", e.target.checked)} />Only jobs matching my verified skills</label>
          <label className="row small" style={{ gap: 6 }}><input type="checkbox" checked={f.saved} onChange={(e) => set("saved", e.target.checked)} />Saved jobs{data?.saved_count ? ` (${data.saved_count})` : ""}</label>
          {(active.length > 0 || q) && <Btn size="sm" kind="ghost" onClick={reset}>Reset</Btn>}
        </div>
        {data && <div className="row wrap small" style={{ gap: 6 }}><b>{data.total} job{data.total === 1 ? "" : "s"} match{data.total === 1 ? "es" : ""}{active.length || q ? " your filters" : ""}</b>
          {active.map(([k, v]) => <button type="button" key={k} className="chip brand" onClick={() => set(k, k === "verified" || k === "saved" ? false : "")} aria-label={`Remove filter ${v}`}>{v} ✕</button>)}</div>}
      </div>
      {data?.banner && <div className="agent disha banner-row"><Disha size={40} /><div className="grow"><b>Verify {data.banner.skill} in 12 minutes to lift your matches.</b><div className="small">It's on your profile but self-reported{data.banner.jobs ? `, and ${data.banner.jobs} of these jobs ask for it` : ""}.</div></div>
        <Btn kind="primary" onClick={() => nav(`/me/skills?skill=${encodeURIComponent(data.banner.skill)}`)}>Start skill check</Btn></div>}
      {error && !data ? <Failed error={error} retry={reload} /> : !data ? <Loading /> : !data.items.length ? (
        <Empty title="No jobs match" mascot={<Disha size={70} />} text={f.verified && !data.verified_skills ? "You have no verified skills yet, so no job matches that filter." : "Try fewer filters or a different search."}
          action={<div className="row"><Btn kind="primary" onClick={reset}>Clear filters</Btn>{!data.verified_skills && <Btn onClick={() => nav("/me/skills")}>Take a skill check</Btn>}</div>} />) : (
        <div className="col" style={{ gap: 12 }}>{data.items.map((j) => (
          <div key={j.id} className="card pad job-row" role="link" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && e.target === e.currentTarget && nav(`/me/jobs/${j.id}`)} onClick={() => nav(`/me/jobs/${j.id}`)}>
            <Ring value={j.match} label={j.match + "%"} neutral />
            <div className="grow col" style={{ gap: 8, minWidth: 0 }}>
              <div className="row wrap" style={{ gap: 8 }}><h3 style={{ margin: 0 }}>{j.title}</h3>{j.applied && <Chip kind="good">✓ Applied</Chip>}</div>
              <div className="small muted">{j.company || "Confidential"} · {j.location} · {j.work_mode}{j.level ? ` · ${j.level}` : ""}{j.salary ? ` · ${inr(j.salary[0])} – ${inr(j.salary[1])}` : ""}</div>
              <SkillChips have={j.matched} learn={j.missing} onLearn={(m) => learn(m, j.title)} />
              {j.missing.length > 0 && !j.applied && <div className="small" style={{ color: "var(--brand-ink)" }}>Close the gap with a short <button type="button" className="linkbtn" onClick={(e) => { e.stopPropagation(); learn(j.missing[0], j.title); }}>{j.missing[0]} path</button>.</div>}
              {j.applied && <div className="small muted">You applied on {fmtDate(j.applied_at)}.</div>}
            </div>
            <div className="col job-actions" style={{ gap: 8 }} onClick={(e) => e.stopPropagation()}>
              <button type="button" className={"btn icon-btn bookmark" + (j.saved ? " on" : "")} aria-pressed={j.saved} aria-label={j.saved ? `Remove ${j.title} from saved jobs` : `Save ${j.title}`} title={j.saved ? "Saved" : "Save job"} onClick={() => save(j)}>{j.saved ? "★" : "☆"}</button>
              {j.applied ? <Btn size="sm" onClick={() => nav("/me/applications")}>View application</Btn> : <Btn size="sm" onClick={() => nav(`/me/jobs/${j.id}`)}>View and apply</Btn>}
            </div>
          </div>))}
        </div>)}
      {data?.pages > 1 && <div className="row"><Btn disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Btn><span>Page {page} of {data.pages}</span><Btn disabled={page >= data.pages} onClick={() => setPage(page + 1)}>Next</Btn></div>}
    </>
  );
}

export function JobView() {
  const { id } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const { data: j, reload, error } = useAsync(() => api.get(`/me/jobs/${id}`), [id]);
  const [run, busy] = useAction();
  const [done, setDone] = useState(null);
  const [needResume, setNeedResume] = useState(false);
  if (error && !j) return <Failed error={error} retry={reload} />;
  if (!j) return <Loading />;
  // CP-003: a clear confirmation after applying, and the resume asked for right here when it's missing
  const apply = () => run(() => api.post(`/me/jobs/${id}/apply`)).then((r) => { setDone(r); reload(); })
    .catch((e) => { if (e.fields?.resume) setNeedResume(true); else toast(e.message, "bad"); });
  return (
    <>
      <PageHead back="/me/jobs" title={j.title} sub={`${j.company || "Confidential company"} · ${j.location} · ${j.work_mode} · ${j.level}`}
        actions={<><button type="button" className={"btn icon-btn bookmark" + (j.saved ? " on" : "")} aria-pressed={j.saved} aria-label={j.saved ? "Remove from saved jobs" : "Save job"} onClick={() => api.post(`/me/jobs/${id}/save`, { on: !j.saved }).then(reload)}>{j.saved ? "★" : "☆"}</button>
          {j.applied ? <><Chip kind="good">✓ Applied {fmtDate(j.applied_at)}</Chip><Btn onClick={() => nav("/me/applications")}>View application</Btn></> : <Btn kind="primary" busy={busy} onClick={apply}>Apply</Btn>}</>} />
      <div className="split">
        <div className="card pad col"><p style={{ whiteSpace: "pre-wrap" }}>{j.description}</p>
          <h3>How hiring works here</h3>
          <ol className="round-list">{j.rounds.map((r, i) => <li key={i}><b>{r.name}</b>{r.about && <div className="small muted">{r.about}</div>}</li>)}</ol>
          {j.salary && <div>Salary {inr(j.salary[0])} – {inr(j.salary[1])}</div>}</div>
        <div className="col" style={{ gap: 16 }}>
          <div className="card pad col"><div className="row"><Ring value={j.match} label={j.match + "%"} neutral /><h3>Your match</h3></div>
            <SkillChips have={j.matched} learn={j.missing} max={20} onLearn={(m) => api.post("/me/learning", { skill: m, goal: j.title }).then(() => nav("/me/learning"))} /></div>
          {j.missing.length > 0 && <div className="agent disha col" style={{ alignItems: "stretch" }}><b>Close the gap</b><span className="small">Learning {j.missing.join(", ")} would raise your match. A verified badge raises it most.</span>
            <div><Btn size="sm" onClick={() => api.post("/me/learning", { skill: j.missing[0], goal: j.title }).then(() => nav("/me/learning"))}>Start a {j.missing[0]} path</Btn></div></div>}
          {/* CAN-018 (V02.00.11): the candidate updates their own skills from here, and the match is recalculated */}
          {j.missing.length > 0 && <div className="card pad col" style={{ gap: 8 }}><b className="small">Already have one of these?</b>
            <span className="tiny muted">Add it to your profile and your match is recalculated. It shows as self-reported until you verify it.</span>
            <div className="row wrap" style={{ gap: 6 }}>{j.missing.map((m) => <button type="button" key={m} className="chip" onClick={() => api.post("/me/skills/add", { name: m.split(" / ")[0].replace(/\s*\(.*\)$/, ""), level: 2 }).then((r) => { toast(r.message, "good"); reload(); }).catch((e) => toast(e.message, "bad"))}>+ I have {m}</button>)}</div>
            <Link className="tiny" to="/me/profile#skills">Edit all my skills</Link></div>}
        </div>
      </div>
      {done && <Modal title="Application submitted" onClose={() => setDone(null)} footer={<><Btn onClick={() => setDone(null)}>Stay here</Btn><Btn kind="primary" onClick={() => nav("/me/applications")}>View my application</Btn></>}>
        <div className="row" style={{ gap: 12 }}><Disha size={56} mood="happy" /><div className="col" style={{ gap: 6 }}><b>{done.message}</b><span className="small muted">Your match for this job: {done.match}%. We'll notify you when the hiring team invites you to a round.</span></div></div>
      </Modal>}
      {needResume && <Modal title="Add your resume first" onClose={() => setNeedResume(false)} footer={<><Btn onClick={() => setNeedResume(false)}>Cancel</Btn><Btn kind="primary" onClick={() => nav("/me/profile#resume")}>Add my resume</Btn></>}>
        <p style={{ margin: 0 }}>The hiring team needs your resume to review your application. Add it on your profile, then come back and apply.</p></Modal>}
    </>
  );
}

/** Join is only active inside the join window; before that it says when it opens, and switches on by itself. */
/** Bug 8 (V02.00.07): a scheduled interview is shown at the top of the candidate's home page, not only in notifications. */
function Upcoming({ item, setupOk, onJoin, onSetup }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  const at = new Date(item.scheduled_at);
  const left = at.getTime() - now;
  const live = item.type === "f2f_isha" || item.type === "f2f_human";
  const d = Math.floor(left / 86400000), h = Math.floor((left % 86400000) / 3600000), m = Math.floor((left % 3600000) / 60000), sec = Math.floor((left % 60000) / 1000);
  const count = left <= 0 ? "Starting now" : d > 0 ? `in ${d} day${d > 1 ? "s" : ""} ${h} h` : h > 0 ? `in ${h} h ${m} min` : `in ${m}:${String(sec).padStart(2, "0")}`;
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  return (
    <div className="card upcoming" role="region" aria-label="Upcoming interview">
      <div className="up-when"><div className="up-day">{at.toLocaleDateString([], { weekday: "short" })}</div><div className="up-date">{at.getDate()}</div><div className="up-mon">{at.toLocaleDateString([], { month: "short" })}</div></div>
      <div className="grow col" style={{ gap: 4 }}>
        <div className="row wrap" style={{ gap: 6 }}><Chip kind="brand">Upcoming interview</Chip>{item.rescheduled && <Chip kind="warn">Rescheduled</Chip>}{item.status === "in_progress" && <Chip kind="bad">● Started</Chip>}</div>
        <h3 style={{ margin: 0 }}>{item.name}</h3>
        <div className="small">{item.job}{item.company ? ` · ${item.company}` : ""}{live ? " · Live video interview" : ` · ${ROUND_LABEL[item.type]}`}{item.minutes ? ` · about ${item.minutes} min` : ""}{item.interviewer ? ` · with ${item.interviewer}` : ""}</div>
        <div className="b">{at.toLocaleString([], { weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" })} <span className="small muted">({tz})</span> · <span style={{ color: left < 3600000 ? "var(--bad)" : "var(--brand-ink)" }}>{count}</span></div>
        <div className="row wrap" style={{ gap: 8, marginTop: 4 }}>
          {setupOk ? <Chip kind="good">✓ Setup tested</Chip> : <Btn size="sm" onClick={onSetup}>Test my setup</Btn>}
          {live ? <JoinButton item={item} onJoin={onJoin} /> : <Btn kind="primary" size="sm" onClick={onJoin}>{item.status === "in_progress" ? "Continue" : "Start"}</Btn>}
        </div>
        <span className="tiny muted">Use a laptop or desktop with Chrome or Edge.</span>
      </div>
    </div>
  );
}

function JoinButton({ item, onJoin, size, label = "📹 Join video interview" }) {
  const [, tick] = useState(0);
  const opens = item.opens_at ? new Date(item.opens_at) : null;
  const open = item.can_join || (opens && Date.now() >= opens.getTime());
  useEffect(() => {
    if (open || !opens) return undefined;
    const ms = Math.min(opens.getTime() - Date.now() + 500, 30000);
    const t = setTimeout(() => tick((x) => x + 1), Math.max(500, ms));
    return () => clearTimeout(t);
  });
  if (open) return <Btn size={size} kind="primary" onClick={onJoin}>{label}</Btn>;
  const mins = opens ? Math.round((opens.getTime() - Date.now()) / 60000) : null;
  const when = opens ? (mins < 60 ? `in ${mins} min` : opens.toDateString() === new Date().toDateString() ? `at ${fmtTime(opens)}` : fmtDate(opens, true)) : "later";
  return <Btn size={size} disabled title="The room opens shortly before the interview starts.">Opens {when}</Btn>;
}

// ---------------------------------------------------------------------------------------------------------- Applications

export function Applications() {
  const nav = useNavigate();
  const { data, reload, error } = useAsync(() => api.get("/me/applications"), []);
  const [run] = useAction();
  const ask = useConfirm();
  const [open, setOpen] = useState(null);  // APP-08: round details
  if (error && !data) return <Failed error={error} retry={reload} />;
  if (!data) return <Loading />;
  if (!data.length) return <><PageHead title="My applications" /><Empty title="No applications yet" mascot={<Disha size={70} />} text="When you apply to a job, every round shows up here." action={<Btn kind="primary" onClick={() => nav("/me/jobs")}>See matching jobs</Btn>} /></>;
  const active = data.filter((a) => a.active);
  const scheduled = active.flatMap((a) => a.steps.filter((s) => s.state === "scheduled").map((s) => ({ ...s, job: a.job })));
  const next = active.map((a) => ({ a, s: a.steps.find((s) => s.state === "next" || s.state === "scheduled") })).find((x) => x.s);
  const prep = (a) => nav(`/me/practice?role=${encodeURIComponent(a.prepare.role)}&skills=${encodeURIComponent(a.prepare.skills.join(","))}`);
  return (
    <>
      <PageHead title="My applications" sub="Where you stand in every hiring process." />
      <div className="grid g3">
        <div className="card stat"><div className="l">Active applications</div><div className="v">{active.length}</div></div>
        <div className="card stat"><div className="l">Interviews scheduled</div><div className="v">{scheduled.length}</div><div className="tiny muted">{scheduled.length ? `Next: ${fmtDate(scheduled[0].scheduled_at, true)}` : "We'll notify you when a date is set."}</div></div>
        <div className="card stat col" style={{ gap: 6 }}><div className="l">Next up</div>{next ? <><b className="small">{next.s.name}</b><span className="tiny muted">{next.a.job.title}</span><div><Btn size="sm" onClick={() => prep(next.a)}>Prepare with Disha</Btn></div></> : <span className="small muted">Nothing waiting.</span>}</div>
      </div>
      {data.map((a) => (
        <div key={a.id} className="card pad col">
          <div className="row wrap"><div className="grow"><h3>{a.job.title}</h3><div className="small muted">{a.job.company || "Confidential"} · applied {fmtDate(a.applied)}</div></div><Chip kind={a.raw_stage === "offer" || a.raw_stage === "hired" ? "good" : a.raw_stage === "rejected" ? "bad" : "brand"}>{a.stage}</Chip></div>
          <ol className="app-steps" aria-label={`Rounds for ${a.job.title}`}>{a.steps.map((s, i) => (
            <li key={i} className={"as-step st-" + s.state}>
              <button type="button" className="step-dot" aria-label={`Round ${i + 1}: ${s.name}, ${s.label}. Show details`} onClick={() => setOpen(open?.k === `${a.id}-${i}` ? null : { k: `${a.id}-${i}`, s, a })}>{s.state === "completed" ? "✓" : i + 1}</button>
              <span className="step-name small">{s.name}</span>
              <span className={"tiny step-state st-" + s.state}>{s.label}{s.state === "scheduled" && s.scheduled_at ? ` · ${fmtDate(s.scheduled_at, true)}` : ""}</span>
              {["invited", "scheduled", "in_progress", "paused"].includes(s.status) && (s.type.startsWith("f2f") ? <JoinButton item={s} size="sm" label="Join call" onJoin={() => nav(`/room/${s.attempt_id}`)} /> : <Btn size="sm" kind="primary" onClick={() => nav(`/room/${s.attempt_id}`)}>Open</Btn>)}
            </li>))}</ol>
          {open && open.a.id === a.id && <div className="note col" style={{ gap: 4 }}><b>{open.s.name}</b><span className="small">{open.s.about}</span>
            <span className="small muted">{[open.s.minutes ? `About ${open.s.minutes} minutes` : null, open.s.scheduled_at ? `Scheduled for ${fmtDate(open.s.scheduled_at, true)}` : null, open.s.label].filter(Boolean).join(" · ")}</span>
            <span className="small">To prepare: {open.s.type === "mcq" ? "revise the job's key skills and test your setup." : open.s.type === "ai_interview" ? "practise a voice interview for this role and test your microphone." : "practise explaining your projects out loud and test your camera and microphone."}</span></div>}
          <div className="row wrap">
            {a.active && <Btn size="sm" kind="primary" onClick={() => prep(a)}>Prepare for next round</Btn>}
            <Btn size="sm" onClick={() => nav(`/me/jobs/${a.job.id}`)}>View job</Btn>
            {a.active && <Btn size="sm" kind="danger-outline" className="right" onClick={async () => (await ask({ title: "Withdraw this application?", text: "The hiring team will see that you withdrew. You can't undo this.", yes: "Withdraw application", danger: true })) && run(() => api.post(`/me/applications/${a.id}/withdraw`), "Withdrawn").then(reload)}>Withdraw application</Btn>}
          </div>
        </div>
      ))}
    </>
  );
}

// ---------------------------------------------------------------------------------------------------------- Practice

const KIND_ABOUT = { ai_interview: "Hira, our AI interviewer, asks questions out loud and you answer by speaking. You get a score and feedback from Disha.",
  mcq: "A timed multiple-choice quiz on the role's skills. You get your score and the right answers straight away." };

export function Practice() {
  const nav = useNavigate();
  const toast = useToast();
  const [sp] = useSearchParams();
  const { data, reload, error } = useAsync(() => api.get("/me/practice"), []);
  const { data: sug } = useAsync(() => api.get("/me/practice/suggest").catch(() => null), []);
  const { data: bank } = useAsync(() => api.get("/me/practice/topics").catch(() => []), []);  // CD-005 (V02.00.08)
  const [f, setF] = useState({ type: "ai_interview", role: sp.get("role") || "", skills: (sp.get("skills") || "").split(",").map((s) => s.trim()).filter(Boolean), difficulty: "medium", questions: 4 });
  const [roleSkills, setRoleSkills] = useState([]);
  const [showAll, setShowAll] = useState(false);
  const [filter, setFilter] = useState("");
  const [roleErr, setRoleErr] = useState("");
  const [run, busy] = useAction();
  const [view, setView] = useState(null);
  const ask = useConfirm();
  // CAN-004 (V02.00.11): delete a practice session for good
  const remove = async (p) => {
    const yes = await ask({ title: "Delete this practice session?", text: `“${p.title}” will be deleted permanently: your answers, the feedback and the recording. You can't undo this.`, yes: "Delete permanently", danger: true });
    if (yes) api.del(`/me/practice/${p.id}`).then(() => { toast("Practice session deleted", "good"); reload(); }).catch((e) => toast(e.message, "bad"));
  };
  // PRA-04: once a role is chosen, the skills that fit it are offered (and preselected when none are picked)
  useEffect(() => {
    if (f.role.trim().length < 2) { setRoleSkills([]); return undefined; }
    const t = setTimeout(() => api.get("/me/practice/role-skills", { role: f.role.trim() }).then((r) => {
      setRoleSkills(r.skills); setF((x) => (x.skills.length ? x : { ...x, skills: r.skills.slice(0, 4) }));
    }).catch(() => {}), 450);
    return () => clearTimeout(t);
  }, [f.role]);
  const qMax = f.type === "mcq" ? 30 : 10;
  const qn = Number(f.questions) || 0;
  const mins = Math.max(1, Math.round(qn * (f.type === "mcq" ? 1.5 : 2.5)));
  const qErr = qn < 1 || qn > qMax ? `Choose from 1 to ${qMax} questions.` : "";
  const toggle = (s) => setF({ ...f, skills: f.skills.some((x) => x.toLowerCase() === s.toLowerCase()) ? f.skills.filter((x) => x.toLowerCase() !== s.toLowerCase()) : [...f.skills, s] });
  const all = useMemo(() => { const out = [...roleSkills]; (sug?.profile_skills || []).forEach((s) => { if (!out.some((x) => x.toLowerCase() === s.toLowerCase())) out.push(s); }); f.skills.forEach((s) => { if (!out.some((x) => x.toLowerCase() === s.toLowerCase())) out.unshift(s); }); return out; }, [roleSkills, sug, f.skills]);
  const shown = (showAll ? all.filter((s) => s.toLowerCase().includes(filter.toLowerCase())) : all.slice(0, 10));
  const start = (e) => {
    e?.preventDefault();
    if (f.role.trim().length < 2) { setRoleErr("Type or pick the role you're practising for."); return; }
    run(() => api.post("/me/practice", { ...f, role: f.role.trim(), questions: qn })).then((r) => nav(`/room/${r.attempt_id}`)).catch((x) => x.fields?.role && setRoleErr(x.fields.role));
  };
  const mine = (data || []).filter((p) => !p.skill_check);
  return (
    <>
      <PageHead title="Practice interviews" sub="Private mock interviews and quizzes. Employers never see these." />
      <div className="split">
        <div className="col" style={{ gap: 16 }}>
          {sug?.suggestions?.length > 0 && <div className="card">
            <div className="card-h"><h3>Suggested for you</h3></div>
            {sug.suggestions.map((s) => <div key={s.role} className="list-row"><div className="grow"><b>{s.role}</b><div className="small muted">{s.why}{s.skills.length ? ` · ${s.skills.join(", ")}` : ""}</div></div>
              <Btn size="sm" onClick={() => { setF({ ...f, role: s.role, skills: s.skills }); setRoleErr(""); document.getElementById("new-practice")?.scrollIntoView({ behavior: "smooth" }); }}>Use this</Btn></div>)}
          </div>}
          <div className="card">
            <div className="card-h"><h3>Your practice</h3></div>
            {error && !data ? <Failed error={error} retry={reload} /> : !data ? <Loading /> : !mine.length
              ? <Empty title="Start your first practice" mascot={<Disha size={64} />} text="Pick a role on the right. After each practice you get a score and feedback from Disha. Nobody else sees it." />
              : mine.map((p) => <div key={p.id} className="list-row"><div className="grow"><b>{p.title}</b><div className="small muted">{ROUND_LABEL[p.type]} · {fmtDate(p.created_at)}</div></div><Status s={p.status} />
                {p.score != null && <Score value={p.score} type={p.type} pct />}
                {p.report ? <><Btn size="sm" onClick={() => setView(p)}>Feedback</Btn><Btn size="sm" kind="ghost" onClick={() => { setF({ ...f, type: p.type, role: (p.title || "").replace(/^Practice:\s*/, "") }); document.getElementById("new-practice")?.scrollIntoView({ behavior: "smooth" }); }}>Retry</Btn></>
                  : <Btn size="sm" kind="primary" onClick={() => nav(`/room/${p.id}`)}>Open</Btn>}
                <button type="button" className="btn ghost icon-btn" aria-label={`Delete ${p.title}`} title="Delete permanently" onClick={() => remove(p)}>🗑</button></div>)}
          </div>
        </div>
        <form id="new-practice" className="card pad col" onSubmit={start} noValidate>
          <div className="row"><Disha size={48} /><h3 style={{ margin: 0 }}>New practice</h3></div>
          <Field label="Kind"><Seg value={f.type} onChange={(v) => setF({ ...f, type: v, questions: v === "mcq" ? 8 : 4 })} options={[["ai_interview", "Voice interview with Hira"], ["mcq", "Quiz"]]} /></Field>
          <div className="tiny muted" style={{ marginTop: -6 }}>{KIND_ABOUT[f.type]}</div>
          <Field label="Role" required error={roleErr} hint="Questions are only about this role."><Input list="practice-roles" value={f.role} onChange={(e) => { setF({ ...f, role: e.target.value, skills: [] }); setRoleErr(""); }} placeholder="e.g. Backend developer" maxLength={120} aria-invalid={!!roleErr} />
            <datalist id="practice-roles">{(sug?.roles || []).map((r) => <option key={r} value={r} />)}</datalist></Field>
          <Field label="Skills" hint="Pick the skills to be asked about. Leave all unselected to use the role's skills.">
            <div className="col" style={{ gap: 6 }}>
              {showAll && <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Search skills" aria-label="Search skills" />}
              <div className="row wrap" style={{ gap: 6 }}>{shown.map((s) => { const on = f.skills.some((x) => x.toLowerCase() === s.toLowerCase());
                return <button type="button" key={s} className={"chip " + (on ? "brand" : "")} aria-pressed={on} onClick={() => toggle(s)}>{on ? "✓ " : ""}{s}</button>; })}
                {!shown.length && <span className="tiny muted">{f.role.trim().length < 2 ? "Choose a role to see its skills." : "No skills found."}</span>}</div>
              {all.length > 10 && <button type="button" className="linkbtn small" style={{ alignSelf: "flex-start" }} onClick={() => setShowAll(!showAll)}>{showAll ? "Show fewer" : `Show all ${all.length}`}</button>}
            </div></Field>
          {f.type === "mcq" && bank?.length > 0 && <div className="col" style={{ gap: 6 }}><span className="tiny muted">Topics in the Code2Hire question bank (questions available):</span>
            <div className="row wrap" style={{ gap: 6 }}>{bank.slice(0, 18).map((t) => { const on = f.skills.some((x) => x.toLowerCase() === t.skill.toLowerCase());
              return <button type="button" key={t.skill} className={"chip " + (on ? "brand" : "")} aria-pressed={on} onClick={() => toggle(t.skill)}>{t.skill} · {t.count}</button>; })}</div></div>}
          <Field label="Difficulty"><Seg value={f.difficulty} onChange={(v) => setF({ ...f, difficulty: v })} options={[["easy", "Easy"], ["medium", "Medium"], ["hard", "Hard"]]} /></Field>
          <Field label="Questions" error={qErr}><div className="row stepper-input">
            <Btn type="button" size="sm" aria-label="Fewer questions" disabled={qn <= 1} onClick={() => setF({ ...f, questions: Math.max(1, qn - 1) })}>−</Btn>
            <b style={{ minWidth: 24, textAlign: "center" }} aria-live="polite">{qn}</b>
            <Btn type="button" size="sm" aria-label="More questions" disabled={qn >= qMax} onClick={() => setF({ ...f, questions: Math.min(qMax, qn + 1) })}>+</Btn>
            <span className="small muted">1 to {qMax} · about {mins} minute{mins === 1 ? "" : "s"}</span></div></Field>
          {f.type === "ai_interview" && <div className="note row" style={{ gap: 8 }}><span className="grow small">Voice interviews need your microphone. Allow it when the browser asks.</span><Btn type="button" size="sm" onClick={() => nav("/me/setup")}>Test mic</Btn></div>}
          <Btn kind="primary" type="submit" busy={busy} disabled={!!qErr}>Start practising</Btn>
        </form>
      </div>
      {view && <Modal wide title={view.title} onClose={() => { setView(null); reload(); }}
        footer={<><Btn onClick={() => download(`/me/practice/${view.id}/pdf`, `practice-report-${view.id}.pdf`).catch((e) => toast(e.message, "bad"))}>Download report (PDF)</Btn><Btn kind="primary" onClick={() => { setView(null); reload(); }}>Close</Btn></>}><ReportView r={{ sections: view.report, overall: view.report.overall ?? (view.type === "mcq" ? view.score / 20 : view.score), round: view.title, type: view.type, recommendation: null, version: 1, scale: 5, candidate: { name: "You" }, job: { title: "Practice" } }} /></Modal>}
    </>
  );
}

// ---------------------------------------------------------------------------------------------------------- Skill checks

export function Skills() {
  const nav = useNavigate();
  const toast = useToast();
  const [sp] = useSearchParams();
  const { data: badges, error, reload } = useAsync(() => api.get("/me/badges"), []);
  const { data: rec } = useAsync(() => api.get("/me/skills/recommend").catch(() => null), []);
  const [f, setF] = useState({ skill: sp.get("skill") || "", level: Number(sp.get("level")) || 2 });
  const [run, busy] = useAction();
  const start = (skill, level) => run(() => api.post("/me/skill-check", { skill, level })).then((r) => nav(`/room/${r.attempt_id}`));
  const list = (badges || []).filter((b) => b.kind !== "course");
  return (
    <>
      <PageHead title="Skill checks and badges" sub="Short proctored quizzes. Pass one and that skill shows as verified to employers." />
      <div className="split">
        <div className="col" style={{ gap: 16 }}>
          <div className="card pad col">
            <h3 style={{ margin: 0 }}>Your badges</h3>
            {error && !badges ? <Failed error={error} retry={reload} /> : !badges ? <Loading /> : !list.length
              ? <Empty title="Earn your first badge" mascot={<Disha size={64} />} text="A pass turns a self-reported skill into a verified one. A check takes about 12 minutes." />
              : <div className="grid g3">{list.map((b) => (
                <div key={b.id} className="card pad col" style={{ alignItems: "center", textAlign: "center", opacity: b.revoked ? .5 : 1 }}>
                  <div className="badge-disc" data-kind={b.kind}>{b.level ? "L" + b.level : "★"}</div>
                  <b>{b.title}</b><span className="tiny muted">{b.issuer} · {b.grade || b.kind}</span>
                  <span className="tiny">Earned {fmtDate(b.created_at)}{b.expires_at ? ` · valid until ${fmtDate(b.expires_at)}` : ""}</span>
                  <span className="tiny mono">{b.code}</span>{b.revoked && <Chip kind="bad">Revoked</Chip>}
                  <Link className="small" to={`/verify/${b.code}`}>Verification page</Link>
                  {!b.revoked && <Btn size="sm" kind="ghost" onClick={() => download(`/me/credentials/${b.code}/pdf`, `certificate-${b.code}.pdf`).catch((e) => toast(e.message, "bad"))}>Download PDF</Btn>}
                </div>))}</div>}
          </div>
          {rec?.recommended?.length > 0 && <div className="card">
            <div className="card-h"><h3>Recommended checks</h3></div>
            {rec.recommended.map((r) => <div key={r.skill} className="list-row"><div className="grow"><b>{r.skill} · Level {r.level}</b><div className="small muted">{r.why}</div></div>
              <Btn size="sm" busy={busy} onClick={() => start(r.skill, r.level)}>Start check</Btn></div>)}
          </div>}
        </div>
        <form className="card pad col" onSubmit={(e) => { e.preventDefault(); start(f.skill.trim(), f.level); }}>
          <h3>Take a skill check</h3>
          <Field label="Skill"><Input list="check-skills" value={f.skill} onChange={(e) => setF({ ...f, skill: e.target.value })} placeholder="e.g. Python" maxLength={80} />
            <datalist id="check-skills">{(rec?.skills || []).map((s) => <option key={s} value={s} />)}</datalist></Field>
          {rec?.quick?.length > 0 && <div className="row wrap" style={{ gap: 6 }}>{rec.quick.map((s) => <button type="button" key={s} className={"chip " + (f.skill === s ? "brand" : "")} onClick={() => setF({ ...f, skill: s })}>{s}</button>)}</div>}
          <Field label="Level"><Seg value={String(f.level)} onChange={(v) => setF({ ...f, level: Number(v) })} options={["1", "2", "3", "4", "5"].map((l) => [l, `L${l}`])} /></Field>
          <div className="tiny" style={{ marginTop: -6 }}><b>{levelName(f.level)}.</b> {LEVELS[f.level][1]}</div>
          <ul className="ticks small"><li>8 questions</li><li>12 minutes</li><li>Fullscreen and camera on; leaving the tab is recorded</li><li>Score 70% to earn the badge. You can retake a check if you don't pass.</li></ul>
          <div className="note row" style={{ gap: 8 }}><span className="grow small">We'll ask for camera access when you start.</span><Btn type="button" size="sm" onClick={() => nav("/me/setup")}>Test camera</Btn></div>
          <Btn kind="primary" type="submit" busy={busy} disabled={f.skill.trim().length < 2}>Start skill check</Btn>
        </form>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------------------------------------- Learning

export function Learning() {
  const nav = useNavigate();
  const toast = useToast();
  const ask = useConfirm();
  const [sp] = useSearchParams();
  const { data, reload, error, setData } = useAsync(() => api.get("/me/learning"), []);
  const [skill, setSkill] = useState(sp.get("skill") || "");
  const [openTopic, setOpenTopic] = useState({});
  const [run, busy] = useAction();
  const [rb, setRb] = useState(null);
  const build = (s) => run(() => api.post("/me/learning", { skill: s })).then((r) => { toast(r.existing ? "You already have this path. Here it is." : "Path ready", "good"); setSkill(""); reload(); });
  // ticks at once; the server's answer (progress, current topic) replaces it
  const put = (np) => setData((x) => ({ ...x, paths: x.paths.map((q) => (q.id === np.id ? np : q)) }));
  const toggle = (lp, i, done) => {
    const topics = lp.topics.map((t, k) => (k === i ? { ...t, done } : t));
    put({ ...lp, topics, done_count: topics.filter((t) => t.done).length });
    api.patch(`/me/learning/${lp.id}/topics/${i}`, { done }).then(put).catch((e) => { toast(e.message, "bad"); reload(); });
  };
  const rebuild = (lp) => { setRb(lp.id); api.post(`/me/learning/${lp.id}/rebuild`).then(() => { toast("Disha rebuilt the path", "good"); reload(); }).catch((e) => toast(e.message, "bad")).finally(() => setRb(null)); };
  const paths = data?.paths || [];
  return (
    <>
      <PageHead title="Learning paths" sub="Short, ordered topics with practice prompts. Disha builds them around your goal." />
      <div className="card pad col">
        <form className="row" onSubmit={(e) => { e.preventDefault(); if (skill.trim().length >= 2) build(skill.trim()); }}>
          <Disha size={40} /><Input value={skill} onChange={(e) => setSkill(e.target.value)} placeholder="What do you want to learn? e.g. SQL joins, Power BI, System design" maxLength={80} aria-label="What do you want to learn?" />
          <Btn kind="primary" type="submit" busy={busy} disabled={skill.trim().length < 2}>Build path</Btn></form>
        {data?.try?.length > 0 && <div className="row wrap" style={{ gap: 6 }}><span className="tiny muted">Try (from the gaps in your matching jobs):</span>{data.try.map((t) => <button type="button" key={t} className="chip" onClick={() => setSkill(t)}>{t}</button>)}</div>}
      </div>
      {error && !data ? <Failed error={error} retry={reload} /> : !data ? <Loading /> : !paths.length ? <Empty title="No paths yet" mascot={<Disha size={64} />} text="Type a skill above, or pick one from your job gaps." /> : paths.map((lp) => {
        const n = lp.topics.length;
        return (
          <div key={lp.id} className="split path-split">
            <div className="card">
              <div className="card-h"><div className="grow"><h3>{lp.title}</h3><div className="small muted">{lp.reason}</div></div>
                <div style={{ width: 160 }}><Bar value={lp.done_count} max={n} tone="good" /></div><b className="small">{lp.done_count} of {n} done</b></div>
              {lp.meta?.basic && <div className="sc-note calm row" style={{ margin: "0 16px 8px", gap: 8 }}><span className="grow small">This is a basic outline: Disha couldn't reach the AI when it was built.</span><Btn size="sm" busy={rb === lp.id} onClick={() => rebuild(lp)}>Rebuild with Disha</Btn></div>}
              {lp.topics.map((t, i) => {
                const cur = lp.current === i; const last = i === n - 1 && /skill check/i.test(t.title);
                return (
                  <div key={i} className={"list-row topic-row" + (t.done ? " done" : "") + (cur ? " current" : "")} style={{ alignItems: "flex-start" }}>
                    <span className={"ns-dot" + (t.done ? " done" : "")} aria-hidden="true">{t.done ? "✓" : i + 1}</span>
                    <div className="grow col" style={{ gap: 4 }}>
                      <div className="row wrap" style={{ gap: 8 }}><b>{t.title}</b><span className="tiny muted">{t.minutes || 10} min</span>{cur && <Chip kind="brand">Current</Chip>}</div>
                      <div className="small">{t.summary}</div>
                      {(openTopic[`${lp.id}-${i}`] || t.done) && (t.practice || []).length > 0 && <ul className="small muted" style={{ margin: 0, paddingLeft: 18 }}>{t.practice.map((p, j) => <li key={j}>{p}</li>)}</ul>}
                      <div className="row wrap" style={{ gap: 6 }}>
                        {last ? <Btn size="sm" kind={cur ? "primary" : ""} onClick={() => nav(`/me/skills?skill=${encodeURIComponent(lp.skill)}`)}>Start skill check</Btn>
                          : t.done ? <Btn size="sm" kind="ghost" onClick={() => setOpenTopic({ ...openTopic, [`${lp.id}-${i}`]: !openTopic[`${lp.id}-${i}`] })}>Review topic</Btn>
                            : <><Btn size="sm" kind={cur ? "primary" : ""} onClick={() => setOpenTopic({ ...openTopic, [`${lp.id}-${i}`]: true })}>Start topic</Btn>
                              <Btn size="sm" kind="ghost" onClick={() => nav(`/me/practice?role=${encodeURIComponent(lp.meta?.goal && lp.meta.goal.toLowerCase() !== "your next role" ? lp.meta.goal : lp.skill)}&skills=${encodeURIComponent(lp.skill)}`)}>Practise with Disha</Btn></>}
                        <label className="row tiny" style={{ gap: 4 }}><input type="checkbox" checked={!!t.done} onChange={(e) => toggle(lp, i, e.target.checked)} />Mark done</label>
                      </div>
                    </div>
                  </div>);
              })}
            </div>
            <div className="col" style={{ gap: 12 }}>
              <div className="card pad col" style={{ gap: 6 }}><h3 style={{ margin: 0 }}>Path details</h3>
                <span className="small">Topics left: <b>{n - lp.done_count}</b></span><span className="small">Time left: <b>about {lp.minutes_left} minutes</b></span></div>
              <div className="card pad col" style={{ gap: 6 }}><h3 style={{ margin: 0 }}>This path leads to</h3>
                {lp.meta?.application_id ? <><b className="small">{lp.meta.job_title}</b><span className="tiny muted">{lp.meta.company || "Confidential"}{lp.meta.applied ? ` · applied on ${fmtDate(lp.meta.applied)}` : ""}</span><div><Btn size="sm" onClick={() => nav("/me/applications")}>View application</Btn></div></>
                  : <span className="small muted">{lp.reason || "Your next role"}</span>}</div>
              <Btn kind="danger-outline" onClick={async () => (await ask({ title: "Remove this path?", text: `Your progress on “${lp.title}” will be lost.`, yes: "Remove path", danger: true })) && api.del(`/me/learning/${lp.id}`).then(() => { toast("Path removed", "good"); reload(); })}>Remove this path</Btn>
            </div>
          </div>);
      })}
    </>
  );
}

// ---------------------------------------------------------------------------------------------------------- Certifications

const CERT_STATE = { in_progress: ["brand", "In progress"], locked: ["warn", "Locked"], held: ["good", "Earned"], cooldown: ["", "Retake later"], used_up: ["bad", "No attempts left"], open: ["", "Available"] };

export function Certs() {
  const nav = useNavigate();
  const toast = useToast();
  const { data: cat, error, reload } = useAsync(() => api.get("/certs-catalog"), []);
  const { data: mine, reload: reloadMine } = useAsync(() => api.get("/me/certifications"), []);
  const [run] = useAction();
  // CAN-005 (V02.00.11): while Hira scores a section, check again every few seconds so the count never jumps later
  const scoring = (mine || []).some((a) => a.scoring);
  useEffect(() => { if (!scoring) return undefined; const t = setInterval(() => { reloadMine(); reload(); }, 6000); return () => clearInterval(t); }, [scoring]); // eslint-disable-line react-hooks/exhaustive-deps
  const live = (mine || []).filter((a) => !a.final);
  const past = (mine || []).filter((a) => a.final);
  return (
    <>
      <PageHead title="Certifications" sub="Proctored exams that issue a certificate anyone can verify." actions={<Link className="btn" to="/verify">Verify a certificate</Link>} />
      {live.length > 0 && <div className="card"><div className="card-h"><h3>Your exam in progress</h3></div>{live.map((a) => (
        <div key={a.id} className="list-row" style={{ flexDirection: "column", alignItems: "stretch", gap: 8 }}>
          <div className="row wrap">
            <div className="grow"><b>{a.cert}</b><div className="small muted">Started {fmtDate(a.created_at)} · {a.progress.done} of {a.progress.total} sections done</div></div>
            <div style={{ width: 160 }}><Bar value={a.progress.done} max={Math.max(1, a.progress.total)} tone="good" /></div><b className="small">{Math.round((100 * a.progress.done) / Math.max(1, a.progress.total))}%</b>
            <Chip kind="brand">In progress</Chip>
            {a.next_attempt_id ? <Btn size="sm" kind="primary" onClick={() => nav(`/room/${a.next_attempt_id}`)}>Continue</Btn> : a.scoring && <span className="small muted">Hira is scoring your last section. The next one opens by itself.</span>}
          </div>
          <CertTable a={a} onStart={a.next_attempt_id ? () => nav(`/room/${a.next_attempt_id}`) : null} />
        </div>))}</div>}
      <h3 style={{ margin: "8px 0 0" }}>Available certifications</h3>
      <div className="small muted">Levels use the same scale as skill checks: {Object.entries(LEVELS).map(([k, v]) => `L${k} ${v[0]}`).join(", ")}.</div>
      {error && !cat ? <Failed error={error} retry={reload} /> : !cat ? <Loading /> : <div className="grid g3">{cat.map((c) => {
        const [tone, tag] = CERT_STATE[c.state] || ["", ""];
        const spoken = (c.sections || []).find((s) => s.type === "ai_interview");
        return (
          <div key={c.id} className="card pad col">
            <div className="row wrap" style={{ gap: 6 }}><h3 className="grow" style={{ margin: 0 }}>{c.name}</h3><Chip kind={tone}>{tag}</Chip></div>
            <div className="small muted">Issued by {c.issuer} · Level {c.level} ({LEVELS[c.level]?.[0]}) · {c.minutes} min · valid {c.validity_months} months · {c.fee ? "₹" + c.fee : "Free"}</div>
            <div className="row wrap">{c.sections.map((s, i) => <Chip key={i} title="Share of the final score">{s.name || ROUND_LABEL[s.type]} · {s.weight}%</Chip>)}</div>
            <div className="tiny muted">Pass mark {c.pass_mark}%. Passing the knowledge section also verifies the skill.</div>
            {spoken && c.state !== "held" && <div className="tiny">Includes a spoken interview (about {spoken.minutes || 10} min). <Link to="/me/setup">Test your microphone</Link> first.</div>}
            {c.why && <span className="small" style={{ color: c.state === "locked" || c.state === "cooldown" ? "var(--warn)" : "var(--ink)" }}>{c.why}</span>}
            {c.state === "open" && <Btn kind="primary" onClick={() => run(() => api.post(`/certs/${c.id}/start`)).then((r) => nav(`/room/${r.attempt_id}`)).catch((e) => toast(e.message, "bad"))}>Start exam</Btn>}
            {c.state === "in_progress" && <Btn kind="primary" onClick={() => run(() => api.post(`/certs/${c.id}/start`)).then((r) => nav(`/room/${r.attempt_id}`))}>Continue</Btn>}
            {c.state === "locked" && c.action && <Btn onClick={() => nav(`/me/skills?skill=${encodeURIComponent(c.action.skill)}&level=${c.action.level}`)}>{c.action.label}</Btn>}
          </div>);
      })}</div>}
      {past.length > 0 && <div className="card"><div className="card-h"><h3>Finished attempts</h3></div>{past.map((a) => (
        <div key={a.id} className="list-row" style={{ flexDirection: "column", alignItems: "stretch", gap: 8 }}>
          <div className="row wrap"><div className="grow"><b>{a.cert}</b><div className="small muted">{fmtDate(a.created_at)}</div></div>
            {a.score != null && <Chip kind={a.passed ? "good" : "bad"}>Score {Number(a.score).toFixed(1)}%</Chip>}{a.grade && <Chip kind="good">{a.grade}</Chip>}<Status s={a.status} />
            {a.credential_code && <><Btn size="sm" onClick={() => download(`/me/credentials/${a.credential_code}/pdf`, `certificate-${a.credential_code}.pdf`)}>Download certificate</Btn><Link className="small" to={`/verify/${a.credential_code}`}>Public verify link</Link></>}</div>
          <CertTable a={a} />
        </div>))}</div>}
    </>
  );
}

function CertTable({ a, onStart }) {
  if (!a.breakdown?.length) return null;
  return (
    <div className="tbl-wrap"><table className="tbl small"><thead><tr><th>Section</th><th>Status</th><th>Your score</th><th>Weight</th><th>Points toward total</th></tr></thead><tbody>
      {a.breakdown.map((b, i) => <tr key={i}><td>{b.name}</td>
        <td>{b.scoring ? <span className="row tiny" style={{ gap: 6 }}><span className="spin" style={{ width: 12, height: 12 }} />Scoring…</span> : b.done ? <Chip kind="good">Done</Chip> : onStart ? <button type="button" className="linkbtn" onClick={onStart}>Start section</button> : <span className="faint">Not done</span>}</td>
        <td>{b.done ? `${Number(b.pct).toFixed(1)}%` : "—"}{b.minimum ? <span className="tiny muted"> (minimum {b.minimum}%)</span> : null}</td><td>{b.weight}%</td><td>{b.points != null ? b.points.toFixed(1) : "—"}</td></tr>)}
      <tr><td className="b">Points so far</td><td /><td /><td>{a.breakdown.reduce((x, b) => x + b.weight, 0)}%</td><td className="b">{a.points_so_far} of 100 · pass mark {a.pass_mark}</td></tr>
    </tbody></table></div>
  );
}

// ---------------------------------------------------------------------------------------------------------- Feedback

export function Feedback() {
  const nav = useNavigate();
  const { data, reload, error } = useAsync(() => api.get("/me/feedback"), []);
  const { data: waiting } = useAsync(() => api.get("/me/feedback/waiting").catch(() => []), []);
  const toast = useToast();
  const [d, setD] = useState(null);
  const [run, busy] = useAction();
  const [how, setHow] = useState(null);
  if (error && !data) return <Failed error={error} retry={reload} />;
  if (!data) return <Loading />;
  const showHow = how ?? !data.length;
  return (
    <>
      <PageHead title="Feedback" sub="What employers shared after your rounds, and a way to tell us what you think of Code2Hire." />
      <div className="card pad col">
        <button type="button" className="row linkless" style={{ justifyContent: "space-between" }} aria-expanded={showHow} onClick={() => setHow(!showHow)}><h3 style={{ margin: 0 }}>How feedback works</h3><span className="small muted">{showHow ? "Hide" : "Show"}</span></button>
        {showHow && <ol className="how-steps"><li><b>A company shares feedback</b><span className="small muted">after a round, when they choose to.</span></li><li><b>Disha reads it for you</b><span className="small muted">and pulls out strengths and gaps.</span></li><li><b>You get clear next steps</b><span className="small muted">with a learning path, a skill check or a practice.</span></li></ol>}
      </div>
      {!data.length && <Empty title="No feedback yet" mascot={<Disha size={70} />} text="When a company shares feedback, Disha turns it into clear next steps here." action={<Btn kind="primary" onClick={() => nav("/me/practice")}>Practise an interview while you wait</Btn>} />}
      {waiting?.length > 0 && <div className="card"><div className="card-h"><h3>Waiting on</h3></div>{waiting.map((w) => <div key={w.application_id} className="list-row"><div className="grow"><b>{w.job}</b><div className="small muted">{w.company || "Confidential"} · {w.stage}</div></div><Btn size="sm" onClick={() => nav("/me/applications")}>View status</Btn></div>)}</div>}
      {data.map((r) => <div key={r.id} className="card pad col">
        <div className="row wrap"><h3 className="grow">{r.job.title} · {r.round}</h3>
          {r.pdf && <Btn size="sm" onClick={() => download(`/me/feedback/${r.id}/pdf`, `feedback-${r.id}.pdf`).catch((e) => toast(e.message, "bad"))}>Download PDF</Btn>}
          {r.disputed ? <Chip kind="warn">Concern raised</Chip> : <Btn size="sm" kind="ghost" onClick={() => setD({ id: r.id, note: "" })}>Something looks wrong?</Btn>}</div>
        {r.result?.cleared && <div className="note" role="status">🎉 You cleared this round.{r.result.next_step ? " " + r.result.next_step : ""}</div>}
        {r.result?.score != null && <div className="row small"><span className="muted">Your score</span><Score value={r.result.score} scale={r.scale || 5} pct /></div>}
        <ReportView r={r} /></div>)}
      <SendFeedback />
      {d && <Modal title="Raise a concern" dirty={!!d.note.trim()} onClose={() => setD(null)} footer={(close) => <><Btn onClick={close}>Cancel</Btn><Btn kind="primary" busy={busy} disabled={d.note.trim().length < 10} onClick={() => run(() => api.post(`/me/feedback/${d.id}/dispute`, { note: d.note.trim() }), "Sent to the hiring team").then(() => { setD(null); reload(); }).catch(() => {})}>Send</Btn></>}>
        <p style={{ margin: 0 }}>Tell the team what you think is wrong, for example a technical problem during the round. A person will look into it and you'll see their answer here.</p>
        <Field label="What went wrong?" required hint={`${d.note.trim().length < 10 ? "At least 10 characters. " : ""}${2000 - d.note.length} characters left.`}><Textarea value={d.note} maxLength={2000} onChange={(e) => setD({ ...d, note: e.target.value })} autoFocus /></Field></Modal>}
    </>
  );
}

/** CP-008: tell Code2Hire what works and what doesn't, with common topics to pick from. */
function SendFeedback() {
  const { data } = useAsync(() => api.get("/me/product-feedback").catch(() => null), []);
  const [topics, setTopics] = useState([]);
  const [rating, setRating] = useState(0);
  const [text, setText] = useState("");
  const [sent, setSent] = useState(false);
  const [run, busy] = useAction();
  if (!data) return null;
  if (sent) return <div className="card pad row" role="status"><Disha size={44} mood="happy" /><div className="grow"><b>Thank you!</b><div className="small muted">The Code2Hire team reads every message.</div></div><Btn size="sm" onClick={() => { setSent(false); setTopics([]); setText(""); setRating(0); }}>Send more</Btn></div>;
  return (
    <div className="card pad col">
      <h3 style={{ margin: 0 }}>Tell us what you think of Code2Hire</h3>
      <span className="small muted">Common feedback. Pick any that apply:</span>
      <div className="row wrap" style={{ gap: 6 }}>{data.topics.map((t) => { const on = topics.includes(t); return <button type="button" key={t} className={"chip " + (on ? "brand" : "")} aria-pressed={on} onClick={() => setTopics(on ? topics.filter((x) => x !== t) : [...topics, t])}>{on ? "✓ " : ""}{t}</button>; })}</div>
      <div className="row small" style={{ gap: 6 }} role="radiogroup" aria-label="Rating"><span className="muted">How is it going?</span>{[1, 2, 3, 4, 5].map((n) => <button type="button" key={n} role="radio" aria-checked={rating === n} className={"star" + (n <= rating ? " on" : "")} onClick={() => setRating(rating === n ? 0 : n)} aria-label={`${n} of 5`}>★</button>)}</div>
      <Field label="Anything else? (optional)"><Textarea value={text} onChange={(e) => setText(e.target.value)} maxLength={3000} placeholder="What should we improve?" /></Field>
      <div><Btn kind="primary" busy={busy} disabled={!topics.length && text.trim().length < 5} onClick={() => run(() => api.post("/me/product-feedback", { topics, rating: rating || null, text, page: "feedback" })).then(() => setSent(true))}>Send feedback</Btn></div>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------- Profile

const VIS = { applied: "Only companies I apply to", everyone: "All employers on Code2Hire", nobody: "Nobody" };
const VIS_ABOUT = { applied: "Companies see your profile after you apply to one of their jobs.", everyone: "Any employer on Code2Hire can find you and invite you.", nobody: "Hidden from searches. Companies you already applied to can still see your application." };

export function Profile() {
  const { logout } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const { data, reload, error } = useAsync(() => api.get("/me"), []);
  const [f, setF] = useState(null);
  const [fe, setFe] = useState({});
  const [newSkill, setNewSkill] = useState("");
  const [skillErr, setSkillErr] = useState("");
  const [preview, setPreview] = useState(null);
  const [run, busy] = useAction();
  const ask = useConfirm();
  const dirty = !!f;
  // PRF-08: warn before leaving with unsaved changes
  useEffect(() => {
    if (!dirty) return undefined;
    const h = (e) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [dirty]);
  useEffect(() => { if (data && loc.hash) setTimeout(() => { const el = document.getElementById(loc.hash.slice(1)); el?.scrollIntoView({ behavior: "smooth", block: "center" }); el?.querySelector?.("input")?.focus?.(); el?.focus?.(); }, 80); }, [!!data, loc.key]); // eslint-disable-line react-hooks/exhaustive-deps
  if (error && !data) return <Failed error={error} retry={reload} />;
  if (!data) return <Loading />;
  const p = f || { name: data.user.name, headline: data.profile.headline || "", location: data.profile.location || "", phone: data.profile.phone || "", experience_years: data.profile.experience_years ?? "", visibility: data.profile.visibility, skills: data.profile.skills || [] };
  const st = data.completeness;
  const verifiedN = p.skills.filter((s) => s.verified).length;
  const addSkill = (e) => {
    e.preventDefault();
    const v = newSkill.trim();
    if (!v) return;
    if (p.skills.some((s) => s.name.toLowerCase() === v.toLowerCase())) { setSkillErr(`${v} is already on your profile.`); return; }
    setF({ ...p, skills: [{ name: v, level: 2 }, ...p.skills] }); setNewSkill(""); setSkillErr("");
  };
  const save = () => { setFe({}); return run(() => api.patch("/me/profile", { ...p, experience_years: p.experience_years === "" ? null : Number(p.experience_years) }), "Profile saved").then(() => { setF(null); reload(); }).catch((e) => e.fields && setFe(e.fields)); };
  const strengthChip = (i) => <a key={i.key} href={i.link} onClick={(e) => { e.preventDefault(); nav(i.link); }} className={"chip " + (i.done ? "good" : "warn")}>{i.done ? "✓" : "+"} {i.label}</a>;
  return (
    <>
      <PageHead title="Profile and privacy" sub="Keep your details current so Disha can match you to the right jobs." />
      <div className="card pad col strength-banner">
        <div className="row" style={{ gap: 14 }}><Ring value={st.pct} label={st.pct + "%"} neutral /><div className="grow"><b>Profile strength {st.pct}%</b><div className="small muted">{st.missing.length ? `Add ${st.missing.length} more thing${st.missing.length === 1 ? "" : "s"} to reach 100%.` : "Your profile is complete."}</div></div></div>
        <div className="row wrap" style={{ gap: 6 }}>{st.items.map(strengthChip)}</div>
      </div>
      <div className="grid g2">
        <div className="card pad col"><h3>About you</h3>
          <div className="grid g2">
            <Field label="Name" required error={fe.name}><Input id="f-name" value={p.name} maxLength={80} onChange={(e) => setF({ ...p, name: e.target.value })} /></Field>
            <Field label="Headline" error={fe.headline} hint="Your current or target role in a few words."><Input id="f-headline" value={p.headline} maxLength={120} placeholder="e.g. Backend developer" onChange={(e) => setF({ ...p, headline: e.target.value })} /></Field>
            <Field label="City" error={fe.location}><Input id="f-location" value={p.location} maxLength={120} placeholder="e.g. Bengaluru" onChange={(e) => setF({ ...p, location: e.target.value })} /></Field>
            <Field label="Phone" error={fe.phone} hint="Include the country code, e.g. +91 98450 00000"><Input id="f-phone" type="tel" inputMode="tel" maxLength={20} value={p.phone} onChange={(e) => setF({ ...p, phone: e.target.value.replace(/[^\d+\s\-()]/g, "") })} /></Field>
            <Field label="Years of experience" error={fe.experience_years} hint="Use 0 if you're a fresher."><Input id="f-experience" type="number" min={0} max={60} step={1} value={p.experience_years ?? ""} placeholder="e.g. 3" onChange={(e) => setF({ ...p, experience_years: e.target.value === "" ? "" : Math.max(0, Math.min(60, Math.round(Number(e.target.value)))) })} /></Field>
            <Field label="Who can see my profile" hint={VIS_ABOUT[p.visibility]}><Select value={p.visibility} onChange={(v) => setF({ ...p, visibility: v })} options={Object.entries(VIS).map(([value, label]) => ({ value, label }))} /></Field>
          </div>
          <div className="tiny muted">Practice sessions are never shared with employers.</div>
          <div id="skills" tabIndex={-1} className="col" style={{ gap: 8 }}>
            <div className="row wrap"><b className="grow">Skills</b><span className="small muted">{p.skills.length} skill{p.skills.length === 1 ? "" : "s"} · {verifiedN} verified</span></div>
            <span className="tiny muted">Add at least 5. Verify a skill with a short check to show employers it's proven.</span>
            <form className="row" onSubmit={addSkill}><Input list="all-skills" value={newSkill} onChange={(e) => { setNewSkill(e.target.value); setSkillErr(""); }} placeholder="Add a skill" maxLength={80} aria-label="Add a skill" /><Btn type="submit" disabled={!newSkill.trim()}>Add</Btn></form>
            <datalist id="all-skills">{["Python", "Java", "JavaScript", "TypeScript", "React", "SQL", "Excel", "Power BI", "Tableau", "Data Analytics", "AWS", "Docker", "Kubernetes", "Testing", "Selenium", "Communication", "SAP", "SAP ATTP", "Node.js", "Spring Boot"].map((s) => <option key={s} value={s} />)}</datalist>
            {skillErr && <span className="small" style={{ color: "var(--bad)" }} role="alert">{skillErr}</span>}
            <div className="skill-grid">{p.skills.map((s, i) => <div key={s.name + i} className="skill-cell">
              <span className="grow skill-name" title={s.name}>{s.name}</span>
              {s.verified ? <Chip kind="good" title={levelName(s.level)}>✓ L{s.level} verified</Chip> : <>
                <div style={{ width: 150 }}><Select value={String(s.level)} onChange={(v) => setF({ ...p, skills: p.skills.map((x, j) => (j === i ? { ...x, level: +v } : x)) })} options={[1, 2, 3, 4, 5].map((l) => ({ value: String(l), label: `L${l} · ${LEVELS[l][0]}` }))} aria-label={`Level for ${s.name}`} /></div>
                <Link className="tiny" to={`/me/skills?skill=${encodeURIComponent(s.name)}&level=${s.level}`}>Verify</Link>
                <button type="button" className="btn ghost icon-btn" aria-label={`Remove ${s.name}`} title={`Remove ${s.name}`} onClick={async () => (await ask({ title: `Remove ${s.name}?`, text: "You can add it again later.", yes: "Remove", danger: true })) && setF({ ...p, skills: p.skills.filter((_, j) => j !== i) })}>✕</button></>}
            </div>)}</div>
          </div>
        </div>
        <div className="col" style={{ gap: 16 }}>
          <div className="card pad col" id="resume" tabIndex={-1}><h3>Resume</h3>
            <span className="small muted">Upload it and Disha can fill in your headline, skills and experience. You'll see what changes before anything is saved.</span>
            {data.profile.resume_text ? (data.profile.resume_text.trim().length >= 200 ? <Chip kind="good">✓ Resume saved</Chip> : <Chip kind="warn">Resume saved, but it looks too short to count. Add the full resume.</Chip>) : <Chip kind="warn">No resume saved yet</Chip>}
            <ResumeFileLine file={data.resume_file} history={data.resume_history} href="/me/resume/file" />
            <ResumeInput base="/me" onRead={setPreview} />
            {data.profile.resume_text && <details><summary className="small">Current resume</summary><pre className="small" style={{ whiteSpace: "pre-wrap", fontFamily: "inherit" }}>{data.profile.resume_text}</pre></details>}
          </div>
          <div className="card pad col"><h3>Password</h3><PwCard /></div>
          <div className="card pad col"><h3>Your data</h3>
            <span className="small muted">Download a copy of everything Code2Hire holds about you. Deleting your account removes your profile and applications; you'll be asked to confirm first, so download your data before you delete.</span>
            <div className="row wrap"><Btn onClick={() => api.get("/me/export").then((d) => { const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([JSON.stringify(d, null, 2)], { type: "application/json" })); a.download = "code2hire-my-data.json"; a.click(); })}>Download my data</Btn>
              <Btn kind="danger" onClick={async () => { const c = await ask({ title: "Delete your account?", text: "This removes your personal data and applications and signs you out. It can't be undone.", input: { label: "Type DELETE to confirm", required: true, match: "DELETE" }, yes: "Delete my account", danger: true }); if (c === "DELETE") run(() => api.del("/me", { confirm: "DELETE" })).then(() => { logout(); nav("/"); }); }}>Delete my account</Btn></div>
          </div>
        </div>
      </div>
      {dirty && <div className="save-bar" role="region" aria-label="Unsaved changes"><span className="grow b">You have unsaved changes</span><Btn onClick={() => { setF(null); setFe({}); }}>Discard</Btn><Btn kind="primary" busy={busy} onClick={save}>Save profile</Btn></div>}
      {preview && <ResumeReview base="/me" preview={preview} onClose={() => setPreview(null)} onSaved={() => { setPreview(null); setF(null); reload(); }} />}
    </>
  );
}

function PwCard() {
  const { me } = useAuth();
  const [open, setOpen] = useState(false);
  const viaLink = me?.link_session && me?.must_change_password;
  if (!open) return <div className="row"><span className="small muted grow">{viaLink ? "You haven't set a password yet." : "Change the password you sign in with."}</span><Btn onClick={() => setOpen(true)}>{viaLink ? "Set password" : "Change password"}</Btn></div>;
  return <PasswordForm needCurrent={!viaLink} onDone={() => setOpen(false)} />;
}
