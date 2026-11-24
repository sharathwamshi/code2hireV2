import FileUnder, { normSentence } from "../../components/FileUnder";
import { describeCall } from "../../components/CallStatus";
import InterviewAgain from "../../components/InterviewAgain";
import CloseInterview from "../../components/CloseInterview";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { Isha } from "../../components/Mascot";
import { Avatar, Bar, Btn, Chip, Field, Input, Loading, Modal, Seg, Select, Textarea, useAction, useAsync, useConfirm, useToast } from "../../components/ui";
import CallWindow, { useChatSend } from "../../components/CallWindow";
import { useCall } from "../../lib/call";
import { recorderSupported, startRecording } from "../../lib/recorder";
import { listen, micLevel } from "../../lib/speech";
import SystemCheck from "../../components/SystemCheck";
import { lostText, repairStream, useDeviceWatch } from "../../lib/devices";
import { VERSION } from "../../version";
import PrepareQuestions from "../../components/PrepareQuestions";

const fmtSecs = (s) => `${String(Math.floor((s || 0) / 60)).padStart(2, "0")}:${String(Math.floor((s || 0) % 60)).padStart(2, "0")}`;

const TAG = { good: ["good", "✓"], claim: ["info", "+"], vague: ["warn", "~"], flag: ["bad", "!"] };
// V02.00.13: where a question or follow-up came from, shown on every one
const FU_SOURCE = { claude: "Claude, live", prepared: "Prepared", builtin: "Built-in", plan: "From your plan" };
const SRC_TONE = { claude: "good", builtin: "warn", own: "brand", bank: "info" };
const SRC_LABEL = { claude: "Written by Claude", builtin: "Built-in · Claude was unavailable", own: "Yours", bank: "From the question bank" };

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

