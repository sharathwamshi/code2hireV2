// "Ask Disha" (V02.00.09, N1): the candidate's assistant, on every candidate page. It answers from the candidate's own
// record (applications, upcoming rounds, practice, badges, matching jobs) and how-to help. Never anyone else's data,
// nothing the hiring team hasn't shared.
import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import { Disha } from "./Mascot";
import { Btn, Input, useToast } from "./ui";

export default function AskDisha() {
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
    api.get("/disha/history").then((r) => { setMsgs(r.messages); setExamples(r.examples); }).catch(() => setMsgs([]));
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { feed.current?.scrollTo({ top: 1e6, behavior: "smooth" }); }, [msgs?.length, busy, open]);
  useEffect(() => {
    const k = (e) => { if (e.key === "Escape") setOpen(false); };
    if (open) window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [open]);
  if (loc.pathname.startsWith("/room/")) return null; // never during a round
  const ask = async (text) => {
    const t = (text ?? q).trim();
    if (!t || busy) return;
    setQ(""); setBusy(true);
    setMsgs((m) => [...(m || []), { id: "u" + Date.now(), role: "user", text: t }]);
    try { const r = await api.post("/disha/ask", { q: t }); setMsgs((m) => [...(m || []), r]); }
    catch (e) { toast(e.message, "bad"); setMsgs((m) => [...(m || []), { id: "e" + Date.now(), role: "disha", text: "I couldn't look that up just now. Try again in a moment." }]); }
    finally { setBusy(false); }
  };
  const clear = async () => { await api.del("/disha/history").catch(() => {}); setMsgs([]); };
  if (!open) return <button className="ask-fab disha" onClick={() => setOpen(true)} aria-label="Ask Disha"><Disha size={28} />Ask Disha</button>;
  return (
    <div className="ask-panel" role="dialog" aria-label="Ask Disha">
      <div className="ask-h"><Disha size={34} mood={busy ? "think" : "idle"} /><div className="grow"><b>Ask Disha</b><div className="tiny muted">Answers come from your own applications, interviews and practice. Only you see this chat.</div></div>
        {msgs?.length > 0 && <Btn size="sm" kind="ghost" onClick={clear} title="Clear this chat">Clear</Btn>}
        <Btn size="sm" kind="ghost" onClick={() => setOpen(false)} aria-label="Close">✕</Btn></div>
      <div className="ask-feed" ref={feed} aria-live="polite">
        {msgs === null && <span className="small muted">Loading…</span>}
        {msgs?.length === 0 && <div className="col" style={{ gap: 8 }}>
          <div className="ask-msg hira">Hi! I'm Disha. Ask me about your applications, interviews, practice or jobs that match you. For example:</div>
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
        {busy && <div className="ask-msg hira"><span className="spin" style={{ width: 12, height: 12 }} /> Disha is looking…</div>}
      </div>
      <form className="ask-f" onSubmit={(e) => { e.preventDefault(); ask(); }}>
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. When is my next interview?" maxLength={500} aria-label="Ask Disha a question" autoFocus />
        <Btn kind="primary" type="submit" busy={busy} disabled={!q.trim()}>Ask</Btn>
      </form>
    </div>
  );
}
