import { useEffect, useMemo, useRef, useState } from "react";
import { api, download } from "../api";
import { useAuth } from "../auth";
import { COUNTRIES, emailError, fmtPhone, nameError, normalisePhone, textError, intError } from "../lib/validate";
import { AgentNote } from "./Mascot";
import { Btn, Chip, Field, Input, ListEditor, Modal, Seg, Select, Textarea, fmtDate, useAsync, useToast } from "./ui";

export function fullLink(path) { return window.location.origin + path; }

const CITIES = ["Bengaluru", "Mumbai", "Delhi", "New Delhi", "Hyderabad", "Chennai", "Pune", "Kolkata", "Ahmedabad", "Noida", "Gurugram",
  "Jaipur", "Kochi", "Coimbatore", "Indore", "Chandigarh", "Lucknow", "Bhubaneswar", "Thiruvananthapuram", "Mysuru", "Mangaluru", "Hubballi",
  "Nagpur", "Vadodara", "Surat", "Visakhapatnam", "Vijayawada", "Madurai", "Goa", "Remote", "Dubai", "Singapore", "London", "New York"];

/**
 * Copy, email or WhatsApp a candidate's personal portal link. Every action records that the link was shared, so the
 * list shows "Sent" only after something actually went out.
 */
export function ShareLink({ userId, name, email, link, job, company, expires, onShared }) {
  const toast = useToast();
  const url = fullLink(link);
  const first = ((name || "").trim().split(" ")[0] || "there").replace(/^./, (c) => c.toUpperCase());
  const msg = `Hi ${first},\n${company || "Our hiring team"} has invited you to Code2Hire${job ? ` for the ${job} role` : ""}.\nOpen your personal link to see your next steps and set your password:\n${url}\n${expires ? `This link is only for you and works until ${fmtDate(expires)}. Please don't share it.` : "This link is only for you. Please don't share it."}`;
  const emailBad = emailError(email || "");
  const shared = (via) => { if (userId) api.post(`/candidates/${userId}/link/shared`, { via }).then((r) => onShared?.(r.state)).catch(() => {}); };
  const copy = async (text, what, via) => {
    try { await navigator.clipboard.writeText(text); toast(`${what} copied`, "good"); shared(via); }
    catch { toast("Your browser blocked copying. Select the link and copy it by hand.", "bad"); }
  };
  return (
    <div className="col" style={{ gap: 8 }}>
      <div className="linkbox"><code title={url}>{url}</code></div>
      {expires && <div className="expiry-note">Works until <b>{fmtDate(expires)}</b>, or until {first} sets a password. A new link cancels this one.</div>}
      <div className="row wrap" style={{ gap: 6 }}>
        {emailBad
          ? <span className="btn sm" aria-disabled="true" title={`Can't email: ${email || "no email"} isn't a valid address.`} style={{ opacity: .55, cursor: "not-allowed" }}>✉ Email</span>
          : <a className="btn sm primary" onClick={() => shared("email")} href={`mailto:${encodeURIComponent(email)}?subject=${encodeURIComponent(`Your Code2Hire link${job ? ` · ${job}` : ""}`)}&body=${encodeURIComponent(msg)}`}>✉ Email</a>}
        <a className="btn sm primary" target="_blank" rel="noreferrer" onClick={() => shared("message")} href={`https://wa.me/?text=${encodeURIComponent(msg)}`}>WhatsApp</a>
        <Btn size="sm" onClick={() => copy(url, "Link", "copy")}>Copy link</Btn>
        <Btn size="sm" onClick={() => copy(msg, "Message", "message")}>Copy message</Btn>
      </div>
      {emailBad && <span className="tiny" style={{ color: "var(--bad)" }}>Email is off: “{email}” isn't a valid address. Copy the link and send it another way.</span>}
    </div>
  );
}

// ---------------------------------------------------------------- list parsing (paste)

/** One line of CSV with quotes ("Rao, Asha"), or tab-separated (pasted from Excel). */
function splitLine(line) {
  if (line.includes("\t")) return line.split("\t").map((x) => x.trim());
  const out = []; let cur = "", q = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (q) { if (ch === '"' && line[i + 1] === '"') { cur += '"'; i++; } else if (ch === '"') q = false; else cur += ch; }
    else if (ch === '"') q = true; else if (ch === ",") { out.push(cur.trim()); cur = ""; } else cur += ch;
  }
  out.push(cur.trim());
  return out;
}
const HEAD = { name: ["name", "full name", "candidate"], email: ["email", "e-mail", "email address"], phone: ["phone", "mobile", "whatsapp", "phone number"],
  skills: ["skills", "skill"], location: ["city", "location"], headline: ["headline", "title", "designation", "current role"], experience_years: ["experience", "years", "exp"] };