// gap 2 (V02.00.07): a candidate caption that repeats what the interviewer said in the last 20 seconds is the
// interviewer's voice coming back through the candidate's speakers, not an answer.
function echoWords(t) { return (t || "").toLowerCase().replace(/[^a-z0-9\s]/g, " ").split(/\s+/).filter((w) => w.length > 2); }
function isEcho(text, recent) {
  const w = echoWords(text);
  if (w.length < 3) return false;
  return recent.some((r) => Date.now() - r.at < 20000 && w.filter((x) => r.words.includes(x)).length / w.length >= 0.7);
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
  const [retake, setRetake] = useState(false);  // V02.00.08: end because of a technical problem and send a retake
  const [closing, setClosing] = useState(false);  // N4 (V02.00.09)
  const [params] = useSearchParams();
  const wantCard = params.get("scorecard") === "1";
  const [secs, setSecs] = useState(0);
  const [planQ, setPlanQ] = useState("");
  const [checkOpen, setCheckOpen] = useState(false);   // the interviewer's own system check (F2F-001, F2F-003)
  const [checked, setChecked] = useState(false);
  // the call sits in the room, not over it (F2F-005); V02.00.08 remembers each interviewer's choice
  // V02.01.02: docked by default for every interview; popping out lasts for this interview only
  const [docked, setDockedRaw] = useState(() => { try { return sessionStorage.getItem(`c2h_dock_${id}`) !== "0"; } catch { return true; } });
  const setDocked = (v) => { setDockedRaw(v); try { sessionStorage.setItem(`c2h_dock_${id}`, v ? "1" : "0"); } catch { /* private mode */ } };
  const [callLevel, setCallLevel] = useState(0);
  const [preLines, setPreLines] = useState([]);        // captions before "Start interview" (F2F-007)
  const preBuf = useRef([]);   // V02.01.04: both voices before Start, kept in the transcript when the interview starts
  const [autoIn, setAutoIn] = useState(null);           // V02.01.04: seconds until the automatic start
  const [held, setHeldRaw] = useState(() => { try { return sessionStorage.getItem(`c2h_autohold_${id}`) === "1"; } catch { return false; } });
  const setHeld = (v) => { setHeldRaw(v); try { sessionStorage.setItem(`c2h_autohold_${id}`, v ? "1" : "0"); } catch { /* private mode */ } };
  const beeped = useRef(false);
  const [moved, setMoved] = useState(null);            // Isha moved to a plan question by herself
  const ivRec = useRef(null);
  const lastHeard = useRef(Date.now());              // for "Good time to move on" when the candidate goes quiet
  const lastCaption = useRef(0);                     // gap 1: caption health ("last caption 3 s ago")
  const [echoes, setEchoes] = useState(0);
  const queue = useRef(Promise.resolve());
  const feed = useRef();
  const [run, busy] = useAction();
  // V02.00.13: the stage layout, pinned follow-ups, "Did you ask …?", Ask Isha, Prepare questions
  const [pins, setPins] = useState([]);
  const pinsRef = useRef([]);
  pinsRef.current = pins;
  const [maybe, setMaybe] = useState(null);
  const [drawer, setDrawer] = useState(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [ishaChat, setIshaChat] = useState([]);
  const [chatMsg, setChatMsg] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const chatFeed = useRef();
  const [prepOpen, setPrepOpen] = useState(false);
  const prepShown = useRef(false);
  useEffect(() => {
    if (!data) return;
    setIshaChat(data.chat || []);
    if ((data.options || []).length) setOptions(data.options);  // the latest follow-ups survive a reload
    // the first time a not-yet-started interview with Isha opens and nobody has chosen questions: open Prepare
    if (!prepShown.current && data.isha && ["invited", "scheduled"].includes(data.attempt.status) && data.brief?.prep && !data.brief.prep.saved) setPrepOpen(true);
    prepShown.current = true;
  }, [data?.attempt?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { chatFeed.current?.scrollTo({ top: 1e6, behavior: "smooth" }); }, [ishaChat, chatOpen]);
  // a pinned follow-up that was asked (heard or marked) unpins by itself
  useEffect(() => {
    const qs = new Set((state?.areas_log || []).map((e) => (e.q || "").trim()));
    setPins((p) => (p.some((x) => qs.has(x.q.trim())) ? p.filter((x) => !qs.has(x.q.trim())) : p));
  }, [state]);

  // only when the room loads: later changes come with their own state (and live events must not be wiped)
  useEffect(() => { if (data) { setState(data.state); setEvents(data.integrity || []); } }, [data?.attempt?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  // N4 (V02.00.09): "Open scorecard" from the Interviews list or the application page lands here with ?scorecard=1
  useEffect(() => {
    if (wantCard && data && ["not_finished", "in_progress", "paused"].includes(data.attempt.status))
      api.post(`/isha/${id}/redraft?ai=0`).then((r) => setCard(r.draft)).catch(() => {});
  }, [data?.attempt?.id]); // eslint-disable-line react-hooks/exhaustive-deps
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

  // C2 (V02.00.06): where the candidate is until the call connects, and C3: an earlier round of theirs still running
  const [candStatus, setCandStatus] = useState(null);
  const connected = inCall && call.state === "connected";
  const everConnected = useRef(false);
  if (connected) everConnected.current = true;
  const callSt = describeCall(call, "candidate", everConnected.current);
  useEffect(() => {
    if (!data || data.state?.ended) return undefined;
    let alive = true;
    const get = () => api.get(`/isha/${id}/candidate-status`).then((r) => alive && setCandStatus(r)).catch(() => {});
    get();
    const t = setInterval(get, connected ? 30000 : 5000);
    return () => { alive = false; clearInterval(t); };
  }, [id, !!data, connected]); // eslint-disable-line react-hooks/exhaustive-deps
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
  // V02.00.07: they also go to the candidate as subtitles (bug 5; the candidate turns them on with CC), from the moment
  // the call starts, and Isha remembers them for a few seconds to drop the same words echoing back from the candidate's
  // speakers (gap 2).
  const running0 = data?.attempt?.status === "in_progress";
  const liveRef = useRef({ running: false, captions: true });
  liveRef.current = { running: running0, captions };
  const ivSaid = useRef([]);   // [{ words, at }]
  useEffect(() => {
    if (!inCall || !localStream || source !== "call") return undefined;
    let stop = false, lastPartial = 0;
    (async () => {
      const l = await listen({ language: "en-IN", stream: new MediaStream(localStream.getAudioTracks()),
        onPartial: (t) => { if (t && Date.now() - lastPartial > 900 && localStream.getAudioTracks()[0]?.enabled !== false) { lastPartial = Date.now(); call.send("iv_caption", { text: t }); } },
        onSentence: (t) => {
          ivSaid.current = [...ivSaid.current.filter((x) => Date.now() - x.at < 20000), { words: echoWords(t), at: Date.now() }];
          if (localStream.getAudioTracks()[0]?.enabled !== false) call.send("iv_caption", { text: t, final: true });
          if (liveRef.current.running && liveRef.current.captions) {
            api.post(`/isha/${id}/said`, { text: t, pinned: pinsRef.current.map((p) => p.q) }).then((r) => { setState(r.state); if (r.moved) { setMoved(r.moved); setOptions([]); setMaybe(null); } else if (r.maybe) setMaybe(r.maybe); }).catch(() => {});
          } else if (liveRef.current.captions) {
            preBuf.current = [...preBuf.current.slice(-59), { who: "interviewer", text: t }];
          }
        },
        onError: () => {} });
      if (stop) l.stop(); else ivRec.current = l;
    })();
    return () => { stop = true; ivRec.current?.stop(); ivRec.current = null; };
  }, [inCall, localStream, source]); // eslint-disable-line react-hooks/exhaustive-deps

  // V02.01.04: once the interviewer and the candidate are both in the call, the interview starts by itself after a
  // 5-second countdown ("Not yet" holds it). With a meeting outside Code2Hire, a sound and a banner say the candidate
  // has joined.
  const notStarted = !!data && data.attempt?.status !== "in_progress" && !data.state?.ended && !(state?.ended)
    && !["completed", "reviewed", "not_finished", "voided", "cancelled"].includes(data.attempt?.status);
  useEffect(() => {
    if (connected && notStarted && !held && autoIn === null) setAutoIn(5);
    if ((!connected || !notStarted) && autoIn !== null) setAutoIn(null);
  }, [connected, notStarted, held]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (autoIn === null) return undefined;
    if (autoIn <= 0) { setAutoIn(null); startRef.current?.({ auto: true }); return undefined; }
    const t = setTimeout(() => setAutoIn((n) => (n === null ? null : n - 1)), 1000);
    return () => clearTimeout(t);
  }, [autoIn]);
  const outsideJoined = notStarted && !(callInfo?.enabled && inCall) && candStatus?.stage === "joined";
  useEffect(() => {
    if (!outsideJoined || beeped.current) return;
    beeped.current = true;
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const o = ctx.createOscillator(); const g = ctx.createGain();
      o.frequency.value = 880; g.gain.value = 0.08; o.connect(g); g.connect(ctx.destination); o.start(); o.stop(ctx.currentTime + 0.25);
    } catch { /* no sound available */ }
  }, [outsideJoined]);
  const startRef = useRef(null);
  // V02.01.04: Isha's live score for a topic: when its answer ends (the topic changes) or after 20 s of quiet
  const scoring = useRef({});
  const scoreTopic = (area) => {
    if (!area || scoring.current[area]) return;
    scoring.current[area] = true;
    api.post(`/isha/${id}/score-topic`, { area }).then((r) => r?.state && setState(r.state)).catch(() => {}).finally(() => { scoring.current[area] = false; });
  };
  const rateTopic = (area, score) => api.post(`/isha/${id}/topic-rating`, { area, score }).then(setState).catch((e) => toast(e.message, "bad"));
  const quietScored = useRef("");
  useEffect(() => {
    const t = setInterval(() => {
      const st = liveState.current;
      if (!st.running || !st.now) return;
      const key = `${st.now}:${st.heard}`;
      if (Date.now() - lastHeard.current > 20000 && quietScored.current !== key) { quietScored.current = key; scoreTopic(st.now); }
    }, 5000);
    return () => clearInterval(t);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const liveState = useRef({});
  liveState.current = { running: data?.attempt?.status === "in_progress", now: state?.topics?.now, heard: state?.topics?.heard };

  const [chatSend, chatRetry] = useChatSend(call, setChat, "interviewer");  // F2F-002 (V02.00.08)
  const [editing, setEditing] = useState(null);  // F2F-001 (V02.00.08): the caption being corrected
  if (error) return <div className="page"><div className="card pad">{error}</div></div>;
  const retakeModal = retake && <InterviewAgain attemptId={id} preset="retake" onClose={() => setRetake(false)}
    onDone={(r) => { setRetake(false); toast(r?.message || "Done"); try { call.hangup?.(true); } catch { /* not in the call */ } nav(r?.attempt_id && String(r.attempt_id) !== String(id) ? `/app/isha/${r.attempt_id}` : "/app/interviews"); }} />;
  const openCard = () => api.post(`/isha/${id}/redraft?ai=0`).then((r) => setCard(r.draft)).catch((e) => { if (data?.draft) setCard(data.draft); else toast(e.message, "bad"); });
  if (!data || !state) return <Loading text="Isha is preparing the brief…" />;
  const att = data.attempt;
  const running = att.status === "in_progress";
  const areas = data.brief?.areas || [];
  const log = state.areas_log || [];
  const cur = state.current ? log[state.current.index] : null;
  const asked = new Set(log.map((a) => a.area));

  const silentSecs = (Date.now() - lastHeard.current) / 1000;
  // F2F-001 (V02.00.08): correct or remove a caption
  const saveEdit = (e = editing) => { if (!e) return; api.post(`/isha/${id}/edit-sentence`, { index: e.i, sentence: e.j, text: e.text }).then((st) => { setState(st); setEditing(null); toast(e.text ? "Corrected" : "Removed"); }).catch((err) => toast(err.message, "bad")); };
  const sendSentence = (text) => {
    lastHeard.current = Date.now();
    const parts = text.split(/(?<=[.?!])\s+/).map((s) => s.trim()).filter((s) => s.length > 1);
    parts.forEach((p) => {
      queue.current = queue.current.then(async () => {
        setThinking(true);
        try {
          const r = await api.post(`/isha/${id}/sentence`, { text: p }); setState(r.state); if (r.options?.length) setOptions(r.options);
          if (r.topic_ended) scoreTopic(r.topic_ended);   // V02.01.04: the answer to that topic ended: Isha scores it
        }
        catch (e) { toast(e.message, "bad"); } finally { setThinking(false); }
      });
    });
  };
  onMsg.current = (m) => {
    if (m.kind === "caption") {
      lastCaption.current = Date.now();
      if (isEcho(m.payload.text, ivSaid.current)) { setEchoes((n) => n + 1); return; }   // gap 2: the interviewer's own words, heard through the candidate's speakers
      if (source === "call" && captions && running) { setPartial(""); sendSentence(m.payload.text); }
      else if (source === "call" && captions) { setPartial(""); setPreLines((l) => [...l.slice(-30), m.payload.text]); preBuf.current = [...preBuf.current.slice(-59), { who: "candidate", text: m.payload.text }]; }
    } else if (m.kind === "partial") { lastHeard.current = Date.now(); lastCaption.current = Date.now(); if (source === "call" && captions && !isEcho(m.payload.text, ivSaid.current)) setPartial(m.payload.text); }
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
  // C1 (V02.00.06): start when the candidate is connected; starting earlier asks first
  const start = async (opts = {}) => {
    let video = null;
    if (!opts.auto && callInfo?.enabled && !connected) {
      const here = inCall && call.peerOnline;
      const where = candStatus?.text ? ` Right now: ${candStatus.text.toLowerCase()}.` : "";
      // V02.00.08: "here but the video can't connect" is a different problem from "hasn't joined", so it says so
      const ok = here
        ? await askConfirm({ title: "The video isn't connected", text: `The candidate is here, but the video hasn't connected${call.attempt ? ` after ${call.attempt + 1} attempts` : ""}. You can wait while it keeps trying, or start now: captions, chat and Isha still work, nothing is recorded until the video connects, and the report notes that the interview started without video.`, yes: "Start without video", no: "Keep trying" })
        : await askConfirm({ title: "The candidate hasn't joined yet", text: `Start the interview anyway? The timer starts now and nothing is recorded until the call connects.${where}`, yes: "Start anyway", no: "Wait for them" });
      if (!ok) return;
      video = here ? "not_connected" : "candidate_absent";
    }
    const pre = preBuf.current.slice(-60);
    const s = await run(() => api.post(`/isha/${id}/start`, { ...(video ? { video } : {}), ...(pre.length ? { pre } : {}), ...(opts.auto ? { auto: true } : {}) })).catch(() => null);
    if (!s) return;
    preBuf.current = [];
    if (opts.auto) toast("The interview has started: recording, timer and Isha are on.", "good");
    setState(s); setData({ ...data, attempt: { ...att, status: "in_progress", started_at: new Date().toISOString() } });
  };
  startRef.current = start;
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
    const l = await listen({ language: "en-IN", source: source === "tab" ? "tab" : "mic", stream: source === "tab" && s?.getAudioTracks().length ? new MediaStream(s.getAudioTracks()) : null,
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
  const heardAny = (state.areas_log || []).some((e) => (e.sentences || []).length);
  // the live timer counts from when the interview started (the same clock as the report), not from opening this page
  const since = att.started_at ? Math.max(0, Math.floor((Date.now() - new Date(att.started_at.endsWith("Z") ? att.started_at : att.started_at + "Z").getTime()) / 1000)) : secs;
  const mm = `${String(Math.floor(since / 60)).padStart(2, "0")}:${String(since % 60).padStart(2, "0")}`;

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
    onChat={chatSend} onChatRetry={chatRetry} />;
  // V02.00.13 helpers for the stage
  const fuList = [...pins, ...options.filter((o) => !pins.some((p) => p.q === o.q))].slice(0, 6);
  const togglePin = (o) => setPins((p) => (p.some((x) => x.q === o.q) ? p.filter((x) => x.q !== o.q) : p.length >= 3 ? (toast("You can pin up to 3 follow-ups. Unpin one first.", "bad"), p) : [{ ...o }, ...p]));
  const curPlan = cur ? areas.find((a) => a.area === cur.area) : null;
  const topics = state?.topics?.topics || [];
  const topicOf = (area) => topics.find((t) => t.area === area);
  const nowTopic = state?.topics?.now || null;
  const areaStatus = (a) => {
    // V02.01.01: while the interview runs, nothing is filed: each topic shows how much of it has come up so far,
    // from the whole transcript. After the end, Isha's review decides and the scores show.
    const tp = topicOf(a.area);
    if (tp && !ended) {
      const score = tp.your_rating ?? tp.score ?? null;   // V02.01.04: your rating, else Isha's live score
      if (a.skipped && tp.state === "none") return { cls: "skip", tone: "", label: "Skipped" };
      if (running && nowTopic === a.area) return { cls: "now", tone: "brand", label: "Talking now", score };
      if (tp.state === "well") return { cls: "done", tone: "good", label: "Well covered", score };
      if (tp.state === "touched") return { cls: "done", tone: "warn", label: "Touched", score };
      return { cls: "", tone: "", label: "Not touched" };
    }
    const es = log.filter((e) => e.area === a.area && e.followup_of == null && (e.type === "main" || !e.type || e.auto));
    const e = es[es.length - 1];
    const isNow = cur && cur.area === a.area;
    if (!e) return a.skipped ? { cls: "skip", tone: "", label: "Skipped" } : { cls: "", tone: "", label: "Not asked" };
    const cov = e.coverage || [];
    const full = cov.filter((c) => c === "full").length;
    const score = e.rating ?? (e.score != null ? Math.round(e.score) : null);
    if (isNow && running) return { cls: "now", tone: "brand", label: "Asking", score };
    if (!(e.sentences || []).length) return { cls: "done", tone: "warn", label: "No answer heard", score };
    const good = (e.good || []).length;
    return { cls: "done", tone: good && full >= good ? "good" : full ? "warn" : "", label: good ? (full >= good ? "Answered" : full ? "Partly" : "Answered, points missing") : "Answered", score };
  };
  const sendChat = async () => {
    const m = chatMsg.trim();
    if (m.length < 2) return;
    setChatBusy(true);
    setIshaChat((c) => [...c, { who: "you", text: m }]);
    setChatMsg("");
    try { const r = await api.post(`/isha/${id}/chat`, { message: m }); setIshaChat(r.chat); }
    catch (e) { toast(e.message, "bad"); setIshaChat((c) => c.slice(0, -1)); setChatMsg(m); }
    finally { setChatBusy(false); }
  };

  return (
    <div className="isha-room">
      <div className="isha-top">
        <Btn size="sm" kind="ghost" onClick={() => nav(-1)}>← Back</Btn><span className="version-tag">{VERSION}</span>
        <Isha size={34} mood={thinking ? "think" : running ? "talk" : "idle"} />
        <div className="col ell" style={{ gap: 0 }} title={`${data.candidate.name} · ${data.job.title} · ${att.name}`}><b className="ell">{data.candidate.name}</b><span className="tiny muted ell">{data.job.title} · {att.name}{data.isha ? " · Isha is helping" : " · scorecard only"}</span></div>
        <Chip kind={running && !ended ? "bad" : ""}>{running && !ended ? "● Live " + mm : ended && running ? "Ended · scorecard to submit" : att.status.replace("_", " ")}</Chip>
        <div className="right row">
          {callInfo?.enabled && !inCall && !ended && !["completed", "reviewed", "not_finished"].includes(att.status) && <Btn kind="primary" onClick={joinCall}>📹 {att.status === "in_progress" || checked ? "Rejoin call" : "Join video call"}</Btn>}
          {inCall && <Btn size="sm" onClick={leaveCall} title="Only you leave. The candidate waits and the interview stays open.">Leave call</Btn>}
          {data.isha && ["invited", "scheduled"].includes(att.status) && <Btn onClick={() => setPrepOpen(true)}>{data.brief?.prep?.saved ? "Change questions" : "Prepare questions"}</Btn>}
          {!running && ["invited", "scheduled", "paused", "not_finished"].includes(att.status) && <Btn kind={att.status === "not_finished" ? "" : "primary"} busy={busy} onClick={start}>{heardAny ? "Continue interview" : "Start interview"}</Btn>}
          {((ended && att.status === "in_progress") || att.status === "not_finished") && !card && <Btn kind="primary" onClick={openCard}>Open scorecard</Btn>}
          {(running || ended) && att.status !== "voided" && !["completed", "reviewed"].includes(att.status) && <Btn kind="ghost" onClick={() => setRetake(true)} title="The interview can't go on for a technical reason: void it and send the candidate a new invite">Technical problem?</Btn>}
          {["in_progress", "paused", "not_finished"].includes(att.status) && !(running && !ended && inCall) && <Btn kind="ghost" onClick={() => setClosing(true)} title="Submit the scorecard from what was captured, or close it without one">Close interview</Btn>}
          {running && !ended && <Btn kind="danger" busy={busy} onClick={end}>End interview</Btn>}
        </div>
      </div>
      <div className="isha-sub">
        {callInfo?.enabled && <>
          <span className="lbl">You</span>
          {inCall ? <><Chip kind={camOk ? "good" : "bad"}>{camOk ? "✓ Camera" : "✗ Camera off"}</Chip><Chip kind={micOk ? "good" : "bad"}>{micOk ? "✓ Microphone" : "✗ Microphone off"}</Chip><Chip kind="good">🔊 Speaker checked</Chip></>
            : <><Chip kind="warn">Camera and microphone not checked yet</Chip>{!ended && <Btn size="sm" kind="ghost" onClick={joinCall}>Check camera and mic</Btn>}</>}
          {inCall && <Chip kind={callSt.tone || "warn"}>{call.state === "connected" ? "● Call connected" : callSt.chip}</Chip>}
          {inCall && call.state === "connected" && call.path && call.path.path !== "unknown" && <Chip kind={call.path.path === "relay" ? "info" : "good"} title="How the video travels between you and the candidate">{call.path.path === "relay" ? "Video via relay" : "Video direct"}</Chip>}
          {inCall && (callSt.failed || (call.peerOnline && call.attempt > 0)) && <Btn size="sm" onClick={call.reconnect}>Try again</Btn>}
          {inCall && !call.peerOnline && call.state !== "connected" && <Btn size="sm" onClick={() => call.send("join")}>Ring again</Btn>}
          {recording && recStatus && <Chip kind={recStatus.failing ? "bad" : "good"} title="The video uploads every 10 seconds">● Saved up to {fmtSecs(recStatus.savedSeconds)}{recStatus.lowQuality ? " · lower quality" : ""}</Chip>}
          {capText && <Chip kind={device.captions === "none" || device.cap_state === "paused" ? "warn" : "info"}>{device.cap_state === "paused" ? "Captions paused on the candidate's side, reconnecting…" : capText}</Chip>}
          {connected && source === "call" && captions && lastCaption.current > 0 && <span className="tiny muted" title="When the last words from the candidate arrived">Last caption {Math.max(0, Math.round((Date.now() - lastCaption.current) / 1000))} s ago</span>}
          {callInfo?.captions && callInfo.azure_speech === false && <Chip kind="warn" title="Ask your administrator to add an Azure Speech key on the server, so captions work in every browser">Captions: Chrome or Edge only (Azure Speech isn't set up)</Chip>}
          {/* B1 (V02.00.12): the chip says what THIS plan was written with, not whether some other AI call failed lately */}
          {data.isha && data.ai && (!data.ai.configured || data.brief?.ai === false) && <Chip kind="warn" title={data.ai.error || "Add the Anthropic key under AI, voice and defaults"}>{!data.ai.configured ? "Claude isn't set up: Isha uses built-in questions" : "This plan uses built-in questions (Claude didn't answer when it was written)"}</Chip>}
          {echoes > 0 && <Chip kind="warn" title="Sentences that repeated your own words were left out of the answers">{echoes} echo{echoes > 1 ? "es" : ""} ignored: the candidate may not be using headphones</Chip>}
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
      {/* V02.00.13: Option A. The call on top with Isha's follow-ups beside it; the questions, their status and
          your rating at the bottom centre. Resume, plan, notes, integrity and the transcript open from the side rail. */}
      <div className="stage">
        <nav className="stage-rail" aria-label="More about this interview">
          {[["candidate", "Candidate", "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 20a8 8 0 0 1 16 0"], ["plan", "Plan", "M5 6h14M5 12h14M5 18h9"],
            ["resume", "Resume", "M7 3h7l5 5v13H7zM14 3v5h5"], ["rounds", "Rounds", "M4 12a8 8 0 1 0 3-6.2M4 4v4h4"],
            ["notes", "Notes", "M5 4h14v16H5zM8 9h8M8 13h8M8 17h5"], ["integrity", "Integrity", "M12 3l8 4v5c0 5-3.5 8-8 9-4.5-1-8-4-8-9V7z"],
            ["transcript", "Transcript", "M4 6h16M4 11h16M4 16h10"]].map(([k, label, d]) => (
            <button key={k} type="button" className={"rail-btn" + (drawer === k ? " on" : "")} aria-pressed={drawer === k} onClick={() => setDrawer(drawer === k ? null : k)}>
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d={d} /></svg>
              {label}
              {k === "integrity" && events.filter((e) => e.counted).length > 0 && <span className="rail-badge">{events.filter((e) => e.counted).length}</span>}
              {k === "notes" && state.notes.length > 0 && <span className="rail-badge calm">{state.notes.length}</span>}
            </button>))}
        </nav>

        {drawer && <aside className="stage-drawer" aria-label={drawer}>
          <div className="row" style={{ padding: "10px 12px", borderBottom: "1px solid var(--line)" }}><b className="grow" style={{ textTransform: "capitalize" }}>{drawer}</b><Btn size="sm" kind="ghost" onClick={() => setDrawer(null)} aria-label="Close panel">✕</Btn></div>
          <div className="stage-drawer-b">
            {drawer === "candidate" && <div className="card pad col">
            <div className="row"><Avatar name={data.candidate.name} /><div className="ell"><b>{data.candidate.name}</b><div className="tiny muted ell">{data.candidate.headline}</div></div></div>
            <div className="row wrap">{(data.candidate.skills || []).slice(0, 8).map((s, i) => <Chip key={i} kind={s.verified ? "good" : ""}>{s.name}{s.verified ? " ✓" : ""}</Chip>)}</div>
            {callInfo?.enabled && !ended && <div className="col cand-state" style={{ gap: 4 }}><span className="tiny b muted">CANDIDATE</span>
              {!connected && candStatus && <Chip kind={candStatus.stale ? "warn" : candStatus.kind}>{candStatus.text}{candStatus.stale && candStatus.at ? ` · ${Math.round((Date.now() - new Date(candStatus.at).getTime()) / 60000)} min ago` : ""}</Chip>}
              {connected && <Chip kind="good">● Connected</Chip>}
              {candStatus?.earlier_open && <Chip kind="warn">Still in their {candStatus.earlier_open.name} ({candStatus.earlier_open.status === "paused" ? "paused" : "in progress"})</Chip>}
              {candStatus?.check && <span className="tiny muted">System check: {candStatus.check.text}</span>}
              {device ? <div className="row wrap" style={{ gap: 4 }}>
                {device.cam != null && <Chip kind={device.cam ? "good" : "bad"}>{device.cam ? "✓ Camera on" : "✗ Camera off"}</Chip>}
                {device.mic != null && <Chip kind={device.mic ? "good" : "bad"}>{device.mic ? "✓ Microphone on" : "✗ Microphone off"}</Chip>}
                {device.faces != null && device.faces !== "unavailable" && <Chip kind={device.faces === 1 ? "good" : "warn"}>{device.faces === 1 ? "✓ We can see them" : device.faces === 0 ? "No face in view" : `${device.faces} people in view`}</Chip>}
              </div> : <span className="tiny muted">{connected ? "Waiting for their camera and microphone status…" : "Their camera and microphone show here once they join."}</span>}</div>}
            </div>}
          {drawer === "plan" && <div className="card">
            <div className="card-h"><b>{data.isha ? "Isha's plan" : "Interview plan"}</b><span className="small muted">{asked.size ? [...asked].filter((x) => areas.some((a) => a.area === x)).length : 0} of {areas.length} asked{state.coverage.skipped ? ` · ${state.coverage.skipped} skipped` : ""}</span>
              <label className="check tiny right"><input type="checkbox" checked={plain} onChange={(e) => setPlain(e.target.checked)} />Plain words</label></div>
            <div style={{ padding: "0 12px 8px" }}><Bar value={areas.length ? areas.filter((a) => asked.has(a.area)).length : 0} max={Math.max(1, areas.length)} /></div>
            {areas.map((a, i) => (
              <div key={a.area} className="plan-row" style={{ background: cur?.area === a.area ? "var(--isha-soft)" : undefined, opacity: a.skipped && !asked.has(a.area) ? 0.55 : 1 }}>
                <div className="plan-head"><span className="cov"><span className={"m " + (asked.has(a.area) ? "full" : "")} /></span><span className="tiny faint">{i + 1}.</span><b title={a.area}>{a.area}</b>
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
          {drawer === "resume" && <div className="card pad small" style={{ whiteSpace: "pre-wrap" }}>{data.candidate.resume || "No resume on file."}</div>}
          {drawer === "rounds" && <div className="card">{!data.prior.length && <div className="empty small">No earlier rounds.</div>}{data.prior.map((p, i) => <div key={i} className="list-row" style={{ flexDirection: "column", alignItems: "flex-start" }}><div className="row"><b>{p.round}</b><Chip>{p.overall}/5</Chip><Chip>{p.recommendation}</Chip>{p.warnings > 0 && <Chip kind="warn">{p.warnings} warnings</Chip>}</div><span className="small">{p.summary}</span></div>)}</div>}
            {drawer === "notes" && <div className="card pad col">
            <b className="small">Private notes</b>
            {state.notes.map((n, i) => <div key={i} className="small">• {n.text} <span className="faint">({n.area})</span></div>)}
            <form className="row" onSubmit={(e) => { e.preventDefault(); if (note.trim()) api.post(`/isha/${id}/note`, { text: note }).then((ns) => { setState({ ...state, notes: ns }); setNote(""); }); }}>
              <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Quick note" /><Btn type="submit" size="sm">Save</Btn></form>
          </div>}
            {drawer === "integrity" && <div className="card pad col" aria-live="polite">
            <div className="row"><b className="small">Integrity</b><span className="right" /><Chip kind={events.some((e) => e.counted) ? "warn" : "good"}>{events.filter((e) => e.counted).length ? `${events.filter((e) => e.counted).length} warning${events.filter((e) => e.counted).length > 1 ? "s" : ""}` : "Clean"}</Chip></div>
            {!events.length && <span className="tiny muted">Tab switches, pasting, leaving fullscreen and face checks appear here as they happen.</span>}
            {events.slice(-8).reverse().map((e, i) => <div key={i} className="row small" style={{ gap: 6 }}><Chip kind={e.counted ? "bad" : ""}>{e.counted ? "Warning" : "Noted"}</Chip><span className="grow">{e.label}</span><span className="tiny faint">{e.at ? new Date(e.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : ""}</span></div>)}
          </div>}
            {drawer === "transcript" && <div className="card grow" style={{ display: "flex", flexDirection: "column", minHeight: 260 }}>
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
                        {editing && editing.i === i && editing.j === j
                          ? <form className="row" onSubmit={(e) => { e.preventDefault(); saveEdit(); }}><Input autoFocus value={editing.text} onChange={(e) => setEditing({ ...editing, text: e.target.value })} aria-label="Correct this sentence" data-allow-paste="1" /><Btn size="sm" kind="primary" type="submit">Save</Btn><Btn size="sm" onClick={() => setEditing(null)}>Cancel</Btn></form>
                          : <div className="sentence"><span><span className="who cand">{data.candidate.name.split(" ")[0]}</span>{s}{(a.edited || []).includes(j) && <span className="tiny muted"> (corrected)</span>}
                            {(state.manual_filing || {})[normSentence(s)] && <Chip kind="brand">You filed it: {(state.manual_filing || {})[normSentence(s)].replace(/^From the (job description|resume): /, "")}</Chip>}</span>
                            {att.status !== "completed" && <FileUnder topics={state.file_topics} label="File under…" ariaLabel="File this sentence under a topic"
                              onPick={(to) => api.post(`/isha/${id}/file-sentence`, { text: s, to }).then((st) => { setState(st); toast("Filed. Isha keeps it there when she reviews the interview."); }).catch((e) => toast(e.message, "bad"))} />}
                            {att.status !== "completed" && <span className="sentence-edit"><button className="linkbtn tiny" onClick={() => setEditing({ i, j, text: s })} title="Correct a caption that was written out wrong">Edit</button> <button className="linkbtn tiny" onClick={() => saveEdit({ i, j, text: "" })} title="Remove a sentence that wasn't the candidate's">Remove</button></span>}
                            {tags.length > 0 && <div className="tags">{tags.map((t, k) => <Chip key={k} kind={TAG[t.type]?.[0]}>{TAG[t.type]?.[1]} {t.label}</Chip>)}</div>}</div>}
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
          </div>}
            {drawer !== "transcript" && <div className="card pad small muted">The candidate was told this interview is recorded and AI-assisted. Isha suggests; you decide what to ask and how to score.</div>}
          </div>
        </aside>}

        <main className="stage-main v3">
          {/* V02.01.03: everything useful up top, each panel scrolling on its own: the video with your tools under it
              on the left; the current question and Isha's follow-ups on the right. The questions sit along the bottom,
              wrapping onto a second line instead of scrolling sideways. */}
          <section className="stage-grid">
            {/* V02.01.04: left: the video, then the current question (live answer, points, Isha's score) and your tools,
                scrolling under the video; right: Isha's follow-ups at full height */}
            <div className="stage-left">
            <div className={"stage-call" + (docked && callBox ? " docked" : inCall && !docked ? " popped" : " idle")}>
              {docked && callBox}

              {/* V02.01.02: without the video here, a compact card instead of a big empty box: the space goes to Isha */}
              {!(docked && callBox) && <div className="stage-call-empty">
                <Avatar name={data.candidate.name} />
                <b>{data.candidate.name}</b>
                <span className="small" style={{ opacity: .85 }}>{inCall ? (connected ? "Video is in its own window" : callSt.chip || "Connecting…") : callInfo?.enabled ? "Join the video call (top right) when you're ready." : "Listen with your microphone or a meeting tab (Listen, above)"}</span>
                {inCall && !docked && <Btn size="sm" onClick={() => setDocked(true)}>Put it back here</Btn>}
              </div>}
            </div>
              <div className="stage-left-scroll">
              <div className="q-card card">
                {cur ? <div className="q-card-main">
                  <div className="row wrap" style={{ gap: 6 }}>
                    <span className="tiny b" style={{ color: "var(--brand-ink)" }}>{running && nowTopic ? "TALKING ABOUT" : "NOW"} · {(running && nowTopic) || cur.area}</span>
                    {(() => { const pl = (running && nowTopic && areas.find((a) => a.area === nowTopic)) || curPlan; return <>
                      {pl?.type_label && <Chip>{pl.type_label}</Chip>}
                      {pl?.source && <Chip kind={SRC_TONE[pl.source] || ""}>{SRC_LABEL[pl.source] || pl.source}</Chip>}</>; })()}
                    {cur.followup_of != null && <Chip kind="isha">Follow-up</Chip>}
                    {cur.auto && <Chip kind="info">Isha heard you ask it</Chip>}
                    <label className="check tiny right"><input type="checkbox" checked={plain} onChange={(e) => setPlain(e.target.checked)} />Plain words</label>
                  </div>
                  <h2 className="q-text">“{running && nowTopic && nowTopic !== cur.area ? ((areas.find((a) => a.area === nowTopic) || {})[plain ? "simple" : "q"] || areas.find((a) => a.area === nowTopic)?.q) : plain && curPlan?.simple && cur.q === curPlan.q ? curPlan.simple : cur.q}”</h2>
            {moved && <div className="sc-note info row" role="status"><span className="grow">Isha moved to “{moved.area}” because you asked it.</span><Btn size="sm" kind="ghost" onClick={undoMove}>Undo</Btn><Btn size="sm" kind="ghost" onClick={() => setMoved(null)}>OK</Btn></div>}
            {running && <div className="sc-note calm small" role="note">Everything both of you say is recorded. You don't need to mark questions: when the interview ends, Isha reads the whole transcript and works out which topics were covered, the follow-ups and any extra questions.</div>}
            {cur && running && <div className="live-answer" aria-live="polite"><div className="tiny b muted">LIVE ANSWER</div>
              {(cur.sentences || []).length || partial ? <div>{(cur.sentences || []).slice(-3).join(" ")} {partial && <span style={{ opacity: .55, fontStyle: "italic" }}>{partial}…</span>}</div>
                : <span className="small muted">The candidate's words appear here as they speak.</span>}</div>}
            {running && topics.length > 0 ? <TopicPoints topic={topicOf(nowTopic || cur?.area)} onRate={rateTopic} />
              : cur && ended && (cur.good?.length > 0 || cur.score != null) && <RatingCard cur={cur} />}
                </div> : <div className="q-card-empty">
                <span className="tiny b muted">{running ? "YOUR FIRST QUESTION" : ended ? "THE INTERVIEW HAS ENDED" : "YOUR FIRST QUESTION"}</span>
                {nextQ && !ended && <h2 className="q-text">“{plain && nextQ.simple ? nextQ.simple : nextQ.q}”</h2>}

                <div className="row" style={{ gap: 8 }}>
                  {data.isha && !running && !ended && ["invited", "scheduled"].includes(att.status) && <Btn kind={data.brief?.prep?.saved ? "" : "primary"} onClick={() => setPrepOpen(true)}>{data.brief?.prep?.saved ? "Change questions" : "Prepare questions"}</Btn>}
                  {running && nextQ && <Btn size="sm" onClick={() => ask(plain && nextQ.simple ? nextQ.simple : nextQ.q, nextQ.area)}>Mark as asked</Btn>}
                </div>
              </div>}
              </div>
              <div className="stage-tools card" aria-label="Your tools">
                  <TopicSummary topics={topics} areas={areas} />
                  <form className="col" style={{ gap: 6, marginTop: 6 }} onSubmit={(e) => { e.preventDefault(); if (note.trim()) api.post(`/isha/${id}/note`, { text: note }).then((ns) => { setState({ ...state, notes: ns }); setNote(""); toast("Note saved"); }); }}>
                    <label className="tiny b muted" htmlFor="qnote">QUICK NOTE</label>
                    <div className="row"><Input id="qnote" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Private note for this question" /><Btn type="submit" size="sm">Save</Btn></div>
                  </form>
                  {running && nextQ && <div className="next-mini">
                    <span className="tiny b muted">NEXT{moveOn ? " · good time to move on" : ""}</span>
                    <span className="small">“{plain && nextQ.simple ? nextQ.simple : nextQ.q}”</span>
                    <div className="row" style={{ gap: 6 }}><Btn size="sm" onClick={() => ask(plain && nextQ.simple ? nextQ.simple : nextQ.q, nextQ.area)} title="Isha hears it when you ask it. Use this if she didn't.">Mark as asked</Btn><Btn size="sm" kind="ghost" onClick={() => editPlan({ skip: nextQ.area })}>Skip</Btn></div>
                  </div>}
                  <CaptureHealth running={running} topics={state.topics} lastSpeech={Math.max(lastCaption.current || 0, lastHeard.current || 0)}
                    startedAt={att.started_at} live={connected || !!listening} canTranscribe={state.can_transcribe} />
                </div>
              </div>
            </div>
            <div className="stage-right">
            {autoIn !== null && <div className="sc-note good row wrap auto-start" role="status" style={{ gap: 8 }}>
              <span className="grow"><b>Both of you are connected.</b> Starting the interview in {autoIn} s…</span>
              <Btn size="sm" onClick={() => { setHeld(true); setAutoIn(null); }}>Not yet</Btn>
              <Btn size="sm" kind="primary" onClick={() => { setAutoIn(null); start({ auto: true }); }}>Start now</Btn></div>}
            {autoIn === null && held && connected && notStarted && <div className="sc-note calm row wrap" role="status" style={{ gap: 8 }}>
              <span className="grow">You're both connected. Start the interview when you're ready: speech so far is kept.</span>
              <Btn size="sm" kind="primary" onClick={() => { setHeld(false); start({ auto: true }); }}>Start interview</Btn></div>}
            {outsideJoined && <div className="sc-note good row wrap" role="alert" style={{ gap: 8 }}>
              <span className="grow"><b>The candidate is here.</b> Start the interview so the recording, the timer and Isha begin.</span>
              <Btn size="sm" kind="primary" onClick={() => start()}>Start interview</Btn></div>}
            {maybe && running && <div className="sc-note warn row wrap" role="alert" style={{ gap: 8 }}>
              <span className="grow">Did you ask <b>“{maybe.area}”</b>? Isha wasn't sure.</span>
              <Btn size="sm" kind="primary" onClick={() => { const a = areas.find((x) => x.area === maybe.area); ask(a?.q || maybe.q, maybe.area); setMaybe(null); }}>Yes, I asked it</Btn>
              <Btn size="sm" kind="ghost" onClick={() => setMaybe(null)}>No</Btn>
            </div>}
            <aside className="stage-fu" aria-label="Isha's follow-ups" aria-live="polite">
              <div className="stage-fu-h">
                <Isha size={30} mood={thinking ? "think" : fuList.length ? "talk" : "idle"} />
                <b className="grow">Follow-ups</b>
                {state.running_score != null && <span className="small muted" title="Isha's live score for the interview so far">So far <b>{state.running_score}</b>/5</span>}
              </div>
              {/* where the candidate is until the call connects: on the main screen, beside the video */}
              {callInfo?.enabled && !ended && !connected && candStatus && <div className="cand-line" role="status" aria-live="polite">
                <span className="tiny b muted">CANDIDATE</span>
                <Chip kind={candStatus.stale ? "warn" : candStatus.kind}>{candStatus.text}</Chip>
                {candStatus.earlier_open && <Chip kind="warn">Still in their {candStatus.earlier_open.name} ({candStatus.earlier_open.status === "paused" ? "paused" : "in progress"})</Chip>}
                {candStatus.check && <span className="tiny muted">System check: {candStatus.check.text}</span>}
              </div>}
              <div className="stage-fu-b">
                {!fuList.length && <div className="small muted" style={{ padding: 4 }}>{running ? "Follow-ups appear as soon as the candidate starts answering. Pin one to keep it here." : "When the interview runs, Isha suggests follow-ups here from what the candidate says."}</div>}
                {!fuList.length && !running && !ended && <div className="how-box"><span className="tiny b muted">HOW THIS WORKS</span>
                <ol className="how small">
                  <li><b>Pick your questions</b> (Prepare questions). Isha proposes them by skill and type, sized to this candidate's level.</li>
                  <li><b>Just ask them out loud.</b> Everything is recorded. The question cards show which topics have come up: Not touched, Touched or Well covered.</li>
                  <li><b>Follow-ups appear on the right</b> as the candidate answers. Pin the ones you want to keep; ask Isha anything with Ask Isha.</li>
                  <li><b>At the end, Isha reviews the whole transcript</b> and files every answer under its topic. You rate each competency on the scorecard, and can move a quote if she got it wrong.</li>
                </ol>
                </div>}
                {fuList.map((o, i) => {
                  const pinned = pins.some((p) => p.q === o.q);
                  return (
                    <div key={o.q + i} className={"fu-card" + (pinned ? " pin" : "") + (i === 0 && !pinned ? " best" : "")}>
                      <div className="row" style={{ gap: 6 }}>
                        <Chip kind={o.type === "Clarify" || o.type === "Challenge" ? "bad" : o.type === "Probe" ? "warn" : o.type === "Go deeper" ? "good" : o.type === "Move on" ? "" : "info"}>{o.type === "Move on" ? "Next question" : o.type}</Chip>
                        {pinned && <Chip kind="isha">📌 Pinned</Chip>}
                        <span className="grow" />
                        {o.type !== "Move on" && <Btn size="sm" kind="ghost" onClick={() => togglePin(o)} aria-pressed={pinned} aria-label={pinned ? "Unpin this follow-up" : "Pin this follow-up"}>{pinned ? "Unpin" : "📌 Pin"}</Btn>}
                      </div>
                      <b className="fu-q">“{o.q}”</b>
                      <span className="tiny muted">{o.why}{o.source ? ` · ${FU_SOURCE[o.source] || o.source}` : ""}</span>
                      {running && <div className="row" style={{ gap: 6 }}><Btn size="sm" onClick={() => ask(o.q, o.area || cur?.area, o.type === "Move on" ? "main" : o.type)} title="Isha hears it when you say it. Use this only if she didn't.">Mark as asked</Btn></div>}
                    </div>);
                })}
              </div>
              {running && <form className="stage-fu-f" onSubmit={(e) => { e.preventDefault(); if (custom.trim()) ask(custom, cur?.area || "General", "own"); }}>
                <Input value={custom} onChange={(e) => setCustom(e.target.value)} placeholder="Asked something else? Type it here" aria-label="Your own question" />
                <Btn type="submit" size="sm">Add</Btn>
              </form>}
              <div className="tiny muted" style={{ padding: "6px 12px 10px" }}>Just ask out loud. Everything is recorded; at the end Isha works out which topics were covered.</div>
            </aside>
            </div>
          </section>

          <section className="stage-bottom q-strip" aria-label="Questions">
            <div className="q-rail">
              <span className="q-legend" aria-hidden="true"><i className="q-dot good" />Well covered <i className="q-dot warn" />Touched <i className="q-dot" />Not yet</span>
              {areas.map((a, i) => {
                const st = areaStatus(a);
                return (
                  <button type="button" key={a.area} className={"q-pill " + st.cls} title={`${st.label}: ${a.q}`}
                    onClick={() => { if (running && !asked.has(a.area) && !a.skipped) ask(plain && a.simple ? a.simple : a.q, a.area); }}
                    aria-label={`Question ${i + 1}: ${a.area}. ${st.label}`}>
                    <i className={"q-dot " + (st.tone || "") + (st.cls === "now" ? " now" : "")} aria-hidden="true" />
                    <span className="q-pill-h">Q{i + 1}</span>
                    <span className="q-pill-t">{a.section && a.type !== "intro" ? (a.type_label && a.type_label !== a.section ? `${a.section} · ${a.type_label}` : a.section) : a.area}</span>
                    <span className="sr-only">{st.label}</span>
                    {st.score != null && <b className="small">{st.score}/5</b>}
                  </button>);
              })}
            </div>
          </section>
        </main>

        {data.isha && !chatOpen && <button type="button" className="ask-isha-btn" onClick={() => setChatOpen(true)}>
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M4 5h16v11H9l-5 4z" /></svg>
          Ask Isha{!chatOpen && fuList.length > 0 && running && <span className="ask-badge">{fuList.length}</span>}
        </button>}
        {data.isha && chatOpen && <aside className="isha-chat" aria-label="Ask Isha">
          <div className="row" style={{ padding: "10px 12px", borderBottom: "1px solid #F1DDAA", gap: 8 }}>
            <Isha size={28} mood={chatBusy ? "think" : "idle"} /><b className="grow" style={{ color: "var(--isha)" }}>Ask Isha</b>
            <Btn size="sm" kind="ghost" onClick={() => setChatOpen(false)} aria-label="Close Ask Isha">✕</Btn>
          </div>
          <div className="isha-chat-b" ref={chatFeed}>
            {!ishaChat.length && <div className="small muted col" style={{ gap: 6 }}>
              <span>Your AI assistant for this interview, private to you and never added to the report. Ask it anything about hiring:</span>
              <div className="row wrap" style={{ gap: 6 }}>{["Get me 5 simple SQL questions", "Is this answer correct?", "Explain database indexing", "Harder follow-up for this answer", "What should I ask about their resume?", "How much time is left?"].map((t) =>
                <button type="button" key={t} className="chip" onClick={() => setChatMsg(t)}>{t}</button>)}</div>
              <span>New follow-ups keep arriving below while this is open.</span></div>}
            {ishaChat.map((m, i) => (
              <div key={i} className={"chat-msg " + (m.who === "you" ? "me" : "isha")}>
                <span>{m.text}</span>
                {m.source === "offline" && <span className="tiny muted"> (Claude unavailable: from the question bank and your plan)</span>}
                {(m.questions || []).map((q, k) => <ChatQuestion key={k} q={q} offline={m.source === "offline"} ended={ended}
                  onPin={() => togglePin({ q: q.q, type: "Isha", why: q.why || "From Ask Isha", source: m.source === "offline" ? "prepared" : "claude" })}
                  onAdd={() => editPlan({ add: q.q }).then(() => toast("Added to the plan"))} />)}
              </div>))}
            {running && fuList.length > 0 && <div className="chat-msg isha live"><span className="tiny b" style={{ color: "var(--isha)" }}>LATEST FOLLOW-UP</span><span>“{fuList[0].q}”</span></div>}
          </div>
          <form className="row" style={{ padding: 10, borderTop: "1px solid #F1DDAA", gap: 8 }} onSubmit={(e) => { e.preventDefault(); sendChat(); }}>
            <Input value={chatMsg} onChange={(e) => setChatMsg(e.target.value)} placeholder="Ask anything: questions on a skill, check an answer, explain a concept…" aria-label="Message to Isha" maxLength={800} />
            <Btn type="submit" kind="primary" busy={chatBusy} disabled={chatMsg.trim().length < 2}>Send</Btn>
          </form>
        </aside>}
      </div>
      {!docked && callBox}
      {prepOpen && <PrepareQuestions attemptId={id} candidateName={data.candidate.name} onClose={() => setPrepOpen(false)}
        onSaved={(out) => { setPrepOpen(false); setData({ ...data, brief: out.brief }); }} />}
      {showVideo && !inCall && source === "tab" && <FloatingVideo stream={stream} label={stream?.getVideoTracks()[0]?.label?.includes("screen") || source === "tab" ? "Meeting" : "Camera"} onClose={() => setShowVideo(false)} />}
      {checkOpen && <Modal wide title="Check your camera, microphone and speaker" onClose={() => setCheckOpen(false)}>
        <SystemCheck attemptId={id} role="interviewer" mode={checked ? "recheck" : "full"} onPassed={onChecked} />
      </Modal>}
      {retakeModal}
      {closing && <CloseInterview attemptId={id} inRoom onClose={() => setClosing(false)} onScorecard={() => { setClosing(false); openCard(); }}
        onAgain={() => { setClosing(false); setRetake(true); }}
        onDone={(r) => { setClosing(false); setState(r.state); setData({ ...data, attempt: { ...att, status: r.status } }); }} />}
      {card && <Scorecard id={id} draft={card} review={state?.review} canUndo={state?.can_undo_review} rubric={data.job.rubric} areas={areas}
        unanswered={state?.unanswered || []} extras={state?.extras || []} transcribe={state?.transcribe} canTranscribe={state?.can_transcribe}
        heard={state?.topics?.heard || 0} fileTopics={state?.file_topics} onClose={() => setCard(null)}
        onReviewed={(r) => { setState(r.state); setCard(r.draft); }} onDone={(r) => nav(`/app/reports/${id}`)} />}
    </div>
  );
}

const LEVEL = (v) => (v >= 4.5 ? "Excellent" : v >= 3.5 ? "Strong" : v >= 2.5 ? "Meets the bar" : v >= 1.5 ? "Below the bar" : "Weak");
const TONE = (v) => (v >= 3.5 ? "good" : v >= 2.5 ? "warn" : "bad");

/** N3 (V02.00.09): the live rating card. A big score, every point of a good answer with a clear marker, and the
 * interviewer can tick a point Isha missed. Every point covered = full marks. */
export function RatingCard({ cur, canTick, onTick }) {
  const good = cur.good || [];
  const cov = cur.coverage || [];
  const ticks = new Set(cur.ticks || []);
  const done = cov.filter((c) => c === "full").length;
  const v = cur.score;
  const LBL = { full: "Covered", partial: "Partly", none: "Not yet" };
  return (
    <div className={"rating-card" + (v != null ? " t-" + TONE(v) : "")} aria-live="polite">
      <div className="rc-top">
        <div className="rc-score">{v != null ? <><b>{Number(v).toFixed(1)}</b><span>/ 5</span></> : <span className="muted small">No score yet</span>}</div>
        <div className="grow col" style={{ gap: 2 }}>
          <span className="tiny b muted">ANSWER SO FAR</span>
          {v != null && <b className="rc-level">{LEVEL(v)}{cur.full_marks ? " · full marks" : ""}</b>}
          {v != null && <Bar value={v} max={5} tone={TONE(v)} />}
          <span className="small muted">{(cur.sentences || []).length} sentence{(cur.sentences || []).length === 1 ? "" : "s"} heard{good.length ? ` · ${done} of ${good.length} points covered` : ""}</span>
        </div>
      </div>
      {good.length > 0 && <div className="rc-points">
        <span className="tiny b muted">A GOOD ANSWER COVERS{canTick ? " · tick a point Isha missed" : ""}</span>
        {good.map((g, i) => {
          const c = cov[i] || "none";
          return (
            <div key={i} className={"rc-point " + c}>
              <span className={"m " + c} aria-hidden />
              <span className="grow">{g}</span>
              <span className={"chip " + (c === "full" ? "good" : c === "partial" ? "warn" : "")}>{ticks.has(i) ? "Ticked by you" : LBL[c]}</span>
              {canTick && (ticks.has(i) || c !== "full") && <button type="button" className="btn sm ghost" aria-pressed={ticks.has(i)} onClick={() => onTick(i, !ticks.has(i))}>{ticks.has(i) ? "Untick" : "Mark covered"}</button>}
            </div>);
        })}
        {cur.full_marks && <div className="small" style={{ color: "var(--good)" }}>Every point is covered, so this answer gets full marks.</div>}
      </div>}
    </div>
  );
}

/** V02.01.02: selected questions Isha found no answer for (pick the answer from the transcript, or Skip with an
 * optional reason and "Show on report"), and the extra questions you asked (on the report only when ticked). */
function QuestionDecisions({ id, unanswered, extras, review, decisions, decide, undecided, showExtras, setShowExtras, onReviewed }) {
  const toast = useToast();
  const [busy, setBusy] = useState("");
  if (!unanswered.length && !extras.length) return null;
  const quotes = [];
  (review?.map || []).forEach((m) => (m.quotes || []).forEach((qt, k) => quotes.push({ index: m.index, sentence: k, text: qt, under: m.type === "main" ? m.area : m.type === "Follow-up" ? `Follow-up · ${m.area}` : "Not in the plan" })));
  const pick = async (area, v) => {
    if (!v) return;
    const [index, sentence] = v.split(":").map(Number);
    setBusy(area);
    try { const r = await api.post(`/isha/${id}/move-quote`, { index, sentence, to: area }); onReviewed(r); toast(`Answer filed under “${area}”.`, "good"); }
    catch (e) { toast(e.message, "bad"); }
    finally { setBusy(""); }
  };
  return (
    <div className="qd card">
      {unanswered.length > 0 && <>
        <b>Selected questions with no answer ({unanswered.length})</b>
        <span className="tiny muted">Isha didn't find these in the transcript. If you asked it, pick its answer. Otherwise press Skip: a skipped question isn't scored, and it's on the report only if you tick “Show on report”.</span>
        {!quotes.length && <div className="sc-note warn small">No candidate speech was captured, so there's nothing to pick from. Check that captions were on{""}, or transcribe the video (above).</div>}
        {undecided.length > 0 && <div className="sc-note warn" role="alert"><b>Decision needed for: {undecided.join(", ")}.</b> Pick its answer from the transcript, or press Skip.</div>}
        {unanswered.map((u) => { const d = decisions[u.area] || {}; return (
          <div key={u.area} className={"qd-row" + (undecided.includes(u.area) ? " missing" : "")}>
            <div className="row wrap" style={{ gap: 8 }}>
              <span className="grow"><b className="small">{u.area}</b><span className="tiny muted"> · “{(u.q || "").slice(0, 140)}”</span></span>
              <Select value="" disabled={!!busy || !quotes.length} aria-label={`Pick the answer to ${u.area}`} onChange={(v) => pick(u.area, v)}
                options={[{ value: "", label: quotes.length ? "It was asked: pick its answer…" : "No candidate speech was captured" },
                  ...quotes.map((q) => ({ value: `${q.index}:${q.sentence}`, label: `“${q.text.slice(0, 70)}${q.text.length > 70 ? "…" : ""}” (now under ${q.under})` }))]} />
              <Btn size="sm" kind={d.skip ? "primary" : "ghost"} onClick={() => decide(u.area, { skip: !d.skip })} aria-pressed={!!d.skip}>{d.skip ? "Skipped" : "Skip"}</Btn>
            </div>
            {d.skip && <div className="row wrap" style={{ gap: 12, alignItems: "flex-end" }}>
              <div style={{ flex: 1, minWidth: 220 }}><Field label="Why skip? (optional)"><Input value={d.reason || ""} maxLength={300} onChange={(e) => decide(u.area, { reason: e.target.value })} placeholder="e.g. Not asked: ran out of time" /></Field></div>
              <label className="check small"><input type="checkbox" checked={!!d.show} onChange={(e) => decide(u.area, { show: e.target.checked })} />Show on report</label>
            </div>}
          </div>); })}
      </>}
      {extras.length > 0 && <>
        <b style={{ marginTop: unanswered.length ? 6 : 0 }}>Extra questions you asked ({extras.length})</b>
        <span className="tiny muted">Not in your plan. They're left off the report unless you tick them.</span>
        {extras.map((x) => <label key={x.index} className="check small qd-extra"><input type="checkbox" checked={showExtras.includes(x.index)}
          onChange={(e) => setShowExtras((s) => (e.target.checked ? [...s, x.index] : s.filter((i) => i !== x.index)))} />
          <span>“{(x.q || "").slice(0, 160)}” <span className="tiny muted">· {x.sentences} sentence{x.sentences === 1 ? "" : "s"} · Show on report</span></span></label>)}
      </>}
    </div>
  );
}

/** V02.01.01: the points of a good answer for the topic being discussed, from the whole transcript so far. */
function TopicPoints({ topic, onRate }) {
  if (!topic || (!(topic.good || []).length && topic.score == null)) return null;
  const LBL = { full: "Heard", partial: "Partly", none: "Not yet" };
  const SRC = { claude: "Claude", points: "from the points covered · please check" };
  return (
    <div className="rating-card" aria-live="polite">
      {/* V02.01.04: Isha's suggested score, live, and your optional one-click rating (it wins when given) */}
      <div className="rc-score live-score row wrap" style={{ gap: 8 }}>
        <span className="tiny b muted">ISHA'S SCORE</span>
        {topic.score != null ? <><b className="rc-num">{topic.score}/5</b><span className="tiny muted">{topic.reason}{topic.score_source ? ` · ${SRC[topic.score_source] || topic.score_source}` : ""}</span></>
          : <span className="tiny muted">Isha scores this when the answer ends.</span>}
        {onRate && <span className="right row" style={{ gap: 4 }} role="radiogroup" aria-label={`Your rating for ${topic.area}`}>
          <span className="tiny muted">Yours:</span>
          {[1, 2, 3, 4, 5].map((n) => <button type="button" key={n} role="radio" aria-checked={topic.your_rating === n} className={"rate-dot" + (topic.your_rating === n ? " on" : "")}
            onClick={() => onRate(topic.area, topic.your_rating === n ? null : n)} title={topic.your_rating === n ? "Clear your rating" : `Rate ${n}`}>{n}</button>)}
        </span>}
      </div>
      <div className="rc-points">
        <span className="tiny b muted">{topic.area.toUpperCase()} · A GOOD ANSWER COVERS</span>
        {topic.good.map((g, i) => { const c = topic.coverage?.[i] || "none"; return (
          <div key={i} className={"rc-point " + c}><span className={"m " + c} aria-hidden /><span className="grow">{g}</span>
            <span className={"chip " + (c === "full" ? "good" : c === "partial" ? "warn" : "")}>{LBL[c]}</span></div>); })}
        {topic.missing?.length > 0 && <span className="tiny muted">Not heard yet: ask a follow-up on {topic.missing.slice(0, 2).join(" or ")}.</span>}
      </div>
    </div>
  );
}

/** V02.01.04: when the live captions missed the candidate, the server can transcribe the interview video (Azure
 * Speech) and Isha reviews it again. */
function TranscribeBox({ id, t, can, heard, onDone }) {
  const toast = useToast();
  const [st, setSt] = useState(t || null);
  useEffect(() => setSt(t || null), [t]);
  useEffect(() => {
    if (st?.state !== "running") return undefined;
    const iv = setInterval(async () => {
      try {
        const r = await api.get(`/isha/${id}`);
        const now = r.state?.transcribe;
        setSt(now);
        if (now?.state !== "running") {
          clearInterval(iv);
          const d = await api.post(`/isha/${id}/redraft?ai=1`);
          onDone({ state: r.state, draft: d.draft });
          toast(now?.state === "done" ? (now.replaced?.length ? "The video was transcribed and Isha reviewed the interview again." : "The video didn't add anything the captions missed.") : now?.error || "Transcribing failed.", now?.state === "done" ? "good" : "bad");
        }
      } catch { /* try again on the next tick */ }
    }, 4000);
    return () => clearInterval(iv);
  }, [st?.state]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!can && st?.state !== "running") return null;
  const thin = heard < 8;
  if (!thin && !st) return null;
  return (
    <div className={"sc-note " + (st?.state === "failed" ? "warn" : "calm") + " row wrap"} style={{ gap: 8 }} role="status">
      <span className="grow small">
        {st?.state === "running" ? <><b>Transcribing the interview video…</b> {st.total ? `${st.done} of ${st.total} pieces` : "starting"}. You can keep working.</>
          : st?.state === "done" ? <>The video was transcribed{st.replaced?.length ? ` (${st.replaced.join(" and ")} speech replaced the live captions)` : ": the live captions already had it all"}.</>
            : st?.state === "failed" ? <>Transcribing failed: {st.error}</>
              : st?.state === "nothing" ? <>{st.error}</>
                : <><b>Only {heard} sentence{heard === 1 ? "" : "s"} from the candidate were captured live.</b> Isha can transcribe the interview video and review it again.</>}
      </span>
      {st?.state !== "running" && can && <Btn size="sm" kind={thin ? "primary" : ""} onClick={() => api.post(`/isha/${id}/transcribe`).then((r) => setSt(r.transcribe || { state: "running" })).catch((e) => toast(e.message, "bad"))}>{st ? "Transcribe again" : "Transcribe the video"}</Btn>}
    </div>
  );
}

/** V02.01.04: what's being captured, and a warning when the candidate hasn't been heard for a while. */
function CaptureHealth({ running, topics, lastSpeech, startedAt, live, canTranscribe }) {
  const [, setTick] = useState(0);
  useEffect(() => { if (!running) return undefined; const t = setInterval(() => setTick((n) => n + 1), 5000); return () => clearInterval(t); }, [running]);
  if (!running || !topics) return null;
  const now = Date.now();
  const since = startedAt ? (now - new Date(startedAt).getTime()) / 1000 : 0;
  const quiet = lastSpeech ? (now - lastSpeech) / 1000 : since;
  const warn = live && since > 45 && quiet > 45;
  return (
    <div className={"capture" + (warn ? " warn" : "")} role={warn ? "alert" : "status"}>
      <span className="tiny b muted">CAPTURE</span>
      <span className="small">Candidate: <b>{topics.heard || 0}</b> sentence{topics.heard === 1 ? "" : "s"} heard · Your questions: <b>{topics.questions_heard || 0}</b></span>
      {warn && <span className="small"><b>No candidate speech heard for {Math.round(quiet)} s.</b> Check that “Isha reads captions” is ticked, the candidate's microphone is on, and the right source is chosen (Call captions, My microphone or Other meeting tab).{canTranscribe ? " If captions stay off, the video can be transcribed after the interview." : ""}</span>}
    </div>
  );
}

function TopicSummary({ topics, areas }) {
  if (!topics.length) return <span className="tiny muted">Topics show here once the interview starts.</span>;
  const n = (st) => topics.filter((t) => t.state === st).length;
  const todo = areas.filter((a) => !a.skipped && topicOf0(topics, a.area)?.state === "none").slice(0, 6);
  return (
    <div className="col" style={{ gap: 6 }} aria-label="Topic coverage">
      <span className="tiny b muted">TOPIC COVERAGE</span>
      <div className="row wrap" style={{ gap: 6 }}><Chip kind="good">{n("well")} well covered</Chip><Chip kind="warn">{n("touched")} touched</Chip><Chip>{n("none")} not touched</Chip></div>
      {todo.length > 0 && <span className="tiny muted">Not touched yet: {[...new Set(todo.map((a) => a.section && a.type !== "intro" ? a.section : a.area))].join(" · ")}</span>}
    </div>
  );
}
const topicOf0 = (topics, area) => topics.find((t) => t.area === area);

/** V02.01.01: a question from Ask Isha, with what a good answer covers and a model answer. */
function ChatQuestion({ q, ended, onPin, onAdd }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const copy = () => { try { navigator.clipboard.writeText(q.q + (q.model ? "\n\nModel answer: " + q.model : "")); toast("Copied"); } catch { toast("Couldn't copy", "bad"); } };
  return (
    <div className="chat-q">
      <b className="small">“{q.q}”</b>
      <span className="tiny muted">{[q.level, q.why].filter(Boolean).join(" · ")}</span>
      {(q.good?.length > 0 || q.model) && <button type="button" className="linkbtn tiny" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "Hide" : "Show"} good answer</button>}
      {open && <div className="chat-ans">
        {q.good?.length > 0 && <ul className="tiny">{q.good.map((g, i) => <li key={i}>{g}</li>)}</ul>}
        {q.model && <div className="tiny"><b>Model answer:</b> {q.model}</div>}
      </div>}
      <div className="row" style={{ gap: 6 }}><Btn size="sm" onClick={onPin}>📌 Pin</Btn>
        {!ended && <Btn size="sm" kind="ghost" onClick={onAdd}>Add to plan</Btn>}
        <Btn size="sm" kind="ghost" onClick={copy}>Copy</Btn></div>
    </div>
  );
}

function ReviewMap({ id, review, canUndo, onReviewed, areas = [], fileTopics }) {
  // V02.01.01: what Isha found when she read the whole transcript, question by question
  const toast = useToast();
  const [busy, setBusy] = useState("");
  const [open, setOpen] = useState(true);   // V02.01.04: open by default, so every answer's "File under…" is in view
  if (!review) return null;
  const go = async (payload, key, msg) => {
    setBusy(key);
    try { const r = await api.post(`/isha/${id}/review`, payload); onReviewed(r); toast(msg, "good"); }
    catch (e) { toast(e.message, "bad"); }
    finally { setBusy(""); }
  };
  const map = review.map || [];
  // V02.01.01: the interviewer can move a quote Isha filed under the wrong topic; both topics are scored again
  const topicChoices = [...areas.filter((a) => !a.skipped).map((a) => a.area), "Small talk", "Not in the plan"];
  const go2 = async (payload) => {
    setBusy("move");
    try { const r = await api.post(`/isha/${id}/move-quote`, payload); onReviewed(r); toast(`Filed under “${payload.to.replace(/^From the (job description|resume): /, "")}”. Both topics were scored again, and Isha keeps it there if she reviews again.`, "good"); }
    catch (e) { toast(e.message, "bad"); }
    finally { setBusy(""); }
  };
  const mmss = (s) => `${Math.floor((s || 0) / 60)}:${String((s || 0) % 60).padStart(2, "0")}`;
  return (
    <div className="review-map" aria-label="What Isha found in the transcript">
      <div className="row wrap" style={{ gap: 8 }}>
        <b className="grow">{review.undone ? "Answers are filed as they were during the interview"
          : review.turns ? `Isha read the whole transcript (${review.turns} turns): ${review.asked} of ${review.of} planned questions were asked`
            : "No transcript was saved for this interview"}</b>
        {review.source === "claude" && <Chip kind="good">Read by Claude</Chip>}
        {review.source === "keywords" && <Chip kind="warn" title="Claude wasn't available, so answers were matched to questions by their words">Matched by keywords</Chip>}
        {review.followups > 0 && <Chip>{review.followups} follow-up{review.followups === 1 ? "" : "s"}</Chip>}
        {review.extra > 0 && <Chip kind="info">{review.extra} question{review.extra === 1 ? "" : "s"} not in the plan</Chip>}
      </div>
      {review.moved > 0 && <div className="tiny muted">You moved {review.moved} quote{review.moved === 1 ? "" : "s"}.</div>}
      {(review.not_asked || []).length > 0 && !review.undone && <div className="small" style={{ color: "var(--warn-ink, #8A4A06)" }}>Not found in the transcript: {review.not_asked.join(" · ")}</div>}
      {map.length > 0 && <button type="button" className="linkbtn small" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "Hide" : "Show"} where each answer was found</button>}
      {open && <ol className="review-list">
        {map.map((m, i) => <li key={i} className={m.type === "main" ? "" : "sub"}>
          <div className="row" style={{ gap: 8 }}>
            <span className="tiny muted">{mmss(m.at)}</span>
            <span className="grow"><b className="small">{m.type === "main" ? m.area : m.type === "Follow-up" ? `Follow-up · ${m.area}` : m.type === "smalltalk" ? "Small talk" : m.type === "added" ? `${m.area} (you added it)` : "Not in the plan"}</b>
              {m.type !== "main" && m.q && <span className="tiny muted"> “{m.q.slice(0, 120)}”</span>}</span>
            <span className="tiny muted">{m.sentences} sentence{m.sentences === 1 ? "" : "s"}{m.points ? ` · ${m.covered}/${m.points} points` : ""}</span>
            {m.score != null && <b className="small">{m.score}/5</b>}
          </div>
          {(m.quotes || []).map((qt, k) => <div key={k} className="review-quote">
            <span className="grow small">“{qt}”</span>
            <FileUnder topics={fileTopics} current={m.type === "main" ? m.area : m.type === "smalltalk" ? "Small talk" : null} disabled={!!busy}
              onPick={(to) => go2({ index: m.index, sentence: k, to })} ariaLabel={`File “${qt.slice(0, 40)}” under a topic`} />
          </div>)}
        </li>)}
      </ol>}
      <div className="row wrap" style={{ gap: 6 }}>
        <Btn size="sm" busy={busy === "ai"} onClick={() => go({}, "ai", "Isha re-read the transcript.")}>Review again</Btn>
        <Btn size="sm" kind="ghost" busy={busy === "kw"} onClick={() => go({ ai: false }, "kw", "Answers matched to questions by their words.")}>Match by keywords</Btn>
        {canUndo && !review.undone && <Btn size="sm" kind="ghost" busy={busy === "undo"} onClick={() => go({ undo: true }, "undo", "Answers put back as they were filed during the interview.")}>Undo: keep as filed live</Btn>}
      </div>
    </div>
  );
}

function Scorecard({ id, draft: first, review, canUndo, onReviewed, onClose, onDone, areas, unanswered = [], extras = [], transcribe, canTranscribe, heard = 0, fileTopics }) {
  // F2F-004 / SA-010 (V02.00.08): scored against the job's competencies, with the recommendation and summary pre-filled.
  // N2 (V02.00.09): opens at once from Isha's own scores while Claude improves the draft in the background; a clear 1-5
  // rating per competency with Isha's suggestion marked; changing it asks why.
  const toast = useToast();
  const [draft, setDraft] = useState(first);
  const mk = (d) => d.competencies.map((c) => ({ ...c, note: "", disagree: "", skipped: false, skip_reason: "", show_on_report: false, suggested: c.suggested ?? c.score ?? null }));
  const [missing, setMissing] = useState([]);
  // V02.01.02: a decision for each selected question with no answer, and which extra questions go on the report
  const [decisions, setDecisions] = useState({});
  const [showExtras, setShowExtras] = useState([]);
  const [undecided, setUndecided] = useState([]);
  const decide = (area, patch) => { setDecisions((d) => ({ ...d, [area]: { ...(d[area] || {}), ...patch } })); setUndecided((u) => u.filter((a) => a !== area)); };
  const [rows, setRows] = useState(mk(first));
  const [rec, setRec] = useState(first.recommendation || "proceed");
  const [summary, setSummary] = useState(first.summary || "");
  const [note, setNote] = useState("");
  const [run, busy] = useAction();
  const [redrafting, setRedrafting] = useState(false);
  const touched = useRef(false);
  const apply = (d) => { setDraft(d); setRows(mk(d)); setRec(d.recommendation || rec); setSummary(d.summary || ""); };
  const redraft = async (auto) => {
    setRedrafting(true);
    try { const r = await api.post(`/isha/${id}/redraft`); if (!auto || !touched.current) apply(r.draft); else setDraft({ ...draft, ai: true }); }
    catch (e) { if (!auto) toast(e.message || "Isha couldn't rebuild the draft. Your scores are unchanged.", "bad"); }
    finally { setRedrafting(false); }
  };
  useEffect(() => { if (first.captured && !first.ai) redraft(true); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const set = (i, patch) => { touched.current = true; const x = [...rows]; x[i] = { ...x[i], ...patch }; setRows(x); if (missing.length) setMissing(missing.filter((n) => n !== x[i].name)); };
  const scored = rows.filter((r) => r.score != null);
  const avg = scored.length ? (scored.reduce((a, r) => a + Number(r.score), 0) / scored.length).toFixed(1) : null;
  const differs = (r) => r.suggested != null && r.score != null && Number(r.score) !== Number(r.suggested);
  const skipped = rows.filter((r) => r.score == null && r.skipped);
  const unrated = rows.filter((r) => r.score == null && !r.skipped);
  const showMissing = (names) => {
    setMissing(names);
    setTimeout(() => document.querySelector(".sc-row.missing")?.scrollIntoView({ behavior: "smooth", block: "center" }), 30);
  };
  const open_ = unanswered.filter((u) => !decisions[u.area]?.skip);
  const submit = async () => {
    // V02.01.01: every competency needs a rating from 1 to 5 or an explicit Skip
    // V02.01.02: and every selected question with no answer needs its answer picked, or Skip
    if (unrated.length || open_.length) {
      if (open_.length) setUndecided(open_.map((u) => u.area));
      if (unrated.length) showMissing(unrated.map((r) => r.name));
      else setTimeout(() => document.querySelector(".qd-row.missing")?.scrollIntoView({ behavior: "smooth", block: "center" }), 30);
      return;
    }
    const question_decisions = unanswered.map((u) => ({ area: u.area, skip: true, reason: decisions[u.area]?.reason || "", show_on_report: !!decisions[u.area]?.show }));
    try {
      const r = await run(() => api.post(`/isha/${id}/scorecard`, { competencies: rows, recommendation: rec, summary, note, question_decisions, show_extras: showExtras }), "Scorecard submitted");
      if (r) onDone(r);
    } catch (e) { if (e.fields?.missing?.length) showMissing(e.fields.missing); if (e.fields?.undecided?.length) setUndecided(e.fields.undecided); }
  };
  return (
    <Modal wide title="Scorecard" onClose={onClose} footer={<><Btn onClick={onClose}>Back to interview</Btn><Btn kind="primary" busy={busy} onClick={submit}>Submit scorecard</Btn></>}>
      <div className="agent isha"><Isha size={36} mood={redrafting ? "think" : "idle"} /><div className="grow small">{draft.captured
        ? <>Isha scored each competency from the candidate's answers. Her suggestion has a dashed outline; pick a different number if you disagree and say why.{avg && <> Average so far: <b>{avg} / 5</b>.</>}{redrafting && <div className="row" style={{ gap: 6, marginTop: 4 }}><span className="spin" style={{ width: 12, height: 12 }} /> Isha is improving the draft with Claude…</div>}</>
        : <>No answers were captured, so nothing could be scored automatically. Score each competency from your notes, the transcript or the video.</>}</div>
        <Btn size="sm" busy={redrafting} onClick={() => redraft(false)} title="Rebuild the draft from the answers as they are now">Re-draft</Btn></div>
      <ReviewMap id={id} review={review} canUndo={canUndo} areas={areas} fileTopics={fileTopics} onReviewed={(r) => { apply(r.draft); onReviewed?.(r); }} />
      <TranscribeBox id={id} t={transcribe} can={canTranscribe} heard={heard} onDone={(r) => { apply(r.draft); onReviewed?.(r); }} />
      <QuestionDecisions id={id} unanswered={unanswered} extras={extras} review={review} decisions={decisions} decide={decide}
        undecided={undecided} showExtras={showExtras} setShowExtras={setShowExtras} onReviewed={(r) => { apply(r.draft); onReviewed?.(r); }} />
      {missing.length > 0 && <div className="sc-note warn" role="alert"><b>Rating not received for: {missing.join(", ")}.</b> Rate each from 1 to 5, or press Skip if you didn't assess it. Skipped competencies show in the report as “Skipped by the interviewer” and aren't counted.</div>}
      <div className="col" style={{ gap: 10 }}>
        {rows.map((r, i) => <div key={r.name} className={"sc-row" + (missing.includes(r.name) ? " missing" : "")}>
          <div className="sc-h"><b className="grow">{r.name}</b>
            <div className="rate5" role="radiogroup" aria-label={`Score for ${r.name}`}>
              {[1, 2, 3, 4, 5].map((n) => <button type="button" key={n} role="radio" aria-checked={Number(r.score) === n} className={(Number(r.score) === n ? "on " : "") + (Number(r.suggested) === n ? "sug" : "")} title={Number(r.suggested) === n ? "Isha's suggestion" : undefined} onClick={() => set(i, { score: n, skipped: false })}>{n}</button>)}
              <button type="button" role="radio" aria-checked={r.skipped && r.score == null} className={"skip " + (r.skipped && r.score == null ? "on" : "")} onClick={() => set(i, { score: null, skipped: true })}>Skip</button>
            </div>
            {r.score != null && <Chip kind={TONE(r.score)}>{LEVEL(r.score)}</Chip>}
            {r.score == null && r.skipped && <Chip>Skipped · not counted</Chip>}
            {r.score == null && !r.skipped && <Chip kind="warn">Not rated yet</Chip>}
          </div>
          {r.score == null && r.skipped && <div className="row wrap" style={{ gap: 12, alignItems: "flex-end" }}>
            <div style={{ flex: 1, minWidth: 220 }}><Field label="Why skip? (optional)"><Input value={r.skip_reason} onChange={(e) => set(i, { skip_reason: e.target.value })} placeholder="e.g. Ran out of time; covered in the next round" maxLength={300} /></Field></div>
            <label className="check small"><input type="checkbox" checked={!!r.show_on_report} onChange={(e) => set(i, { show_on_report: e.target.checked })} />Show on report</label></div>}
          {r.not_covered && <div className="sc-note calm">{r.reason || "Not covered in this interview."} Score it from your notes or leave it as Skip.</div>}
          {r.elsewhere && <div className="sc-note calm">{r.reason}</div>}
          {r.ai_score != null && <span className="tiny muted">Isha's live score {r.ai_score}{r.suggested != null ? ` · suggested ${r.suggested} / 5` : ""}</span>}
          {differs(r) && <Field label={`Why do you disagree with Isha's ${r.suggested}?`}><Input value={r.disagree} onChange={(e) => set(i, { disagree: e.target.value })} placeholder="e.g. Gave a textbook answer but no real project" /></Field>}
          <div className="grid g2"><Field label="Evidence quote"><Textarea style={{ minHeight: 50 }} value={r.quote || ""} onChange={(e) => set(i, { quote: e.target.value })} /></Field>
            <Field label="Your note"><Input value={r.note} onChange={(e) => set(i, { note: e.target.value })} /></Field></div>
        </div>)}
      </div>
      {/* V02.00.13: say plainly what's missing instead of failing on submit */}
      {unrated.length > 0 && !missing.length && <div className="sc-note calm" role="status">Still to rate: {unrated.map((r) => r.name).join(", ")}. Rate each from 1 to 5 or press Skip.</div>}
      {skipped.length > 0 && <div className="sc-note calm" role="status">{skipped.length} skipped and left out of every score. A skipped competency is on the report only when you tick “Show on report”.</div>}
      {!scored.length && !unrated.length && <div className="sc-note warn" role="status">Rate at least one competency from 1 to 5. Skipped ones aren't counted.</div>}
      <Field label="Your recommendation"><Seg value={rec} onChange={setRec} options={[["proceed", "Proceed"], ["hold", "Hold"], ["reject", "Do not proceed"]]} /></Field>
      <Field label="Summary for the hiring team"><Textarea value={summary} onChange={(e) => setSummary(e.target.value)} /></Field>
      <Field label="Private note"><Input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
    </Modal>
  );
}
