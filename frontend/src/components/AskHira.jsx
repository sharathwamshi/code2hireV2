// "Ask Hira" (V02.00.05): the hiring team's assistant, on every staff page. It answers from live data the person's
// role can see (jobs, candidates, stages, scores, reviews, today's interviews), knows the page you're on, and links
// each answer to the record. It answers and suggests; it doesn't add, move or invite anyone.
import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import { Hira } from "./Mascot";
import { Btn, Input, useToast } from "./ui";

function pageContext(path) {
  const job = path.match(/^\/app\/jobs\/(\d+)/);
  const app = path.match(/^\/app\/applications\/(\d+)/);
  return { job_id: job ? Number(job[1]) : undefined, application_id: app ? Number(app[1]) : undefined };
}

export default function AskHira() {
  const loc = useLocation();
  const nav = useNavigate();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState(null);
  const [examples, setExamples] = useState([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const feed = useRef();
  useEffect(() => {
    if (!open || msgs) return;
    api.get("/assistant/history").then((r) => { setMsgs(r.messages); setExamples(r.examples); }).catch(() => setMsgs([]));
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { feed.current?.scrollTo({ top: 1e6, behavior: "smooth" }); }, [msgs?.length, busy, open]);
  useEffect(() => {
    const k = (e) => { if (e.key === "Escape") setOpen(false); };
    if (open) window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [open]);
  if (loc.pathname.startsWith("/app/interviews/") || loc.pathname.startsWith("/app/isha/")) return null; // the live room is busy enough
  const ctx = pageContext(loc.pathname);
  const ask = async (text) => {
    const t = (text ?? q).trim();
    if (!t || busy) return;
    setQ(""); setBusy(true);
    setMsgs((m) => [...(m || []), { id: "u" + Date.now(), role: "user", text: t }]);
    try { const r = await api.post("/assistant/ask", { q: t, page: ctx }); setMsgs((m) => [...(m || []), r]); }
    catch (e) { toast(e.message, "bad"); setMsgs((m) => [...(m || []), { id: "e" + Date.now(), role: "hira", text: "I couldn't look that up just now. Try again in a moment." }]); }
    finally { setBusy(false); }
  };
  const clear = async () => { await api.del("/assistant/history").catch(() => {}); setMsgs([]); };
  if (!open) return <button className="ask-fab" onClick={() => setOpen(true)} aria-label="Ask Hira"><Hira size={28} />Ask Hira</button>;
  return (
    <div className="ask-panel" role="dialog" aria-label="Ask Hira">
      <div className="ask-h"><Hira size={34} mood={busy ? "think" : "idle"} /><div className="grow"><b>Ask Hira</b><div className="tiny muted">Answers come from your live hiring data. {ctx.job_id ? "I know which job you're on." : ""}</div></div>
        {msgs?.length > 0 && <Btn size="sm" kind="ghost" onClick={clear} title="Clear this chat">Clear</Btn>}
        <Btn size="sm" kind="ghost" onClick={() => setOpen(false)} aria-label="Close">✕</Btn></div>
      <div className="ask-feed" ref={feed} aria-live="polite">
        {msgs === null && <span className="small muted">Loading…</span>}
        {msgs?.length === 0 && <div className="col" style={{ gap: 8 }}>
          <div className="ask-msg hira">Hi! Ask me about your jobs and candidates. For example:</div>
          <div className="ask-items">{examples.map((e) => <button key={e} className="ask-item" onClick={() => ask(e)}>{e}</button>)}</div>
        </div>}
        {(msgs || []).map((m) => (
          <div key={m.id} className={"ask-msg " + m.role}>
            {m.text}
            {m.items?.length > 0 && <div className="ask-items">{m.items.map((it, k) => (
              <button key={k} className="ask-item" onClick={() => (it.ask ? ask(it.ask) : it.link ? nav(it.link, it.pick ? { state: { pick: it.pick } } : undefined) : null)}>
                <b className="small">{it.label}</b>{it.sub && <span className="sub">{it.sub}</span>}
              </button>))}</div>}
          </div>
        ))}
        {busy && <div className="ask-msg hira"><span className="spin" style={{ width: 12, height: 12 }} /> Looking it up…</div>}
      </div>
      <form className="ask-f" onSubmit={(e) => { e.preventDefault(); ask(); }}>
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={ctx.job_id ? "e.g. Who should I add to this job?" : "e.g. Which jobs are open?"} maxLength={500} aria-label="Ask Hira a question" autoFocus />
        <Btn kind="primary" type="submit" busy={busy} disabled={!q.trim()}>Ask</Btn>
      </form>
    </div>
  );
}
