import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../../api";
import { Isha } from "../../components/Mascot";
import { Avatar, Bar, Btn, Chip, Field, Input, Loading, Modal, Seg, Select, Textarea, useAction, useAsync, useToast } from "../../components/ui";
import CallWindow from "../../components/CallWindow";
import { getMedia, startRecorder, uploadRecording, useCall } from "../../lib/call";
import { listen } from "../../lib/speech";

const TAG = { good: ["good", "✓"], claim: ["info", "+"], vague: ["warn", "~"], flag: ["bad", "!"] };

/** Floating, draggable, resizable video window. Shows the shared meeting tab (candidate) or the local camera. */
function FloatingVideo({ stream, label, onClose }) {
  const ref = useRef();
  const vid = useRef();
  const [pos, setPos] = useState({ x: window.innerWidth - 400, y: Math.max(80, window.innerHeight - 250) });
  const drag = useRef(null);
  useEffect(() => { if (vid.current) vid.current.srcObject = stream || null; }, [stream]);
  useEffect(() => {
    const mv = (e) => { if (!drag.current) return; setPos({ x: Math.max(0, Math.min(window.innerWidth - 120, e.clientX - drag.current.dx)), y: Math.max(56, Math.min(window.innerHeight - 60, e.clientY - drag.current.dy)) }); };
    const up = () => (drag.current = null);
    window.addEventListener("pointermove", mv); window.addEventListener("pointerup", up);
    return () => { window.removeEventListener("pointermove", mv); window.removeEventListener("pointerup", up); };
  }, []);
  return (
    <div ref={ref} className="float-video" style={{ left: pos.x, top: pos.y, width: 360, height: 220 }}>
      <div className="fv-h" onPointerDown={(e) => { const r = ref.current.getBoundingClientRect(); drag.current = { dx: e.clientX - r.left, dy: e.clientY - r.top }; }}>
        <span className="dot" style={{ color: "#FF5A5A" }} /> {label}<span style={{ marginLeft: "auto", opacity: .8 }}>drag · resize corner</span>
        <button onClick={onClose} style={{ background: "none", border: 0, color: "#fff", cursor: "pointer" }} aria-label="Hide video">✕</button>
      </div>
      {stream ? <video ref={vid} autoPlay playsInline muted /> : <div style={{ color: "#aaa", display: "grid", placeItems: "center", height: "100%", fontSize: 13, padding: 20, textAlign: "center" }}>No video yet. Share the meeting tab or turn on your camera.</div>}
    </div>
  );
}