/** Lines -> rows. A header row (Name, Email, ...) sets the column order; without one: name, email, phone, skills. */
export function parseList(text) {
  const lines = text.split(/\r?\n/).filter((l) => l.trim());
  if (!lines.length) return [];
  let cols = ["name", "email", "phone", "skills"];
  const first = splitLine(lines[0]).map((x) => x.toLowerCase());
  if (first.some((x) => HEAD.email.includes(x))) {
    cols = first.map((h) => Object.keys(HEAD).find((k) => HEAD[k].includes(h)) || "");
    lines.shift();
  }
  return lines.map((l, i) => {
    const parts = splitLine(l);
    const r = { line: i + 1 };
    cols.forEach((c, j) => { if (c && parts[j] !== undefined && parts[j] !== "") r[c] = parts[j]; });
    // someone typed more than 4 commas without quotes: the rest are skills
    if (cols.length === 4 && parts.length > 4) r.skills = parts.slice(3).join(";");
    if (typeof r.skills === "string") r.skills = r.skills.split(/[;|]/).map((s) => s.trim()).filter(Boolean);
    return r;
  });
}

const EMPTY = { name: "", email: "", phone: "", country: "91", location: "", headline: "", experience_years: "", skills: [], resume_text: "" };
const STAGE = { applied: "Applied", shortlisted: "Shortlisted", in_round: "In a round", awaiting_review: "Waiting for review", decision: "Decision",
  offer: "Offer", hired: "Hired", rejected: "Not selected", on_hold: "On hold", withdrawn: "Withdrawn" };

/** Matches for what's typed in Name or Email (V02.00.05): your company's candidates, then Disha candidates. */
function useMatches(text, jobId, off) {
  const [items, setItems] = useState([]);
  useEffect(() => {
    const q = (text || "").trim();
    if (off || q.length < 2) { setItems([]); return undefined; }
    const t = setTimeout(() => api.get("/candidates/search", { q, job_id: jobId || undefined }).then((r) => setItems(r.items)).catch(() => setItems([])), 250);
    return () => clearTimeout(t);
  }, [text, jobId, off]);
  return [items, setItems];
}

function MatchList({ items, onPick, onClose, active, jobTitle }) {
  if (!items.length) return null;
  return (
    <div className="picker-list" role="listbox" aria-label="Matching candidates" onMouseDown={(e) => e.preventDefault()}>
      <div className="tiny muted" style={{ padding: "4px 10px" }}>Already on Code2Hire. Pick one to use their profile, or keep typing to add someone new.</div>
      {items.map((m, k) => {
        const here = m.in_this_job;
        return (
          <button key={m.user_id} type="button" role="option" aria-selected={k === active} aria-disabled={!!here} className={"picker-opt" + (k === active ? " on" : "")}
            onClick={() => (here ? null : onPick(m))}>
            <span className="row" style={{ gap: 6 }}><b>{m.name}</b>{m.source === "disha" ? <Chip kind="disha">Disha profile</Chip> : <Chip kind="brand">Your pool</Chip>}
              {here && <Chip kind="warn">Already on {jobTitle || "this job"} · {STAGE[here.stage] || here.stage}</Chip>}</span>
            <span className="meta">{m.email || "Email shown once they're added"}{m.headline ? ` · ${m.headline}` : ""}{m.location ? ` · ${m.location}` : ""}</span>
            {m.skills?.length > 0 && <span className="meta">Skills: {m.skills.join(", ")}</span>}
            {m.jobs?.length > 0 && <span className="meta">Jobs: {m.jobs.map((j) => `${j.title} (${STAGE[j.stage] || j.stage})`).join(" · ")}</span>}
            {here && <a className="meta" href={`/app/applications/${here.application_id}`} onClick={(e) => e.stopPropagation()}>Open their application →</a>}
          </button>
        );
      })}
      <button type="button" className="picker-opt" onClick={onClose}><span className="meta">None of these: add a new candidate</span></button>
    </div>
  );
}

