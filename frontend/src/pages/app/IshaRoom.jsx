import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../../api";
import { Isha } from "../../components/Mascot";
import { Avatar, Bar, Btn, Chip, Field, Input, Loading, Modal, Seg, Select, Textarea, useAction, useAsync, useConfirm, useToast } from "../../components/ui";
import CallWindow from "../../components/CallWindow";
import { useCall } from "../../lib/call";
import { recorderSupported, startRecording } from "../../lib/recorder";
import { listen, micLevel } from "../../lib/speech";
import SystemCheck from "../../components/SystemCheck";
import { lostText, repairStream, useDeviceWatch } from "../../lib/devices";
import { VERSION } from "../../version";

const fmtSecs = (s) => `${String(Math.floor((s || 0) / 60)).padStart(2, "0")}:${String(Math.floor((s || 0) % 60)).padStart(2, "0")}`;

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
  const [recStatus, setRecStatus] = useState(null);
  const [device, setDevice] = useState(null);      // the candidate's camera / mic / face check, sent from their side
  const [events, setEvents] = useState([]);        // live integrity events
  const recorder = useRef(null);
  const recStream = useRef(null);
  const askConfirm = useConfirm();
  const onMsg = useRef(null);
  const call = useCall({ attId: id, role: "interviewer", info: callInfo, local: localStream, active: inCall && !!callInfo && !!localStream, onMessage: (m) => onMsg.current?.(m) });
  const [stream, setStream] = useState(null);
  const [showVideo, setShowVideo] = useState(true);
  const [thinking, setThinking] = useState(false);
  const [plain, setPlain] = useState(false);
  const [card, setCard] = useState(null);
  const [secs, setSecs] = useState(0);
  const [tab, setTab] = useState("brief");
  const [planQ, setPlanQ] = useState("");
  const [checkOpen, setCheckOpen] = useState(false);   // the interviewer's own system check (F2F-001, F2F-003)
  const [checked, setChecked] = useState(false);
  const [docked, setDocked] = useState(true);          // the call sits in the room, not over it (F2F-005)
  const [callLevel, setCallLevel] = useState(0);
  const [preLines, setPreLines] = useState([]);        // captions before "Start interview" (F2F-007)
  const [moved, setMoved] = useState(null);            // Isha moved to a plan question by herself
  const ivRec = useRef(null);
  const lastHeard = useRef(Date.now());              // for "Good time to move on" when the candidate goes quiet
  const queue = useRef(Promise.resolve());
  const feed = useRef();
  const [run, busy] = useAction();

  // only when the room loads: later changes come with their own state (and live events must not be wiped)
  useEffect(() => { if (data) { setState(data.state); setEvents(data.integrity || []); } }, [data?.attempt?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    api.get(`/call/${id}`).then((i) => { setCallInfo(i); if (!i.enabled) setSource("mic"); if (i.enabled) api.get(`/call/${id}/chat`).then(setChat).catch(() => {}); }).catch(() => setSource("mic"));
  }, [id]);
  // Every live interview on the built-in call is recorded (V02.00.04): the candidate large, you in the corner, both voices.
  // A new piece starts whenever the call reconnects with a new stream; each piece uploads every 10 seconds.
  const stopRec = async () => {
    const r = recorder.current; recorder.current = null; recStream.current = null; setRecording(false);
    if (r) { const st = await r.stop(); if (st.pending) toast("Some of the video is still uploading. Keep this page open for a moment.", "bad"); }
  };
  useEffect(() => {
    const live = inCall && call.state === "connected" && call.remote && data?.attempt.status === "in_progress" && callInfo?.record;
    if (live && recStream.current !== call.remote) {
      (async () => {
        if (recorder.current) await stopRec();
        if (!recorderSupported()) { setRecStatus({ unsupported: true }); return; }
        recorder.current = startRecording({ attId: id, video: call.remote, pip: localStream, audio: [call.remote, localStream], onStatus: setRecStatus });
        recStream.current = call.remote;
        setRecording(!!recorder.current);
      })();
    }
  }, [inCall, call.state, call.remote, data?.attempt.status]); // eslint-disable-line react-hooks/exhaustive-deps
  // the browser closing or reloading: hand the last chunk over (best effort)
  useEffect(() => () => { recorder.current?.stop(4000); }, []);
  useEffect(() => { const t = setInterval(() => setSecs((s) => s + 1), 1000); return () => clearInterval(t); }, []);
  // recording health: warn at once if sound is missing, the recorder stopped, or uploads fall behind
  // F2F-002: the warning only shows when sound is really missing, and a new state must hold for 4 s before the bar
  // shows or hides, so normal pauses in the conversation can't make it flicker.
  const [recWarn, setRecWarn] = useState("");
  const warnSeen = useRef({ text: "", since: 0 });
  useEffect(() => {
    if (!recording) { setRecWarn(recStatus?.unsupported ? "This browser can't record the interview. Use Chrome, Edge or Safari 15 or newer." : ""); return undefined; }
    const t = setInterval(() => {
      const h = recorder.current?.health?.();
      if (!h) return;
      let w = "";
      if (!h.recording) w = "The browser stopped recording. Leave the call and join again to restart it.";
      else if (h.failing >= 2) w = `The video isn't reaching the server (${h.lastError}). It's kept here and retried; check your internet.`;
      else if (!h.hasAudioTracks) w = "The recording has no microphone. Check that both of you allowed the microphone.";
      else if (!h.running) w = "The recording has no sound yet. Click anywhere on this page to turn it on.";
      else if (h.silentFor > 60) w = "No sound has reached the recording for a minute. Check that both microphones are on and unmuted.";
      const seen = warnSeen.current;
      if (w !== seen.text) { warnSeen.current = { text: w, since: Date.now() }; return; }
      if (Date.now() - seen.since >= 4000) setRecWarn((cur) => (cur === w ? cur : w));
    }, 1000);
    return () => clearInterval(t);
  }, [recording, recStatus?.unsupported]);
  useEffect(() => { feed.current?.scrollTo({ top: 1e6, behavior: "smooth" }); }, [state, partial]);
  const live = useRef({});
  live.current = { listening, stream, localStream };
  useEffect(() => () => { live.current.listening?.stop(); live.current.stream?.getTracks().forEach((t) => t.stop()); live.current.localStream?.getTracks().forEach((t) => t.stop()); }, []);

  // V02.00.05 hooks (before any early return)
  const myLost = useDeviceWatch(localStream, inCall);
  // sound level of the call, for the steady level bar in the call strip (F2F-002)
  useEffect(() => {
    if (!call.remote?.getAudioTracks().length) { setCallLevel(0); return undefined; }
    let stop = null, last = 0;
    micLevel(call.remote, (l) => { if (Date.now() - last > 200) { last = Date.now(); setCallLevel(l); } }).then((s) => { stop = s; });
    return () => stop?.();
  }, [call.remote]);
  // F2F-005 / F2F-007: the interviewer's own speech is captioned too. It goes into the transcript as "You", and when it is
  // a plan question, Isha moves to that question by herself.
  const running0 = data?.attempt?.status === "in_progress";
  useEffect(() => {
    if (!inCall || !localStream || !running0 || source !== "call" || !captions) return undefined;
    let stop = false;
    (async () => {
      const l = await listen({ language: "en-IN", stream: new MediaStream(localStream.getAudioTracks()),
        onSentence: (t) => api.post(`/isha/${id}/said`, { text: t }).then((r) => { setState(r.state); if (r.moved) { setMoved(r.moved); setOptions([]); } }).catch(() => {}),
        onError: () => {} });
      if (stop) l.stop(); else ivRec.current = l;
    })();
    return () => { stop = true; ivRec.current?.stop(); ivRec.current = null; };
  }, [inCall, localStream, running0, source, captions]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error) return <div className="page"><div className="card pad">{error}</div></div>;
  if (!data || !state) return <Loading text="Isha is preparing the brief…" />;
  const att = data.attempt;
  const running = att.status === "in_progress";
  const areas = data.brief?.areas || [];
  const log = state.areas_log || [];
  const cur = state.current ? log[state.current.index] : null;
  const asked = new Set(log.map((a) => a.area));

  const silentSecs = (Date.now() - lastHeard.current) / 1000;
  const sendSentence = (text) => {
    lastHeard.current = Date.now();
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
      if (source === "call" && captions && running) { setPartial(""); sendSentence(m.payload.text); }
      else if (source === "call" && captions) { setPartial(""); setPreLines((l) => [...l.slice(-30), m.payload.text]); }
    } else if (m.kind === "partial") { lastHeard.current = Date.now(); if (source === "call" && captions) setPartial(m.payload.text); }
    else if (m.kind === "devlost") {
      setDevice((d) => ({ ...(d || {}), ...(m.payload.cam ? { cam: false } : {}), ...(m.payload.mic ? { mic: false } : {}) }));
      toast(`${data.candidate.name}'s ${m.payload.cam && m.payload.mic ? "camera and microphone" : m.payload.cam ? "camera" : "microphone"} stopped. They've been asked to fix it.`, "bad");
    } else if (m.kind === "chat") setChat((c) => [...c, { from: "candidate", text: m.payload.text }]);
    else if (m.kind === "focus") { setFocusAway(m.payload.visible === false); if (m.payload.visible === false) toast("The candidate switched away from the call tab."); }
    else if (m.kind === "join") toast(`${data.candidate.name} joined the call`, "good");
    else if (m.kind === "bye") toast(`${data.candidate.name} left the call. They can rejoin while the interview is open.`);
    else if (m.kind === "device") setDevice((d) => ({ ...(d || {}), ...m.payload }));
    else if (m.kind === "integrity") {
      setEvents((e) => [...e, { ...m.payload, at: m.at }]);
      if (m.payload.counted) toast(`Integrity: ${m.payload.label} (warning ${m.payload.warnings})`, "bad");
    }
  };
  /** F2F-001 / F2F-003: the interviewer's own short check (camera, microphone, speaker) before joining. */
  const joinCall = () => setCheckOpen(true);
  const onChecked = ({ stream: s }) => {
    setCheckOpen(false); setChecked(true);
    if (s) { setLocalStream(s); setInCall(true); setShowVideo(true); }
  };
  const fixMine = async () => {
    try { await repairStream(localStream, (kind, t) => call.replaceTrack(kind, t)); toast("Your camera and microphone work again.", "good"); }
    catch { toast("Allow the camera and microphone in the browser bar, then press Fix it again.", "bad"); }
  };
  /** Leave call: only you leave. The candidate sees "The interviewer stepped out" and waits; the interview stays open. */
  const leaveCall = async () => {
    await ivRec.current?.stop(); ivRec.current = null;
    await stopRec();
    setInCall(false);
    localStream?.getTracks().forEach((t) => t.stop()); setLocalStream(null);
  };
  const editPlan = (change) => api.post(`/isha/${id}/plan`, change).then((r) => { setData({ ...data, brief: r.brief, state: r.state }); setState(r.state); }).catch((e) => toast(e.message, "bad"));
  const move = (i, d) => { const names = areas.map((a) => a.area); const [x] = names.splice(i, 1); names.splice(i + d, 0, x); editPlan({ order: names }); };
  const start = () => run(() => api.post(`/isha/${id}/start`)).then((s) => { setState(s); setData({ ...data, attempt: { ...att, status: "in_progress" } }); });
  const ask = (q, area, type = "main") => run(() => api.post(`/isha/${id}/ask`, { q, area, type })).then((s) => { setState(s); setOptions([]); setCustom(""); setMoved(null); lastHeard.current = Date.now(); });
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
  /** End interview: ends it for both (the candidate's room closes), finishes the video, opens the scorecard. */
  const end = async () => {
    if (!(await askConfirm({ title: "End the interview?", text: "This ends the call for both of you and opens the scorecard. The candidate can't rejoin.", yes: "End interview", no: "Keep going", danger: true }))) return;
    const r = await run(() => api.post(`/isha/${id}/end`)).catch(() => null);
    if (!r) return;
    listening?.stop(); setListening(null); setState(r.state); setCard(r.draft);
    await ivRec.current?.stop(); ivRec.current = null;
    await stopRec();
    if (inCall) { setInCall(false); localStream?.getTracks().forEach((t) => t.stop()); setLocalStream(null); }
  };
  const ended = !!state.ended;
  const mm = `${String(Math.floor(secs / 60)).padStart(2, "0")}:${String(secs % 60).padStart(2, "0")}`;

  // the next question from the plan (F2F-006): the first one not asked and not skipped, in plan order
  const nextQ = (state.remaining || [])[0] || null;
  const coveredAll = cur?.good?.length > 0 && (cur.coverage || []).filter((c) => c === "full").length >= cur.good.length;
  const quiet = running && cur && (cur.sentences || []).length > 0 && !partial && !thinking && silentSecs > 20;
  const moveOn = running && nextQ && (coveredAll || quiet);
  const camOk = localStream?.getVideoTracks()[0]?.readyState === "live" && localStream.getVideoTracks()[0].enabled !== false;
  const micOk = localStream?.getAudioTracks()[0]?.readyState === "live" && localStream.getAudioTracks()[0].enabled !== false;
  const capText = device?.captions === "azure" ? "Captions: working (Azure)" : device?.captions === "browser" ? "Captions: working (browser)" : device?.captions === "none" ? "Captions: not available in the candidate's browser" : null;
  const undoMove = () => api.post(`/isha/${id}/undo-move`).then((st) => { setState(st); setMoved(null); }).catch((e) => toast(e.message, "bad"));
  const callBox = showVideo && inCall && <CallWindow docked={docked} onDock={() => setDocked(!docked)} level={callLevel} call={call} local={localStream} info={callInfo} recording={recording}
    recNote={recStatus ? `Saved up to ${fmtSecs(recStatus.savedSeconds)}` : ""} chat={chat} candidateName={data.candidate.name} focusAway={focusAway} onLeave={leaveCall}
    onChat={(t) => { call.send("chat", { text: t }); setChat((c) => [...c, { from: "interviewer", text: t }]); }} />;

  return (
    <div className="isha-room">
      <div className="isha-top">
        <Btn size="sm" kind="ghost" onClick={() => nav(-1)}>← Back</Btn><span className="version-tag">{VERSION}</span>
        <Isha size={34} mood={thinking ? "think" : running ? "talk" : "idle"} />
        <div className="col ell" style={{ gap: 0 }}><b className="ell">{data.candidate.name}</b><span className="tiny muted ell">{data.job.title} · {att.name}{data.isha ? " · Isha is helping" : " · scorecard only"}</span></div>
        <Chip kind={running ? "bad" : ""}>{running ? "● Live " + mm : att.status.replace("_", " ")}</Chip>
        <div className="right row">
          {callInfo?.enabled && !inCall && !ended && !["completed", "reviewed", "not_finished"].includes(att.status) && <Btn kind="primary" onClick={joinCall}>📹 {att.status === "in_progress" || checked ? "Rejoin call" : "Join video call"}</Btn>}
          {inCall && <Btn size="sm" onClick={leaveCall} title="Only you leave. The candidate waits and the interview stays open.">Leave call</Btn>}
          {!running && att.status !== "completed" && <Btn kind="primary" busy={busy} onClick={start}>Start interview</Btn>}
          {running && !ended && <Btn kind="danger" busy={busy} onClick={end}>End interview</Btn>}
          {ended && att.status === "in_progress" && !card && <Btn kind="primary" onClick={() => setCard(data.draft)}>Open scorecard</Btn>}
        </div>
      </div>
      <div className="isha-sub">
        {callInfo?.enabled && <>
          <span className="lbl">You</span>
          {inCall ? <><Chip kind={camOk ? "good" : "bad"}>{camOk ? "✓ Camera" : "✗ Camera off"}</Chip><Chip kind={micOk ? "good" : "bad"}>{micOk ? "✓ Microphone" : "✗ Microphone off"}</Chip><Chip kind="good">🔊 Speaker checked</Chip></>
            : <><Chip kind="warn">Camera and microphone not checked yet</Chip>{!ended && <Btn size="sm" kind="ghost" onClick={joinCall}>Check camera and mic</Btn>}</>}
          {inCall && <Chip kind={call.state === "connected" ? "good" : "warn"}>{call.state === "connected" ? "● Call connected" : call.state === "reconnecting" ? "Reconnecting…" : call.peerOnline ? "Connecting…" : "Waiting for candidate"}</Chip>}
          {inCall && call.state !== "connected" && call.state !== "connecting" && <Btn size="sm" onClick={() => call.send("join")}>Ring again</Btn>}
          {recording && recStatus && <Chip kind={recStatus.failing ? "bad" : "good"} title="The video uploads every 10 seconds">● Saved up to {fmtSecs(recStatus.savedSeconds)}{recStatus.lowQuality ? " · lower quality" : ""}</Chip>}
          {capText && <Chip kind={device.captions === "none" ? "warn" : "info"}>{capText}</Chip>}
        </>}
        <span className="right row" style={{ gap: 8 }}>
          <Seg value={source} onChange={(v) => { if (listening) { listening.stop(); setListening(null); } setSource(v); }} options={[...(callInfo?.enabled && callInfo?.captions ? [["call", "Call captions"]] : []), ["mic", "My microphone"], ["tab", "Other meeting tab"]]} />
          {source === "call" ? <label className="check small"><input type="checkbox" checked={captions} onChange={(e) => setCaptions(e.target.checked)} />Isha reads captions</label>
            : running && <Btn size="sm" kind={listening ? "danger" : "primary"} onClick={toggleListen}>{listening ? "■ Stop listening" : "🎙 Start listening"}</Btn>}
          {inCall && !showVideo && <Btn size="sm" onClick={() => setShowVideo(true)}>Show video</Btn>}
        </span>
      </div>
      {recWarn && <div className="warnbar w1" role="alert" style={{ position: "static" }}><b>!</b>{recWarn}{/no sound yet/.test(recWarn) && <button className="btn sm ghost right" style={{ color: "inherit" }} onClick={() => recorder.current?.resume?.()}>Turn on sound</button>}</div>}
      {myLost && <div className="warnbar w2" role="alert" style={{ position: "static" }}><b>!</b>{lostText(myLost)}<button className="btn sm right" onClick={fixMine}>Fix it</button></div>}
      {inCall && call.peerAwaySince && Date.now() - call.peerAwaySince > 10 * 60000 && running && <div className="warnbar w1" role="status" style={{ position: "static" }}><b>i</b>The candidate has been away for over 10 minutes. You can keep waiting, ring again, or end the interview. If both of you stay away for 30 minutes it closes as not finished.</div>}
      <div className="isha-body">
        {/* left: plan */}
        <div className="isha-col">
          <div className="card pad col">
            <div className="row"><Avatar name={data.candidate.name} /><div className="ell"><b>{data.candidate.name}</b><div className="tiny muted ell">{data.candidate.headline}</div></div></div>
            <div className="row wrap">{(data.candidate.skills || []).slice(0, 8).map((s, i) => <Chip key={i} kind={s.verified ? "good" : ""}>{s.name}{s.verified ? " ✓" : ""}</Chip>)}</div>
            {callInfo?.enabled && !ended && <div className="col" style={{ gap: 4 }}><span className="tiny b muted">CANDIDATE'S CHECK</span>
              {device ? <div className="row wrap" style={{ gap: 4 }}>
                {device.cam != null && <Chip kind={device.cam ? "good" : "bad"}>{device.cam ? "✓ Camera on" : "✗ Camera off"}</Chip>}
                {device.mic != null && <Chip kind={device.mic ? "good" : "bad"}>{device.mic ? "✓ Microphone on" : "✗ Microphone off"}</Chip>}
                {device.faces != null && device.faces !== "unavailable" && <Chip kind={device.faces === 1 ? "good" : "warn"}>{device.faces === 1 ? "✓ We can see them" : device.faces === 0 ? "No face in view" : `${device.faces} people in view`}</Chip>}
              </div> : <span className="tiny muted">Shown when the candidate joins the call. They passed the system check before joining.</span>}</div>}
            <div className="seg"><button className={tab === "brief" ? "on" : ""} onClick={() => setTab("brief")}>Plan</button><button className={tab === "resume" ? "on" : ""} onClick={() => setTab("resume")}>Resume</button><button className={tab === "prior" ? "on" : ""} onClick={() => setTab("prior")}>Earlier rounds</button></div>
          </div>
          {tab === "brief" && <div className="card">
            <div className="card-h"><b>{data.isha ? "Isha's plan" : "Interview plan"}</b><span className="small muted">{asked.size ? [...asked].filter((x) => areas.some((a) => a.area === x)).length : 0} of {areas.length} asked{state.coverage.skipped ? ` · ${state.coverage.skipped} skipped` : ""}</span>
              <label className="check tiny right"><input type="checkbox" checked={plain} onChange={(e) => setPlain(e.target.checked)} />Plain words</label></div>
            <div style={{ padding: "0 12px 8px" }}><Bar value={areas.length ? areas.filter((a) => asked.has(a.area)).length : 0} max={Math.max(1, areas.length)} /></div>
            {areas.map((a, i) => (
              <div key={a.area} className="plan-row" style={{ background: cur?.area === a.area ? "var(--isha-soft)" : undefined, opacity: a.skipped && !asked.has(a.area) ? 0.55 : 1 }}>
                <div className="plan-head"><span className="cov"><span className={"m " + (asked.has(a.area) ? "full" : "")} /></span><span className="tiny faint">{i + 1}.</span><b className="ell" title={a.area}>{a.area}</b>
                  <span className="row" style={{ gap: 4 }}>{a.own && <Chip kind="brand">Yours</Chip>}{a.skipped && !asked.has(a.area) && <Chip>Skipped</Chip>}{nextQ?.area === a.area && <Chip kind="isha">Next</Chip>}</span></div>
                {a.q && <div className="plan-q">{plain && a.simple ? a.simple : a.q}</div>}
                {!a.own && a.why && <div className="plan-why">{a.why}</div>}
                {!ended && <div className="row" style={{ gap: 4 }}>
                  {running && a.q && <Btn size="sm" onClick={() => ask(plain && a.simple ? a.simple : a.q, a.area)}>{asked.has(a.area) ? "Ask again" : "Ask this"}</Btn>}
                  {!asked.has(a.area) && <Btn size="sm" kind="ghost" onClick={() => editPlan(a.skipped ? { unskip: a.area } : { skip: a.area })}>{a.skipped ? "Un-skip" : "Skip"}</Btn>}
                  <span className="right" />
                  <Btn size="sm" kind="ghost" aria-label={`Move ${a.area} up`} disabled={i === 0} onClick={() => move(i, -1)}>↑</Btn>
                  <Btn size="sm" kind="ghost" aria-label={`Move ${a.area} down`} disabled={i === areas.length - 1} onClick={() => move(i, 1)}>↓</Btn>
                </div>}
              </div>
            ))}
            {!ended && <form className="list-row" style={{ gap: 6 }} onSubmit={(e) => { e.preventDefault(); if (planQ.trim()) editPlan({ add: planQ }).then(() => setPlanQ("")); }}>
              <Input value={planQ} onChange={(e) => setPlanQ(e.target.value)} placeholder="Add your own question to the plan" aria-label="Add a question to the plan" maxLength={300} /><Btn type="submit" size="sm" disabled={!planQ.trim()}>Add</Btn></form>}
            {data.brief?.gaps?.length > 0 && <div className="list-row small" style={{ flexDirection: "column", alignItems: "flex-start" }}><b>Probe from earlier rounds</b>{data.brief.gaps.map((g, i) => <span key={i}>• {g}</span>)}</div>}
          </div>}
          {tab === "resume" && <div className="card pad small" style={{ whiteSpace: "pre-wrap" }}>{data.candidate.resume || "No resume on file."}</div>}
          {tab === "prior" && <div className="card">{!data.prior.length && <div className="empty small">No earlier rounds.</div>}{data.prior.map((p, i) => <div key={i} className="list-row" style={{ flexDirection: "column", alignItems: "flex-start" }}><div className="row"><b>{p.round}</b><Chip>{p.overall}/5</Chip><Chip>{p.recommendation}</Chip>{p.warnings > 0 && <Chip kind="warn">{p.warnings} warnings</Chip>}</div><span className="small">{p.summary}</span></div>)}</div>}
        </div>

        {/* centre: the call, the current question and the transcript */}
        <div className="isha-col">
          {docked && callBox}
          <div className="card pad col">
            <div className="tiny b muted">CURRENT QUESTION{cur ? ` · ${cur.area}` : ""}{cur?.auto ? " · Isha heard you ask it" : ""}</div>
            <h2 style={{ fontSize: 18 }}>{cur?.q || (running ? "Ask the next question from the plan, or pick one of Isha's suggestions." : "Start the interview when the candidate has joined.")}</h2>
            {moved && <div className="sc-note info row" role="status"><span className="grow">Isha moved to “{moved.area}” because you asked it.</span><Btn size="sm" kind="ghost" onClick={undoMove}>Undo</Btn><Btn size="sm" kind="ghost" onClick={() => setMoved(null)}>OK</Btn></div>}
            {cur && running && <div className="small muted">Isha heard {(cur.sentences || []).length} sentence{(cur.sentences || []).length === 1 ? "" : "s"}{cur.good?.length ? `, covering ${(cur.coverage || []).filter((c) => c === "full").length} of ${cur.good.length} points` : ""}.</div>}
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
              {preLines.length > 0 && <div className="col" style={{ gap: 4 }}><span className="tiny b muted">BEFORE THE INTERVIEW STARTED</span>{preLines.map((t, i) => <div key={i} className="small"><span className="who cand">{data.candidate.name.split(" ")[0]}</span>{t}</div>)}</div>}
              {log.map((a, i) => {
                const said = a.said || [];
                return (
                  <div key={i} className="col" style={{ gap: 6 }}>
                    {a.q && <div className="small" style={{ color: "var(--isha)" }}><span className="who iv">You asked</span>{a.q}</div>}
                    {a.sentences.map((s, j) => {
                      const tags = (a.tags || []).filter((t) => t.s === j);
                      return (<div key={j} className="col" style={{ gap: 4 }}>
                        {said.filter((x) => x.after === j).map((x, k) => <div key={"y" + k} className="small"><span className="who iv">You</span>{x.t}</div>)}
                        <div className="sentence"><span><span className="who cand">{data.candidate.name.split(" ")[0]}</span>{s}</span>{tags.length > 0 && <div className="tags">{tags.map((t, k) => <Chip key={k} kind={TAG[t.type]?.[0]}>{TAG[t.type]?.[1]} {t.label}</Chip>)}</div>}</div>
                      </div>);
                    })}
                    {said.filter((x) => x.after >= a.sentences.length).map((x, k) => <div key={"z" + k} className="small"><span className="who iv">You</span>{x.t}</div>)}
                  </div>
                );
              })}
              {partial && <div className="sentence" style={{ opacity: .6, fontStyle: "italic" }}><span className="who cand">{data.candidate.name.split(" ")[0]}</span>{partial}…</div>}
              {!log.length && !preLines.length && <div className="empty small">Captions of both of you appear here as you speak, and Isha tags each of the candidate's sentences.</div>}
            </div>
            {running && <form className="row" style={{ padding: 10, borderTop: "1px solid var(--line)" }} onSubmit={(e) => { e.preventDefault(); if (typed.trim()) { sendSentence(typed); setTyped(""); } }}>
              <Input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Type or paste what the candidate said (Enter)" aria-label="Candidate sentence" data-allow-paste="1" />
              <Btn type="submit">Add</Btn>
            </form>}
          </div>
        </div>

        {/* right: next question, Isha, integrity, notes */}
        <div className="isha-col">
          {running && !ended && (nextQ ? (
            <div className={"next-card" + (moveOn ? " move" : "")} aria-live="polite">
              <div className="row"><b className="small" style={{ color: "var(--isha)" }}>NEXT QUESTION</b>{moveOn && <Chip kind="isha">Good time to move on</Chip>}<span className="tiny muted right">{(state.remaining || []).length} left</span></div>
              <div className="tiny muted">{nextQ.area}{nextQ.own ? " · yours" : ""}</div>
              <div style={{ fontWeight: 650 }}>“{plain && nextQ.simple ? nextQ.simple : nextQ.q}”</div>
              {moveOn && <span className="tiny muted">{coveredAll ? "The answer covers every expected point." : "The candidate has gone quiet."}</span>}
              <div className="row"><Btn kind="primary" size="sm" onClick={() => ask(plain && nextQ.simple ? nextQ.simple : nextQ.q, nextQ.area)}>Ask this</Btn><Btn size="sm" kind="ghost" onClick={() => editPlan({ skip: nextQ.area })}>Skip</Btn></div>
            </div>
          ) : <div className="next-card"><b className="small" style={{ color: "var(--isha)" }}>NEXT QUESTION</b><span className="small">Every question in the plan has been asked or skipped. Add one, ask your own, or end the interview.</span></div>)}
          {!running && !ended && nextQ && <div className="next-card"><b className="small" style={{ color: "var(--isha)" }}>FIRST QUESTION</b><div style={{ fontWeight: 650 }}>“{nextQ.q}”</div><span className="tiny muted">Start the interview, then ask it.</span></div>}
          <div className="agent isha"><Isha size={44} mood={thinking ? "think" : options.length ? "talk" : "idle"} /><div className="grow"><b style={{ color: "var(--isha)" }}>Isha suggests follow-ups</b><div className="small muted">Ranked after every sentence. Only you can see this.</div></div>
            {state.running_score != null && <div style={{ textAlign: "right" }}><div className="tiny muted">Interview so far</div><b style={{ fontSize: 20 }}>{state.running_score}</b><span className="small muted"> / 5</span></div>}</div>
          {options.length === 0 && <div className="card pad small muted">{running ? "Follow-ups appear as soon as the candidate starts answering." : "Start the interview to get live suggestions."}</div>}
          {options.map((o, i) => (
            <button key={i + o.q} className={"option " + (i === 0 ? "best" : "")} onClick={() => running && ask(o.q, o.area || cur?.area, o.type)}>
              <div className="row"><Chip kind={o.type === "Clarify" || o.type === "Challenge" ? "bad" : o.type === "Probe" ? "warn" : o.type === "Go deeper" ? "good" : "info"}>{o.type}</Chip>{i === 0 && <Chip kind="isha">Best follow-up</Chip>}<span className="tiny faint right">Click to ask</span></div>
              <div style={{ fontWeight: 650, margin: "6px 0 2px" }}>“{o.q}”</div><div className="small muted">{o.why}</div>
            </button>
          ))}
          {running && <form className="card pad col" onSubmit={(e) => { e.preventDefault(); if (custom.trim()) ask(custom, cur?.area || "General", "own"); }}>
            <b className="small">Ask your own question</b><div className="row"><Input value={custom} onChange={(e) => setCustom(e.target.value)} placeholder="Your question" /><Btn type="submit">Ask</Btn></div></form>}
          {(callInfo?.enabled || events.length > 0) && <div className="card pad col" aria-live="polite">
            <div className="row"><b className="small">Integrity</b><span className="right" /><Chip kind={events.some((e) => e.counted) ? "warn" : "good"}>{events.filter((e) => e.counted).length ? `${events.filter((e) => e.counted).length} warning${events.filter((e) => e.counted).length > 1 ? "s" : ""}` : "Clean"}</Chip></div>
            {!events.length && <span className="tiny muted">Tab switches, pasting, leaving fullscreen and face checks appear here as they happen.</span>}
            {events.slice(-8).reverse().map((e, i) => <div key={i} className="row small" style={{ gap: 6 }}><Chip kind={e.counted ? "bad" : ""}>{e.counted ? "Warning" : "Noted"}</Chip><span className="grow">{e.label}</span><span className="tiny faint">{e.at ? new Date(e.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : ""}</span></div>)}
          </div>}
          <div className="card pad col">
            <b className="small">Private notes</b>
            {state.notes.map((n, i) => <div key={i} className="small">• {n.text} <span className="faint">({n.area})</span></div>)}
            <form className="row" onSubmit={(e) => { e.preventDefault(); if (note.trim()) api.post(`/isha/${id}/note`, { text: note }).then((ns) => { setState({ ...state, notes: ns }); setNote(""); }); }}>
              <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Quick note" /><Btn type="submit" size="sm">Save</Btn></form>
          </div>
          <div className="card pad small muted">The candidate was told this interview is recorded and AI-assisted. Isha suggests; you decide what to ask and how to score.</div>
        </div>
      </div>
      {!docked && callBox}
      {showVideo && !inCall && source === "tab" && <FloatingVideo stream={stream} label={stream?.getVideoTracks()[0]?.label?.includes("screen") || source === "tab" ? "Meeting" : "Camera"} onClose={() => setShowVideo(false)} />}
      {checkOpen && <Modal wide title="Check your camera, microphone and speaker" onClose={() => setCheckOpen(false)}>
        <SystemCheck attemptId={id} role="interviewer" mode={checked ? "recheck" : "full"} onPassed={onChecked} />
      </Modal>}
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