export default function IshaRoom() {
  const { id } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const { data, error, setData } = useAsync(() => api.get(`/isha/${id}`), [id]);
  const [state, setState] = useState(null);
  const [options, setOptions] = useState([]);
  const [partial, setPartial] = useState("");
  const [typed, setTyped] = useState("");
  const [custom, setCustom] = useState("");
  const [note, setNote] = useState("");
  const [listening, setListening] = useState(null);
  const [source, setSource] = useState("call");
  const [callInfo, setCallInfo] = useState(null);
  const [localStream, setLocalStream] = useState(null);
  const [inCall, setInCall] = useState(false);
  const [chat, setChat] = useState([]);
  const [captions, setCaptions] = useState(true);
  const [focusAway, setFocusAway] = useState(false);
  const [recording, setRecording] = useState(false);
  const recorder = useRef(null);
  const onMsg = useRef(null);
  const call = useCall({ attId: id, role: "interviewer", info: callInfo, local: localStream, active: inCall && !!callInfo && !!localStream, onMessage: (m) => onMsg.current?.(m) });
  const [stream, setStream] = useState(null);
  const [showVideo, setShowVideo] = useState(true);
  const [thinking, setThinking] = useState(false);
  const [plain, setPlain] = useState(false);
  const [card, setCard] = useState(null);
  const [secs, setSecs] = useState(0);
  const [tab, setTab] = useState("brief");
  const queue = useRef(Promise.resolve());
  const feed = useRef();
  const [run, busy] = useAction();

  useEffect(() => { if (data) setState(data.state); }, [data]);
  useEffect(() => {
    api.get(`/call/${id}`).then((i) => { setCallInfo(i); if (!i.enabled) setSource("mic"); if (i.enabled) api.get(`/call/${id}/chat`).then(setChat).catch(() => {}); }).catch(() => setSource("mic"));
  }, [id]);
  // record once both sides are connected and the interview is running
  useEffect(() => {
    if (callInfo?.record && call.state === "connected" && call.remote && data?.attempt.status === "in_progress" && !recorder.current) {
      recorder.current = startRecorder(call.remote, localStream);
      setRecording(!!recorder.current);
    }
  }, [call.state, call.remote, data?.attempt.status]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const t = setInterval(() => setSecs((s) => s + 1), 1000); return () => clearInterval(t); }, []);
  useEffect(() => { feed.current?.scrollTo({ top: 1e6, behavior: "smooth" }); }, [state, partial]);
  const live = useRef({});
  live.current = { listening, stream, localStream };
  useEffect(() => () => { live.current.listening?.stop(); live.current.stream?.getTracks().forEach((t) => t.stop()); live.current.localStream?.getTracks().forEach((t) => t.stop()); }, []);

  if (error) return <div className="page"><div className="card pad">{error}</div></div>;
  if (!data || !state) return <Loading text="Isha is preparing the brief…" />;
  const att = data.attempt;
  const running = att.status === "in_progress";
  const areas = data.brief?.areas || [];
  const log = state.areas_log || [];
  const cur = state.current ? log[state.current.index] : null;
  const asked = new Set(log.map((a) => a.area));

  const sendSentence = (text) => {
    const parts = text.split(/(?<=[.?!])\s+/).map((s) => s.trim()).filter((s) => s.length > 1);
    parts.forEach((p) => {
      queue.current = queue.current.then(async () => {
        setThinking(true);
        try { const r = await api.post(`/isha/${id}/sentence`, { text: p }); setState(r.state); if (r.options?.length) setOptions(r.options); }
        catch (e) { toast(e.message, "bad"); } finally { setThinking(false); }
      });
    });
  };
  onMsg.current = (m) => {
    if (m.kind === "caption") {
      if (source === "call" && captions && running) sendSentence(m.payload.text);
      else if (source === "call" && captions) setPartial(m.payload.text);
    } else if (m.kind === "chat") setChat((c) => [...c, { from: "candidate", text: m.payload.text }]);
    else if (m.kind === "focus") { setFocusAway(m.payload.visible === false); if (m.payload.visible === false) toast("The candidate switched away from the call tab."); }
    else if (m.kind === "join") toast(`${data.candidate.name} joined the call`, "good");
    else if (m.kind === "bye") toast(`${data.candidate.name} left the call`);
  };
  const joinCall = async () => {
    try { const s = await getMedia(); setLocalStream(s); setInCall(true); setShowVideo(true); }
    catch { toast("Allow camera and microphone in the browser bar to join the call.", "bad"); }
  };
  const saveRecording = async () => {
    if (!recorder.current) return;
    const r = recorder.current; recorder.current = null; setRecording(false);
    const blob = await r.stop();
    if (blob.size > 1000) { try { await uploadRecording(id, blob, r.seconds()); toast("Recording saved to the report", "good"); } catch (e) { toast("Recording upload failed: " + e.message, "bad"); } }
  };
  const start = () => run(() => api.post(`/isha/${id}/start`)).then((s) => { setState(s); setData({ ...data, attempt: { ...att, status: "in_progress" } }); });
  const ask = (q, area, type = "main") => run(() => api.post(`/isha/${id}/ask`, { q, area, type })).then((s) => { setState(s); setOptions([]); setCustom(""); });
  const toggleListen = async () => {
    if (listening) { await listening.stop(); setListening(null); setPartial(""); return; }
    let s = null;
    if (source === "tab") {
      try { s = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true }); setStream(s); setShowVideo(true); }
      catch { toast("Tab sharing was cancelled.", "bad"); return; }
      if (!s.getAudioTracks().length) toast("No audio in that share. Tick “Share tab audio” in the browser dialog.", "bad");
    } else if (!stream) {
      try { const cam = await navigator.mediaDevices.getUserMedia({ video: true }); setStream(cam); } catch { /* camera optional */ }
    }
    const l = await listen({ language: "en-IN", stream: source === "tab" && s?.getAudioTracks().length ? new MediaStream(s.getAudioTracks()) : null,
      onPartial: setPartial, onSentence: (t) => { setPartial(""); sendSentence(t); }, onError: (m) => toast(m) });
    setListening(l);
    toast(l.engine === "azure" ? "Listening with Azure Speech" : l.engine === "browser" ? "Listening with the browser's speech engine" : "Speech isn't available. Type what the candidate says.");
  };
  const end = () => run(() => api.post(`/isha/${id}/end`)).then((r) => { listening?.stop(); setListening(null); setState(r.state); setCard(r.draft); saveRecording(); });
  const mm = `${String(Math.floor(secs / 60)).padStart(2, "0")}:${String(secs % 60).padStart(2, "0")}`;

  return (
    <div className="isha-room">
      <div className="isha-top">
        <Btn size="sm" kind="ghost" onClick={() => nav(-1)}>← Leave</Btn>
        <Isha size={34} mood={thinking ? "think" : running ? "talk" : "idle"} />
        <div className="col" style={{ gap: 0 }}><b>{data.candidate.name}</b><span className="tiny muted">{data.job.title} · {att.name}{data.isha ? " · Isha is helping" : " · scorecard only"}</span></div>
        <Chip kind={running ? "bad" : ""}>{running ? "● Live " + mm : att.status.replace("_", " ")}</Chip>
        <div className="right row">
          {callInfo?.enabled && !inCall && att.status !== "completed" && <Btn kind="primary" onClick={joinCall}>📹 Join video call</Btn>}
          {inCall && <Chip kind={call.state === "connected" ? "good" : "warn"}>{call.state === "connected" ? "● Call connected" : call.peerOnline ? "Connecting…" : "Waiting for candidate"}</Chip>}
          {inCall && call.state !== "connected" && call.state !== "connecting" && <Btn size="sm" onClick={() => call.send("join")}>Ring again</Btn>}
          <Seg value={source} onChange={(v) => { if (listening) { listening.stop(); setListening(null); } setSource(v); }} options={[...(callInfo?.enabled && callInfo?.captions ? [["call", "Call captions"]] : []), ["mic", "My microphone"], ["tab", "Other meeting tab"]]} />
          {source === "call" ? <label className="check small"><input type="checkbox" checked={captions} onChange={(e) => setCaptions(e.target.checked)} />Isha reads captions</label>
            : running && <Btn kind={listening ? "danger" : "primary"} onClick={toggleListen}>{listening ? "■ Stop listening" : "🎙 Start listening"}</Btn>}
          {!showVideo && <Btn size="sm" onClick={() => setShowVideo(true)}>Show video</Btn>}
          {!running && att.status !== "completed" && <Btn kind="primary" busy={busy} onClick={start}>Start interview</Btn>}
          {running && <Btn kind="gold" busy={busy} onClick={end}>End and score</Btn>}
        </div>
      </div>
      <div className="isha-body">
        {/* left: brief */}
        <div className="isha-col">
          <div className="card pad col">
            <div className="row"><Avatar name={data.candidate.name} /><div><b>{data.candidate.name}</b><div className="tiny muted">{data.candidate.headline}</div></div></div>
            <div className="row wrap">{(data.candidate.skills || []).slice(0, 8).map((s, i) => <Chip key={i} kind={s.verified ? "good" : ""}>{s.name}{s.verified ? " ✓" : ""}</Chip>)}</div>
            <div className="seg"><button className={tab === "brief" ? "on" : ""} onClick={() => setTab("brief")}>Plan</button><button className={tab === "resume" ? "on" : ""} onClick={() => setTab("resume")}>Resume</button><button className={tab === "prior" ? "on" : ""} onClick={() => setTab("prior")}>Earlier rounds</button></div>
          </div>
          {tab === "brief" && <div className="card">
            <div className="card-h"><b>Isha's plan</b><span className="small muted">{state.coverage.covered} / {state.coverage.total} covered</span>
              <label className="check tiny right"><input type="checkbox" checked={plain} onChange={(e) => setPlain(e.target.checked)} />Plain words</label></div>
            {areas.map((a, i) => (
              <div key={i} className="list-row" style={{ flexDirection: "column", alignItems: "stretch", gap: 4, background: cur?.area === a.area ? "var(--isha-soft)" : undefined }}>
                <div className="row"><span className="cov"><span className={"m " + (asked.has(a.area) ? "full" : "")} /></span><b className="grow">{a.area}</b><span className="tiny faint">{a.why}</span></div>
                {a.q && <div className="small">{plain && a.simple ? a.simple : a.q}</div>}
                {running && a.q && <Btn size="sm" onClick={() => ask(plain && a.simple ? a.simple : a.q, a.area)}>{asked.has(a.area) ? "Ask again" : "Ask this"}</Btn>}
              </div>
            ))}
            {data.brief?.gaps?.length > 0 && <div className="list-row small" style={{ flexDirection: "column", alignItems: "flex-start" }}><b>Probe from earlier rounds</b>{data.brief.gaps.map((g, i) => <span key={i}>• {g}</span>)}</div>}
          </div>}
          {tab === "resume" && <div className="card pad small" style={{ whiteSpace: "pre-wrap" }}>{data.candidate.resume || "No resume on file."}</div>}
          {tab === "prior" && <div className="card">{!data.prior.length && <div className="empty small">No earlier rounds.</div>}{data.prior.map((p, i) => <div key={i} className="list-row" style={{ flexDirection: "column", alignItems: "flex-start" }}><div className="row"><b>{p.round}</b><Chip>{p.overall}/5</Chip><Chip>{p.recommendation}</Chip>{p.warnings > 0 && <Chip kind="warn">{p.warnings} warnings</Chip>}</div><span className="small">{p.summary}</span></div>)}</div>}
        </div>

        {/* centre: the live answer */}
        <div className="isha-col">
          <div className="card pad col">
            <div className="tiny b muted">CURRENT QUESTION{cur ? ` · ${cur.area}` : ""}</div>
            <h2 style={{ fontSize: 18 }}>{cur?.q || (running ? "Pick a question from the plan or from Isha's suggestions." : "Start the interview when the candidate has joined.")}</h2>
            {cur?.good?.length > 0 && (
              <div className="col" style={{ gap: 4 }}>
                <span className="tiny b muted">A GOOD ANSWER COVERS</span>
                {cur.good.map((g, i) => <div key={i} className="cov"><span className={"m " + (cur.coverage?.[i] || "")} /><span style={{ color: cur.coverage?.[i] === "full" ? "var(--good)" : undefined }}>{g}</span></div>)}
              </div>
            )}
            {cur?.score != null && <div className="row"><span className="small b">Answer so far</span><div className="grow"><Bar value={cur.score} max={5} /></div><b>{cur.score.toFixed(1)} / 5</b></div>}
          </div>
          <div className="card grow" style={{ display: "flex", flexDirection: "column", minHeight: 260 }}>
            <div className="card-h"><b>Live transcript</b>{listening && <Chip kind="bad">● {listening.engine === "azure" ? "Azure" : "Browser"} listening</Chip>}{thinking && <span className="row small muted"><span className="spin" style={{ width: 12, height: 12 }} /> Isha is reading…</span>}</div>
            <div ref={feed} className="col" style={{ padding: 12, overflow: "auto", flex: 1, gap: 8 }}>
              {log.map((a, i) => (
                <div key={i} className="col" style={{ gap: 6 }}>
                  {a.q && <div className="small" style={{ color: "var(--isha)" }}><b>You:</b> {a.q}</div>}
                  {a.sentences.map((s, j) => {
                    const tags = (a.tags || []).filter((t) => t.s === j);
                    return <div key={j} className="sentence"><span>{s}</span>{tags.length > 0 && <div className="tags">{tags.map((t, k) => <Chip key={k} kind={TAG[t.type]?.[0]}>{TAG[t.type]?.[1]} {t.label}</Chip>)}</div>}</div>;
                  })}
                </div>
              ))}
              {partial && <div className="sentence" style={{ opacity: .6, fontStyle: "italic" }}>{partial}…</div>}
              {!log.length && <div className="empty small">Sentences appear here as the candidate speaks, each tagged by Isha.</div>}
            </div>
            {running && <form className="row" style={{ padding: 10, borderTop: "1px solid var(--line)" }} onSubmit={(e) => { e.preventDefault(); if (typed.trim()) { sendSentence(typed); setTyped(""); } }}>
              <Input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Type or paste what the candidate said (Enter)" aria-label="Candidate sentence" data-allow-paste="1" />
              <Btn type="submit">Add</Btn>
            </form>}
          </div>
        </div>

        {/* right: Isha */}
        <div className="isha-col">
          <div className="agent isha"><Isha size={44} mood={thinking ? "think" : options.length ? "talk" : "idle"} /><div className="grow"><b style={{ color: "var(--isha)" }}>Isha suggests</b><div className="small muted">Ranked after every sentence. Only you can see this.</div></div>
            {state.running_score != null && <div style={{ textAlign: "right" }}><div className="tiny muted">Interview so far</div><b style={{ fontSize: 20 }}>{state.running_score}</b><span className="small muted"> / 5</span></div>}</div>
          {options.length === 0 && <div className="card pad small muted">{running ? "Suggestions appear as soon as the candidate starts answering." : "Start the interview to get live suggestions."}</div>}
          {options.map((o, i) => (
            <button key={i + o.q} className={"option " + (i === 0 ? "best" : "")} onClick={() => running && ask(o.q, o.area || cur?.area, o.type)}>
              <div className="row"><Chip kind={o.type === "Clarify" || o.type === "Challenge" ? "bad" : o.type === "Probe" ? "warn" : o.type === "Go deeper" ? "good" : "info"}>{o.type}</Chip>{i === 0 && <Chip kind="isha">Best next</Chip>}<span className="tiny faint right">Click to ask</span></div>
              <div style={{ fontWeight: 650, margin: "6px 0 2px" }}>“{o.q}”</div><div className="small muted">{o.why}</div>
            </button>
          ))}
          {running && <form className="card pad col" onSubmit={(e) => { e.preventDefault(); if (custom.trim()) ask(custom, cur?.area || "General", "own"); }}>
            <b className="small">Ask your own question</b><div className="row"><Input value={custom} onChange={(e) => setCustom(e.target.value)} placeholder="Your question" /><Btn type="submit">Ask</Btn></div></form>}
          <div className="card pad col">
            <b className="small">Private notes</b>
            {state.notes.map((n, i) => <div key={i} className="small">• {n.text} <span className="faint">({n.area})</span></div>)}
            <form className="row" onSubmit={(e) => { e.preventDefault(); if (note.trim()) api.post(`/isha/${id}/note`, { text: note }).then((ns) => { setState({ ...state, notes: ns }); setNote(""); }); }}>
              <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Quick note" /><Btn type="submit" size="sm">Save</Btn></form>
          </div>
          <div className="card pad small muted">The candidate was told this interview is recorded and AI-assisted. Isha suggests; you decide what to ask and how to score.</div>
        </div>
      </div>
      {showVideo && inCall && <CallWindow call={call} local={localStream} info={callInfo} recording={recording} chat={chat} candidateName={data.candidate.name} focusAway={focusAway}
        onChat={(t) => { call.send("chat", { text: t }); setChat((c) => [...c, { from: "interviewer", text: t }]); }} />}
      {showVideo && !inCall && source === "tab" && <FloatingVideo stream={stream} label={stream?.getVideoTracks()[0]?.label?.includes("screen") || source === "tab" ? "Meeting" : "Camera"} onClose={() => setShowVideo(false)} />}
      {card && <Scorecard id={id} draft={card} rubric={data.job.rubric} onClose={() => setCard(null)} onDone={(r) => nav(`/app/reports/${id}`)} />}
    </div>
  );
}