export default function AddCandidate({ onClose, onDone, jobId, preset }) {
  const { me } = useAuth();
  const toast = useToast();
  const { data: jobs } = useAsync(() => api.get("/jobs", { size: 100, status: "live" }).catch(() => ({ items: [] })), []);
  const [mode, setMode] = useState("one");
  const [jobSel, setJobSel] = useState(jobId ? String(jobId) : "");
  const [f, setF] = useState(EMPTY);
  const [touched, setTouched] = useState({});
  const [submitted, setSubmitted] = useState(false);
  const [serverErr, setServerErr] = useState({});
  const [more, setMore] = useState(false);
  const [dup, setDup] = useState(null);
  const [parsing, setParsing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);      // one person added -> success screen
  const [bulkText, setBulkText] = useState("");
  const [bulkRows, setBulkRows] = useState(null);  // rows from a file, instead of the text box
  const [preview, setPreview] = useState(null);    // dry-run results
  const [summary, setSummary] = useState(null);    // after adding a list
  const [picked, setPicked] = useState(preset || null);  // an existing candidate chosen from the dropdown
  const [focus, setFocus] = useState("");
  const [active, setActive] = useState(0);
  const [hideMatches, setHideMatches] = useState(false);
  const [similar, setSimilar] = useState([]);
  const fileRef = useRef(); const sheetRef = useRef();
  const job = (jobs?.items || []).find((j) => String(j.id) === String(jobSel));
  const [matches] = useMatches(focus === "email" ? f.email : f.name, jobSel, mode !== "one" || !!picked || hideMatches || !focus);

  // ---- one person: field rules (same as the server) ----
  const phone = normalisePhone(f.phone, false, f.country);
  const errs = {
    name: nameError(f.name), email: emailError(f.email), phone: phone.error,
    location: textError(f.location, 120, false, "City"), headline: textError(f.headline, 120, false, "Headline"),
    experience_years: intError(f.experience_years, { lo: 0, hi: 60, label: "Years of experience" }),
  };
  const shown = (k) => serverErr[k] || ((touched[k] || submitted) && errs[k]) || "";
  const missing = [!f.name.trim() && "name", !f.email.trim() && "email"].filter(Boolean);
  const invalid = Object.entries(errs).filter(([, v]) => v).map(([k]) => k);
  const blockedByDup = !!dup?.blocking;
  const canAdd = !missing.length && !invalid.length && !blockedByDup;
  const set = (k, v) => { setF((x) => ({ ...x, [k]: v })); if (serverErr[k]) setServerErr((x) => { const n = { ...x }; delete n[k]; return n; }); };
  const touch = (k) => setTouched((t) => ({ ...t, [k]: true }));
  const dirty = mode === "one" ? JSON.stringify(f) !== JSON.stringify(EMPTY) && !done : (!!bulkText.trim() || !!bulkRows) && !summary;

  // ---- duplicate check while typing (debounced) ----
  useEffect(() => {
    if (mode !== "one" || done) return undefined;
    const e = !errs.email && f.email.trim() ? f.email.trim() : "";
    const p = !phone.error && phone.value ? phone.value : "";
    if (!e && !p) { setDup(null); if (f.name.trim().length >= 3) { const t = setTimeout(() => api.get("/candidates/check", { name: f.name.trim() }).then((r) => setSimilar(r.similar || [])).catch(() => {}), 400); return () => clearTimeout(t); } setSimilar([]); return undefined; }
    const t = setTimeout(() => {
      api.get("/candidates/check", { email: e, phone: p, name: f.name.trim(), job_id: jobSel || undefined }).then((r) => {
        const ex = r.existing;
        setDup(ex ? { ...ex, blocking: ex.kind === "same_phone" || (ex.kind === "in_company" && !jobSel) || !!ex.in_job } : null);
        setSimilar(r.similar || []);
      }).catch(() => setDup(null));
    }, 400);
    return () => clearTimeout(t);
  }, [f.email, f.phone, f.name, f.country, jobSel, mode, done]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- resume upload fills the form ----
  const onResume = async (file) => {
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) { toast("That file is larger than 5 MB.", "bad"); return; }
    setParsing(true);
    try {
      const fd = new FormData(); fd.append("file", file);
      const r = await api.post("/candidates/parse-resume", fd);
      const filled = [];
      setF((x) => {
        const n = { ...x, resume_text: r.resume_text || x.resume_text };
        const put = (k, v) => { if (v && !String(x[k] || "").trim()) { n[k] = v; filled.push(k); } };
        put("name", r.name); put("email", r.email); put("location", r.location); put("headline", r.headline);
        if (r.phone && !x.phone.trim()) { n.phone = r.phone; filled.push("phone"); }
        if (r.experience_years != null && x.experience_years === "") { n.experience_years = String(r.experience_years); filled.push("experience"); }
        if (r.skills?.length) { const have = new Set(x.skills.map((s) => s.toLowerCase())); n.skills = [...x.skills, ...r.skills.filter((s) => !have.has(s.toLowerCase()))].slice(0, 20); }
        return n;
      });
      setMore(true);
      toast(`Read ${file.name}. Check the details before adding.`, "good");
    } catch (e) { toast(e.message, "bad"); }
    finally { setParsing(false); if (fileRef.current) fileRef.current.value = ""; }
  };

  const addPicked = async () => {
    if (busy || !picked) return;
    if (picked.source === "disha" && !jobSel) { toast("Pick a job first. A Disha candidate is added to a job, not to your talent pool.", "bad"); return; }
    setBusy(true);
    try {
      const r = await api.post("/candidates", { candidates: [{ user_id: picked.user_id }], job_id: jobSel || undefined });
      const res = r.results[0];
      if (res.status !== "added") { toast(res.reason === "in_job" ? `${picked.name} is already on ${job?.title || "this job"}.` : res.error || "Couldn't add this person.", "bad"); return; }
      onDone?.(r); setDone({ ...res, picked: true });
    } catch (e) { toast(e.message, "bad"); } finally { setBusy(false); }
  };
  const addOne = async (another) => {
    if (picked) { await addPicked(); return; }
    setSubmitted(true);
    if (!canAdd || busy) return;
    setBusy(true);
    try {
      const r = await api.post("/candidates", { name: f.name.trim(), email: f.email.trim(), phone: phone.value || "", country: f.country, location: f.location.trim(),
        headline: f.headline.trim(), experience_years: f.experience_years === "" ? null : Number(f.experience_years), skills: f.skills, resume_text: f.resume_text, job_id: jobSel || undefined });
      const res = r.results[0];
      if (res.status !== "added") { setServerErr(res.fields || {}); toast(res.error || "Couldn't add this person.", "bad"); return; }
      onDone?.(r);
      if (another) {
        toast(`${res.name} added. Their link is under Added candidates.`, "good");
        setF({ ...EMPTY, country: f.country }); setTouched({}); setSubmitted(false); setDup(null); setMore(false);
      } else setDone(res);
    } catch (e) { if (e.fields) setServerErr(e.fields); toast(e.message, "bad"); }
    finally { setBusy(false); }
  };

  // ---- many people ----
  const rows = useMemo(() => bulkRows || parseList(bulkText), [bulkRows, bulkText]);
  useEffect(() => { setPreview(null); }, [bulkText, bulkRows, jobSel]);
  const onSheet = async (file) => {
    if (!file) return;
    setParsing(true);
    try { const fd = new FormData(); fd.append("file", file); const r = await api.post("/candidates/parse-file", fd); setBulkRows(r.rows.map((x, i) => ({ ...x, line: i + 1 }))); setBulkText("");
      toast(`${r.rows.length} people read from ${file.name}${r.truncated ? " (only the first 200)" : ""}.`, "good"); }
    catch (e) { toast(e.message, "bad"); }
    finally { setParsing(false); if (sheetRef.current) sheetRef.current.value = ""; }
  };
  const checkList = async () => {
    if (!rows.length || busy) return;
    setBusy(true);
    try { setPreview(await api.post("/candidates", { candidates: rows.map(({ line, ...r }) => r), job_id: jobSel || undefined, dry_run: true })); }
    catch (e) { toast(e.message, "bad"); } finally { setBusy(false); }
  };
  const addList = async () => {
    if (!preview || busy) return;
    const ok = preview.results.map((r, i) => (r.status === "ok" ? i : -1)).filter((i) => i >= 0);
    if (!ok.length) return;
    setBusy(true);
    try {
      const r = await api.post("/candidates", { candidates: ok.map((i) => { const { line, ...x } = rows[i]; return x; }), job_id: jobSel || undefined });
      setSummary({ ...r, invalid: preview.invalid, duplicates: preview.duplicates + r.duplicates });
      onDone?.(r);
    } catch (e) { toast(e.message, "bad"); } finally { setBusy(false); }
  };

  // ---------------------------------------------------------------- screens
  if (done) {
    return (
      <Modal title={`${done.name} added`} onClose={onClose} footer={<><Btn onClick={() => { setDone(null); setF({ ...EMPTY, country: f.country }); setTouched({}); setSubmitted(false); setDup(null); }}>Add another</Btn><Btn kind="primary" onClick={onClose}>Close</Btn></>}>
        <div className="row wrap"><Chip kind="good">✓ {done.picked ? "Existing candidate added" : done.existing ? "Added to your pool (already had an account)" : "New candidate"}</Chip>{done.application_id && <Chip kind="brand">On {job?.title || "the job"}</Chip>}</div>
        {done.picked && <span className="small muted">They kept their own profile and were told they've been added, and that they can withdraw if they're not interested.</span>}
        {done.link ? <>
          <AgentNote agent="disha" title="Now send them their link">The link opens their portal straight away, no password needed. There they see their next steps and set their own password. Nothing has been sent yet.</AgentNote>
          <ShareLink userId={done.user_id} name={done.name} email={done.email} link={done.link} job={job?.title} company={me?.company?.name} expires={done.expires_at} />
          <span className="small muted">Not now? Close this. The link stays under <b>Added candidates</b>, marked “Not sent”.</span>
        </> : <AgentNote agent="disha">{done.note}</AgentNote>}
      </Modal>
    );
  }
  if (summary) {
    const added = summary.results.filter((r) => r.status === "added");
    return (
      <Modal size="lg" title="List added" onClose={onClose} footer={<Btn kind="primary" onClick={onClose}>Close</Btn>}>
        <div className="row wrap"><Chip kind="good">{summary.added} added</Chip>{summary.invalid > 0 && <Chip kind="bad">{summary.invalid} skipped (invalid)</Chip>}{summary.duplicates > 0 && <Chip kind="warn">{summary.duplicates} skipped: already added</Chip>}</div>
        {preview?.results.some((r) => r.status !== "ok") && <div className="small col" style={{ gap: 2 }}><b>Skipped</b>{preview.results.map((r, i) => r.status !== "ok" && <span key={i} className="muted">Row {i + 1} · {rows[i]?.name || rows[i]?.email || "?"}: {r.reason === "in_job" ? `already on ${job?.title || "this job"}` : r.error}</span>)}</div>}
        <AgentNote agent="disha">Send each person their link. Each link opens their portal; nothing has been sent yet.</AgentNote>
        {added.map((r) => (
          <div key={r.user_id} className="card pad col" style={{ gap: 8 }}>
            <div className="row wrap"><b>{r.name}</b><span className="small muted">{r.email}</span>{r.existing && <Chip kind="info">Had an account</Chip>}</div>
            {r.link ? <ShareLink userId={r.user_id} name={r.name} email={r.email} link={r.link} job={job?.title} company={me?.company?.name} expires={r.expires_at} /> : <span className="small muted">{r.note}</span>}
          </div>
        ))}
      </Modal>
    );
  }

  const listReady = preview ? preview.results.filter((r) => r.status === "ok").length : 0;
  return (
    <Modal size="lg" dirty={dirty} title="Add candidate" onClose={onClose} footer={(close) => mode === "one" && picked ? <>
      {picked.source === "disha" && !jobSel && <span className="missing-note">Pick a job to add a Disha candidate to.</span>}
      <Btn onClick={close}>Cancel</Btn>
      <Btn kind="primary" busy={busy} disabled={picked.source === "disha" && !jobSel} onClick={addPicked}>Add {picked.name.split(" ")[0]}{job ? ` to ${job.title}` : " to your pool"}</Btn>
    </> : mode === "one" ? <>
      {!canAdd && <span className="missing-note">{missing.length ? `Fill in: ${missing.join(" and ")}.` : blockedByDup ? "This person is already in your talent pool." : `Fix: ${invalid.map((k) => k.replace("_years", "").replace("location", "city")).join(", ")}.`}</span>}
      <Btn onClick={close}>Cancel</Btn>
      <Btn busy={busy} disabled={!canAdd} onClick={() => addOne(true)}>Add and add another</Btn>
      <Btn kind="primary" busy={busy} disabled={!canAdd} onClick={() => addOne(false)}>Add candidate</Btn>
    </> : <>
      {!rows.length && <span className="missing-note">Paste or upload at least one person.</span>}
      {preview && !listReady && <span className="missing-note">No rows are ready. Fix the rows in red.</span>}
      <Btn onClick={close}>Cancel</Btn>
      {!preview ? <Btn kind="primary" busy={busy} disabled={!rows.length} onClick={checkList}>Check {rows.length || ""} {rows.length === 1 ? "person" : "people"}</Btn>
        : <Btn kind="primary" busy={busy} disabled={!listReady} onClick={addList}>Add {listReady} ready</Btn>}
    </>}>
      <Seg value={mode} onChange={setMode} options={[["one", "One person"], ["many", "Several people"]]} />
      <Field label="Add to a job (optional)" hint="Leave empty to add them to your talent pool only.">
        <Select value={jobSel} onChange={setJobSel} options={[{ value: "", label: "No job: talent pool only" }, ...(jobs?.items || []).map((j) => ({ value: String(j.id), label: `${j.title}${j.location ? " · " + j.location : ""}` }))]} />
      </Field>
      {mode === "one" ? (
        <form autoComplete="off" onSubmit={(e) => { e.preventDefault(); addOne(false); }} className="col" style={{ gap: 14 }}>
          <div className="upload-row">
            <div className="grow"><b className="small">Have a resume?</b><div className="tiny muted">Upload a PDF or DOCX (up to 5 MB) and we'll fill in the details.</div></div>
            <input ref={fileRef} type="file" accept=".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain" hidden onChange={(e) => onResume(e.target.files?.[0])} />
            <Btn size="sm" busy={parsing} onClick={() => fileRef.current?.click()}>Upload resume</Btn>
          </div>
          {picked ? (
            <div className="card pad col" style={{ gap: 6 }}>
              <div className="row wrap"><b>{picked.name}</b>{picked.source === "disha" ? <Chip kind="disha">Disha profile</Chip> : <Chip kind="brand">Your pool</Chip>}<Btn size="sm" kind="ghost" className="right" onClick={() => setPicked(null)}>Change</Btn></div>
              <span className="small muted">{picked.email || "Their email is shown once they're on the job."}{picked.headline ? ` · ${picked.headline}` : ""}{picked.location ? ` · ${picked.location}` : ""}</span>
              {picked.skills?.length > 0 && <span className="small">Skills: {picked.skills.join(", ")}</span>}
              {picked.jobs?.length > 0 && <span className="small muted">Already on: {picked.jobs.map((j) => `${j.title} (${STAGE[j.stage] || j.stage})`).join(" · ")}</span>}
              <AgentNote agent="disha">{picked.source === "disha" ? "They keep their own Disha profile. They'll be told you added them, and can withdraw if they're not interested." : "Their existing profile and resume are used. No new account is made."}</AgentNote>
            </div>
          ) : <>
          <div className="grid g2">
            <Field label="Full name" required error={shown("name")}><div className="picker"><Input name="c2h-cand-name" autoComplete="off" placeholder="Type a name: existing candidates appear" maxLength={80} value={f.name}
              onChange={(e) => { set("name", e.target.value); setHideMatches(false); setActive(0); }} onFocus={() => setFocus("name")} onBlur={() => { touch("name"); setTimeout(() => setFocus((x) => (x === "name" ? "" : x)), 150); }}
              onKeyDown={(e) => { if (!matches.length) return; if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(matches.length - 1, a + 1)); } else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); } else if (e.key === "Enter" && matches[active] && !matches[active].in_this_job) { e.preventDefault(); setPicked(matches[active]); } }}
              aria-autocomplete="list" autoFocus />
              {focus === "name" && <MatchList items={matches} active={active} jobTitle={job?.title} onPick={setPicked} onClose={() => setHideMatches(true)} />}</div></Field>
            <Field label="Email" required error={shown("email")}><div className="picker"><Input name="c2h-cand-email" type="email" autoComplete="off" placeholder="name@company.com" maxLength={254} value={f.email}
              onChange={(e) => { set("email", e.target.value); setHideMatches(false); setActive(0); }} onFocus={() => setFocus("email")} onBlur={() => { touch("email"); setTimeout(() => setFocus((x) => (x === "email" ? "" : x)), 150); }} aria-autocomplete="list" />
              {focus === "email" && <MatchList items={matches} active={active} jobTitle={job?.title} onPick={setPicked} onClose={() => setHideMatches(true)} />}</div></Field>
            <Field label="Phone" error={shown("phone")} hint={phone.value && !phone.error ? `Saved as ${fmtPhone(phone.value)}` : "Digits only. Used to message the candidate."}>
              <div className="input-group">
                <Select aria-label="Country code" value={f.country} onChange={(v) => set("country", v)} options={COUNTRIES.map(([v, l]) => ({ value: v, label: l }))} />
                <Input name="c2h-cand-phone" type="tel" inputMode="tel" autoComplete="off" placeholder="98450 00000" maxLength={20} value={f.phone} onChange={(e) => set("phone", e.target.value.replace(/[^\d+\s\-()]/g, ""))} onBlur={() => touch("phone")} />
              </div>
            </Field>
            <Field label="City" error={shown("location")}><Input name="c2h-cand-city" list="c2h-cities" autoComplete="off" placeholder="Start typing, e.g. Bengaluru" maxLength={120} value={f.location} onChange={(e) => set("location", e.target.value)} onBlur={() => touch("location")} /></Field>
          </div>
          <datalist id="c2h-cities">{CITIES.map((c) => <option key={c} value={c} />)}</datalist>
          {!dup && f.name.trim().length >= 3 && f.email.trim() === "" && similar.length === 0 && matches.length === 0 && focus !== "name" && <span className="tiny"><Chip kind="info">New candidate</Chip> No one with this name is in your pool yet.</span>}
          {similar.length > 0 && !dup?.in_job && (
            <div className="dup-note info" role="status">Possible duplicate: {similar.map((x, k) => <span key={x.user_id}>{k ? ", " : ""}<b>{x.name}</b> ({x.email})</span>)} {similar.length > 1 ? "are" : "is"} already in your pool with a different email. Is it the same person?
              <Btn size="sm" kind="ghost" onClick={() => setPicked({ ...similar[0], source: "company", skills: [], jobs: [] })}>Use {similar[0].name.split(" ")[0]}</Btn></div>
          )}
          {dup?.in_job && <div className="dup-note bad" role="status"><b>{dup.name}</b> is already on {dup.in_job.job} ({STAGE[dup.in_job.stage] || dup.in_job.stage}). <a href={`/app/applications/${dup.in_job.application_id}`}>Open their application</a></div>}
          {dup && !dup.in_job && (
            <div className={"dup-note " + (dup.blocking ? "bad" : "info")} role="status">
              {dup.kind === "in_company" && (jobSel ? <>“{dup.name}” ({dup.email}) is already in your talent pool. Adding puts them on {job?.title || "this job"}.</> : <>A candidate with this email already exists in your talent pool: <b>{dup.name}</b>. Pick a job above to add them to it, or open them from the Talent pool.</>)}
              {dup.kind === "same_phone" && <>This phone number is already used by <b>{dup.name}</b> ({dup.email}).</>}
              {dup.kind === "account" && <>This person already has a Code2Hire account. They'll be added to your pool and keep their own sign-in.</>}
            </div>
          )}
          <button type="button" className="more-toggle" aria-expanded={more} onClick={() => setMore(!more)}>{more ? "▾" : "▸"} More details (optional): headline, experience, skills, resume</button>
          {more && <>
            <div className="grid g2">
              <Field label="Headline" error={shown("headline")}><Input autoComplete="off" placeholder="e.g. Backend developer" maxLength={120} value={f.headline} onChange={(e) => set("headline", e.target.value)} onBlur={() => touch("headline")} /></Field>
              <Field label="Years of experience" error={shown("experience_years")}><Input type="number" min={0} max={60} step={1} inputMode="numeric" placeholder="e.g. 4" value={f.experience_years} onChange={(e) => set("experience_years", e.target.value)} onBlur={() => touch("experience_years")} /></Field>
            </div>
            <Field label="Skills" hint="Press Enter or a comma after each skill. Up to 20."><ListEditor value={f.skills} max={20} onChange={(v) => set("skills", v)} placeholder="e.g. Python" /></Field>
            <Field label="Resume text" hint={f.resume_text ? `${f.resume_text.length.toLocaleString()} characters` : "Filled in when you upload a resume. You can also paste it."}><Textarea value={f.resume_text} maxLength={30000} onChange={(e) => set("resume_text", e.target.value)} data-allow-paste="1" style={{ minHeight: 110 }} /></Field>
          </>}
          </>}
        </form>
      ) : (
        <>
          <div className="upload-row">
            <div className="grow"><b className="small">Upload a list</b><div className="tiny muted">CSV or Excel (XLSX) with columns Name, Email, Phone, Skills, City.</div></div>
            <input ref={sheetRef} type="file" accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" hidden onChange={(e) => onSheet(e.target.files?.[0])} />
            <Btn size="sm" kind="ghost" onClick={() => download("/candidates/template.csv", "code2hire-candidates-template.csv").catch((e) => toast(e.message, "bad"))}>Download template</Btn>
            <Btn size="sm" busy={parsing} onClick={() => sheetRef.current?.click()}>Upload file</Btn>
          </div>
          {bulkRows ? (
            <div className="row"><Chip kind="brand">{bulkRows.length} people from your file</Chip><Btn size="sm" kind="ghost" onClick={() => setBulkRows(null)}>Clear and paste instead</Btn></div>
          ) : (
            <Field label="Or paste: one person per line" hint={'Name, email, phone, skills (skills separated by ;). Leave phone empty if you don\'t have it: Vikas Nair, vikas@example.com, , React. Put a name with a comma in quotes: "Rao, Asha". You can paste straight from Excel.'}>
              <Textarea value={bulkText} onChange={(e) => setBulkText(e.target.value)} style={{ minHeight: 150, fontFamily: "ui-monospace, monospace", fontSize: 12.5 }} data-allow-paste="1"
                placeholder={"Asha Rao, asha@example.com, +91 98450 00001, Python; Django\nVikas Nair, vikas@example.com, , React"} />
            </Field>
          )}
          {preview && (
            <div className="tbl-wrap"><table className="tbl small">
              <thead><tr><th>#</th><th>Name</th><th>Email</th><th>Phone</th><th>Status</th></tr></thead>
              <tbody>{preview.results.map((r, i) => (
                <tr key={i} className={r.status === "invalid" ? "row-bad" : r.status === "duplicate" ? "row-warn" : ""}>
                  <td>{i + 1}</td>
                  <td style={r.fields?.name ? { color: "var(--bad)" } : undefined}>{rows[i]?.name || <span className="faint">—</span>}</td>
                  <td style={r.fields?.email ? { color: "var(--bad)" } : undefined}>{rows[i]?.email || <span className="faint">—</span>}</td>
                  <td style={r.fields?.phone ? { color: "var(--bad)" } : undefined}>{r.phone ? fmtPhone(r.phone) : rows[i]?.phone || <span className="faint">—</span>}</td>
                  <td>{r.status === "ok" ? <Chip kind="good">Ready · {r.kind === "in_pool" ? "existing, in your pool" : r.kind === "account" ? "existing Code2Hire account" : "new"}</Chip> : r.reason === "in_job" ? <span style={{ color: "var(--warn)" }}>Already in this job: skipped</span> : <span style={{ color: r.status === "invalid" ? "var(--bad)" : "var(--warn)" }}>{r.status === "invalid" ? Object.entries(r.fields || {}).map(([k, v]) => `${k === "location" ? "City" : k[0].toUpperCase() + k.slice(1)}: ${v}`).join(" ") : r.error}</span>}</td>
                </tr>))}</tbody>
            </table></div>
          )}
          {preview && <div className="row wrap small"><Chip kind="good">{preview.ready} ready</Chip>{preview.invalid > 0 && <Chip kind="bad">{preview.invalid} with errors (skipped)</Chip>}{preview.duplicates > 0 && <Chip kind="warn">{preview.duplicates} already added (skipped)</Chip>}{preview.results.some((r) => r.kind === "in_pool" || r.kind === "account") && <Chip kind="info">{preview.results.filter((r) => r.kind === "in_pool" || r.kind === "account").length} existing</Chip>}<span className="muted">Fix rows in the box above and check again, or add the ready ones now.</span></div>}
        </>
      )}
    </Modal>
  );
}