function Scorecard({ id, draft, onClose, onDone }) {
  const [rows, setRows] = useState(draft.competencies.map((c) => ({ ...c, note: "" })));
  const [rec, setRec] = useState("proceed");
  const [summary, setSummary] = useState("");
  const [note, setNote] = useState("");
  const [run, busy] = useAction();
  return (
    <Modal wide title="Scorecard" onClose={onClose} footer={<><Btn onClick={onClose}>Back to interview</Btn><Btn kind="primary" busy={busy} onClick={() => run(() => api.post(`/isha/${id}/scorecard`, { competencies: rows, recommendation: rec, summary, note }), "Scorecard submitted").then(onDone)}>Submit scorecard</Btn></>}>
      <div className="agent isha"><Isha size={36} /><span className="small">Isha pre-filled these from the live interview, with the strongest quote for each. Change anything you disagree with. Skipped areas are marked.</span></div>
      <div className="tbl-wrap"><table className="tbl"><thead><tr><th>Competency</th><th style={{ width: 120 }}>Score</th><th>Evidence quote</th><th>Your note</th></tr></thead><tbody>
        {rows.map((r, i) => <tr key={r.name}><td className="b">{r.name}{r.not_covered && <div><Chip kind="warn">Not covered</Chip></div>}</td>
          <td><Select value={String(r.score ?? "")} onChange={(v) => { const x = [...rows]; x[i] = { ...r, score: v === "" ? null : +v }; setRows(x); }} options={[{ value: "", label: "Skip" }, ..."12345".split("").map((n) => ({ value: n, label: n + " / 5" }))]} /></td>
          <td><Textarea style={{ minHeight: 50 }} value={r.quote || ""} onChange={(e) => { const x = [...rows]; x[i] = { ...r, quote: e.target.value }; setRows(x); }} /></td>
          <td><Input value={r.note} onChange={(e) => { const x = [...rows]; x[i] = { ...r, note: e.target.value }; setRows(x); }} /></td></tr>)}
      </tbody></table></div>
      <Field label="Your recommendation"><Seg value={rec} onChange={setRec} options={[["proceed", "Proceed"], ["hold", "Hold"], ["reject", "Do not proceed"]]} /></Field>
      <Field label="Summary for the hiring team"><Textarea value={summary} onChange={(e) => setSummary(e.target.value)} /></Field>
      <Field label="Private note"><Input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
    </Modal>
  );
}
